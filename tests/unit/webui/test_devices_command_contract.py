"""Контракт команды устройству (спека 017, US2, FR-016).

Проверяется то, на что опирается интерфейс: успешная команда несёт признак
``automation_synced`` (учла ли её автоматика), а неудача приходит понятной
ошибкой, а не молчаливым откатом.

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from webui.routes.devices import devices as devices_module


ADMIN_HEADERS = {"X-User-ID": "admin_user", "X-Is-Admin": "true"}
DEVICE_UUID = uuid4()


class _FakeDeviceService:
    """Сервис устройств: один прибор, команда уходит «в HA»."""

    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail

    async def get_device(self, device_id: Any) -> Any:
        """Вернуть устройство по идентификатору."""
        return SimpleNamespace(
            id=DEVICE_UUID,
            ha_entity_id="light.girlianda",
            name="Гирлянда",
            device_type="light",
        )

    async def check_device_access(self, *args: Any, **kwargs: Any) -> bool:
        """Доступ проверяется отдельно, здесь — админ."""
        return True

    async def _call_ha_service(self, device: Any, service: str, parameters: dict) -> dict:
        """Позвать сервис Home Assistant (или упасть, если тест проверяет отказ)."""
        if self.fail:
            raise RuntimeError("прибор не ответил")
        return {"service": service}


def _client(*, fail: bool = False) -> TestClient:
    """Клиент с маршрутом команды.

    Args:
        fail: Должен ли вызов Home Assistant упасть.

    Returns:
        Тестовый клиент.
    """
    app = FastAPI()
    app.include_router(devices_module.router)
    app.state.device_service = _FakeDeviceService(fail=fail)
    app.state.persistence = None
    app.state.container = None
    return TestClient(app)


def test_command_should_report_that_automation_did_not_handle_it() -> None:
    """Прямая команда (нет события автомата) сообщает ``automation_synced=False``."""
    response = _client().post(
        f"/api/v1/devices/{DEVICE_UUID}/command",
        json={"name": "set_level", "parameters": {"brightness": 120}},
        headers=ADMIN_HEADERS,
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "success"
    assert body["automation_synced"] is False
    assert body["device_id"] == str(DEVICE_UUID)


def test_command_failure_should_return_reason() -> None:
    """Неудача прибора — 502 с причиной, а не «успех»."""
    response = _client(fail=True).post(
        f"/api/v1/devices/{DEVICE_UUID}/command",
        json={"name": "set_level", "parameters": {}},
        headers=ADMIN_HEADERS,
    )

    assert response.status_code == 502
    assert "прибор не ответил" in response.json()["detail"]
