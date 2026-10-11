"""Кондиционер сквозным путём: охлаждение и запрет зимой (US2).

Проверяется не условие, а решение автомата: жарко ли в комнате, что скажет
условие и какая команда уйдёт. Условие проверяется отдельно; здесь важно, что
соберётся вместе.

Порядок истории: сначала запреты (их можно проверить зимой), и только потом
охлаждение — оно требует тепла и проверяется летом.

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0
"""

from __future__ import annotations

from typing import Any

import pytest

from core.action_handlers import register_all_actions
from core.control_tracker import ControlTracker
from core.events.event_router import EventRouter
from core.fsm.engine import FSMEngine
from core.fsm.factory import FSMFactory
from core.guards.builtin import register_all_guards
from core.models.manifest import (
    AutomationRules,
    BehaviorConfig,
    DeviceConfig,
    InstanceConfig,
    Manifest,
    RoomConfig,
)
from core.registry import Registry


AC = "climate.esphome_web_0d22a4_ac_name"
THERMOSTAT = "climate.termostat_gostinaia"
COMFORT = 25.0


class _RecordingDispatcher:
    """Диспетчер, помнящий команды."""

    def __init__(self) -> None:
        self.intents: list[Any] = []

    async def submit(self, intent: Any) -> bool:
        """Помнить команду.

        Args:
            intent: Команда.

        Returns:
            Всегда True.
        """
        self.intents.append(intent)
        return True

    def services(self) -> list[str]:
        """Сервисы отправленных команд.

        Returns:
            Список сервисов.
        """
        return [i.service for i in self.intents]


def _manifest(*, managed_by_hardware: bool = False) -> Manifest:
    """Манифест с кондиционером в гостиной.

    Args:
        managed_by_hardware: Пометить комнату как управляемую термостатом.

    Returns:
        Модель манифеста.
    """
    params: dict[str, Any] = {"heater_timer": "number.ac_countdown"}
    if managed_by_hardware:
        params["managed_by_hardware"] = True
    return Manifest(
        version=1,
        instance=InstanceConfig(
            id="probe", name="Probe", owner="probe", created_at="2026-01-01T00:00:00Z"
        ),
        rooms=[
            RoomConfig(
                id="gostinaia",
                name="Гостиная",
                sensors={"temperature": "sensor.datchik_temperatury_gostinnaia_temperature"},
                devices=[
                    DeviceConfig(
                        id=AC,
                        type="climate",
                        behaviors=[
                            BehaviorConfig(template="climate_control", priority=20, params=params)
                        ],
                    )
                ],
            )
        ],
        automation_rules=AutomationRules(global_manual_lockout_min=60),
    )


def _build(manifest: Manifest | None = None) -> tuple[FSMEngine, EventRouter, _RecordingDispatcher]:
    """Движок, роутер и диспетчер.

    Args:
        manifest: Манифест; по умолчанию — с кондиционером.

    Returns:
        Движок, роутер, диспетчер.
    """
    registry = Registry()
    register_all_guards(registry, ControlTracker())
    register_all_actions(registry)
    engine = FSMEngine()
    dispatcher = _RecordingDispatcher()
    engine.set_command_dispatcher(dispatcher)  # type: ignore[arg-type]
    actual = manifest or _manifest()
    FSMFactory(engine=engine, registry=registry, event_bus=None).create_and_register(actual)
    return engine, EventRouter(actual, engine), dispatcher


async def _reading(router: EventRouter, value: str, **params: Any) -> None:
    """Доставить показание датчика гостиной.

    Args:
        router: Роутер.
        value: Показание.
        **params: Ключи контекста.

    Returns:
        Ничего.
    """
    # Уставка приходит из глобальных сущностей и в контексте есть всегда.
    # Без неё `may_heat` возвращает «данных нет», и этот отказ перебивает
    # причину зимы — выглядело бы так, будто кондиционер молчит по другой
    # причине, и диагностика уводила бы не туда.
    await router.route_state_change(
        entity_id="sensor.datchik_temperatury_gostinnaia_temperature",
        new_state=value,
        old_state="22.0",
        context={"comfort_max": COMFORT, "climate_setpoint": 21.0, **params},
    )


