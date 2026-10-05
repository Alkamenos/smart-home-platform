"""Шесть эндпоинтов источников обязаны требовать прав администратора.

Очередь 5 продакшен-плана, пункт 3: «`require_admin` на шесть эндпоинтов
источников».

Факт: `require_admin` существовал в проекте, но применялся только к
управлению доступом. Ни один эндпоинт `/api/v1/devices/sources` не проверял
права вообще — не администратора, не даже наличие идентичности. Создание,
удаление и синхронизация источника — операции, меняющие конфигурацию платформы,
и они были доступны любому клиенту.

Проверяется контракт, а не механизм: отсутствие проверки нельзя исправить
добавлением заголовка в тест.

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0
"""

import uuid

import pytest
from fastapi.testclient import TestClient


ADMIN = {"X-User-ID": "admin_user", "X-Is-Admin": "true"}
NON_ADMIN = {"X-User-ID": "ordinary_user", "X-Is-Admin": "false"}
NO_IDENTITY: dict[str, str] = {}


@pytest.fixture
def client() -> TestClient:
    from main import app

    return TestClient(app)


@pytest.fixture
def admin_client() -> TestClient:
    from main import app

    return TestClient(app, headers=ADMIN)


def _create_source(client: TestClient, name: str = "src") -> tuple[int, str]:
    """Создать источник и вернуть код ответа с идентификатором."""
    response = client.post(
        "/api/v1/devices/sources",
        json={"name": name, "url": "http://ha.invalid:8123", "token": "token-long-enough"},
        headers=ADMIN,
    )
    return response.status_code, response.json().get("id", "")


#: Все изменяющие операции: (метод, путь-шаблон, нужен ли созданный источник).
MUTATING = [
    ("post", "/api/v1/devices/sources", False),
    ("get", "/api/v1/devices/sources", False),
    ("get", "/api/v1/devices/sources/{sid}", True),
    ("delete", "/api/v1/devices/sources/{sid}", True),
    ("post", "/api/v1/devices/sources/{sid}/sync", True),
    ("get", "/api/v1/devices/sources/{sid}/discovery-data", True),
]


class TestSourceEndpointsRequireAdmin:
    """Ни один эндпоинт источников не работает без прав администратора."""

    @pytest.mark.parametrize(("method", "path", "needs_source"), MUTATING)
    def test_non_admin_is_refused(
        self, client: TestClient, method: str, path: str, needs_source: bool
    ) -> None:
        """Обычный пользователь получает отказ, а не данные и не изменение."""
        url = path
        if needs_source:
            code, source_id = _create_source(client)
            assert code == 201, f"не удалось создать источник для проверки: {code}"
            url = path.format(sid=source_id)

        response = getattr(client, method)(
            url, headers=NON_ADMIN, **({"json": {}} if method == "post" else {})
        )

        assert response.status_code == 403, (
            f"{method.upper()} {path} без прав администратора вернул "
            f"{response.status_code}, ожидался 403 — проверка прав отсутствует"
        )

    @pytest.mark.parametrize(("method", "path", "needs_source"), MUTATING)
    def test_request_without_identity_is_refused(
        self, client: TestClient, method: str, path: str, needs_source: bool
    ) -> None:
        """Запрос вообще без идентичности тоже отказ."""
        url = path
        if needs_source:
            code, source_id = _create_source(client)
            assert code == 201
            url = path.format(sid=source_id)

        response = getattr(client, method)(
            url, headers=NO_IDENTITY, **({"json": {}} if method == "post" else {})
        )

        assert response.status_code in (401, 403), (
            f"{method.upper()} {path} без идентичности вернул "
            f"{response.status_code}, ожидался 401 или 403"
        )


class TestAdminStillWorks:
    """Права администратора не должны быть сломаны добавлением проверки."""

    @pytest.mark.parametrize(("method", "path", "needs_source"), MUTATING)
    def test_admin_is_not_blocked(
        self, client: TestClient, method: str, path: str, needs_source: bool
    ) -> None:
        """Администратор проходит, иначе проверка прав сделала бы API нерабочим."""
        url = path
        if needs_source:
            code, source_id = _create_source(client)
            assert code == 201
            url = path.format(sid=source_id)

        response = getattr(client, method)(
            url, headers=ADMIN, **({"json": {}} if method == "post" else {})
        )

        assert response.status_code != 403, (
            f"{method.upper()} {path} отказал администратору с 403: проверка прав настроена неверно"
        )

    def test_delete_by_admin_actually_removes_source(self, client: TestClient) -> None:
        """Проверка прав не должна ломать сам эффект операции.

        Отказ, выдаваемый всем, прошёл бы тест «не блокировать администратора»,
        но удаление перестало бы работать.
        """
        code, source_id = _create_source(client)
        assert code == 201

        deleted = client.delete(f"/api/v1/devices/sources/{source_id}", headers=ADMIN)
        assert deleted.status_code == 204, f"удаление сломано: {deleted.status_code}"

        listed = client.get("/api/v1/devices/sources", headers=ADMIN).json()
        assert all(s["id"] != source_id for s in listed), (
            "источник остался в списке после успешного удаления"
        )


class TestUnknownSourceStillReports404:
    """Отказ по правам не должен подменять собой «не найдено»."""

    def test_admin_getting_unknown_source_gets_404(self, client: TestClient) -> None:
        """Администратор получает 404, а не 403, для несуществующего источника."""
        response = client.get(f"/api/v1/devices/sources/{uuid.uuid4()}", headers=ADMIN)

        assert response.status_code == 404
