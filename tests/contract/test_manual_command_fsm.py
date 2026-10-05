"""Ручная команда должна попадать в автомат, а не только в Home Assistant (#69).

Состояние автомата и реальное положение вещей — одно и то же. Если команда
меняет лампу напрямую в HA, а автомат об этом не знает, то следующее же событие
движения переключит автомат и погасит свет по таймауту, отменив ручное действие
пользователя. Это тот же класс расхождения, что закрыт в #65, #66 и #68.

Маршрут: команда отдаётся автомату событием `manual_switch_on` /
`manual_switch_off`, и действие шаблона само вызывает Home Assistant. Поэтому
команда не выполняется дважды, а состояние автомата совпадает с реальным.

Когда в шаблоне такого перехода нет, команда уходит в HA напрямую, а ответ
прямо говорит, что состояние автомата не отслежено. Молча разъезжаться нельзя —
и отказываться тоже: у большинства шаблонов ручных переходов нет вовсе, и отказ
сделал бы управление невозможным.
"""

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import time
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def device(isolated_client: TestClient) -> str:
    """Создаёт источник и устройство света в кухне.

    Args:
        isolated_client: HTTP-клиент от имени администратора.

    Returns:
        Идентификатор созданного устройства.
    """
    source = isolated_client.post(
        "/api/v1/devices/sources",
        json={
            "name": "Источник для автомата",
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
                    "device_entity_id": "light.manual_probe",
                    "device_type": "light",
                    "name": "Свет для ручного управления",
                    "target_room": "kitchen",
                    "behavior_template": "lighting",
                }
            ],
        },
    )
    assert applied.status_code == 201, applied.text
    listing = isolated_client.get("/api/v1/devices?ha_entity_id=light.manual_probe")
    assert listing.status_code == 200, listing.text
    return str(listing.json()[0]["id"])


def _fsm_state(container: object, entity_id: str) -> str | None:
    """Возвращает состояние автомата устройства.

    Args:
        container: Контейнер платформы.
        entity_id: entity_id устройства в Home Assistant.

    Returns:
        Имя состояния либо None, если автомата нет.
    """
    for fsm_id in container.fsm.get_entities_by_device(entity_id):
        state = container.fsm.get_state(fsm_id)
        if state is not None:
            return state.current_state
    return None


class TestManualCommandReachesFsm:
    """Команда переключает автомат."""

    def test_turn_on_should_move_automaton_to_manual_state(
        self, isolated_client: TestClient, isolated_app: object, device: str
    ) -> None:
        """Включение по команде переводит автомат в ON_MANUAL.

        Args:
            isolated_client: HTTP-клиент от имени администратора.
            isolated_app: Изолированное приложение.
            device: Идентификатор устройства.
        """
        container = isolated_app.state.container
        assert _fsm_state(container, "light.manual_probe") == "OFF"

        isolated_client.post(
            f"/api/v1/devices/{device}/command",
            json={"name": "turn_on", "parameters": {}},
        )

        assert _fsm_state(container, "light.manual_probe") == "ON_MANUAL", (
            "ручное включение не отражено в автомате: следующее событие движение "
            "переключит автомат и погасит свет по таймауту, отменив волю "
            "пользователя"
        )

    def test_turn_off_should_move_automaton_back(
        self, isolated_client: TestClient, isolated_app: object, device: str
    ) -> None:
        """Выключение по команде возвращает автомат в OFF.

        Между командами нужна пауза больше `debounce_sec` (в `lighting.yaml` —
        0.5 с). Первая редакция проверки ждала ноль миллисекунд, и движок
        справедливо отвергал вторую команду как «дребезг»: дебаунс существует
        именно для этого и на ручные команды тоже распространяется.

        Args:
            isolated_client: HTTP-клиент от имени администратора.
            isolated_app: Изолированное приложение.
            device: Идентификатор устройства.
        """
        container = isolated_app.state.container
        isolated_client.post(
            f"/api/v1/devices/{device}/command",
            json={"name": "turn_on", "parameters": {}},
        )
        assert _fsm_state(container, "light.manual_probe") == "ON_MANUAL"

        time.sleep(0.6)
        isolated_client.post(
            f"/api/v1/devices/{device}/command",
            json={"name": "turn_off", "parameters": {}},
        )

        assert _fsm_state(container, "light.manual_probe") == "OFF"

    def test_should_report_automation_synced_when_fsm_handled(
        self, isolated_client: TestClient, device: str
    ) -> None:
        """Ответ говорит, что состояние автомата синхронизировано.

        Args:
            isolated_client: HTTP-клиент от имени администратора.
            device: Идентификатор устройства.
        """
        response = isolated_client.post(
            f"/api/v1/devices/{device}/command",
            json={"name": "turn_on", "parameters": {}},
        )

        assert response.status_code == 200, response.text
        assert response.json()["automation_synced"] is True, response.text