class TestWinterForbidsCooling:
    """Зимой кондиционер не включается (FR-014)."""

    @pytest.mark.asyncio
    async def test_hot_winter_room_still_denied(self) -> None:
        """Жарко, но зима — кондиционер не включается.

        Returns:
            Ничего.
        """
        _engine, router, dispatcher = _build()

        await _reading(router, "30.0", is_winter=True, ac_allowed=True)

        assert "set_temperature" not in dispatcher.services(), (
            f"зимой кондиционер включаться не должен: {dispatcher.services()}"
        )

    @pytest.mark.asyncio
    async def test_denial_is_named(self) -> None:
        """Причина отказа называет зиму.

        Returns:
            Ничего.
        """
        engine, router, _dispatcher = _build()
        entity = "climate.esphome_web_0d22a4_ac_name_climate_control_20"

        await _reading(router, "30.0", is_winter=True, ac_allowed=True)

        counts = engine.rejection_counts()
        assert counts.get("ac_forbidden_in_winter", 0) > 0, (
            f"причина зимы должна быть названа, иначе по журналу непонятно, чинить "
            f"датчик или кабель: {counts}"
        )
        assert engine.get_state(entity).current_state == "IDLE"


class TestOwnerGateBlocks:
    """Без разрешения владельца охлаждения нет (FR-013)."""

    @pytest.mark.asyncio
    async def test_gate_off_blocks_cooling(self) -> None:
        """Гейт выключен — кондиционер молчит даже летом.

        Returns:
            Ничего.
        """
        _engine, router, dispatcher = _build()

        await _reading(router, "30.0", is_winter=False, ac_allowed=False)

        assert "set_temperature" not in dispatcher.services()


class TestCoolingInSummer:
    """Летом жаркая комната охлаждается."""

    @pytest.mark.asyncio
    async def test_hot_summer_room_cools(self) -> None:
        """Жарко, лето, гейт есть — охлаждаем до потолка.

        Returns:
            Ничего.
        """
        engine, router, dispatcher = _build()
        entity = "climate.esphome_web_0d22a4_ac_name_climate_control_20"

        await _reading(router, "27.0", is_winter=False, ac_allowed=True)

        assert engine.get_state(entity).current_state == "COOLING", (
            f"летом в жару комната должна охлаждаться, а она "
            f"{engine.get_state(entity).current_state}"
        )
        assert "set_temperature" in dispatcher.services()

    @pytest.mark.asyncio
    async def test_comfortable_room_not_cooled(self) -> None:
        """Комната не выше потолка — не охлаждаем.

        Returns:
            Ничего.
        """
        engine, router, dispatcher = _build()
        entity = "climate.esphome_web_0d22a4_ac_name_climate_control_20"

        await _reading(router, "23.0", is_winter=False, ac_allowed=True)

        assert engine.get_state(entity).current_state != "COOLING"
        assert "set_temperature" not in dispatcher.services()


class TestRoomWithThermostatNotDriven:
    """Комната со штатным термостатом платформой не охлаждается (FR-018)."""

    @pytest.mark.asyncio
    async def test_thermostat_room_left_alone(self) -> None:
        """В комнате с термостатом кондиционер платформой не включается.

        Returns:
            Ничего.
        """
        _engine, router, dispatcher = _build(_manifest(managed_by_hardware=True))

        await _reading(router, "30.0", is_winter=False, ac_allowed=True)

        assert "set_temperature" not in dispatcher.services(), (
            "в комнате, где решение принимает штатный термостат, платформа не "
            "вмешивается: два источника в одной комнате дерутся"
        )
