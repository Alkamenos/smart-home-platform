"""POST /api/v1/devices/apply обязан проверять права (K8 продакшен-плана).

Обработчик применяет выбранные устройства из Home Assistant: он создаёт машины
состояний, строит карту маршрутизации и меняет манифест. Проверки прав в нём не
было вовсе, при этом докстринг обещал 403.

Хуже того, `_current_user_id` возвращал строку `"system"`, когда идентичности в
запросе нет. То есть операция, меняющая конфигурацию платформы, выполнялась от
имени несуществующего пользователя — и попадала в аудит как действие «system»,
то есть подделать авторство было невозможно, но и настоящий автор не
фиксировался.

Та же ловушка, что и в `test_sync_requires_identity`: подготовка теста раньше
создавала источник без заголовков и проходила только потому, что этот эндпоинт
прав не проверял.

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0
"""

import uuid

import pytest
from fastapi.testclient import TestClient


ADMIN = {"X-User-ID": "admin_user", "X-Is-Admin": "true"}
NON_ADMIN = {"X-User-ID": "ordinary_user", "X-Is-Admin": "false"}

#: Тело запроса должно проходить валидацию схемы: FastAPI проверяет тело раньше
#: зависимостей, и на 422 проверка прав не доходит. Реальные имена полей —
#: `source_id` и `device_entity_id`.
SELECTION = {
    "source_id": str(uuid.uuid4()),
    "selections": [
        {
            "device_entity_id": "light.den",
            "target_room": "kitchen",
            "behaviors": [{"template": "lighting", "priority": 10}],
        }
    ],
    "dry_run": True,
}


@pytest.fixture
def admin_client() -> TestClient:
    """Приложение от имени администратора."""
    from main import app

    return TestClient(app, headers=ADMIN)


class TestApplyRequiresAdmin:
    """Применение — операция администратора."""

    def test_non_admin_is_refused(self, admin_client: TestClient) -> None:
        """Обычный пользователь получает 403, даже в режиме dry_run.

        `dry_run` ничего не меняет, но это всё равно чтение конфигурации и
        проверка доступа к ней; отказ должен быть и здесь, иначе проверку можно
        обойти, не меняя ничего.
        """
        client = TestClient(admin_client.app, headers=NON_ADMIN)

        response = client.post("/api/v1/devices/apply", json=SELECTION)

        assert response.status_code == 403, (
            f"обычный пользователь получил {response.status_code} вместо 403: "
            "операция меняет манифест и строит автоматику без проверки прав"
        )

    def test_request_without_identity_is_refused(self, admin_client: TestClient) -> None:
        """Запрос без идентичности — отказ, а не действие от имени «system»."""
        client = TestClient(admin_client.app)

        response = client.post("/api/v1/devices/apply", json=SELECTION)

        assert response.status_code in (401, 403), (
            f"анонимный запрос получил {response.status_code}: операция выполнена "
            "от имени несуществующего пользователя «system»"
        )


class TestAdminCanStillDryRun:
    """Проверка прав не должна делать эндпоинт нерабочим."""

    def test_admin_dry_run_is_not_blocked(self, admin_client: TestClient) -> None:
        """Администратор проходит: отказ всем прошёл бы половину проверок."""
        response = admin_client.post("/api/v1/devices/apply", json=SELECTION)

        assert response.status_code != 403, f"администратору отказано с 403: {response.text[:200]}"

    def test_dry_run_reports_body(self, admin_client: TestClient) -> None:
        """Ответ dry_run остаётся содержательным, а не заглушкой.

        Проверка на то, что добавление зависимости не подменило собой обработчик:
        отказ «на всё» формально прошёл бы предыдущий тест.
        """
        response = admin_client.post("/api/v1/devices/apply", json=SELECTION)

        body = response.json()
        assert "devices_added" in body, f"в ответе нет devices_added: {body}"
        assert body.get("dry_run") is True, f"dry_run не отмечен в ответе: {body}"