class TestCommandWithoutManualTransition:
    """Устройства без ручного перехода работают, но честно сообщают об этом."""

    def test_should_still_execute_when_template_has_no_manual_transition(
        self, isolated_client: TestClient, isolated_app: object
    ) -> None:
        """Вентилятор без ручных переходов всё равно выключается.

        Отказ здесь сделал бы управление вентиляцией невозможным, потому что
        таких переходов нет ни в одном шаблоне, кроме `lighting` и `night_light`.

        Args:
            isolated_client: HTTP-клиент от имени администратора.
            isolated_app: Изолированное приложение.
        """
        source = isolated_client.post(
            "/api/v1/devices/sources",
            json={
                "name": "Источник для вентилятора",
                "url": "http://192.168.1.10:8123",
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
                        "device_entity_id": "fan.manual_probe",
                        "device_type": "fan",
                        "name": "Вентилятор",
                        "target_room": "bathroom",
                        "behavior_template": "humidity_ventilation",
                    }
                ],
            },
        )
        assert applied.status_code == 201, applied.text
        listing = isolated_client.get("/api/v1/devices?ha_entity_id=fan.manual_probe")
        fan_id = str(listing.json()[0]["id"])

        response = isolated_client.post(
            f"/api/v1/devices/{fan_id}/command",
            json={"name": "turn_on", "parameters": {}},
        )

        assert response.status_code == 200, response.text
        assert response.json()["automation_synced"] is False, response.text

    def test_should_reject_command_when_no_fsm_event_and_device_missing_adapter(
        self, isolated_client: TestClient, isolated_app: object
    ) -> None:
        """Ошибка HA по-прежнему не выдаётся за успех.

        Args:
            isolated_client: HTTP-клиент от имени администратора.
            isolated_app: Изолированное приложение.
        """
        device_service = isolated_app.state.device_service
        device_service.ha_adapter = AsyncMock()
        device_service.ha_adapter.call_service = AsyncMock(side_effect=RuntimeError("отказ HA"))

        source = isolated_client.post(
            "/api/v1/devices/sources",
            json={
                "name": "Источник для отказа",
                "url": "http://192.168.1.11:8123",
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
                        "device_entity_id": "fan.failing_probe",
                        "device_type": "fan",
                        "name": "Вентилятор с отказом",
                        "target_room": "bathroom",
                        "behavior_template": "humidity_ventilation",
                    }
                ],
            },
        )
        assert applied.status_code == 201, applied.text
        listing = isolated_client.get("/api/v1/devices?ha_entity_id=fan.failing_probe")
        fan_id = str(listing.json()[0]["id"])

        response = isolated_client.post(
            f"/api/v1/devices/{fan_id}/command",
            json={"name": "turn_off", "parameters": {}},
        )

        assert response.status_code == 502, response.text
        assert "отказ HA" in response.text


class TestNoDoubleCommand:
    """Автомат не должен выполнять команду дважды."""

    def test_should_not_call_home_assistant_directly_when_fsm_handled(
        self, isolated_client: TestClient, isolated_app: object, device: str
    ) -> None:
        """Обработанная автоматом команда не дублируется прямым вызовом.

        Переход шаблона сам вызывает Home Assistant. Если бы маршрут после этого
        ещё раз позвонил в HA, действие исполнилось бы дважды — для включения
        света незаметно, для `fan.set_high_speed` или команды с таймером — нет.

        Args:
            isolated_client: HTTP-клиент от имени администратора.
            isolated_app: Изолированное приложение.
            device: Идентификатор устройства.
        """
        device_service = isolated_app.state.device_service
        adapter = AsyncMock()
        adapter.call_service = AsyncMock(return_value=[])
        device_service.ha_adapter = adapter

        response = isolated_client.post(
            f"/api/v1/devices/{device}/command",
            json={"name": "turn_on", "parameters": {}},
        )

        assert response.status_code == 200, response.text
        assert response.json()["automation_synced"] is True
        assert adapter.call_service.await_count == 0, (
            "команда выполнена и автоматом, и напрямую — действие исполнилось дважды"
        )
