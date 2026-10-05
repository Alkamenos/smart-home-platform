"""Команда устройства должна выполняться, а не только обещать (Known Issue #69).

`POST /api/v1/devices/{id}/command` отвечал 202 со `status: "executing"` и не
делал ничего: в обработчике стоял `# TODO: Использовать
DeviceService.execute_command()`. Проверено на реальной лампе — состояние в Home
Assistant не менялось.

Тесты требуют, чтобы команда **выполнялась**, а её исход был виден в ответе.
Контракт ответа меняется намеренно: 202 и «executing» были ложным успехом, и
проверки, закреплявшие их (в `test_devices_api.py`, `test_access_control.py`,
`test_device_audit_log.py`), обновлены под фактическое поведение.

Маршрут: команда сначала отдаётся автомату (`manual_switch_on` /
`manual_switch_off`), и уже при отсутствии такого перехода уходит в Home Assistant
напрямую через `DeviceService._call_ha_service`. Эти проверки относятся к прямой
ветке, поэтому используют `toggle` — команды, у которой нет события автомата.
Проверки связи с автоматом живут в `test_manual_command_fsm.py`.
"""

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient


DEVICE_ID = "11111111-2222-3333-4444-555555555555"


@pytest.fixture
def ha_adapter(isolated_app: object) -> AsyncMock:
    """Адаптер Home Assistant, запоминающий вызовы сервисов.

    Подменяется у уже собранного экземпляра `DeviceService`: приложение создаётся
    фикстурой `isolated_app`, и подмена в конструкторе была бы слишком поздней —
    первая редакция проверки так и делала, и адаптер оставался MockAdapter, из-за
    чего тесты падали не по той причине, что проверяли.

    Args:
        isolated_app: Изолированное приложение.

    Returns:
        Заглушка адаптера.
    """
    adapter = AsyncMock()
    adapter.call_service = AsyncMock(return_value=[{"entity_id": "light.probe"}])
    device_service = isolated_app.state.device_service
    assert device_service is not None, "у приложения нет сервиса устройств"
    device_service.ha_adapter = adapter
    return adapter


@pytest.fixture
def device(isolated_client: TestClient) -> str:
    """Создаёт источник и устройство, возвращает его идентификатор.

    Args:
        isolated_client: HTTP-клиент от имени администратора.

    Returns:
        Идентификатор созданного устройства.
    """
    source = isolated_client.post(
        "/api/v1/devices/sources",
        json={
            "name": "Источник для команд",
            "url": "http://192.168.1.9:8123",
            "token": "probe_token_long_enough",
        },
    )
    assert source.status_code == 201, source.text

    applied = isolated_client.post(
        "/api/v1/devices/apply",
        json={
            "source_id": source.json()["id"],
            "dry_run": False,
            "selections": [
                {
                    "device_entity_id": "light.command_probe",
                    "device_type": "light",
                    "name": "Свет для проверки команд",
                    "target_room": "kitchen",
                    "behavior_template": "lighting",
                }
            ],
        },
    )
    assert applied.status_code == 201, applied.text

    listing = isolated_client.get("/api/v1/devices?ha_entity_id=light.command_probe")
    assert listing.status_code == 200, listing.text
    return str(listing.json()[0]["id"])


class TestCommandIsExecuted:
    """Команда обязана дойти до Home Assistant."""

    def test_should_call_home_assistant_service(
        self, isolated_client: TestClient, device: str, ha_adapter: AsyncMock
    ) -> None:
        """Вызов сервиса HA происходит с правильными доменом, сервисом и сущностью.

        Args:
            isolated_client: HTTP-клиент от имени администратора.
            device: Идентификатор устройства.
            ha_adapter: Заглушка адаптера.
        """
        isolated_client.post(
            f"/api/v1/devices/{device}/command",
            json={"name": "toggle", "parameters": {}},
        )

        assert ha_adapter.call_service.await_count == 1, "сервис HA не был вызван"
        call = ha_adapter.call_service.await_args
        assert call.kwargs["service"] == "toggle"
        assert call.kwargs["entity_id"] == "light.command_probe"

    def test_should_accept_service_form_with_domain(
        self, isolated_client: TestClient, device: str, ha_adapter: AsyncMock
    ) -> None:
        """Форма `light.turn_on` тоже понимается: домен отбрасывается.

        Args:
            isolated_client: HTTP-клиент от имени администратора.
            device: Идентификатор устройства.
            ha_adapter: Заглушка адаптера.
        """
        isolated_client.post(
            f"/api/v1/devices/{device}/command",
            json={"command_name": "light.toggle"},
        )

        call = ha_adapter.call_service.await_args
        assert call is not None
        assert call.kwargs["service"] == "toggle", "домен остался в имени сервиса"

    def test_should_pass_parameters_to_service(
        self, isolated_client: TestClient, device: str, ha_adapter: AsyncMock
    ) -> None:
        """Параметры команды доходят до сервиса.

        Args:
            isolated_client: HTTP-клиент от имени администратора.
            device: Идентификатор устройства.
            ha_adapter: Заглушка адаптера.
        """
        isolated_client.post(
            f"/api/v1/devices/{device}/command",
            json={"name": "toggle", "parameters": {"transition": 5}},
        )

        call = ha_adapter.call_service.await_args
        assert call is not None
        assert call.kwargs["transition"] == 5


class TestCommandReportsRealOutcome:
    """Ответ обязан отражать фактический исход, а не намерение."""

    def test_should_report_success_when_service_answered(
        self, isolated_client: TestClient, device: str, ha_adapter: AsyncMock
    ) -> None:
        """Успешный вызов даёт статус success, а не «executing».

        Args:
            isolated_client: HTTP-клиент от имени администратора.
            device: Идентификатор устройства.
            ha_adapter: Заглушка адаптера.
        """
        response = isolated_client.post(
            f"/api/v1/devices/{device}/command",
            json={"name": "toggle", "parameters": {}},
        )

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["status"] == "success", response.text
        assert body["completed_at"], "время завершения не заполнено"

    def test_should_report_failure_when_service_raises(
        self, isolated_client: TestClient, device: str, ha_adapter: AsyncMock
    ) -> None:
        """Ошибка HA не выдаётся за успех.

        Args:
            isolated_client: HTTP-клиент от имени администратора.
            device: Идентификатор устройства.
            ha_adapter: Заглушка адаптера.
        """
        ha_adapter.call_service = AsyncMock(side_effect=RuntimeError("HA недоступен"))

        response = isolated_client.post(
            f"/api/v1/devices/{device}/command",
            json={"name": "toggle", "parameters": {}},
        )

        assert response.status_code == 502, response.text
        assert "HA недоступен" in response.text, response.text

    def test_should_not_claim_executing_status(
        self, isolated_client: TestClient, device: str, ha_adapter: AsyncMock
    ) -> None:
        """Статус `executing` больше не выдаётся: команда выполняется синхронно.

        Args:
            isolated_client: HTTP-клиент от имени администратора.
            device: Идентификатор устройства.
            ha_adapter: Заглушка адаптера.
        """
        response = isolated_client.post(
            f"/api/v1/devices/{device}/command",
            json={"name": "toggle", "parameters": {}},
        )

        assert response.json()["status"] != "executing", (
            "статус executing означает «обещание без результата» — именно он "
            "и скрывал неработающий маршрут команды"
        )
