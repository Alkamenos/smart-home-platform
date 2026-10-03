"""Самопроверка тестовой инфраструктуры (спека 009, FR-010, FR-026, R-02…R-04).

Инфраструктура проверяет саму себя: если фикстуры идентичности или изоляции
перестанут работать, это обязано быть видно здесь, а не в виде тихой деградации
покрытия в остальных файлах.

Почему этот файл существует отдельно, а не внутри проверяемых тестов: тест,
который проверяет собственную фикстуру своим же провалом, доказывает мало.
Здесь всё проверяется явно и с утверждениями.

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from tests.helpers.ha_stub import HAUnavailable, async_value, stub_ha


class TestIdentityFixture:
    """Идентичность — часть подготовки, а не украшения каждого запроса."""

    def test_request_without_identity_is_rejected(self, isolated_app):
        """Запрос без идентичности отклоняется, а не проходит вхолостую."""
        with TestClient(isolated_app) as client:
            response = client.post(
                "/api/v1/devices/not-a-real-device/config",
                json={"location": "кухня"},
            )
        assert response.status_code == 401, (
            f"без идентичности ожидался 401, получен {response.status_code}: {response.text}"
        )
        assert response.json()["detail"] == "Missing X-User-ID header"

    def test_request_with_identity_passes_middleware(self, isolated_client):
        """С идентичностью запрос доходит до роута (дальше — его собственные коды)."""
        response = isolated_client.get("/api/v1/devices/not-a-real-device")
        assert response.status_code != 401, (
            f"с идентичностью ожидался не 401, получен {response.status_code}"
        )

    def test_device_list_without_identity_returns_empty_not_error(
        self, isolated_client, synced_device_id
    ):
        """`GET /devices` без идентичности даёт 200 `[]` — и это ловушка.

        Список отдаёт только доступное пользователю, поэтому без заголовка он
        пуст и код успешен. Такой «успех» не является проверкой прав: тест,
        построенный на нём, проходит, ни разу не проверив доступ. Здесь это
        зафиксировано явно, чтобы правомерность такой проверки не пришлось
        угадывать.
        """
        with TestClient(isolated_client.app) as anonymous:
            response = anonymous.get("/api/v1/devices")
        assert response.status_code == 200
        assert response.json() == [], "ожидался пустой список для анонимного запроса"

    def test_admin_can_read_device_list(self, isolated_client, synced_device_id):
        """С идентичностью администратора список содержит устройство."""
        response = isolated_client.get("/api/v1/devices")
        assert response.status_code == 200
        ids = [str(d["id"]) for d in response.json()]
        assert synced_device_id in ids

    def test_distinct_users_have_distinct_headers(
        self, admin_headers, viewer_headers, other_headers
    ):
        """Роли различаются идентификатором, а не только набором заголовков."""
        user_ids = {
            admin_headers["X-User-ID"],
            viewer_headers["X-User-ID"],
            other_headers["X-User-ID"],
        }
        assert len(user_ids) == 3, f"идентификаторы пользователей должны различаться: {user_ids}"

    def test_admin_header_marks_admin_only(self, admin_headers, viewer_headers):
        """Административность выражена отдельным заголовком, а не подразумевается."""
        assert admin_headers.get("X-Is-Admin") == "true"
        assert "X-Is-Admin" not in viewer_headers


class TestStorageIsolation:
    """Персистентность теста не должна попадать в репозиторий."""

    def test_app_persists_only_into_workdir(
        self, isolated_client, synced_device_id, isolated_workdir
    ):
        """Файлы данных создаются во временном каталоге."""
        data_dir = isolated_workdir / "data"
        assert data_dir.exists(), f"ожидался каталог данных {data_dir}"
        produced = {p.name for p in data_dir.iterdir() if p.is_file()}
        assert "sources.json" in produced, f"источник не сохранён: {produced}"
        assert "devices.json" in produced, f"устройство не сохранено: {produced}"

    def test_sync_writes_something(self, isolated_client, synced_device_id, isolated_workdir):
        """Синхронизированное устройство действительно записано на диск."""
        devices_file = isolated_workdir / "data" / "devices.json"
        assert devices_file.exists()
        content = devices_file.read_text(encoding="utf-8")
        assert synced_device_id in content, "устройство не найдено в devices.json"

    def test_isolated_workdir_is_removed_after_test(self, project_root):
        """Прежние временные каталоги удаляются — их не копит каждый прогон."""
        leftovers = list(project_root.glob("shp_integration_*"))
        assert not leftovers, f"остались неудалённые рабочие каталоги: {leftovers}"


class TestExternalSystemStub:
    """Обращение к внешней системе перехватывается на шве подключения."""

    def test_stub_intercepts_before_connection(self, isolated_client, ha_unavailable):
        """Синхронизация не доходит до сети и даёт предсказуемый отказ."""
        with stub_ha(mode=HAUnavailable.REFUSED):
            response = isolated_client.post(f"/api/v1/devices/sources/{ha_unavailable}/sync")
        assert response.status_code == 500, response.text
        assert "unreachable.invalid" in response.json()["detail"], (
            f"сообщение должно называть адрес: {response.text}"
        )

    def test_stub_refused_and_timeout_differ_at_client_level(self, ha_client):
        """На уровне клиента отказ и таймаут различимы.

        На уровне HTTP API они **неразличимы**: `connect_to_ha` гасит любое
        исключение и возвращает False. Это свойство производственного кода, и
        тесты не должны изображать различение, которого нет.
        """
        with stub_ha(mode=HAUnavailable.REFUSED):
            assert awaitable_false(ha_client) is True

    def test_stub_refused_makes_connect_return_false(self, ha_client):
        """Отклонённое соединение даёт `False`, а не исключение."""
        with stub_ha(mode=HAUnavailable.REFUSED):
            assert run_async(ha_client.connect_to_ha()) is False

    def test_stub_available_makes_connect_return_true(self, ha_client):
        """Доступная система даёт `True`."""
        with stub_ha(mode=HAUnavailable.AVAILABLE):
            assert run_async(ha_client.connect_to_ha()) is True

    def test_stub_timeout_raises_at_client_level(self, ha_client):
        """Таймаут на уровне клиента — таймаут, а не молчаливый False."""
        import asyncio

        with stub_ha(mode=HAUnavailable.TIMEOUT), pytest.raises(asyncio.TimeoutError):
            run_async(ha_client.connect_to_ha())

    def test_sync_succeeds_with_available_stub(self, isolated_client, ha_unavailable):
        """Доступная система даёт успешную синхронизацию и ненулевое число устройств."""
        states = [
            {"entity_id": "light.a", "state": "on", "attributes": {"friendly_name": "A"}},
            {"entity_id": "light.b", "state": "off", "attributes": {"friendly_name": "B"}},
        ]
        with stub_ha(states=states):
            response = isolated_client.post(f"/api/v1/devices/sources/{ha_unavailable}/sync")
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["device_count"] == 2, f"ожидались 2 устройства: {body}"

    def test_stub_yields_description_of_what_was_replaced(self):
        """Подмена отдаёт описание — тест может утверждать, что подменено."""
        with stub_ha(mode=HAUnavailable.REFUSED) as stub:
            assert stub.connected is False
            assert stub.states_response() == []
            assert stub.client_patch_target().endswith("connect_to_ha")

    def test_async_value_returns_value(self):
        """Вспомогательная функция возвращает заданное значение."""
        assert run_async(async_value(42)()) == 42


def run_async(coro):
    """Выполняет корутину вне работающего цикла событий.

    Тесты синхронные: внутри команд приложения уже выполняется `asyncio.run`,
    поэтому асинхронный тест упал бы с «cannot be called from a running event
    loop» (решение R-07).

    Args:
        coro: Корутина для выполнения.

    Returns:
        Результат корутины.
    """
    import asyncio

    return asyncio.run(coro)


def awaitable_false(ha_client) -> bool:
    """Проверяет, что подключение отклонено.

    Args:
        ha_client: Экземпляр клиента внешней системы.

    Returns:
        True, если подключение не удалось.
    """
    return run_async(ha_client.connect_to_ha()) is False
