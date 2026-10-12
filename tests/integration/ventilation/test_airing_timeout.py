"""Проветривание самоотключается по таймеру и снимает модификатор (спека 014, T052, T085).

Проверяются три вещи (FR-024…026, T085):

1. модификатор «проветривание» переводит рекуператор в режим максимального
   притока (``mode_airing`` — «Приток MAX»);
2. таймер состояния ``AIRING`` взят из параметра ``airing_seconds``: иначе
   проветривание длилось бы час вместо получаса;
3. по истечении таймера действие ``airing_after_timeout`` возвращает обычный
   режим **и** записывает ``input_boolean`` модификатора в ``off`` — так
   модификатор «сам становится false» (уточнение владельца, research.md D18).

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0
"""

from __future__ import annotations

from typing import Any

import pytest

from core.action_handlers import ACTION_HANDLERS
from core.events.event_router import EventRouter
from core.fsm.engine import FSMEngine
from core.fsm.factory import FSMFactory
from core.models.manifest import (
    AutomationRules,
    BehaviorConfig,
    DeviceConfig,
    InstanceConfig,
    Manifest,
    RoomConfig,
)
from core.registry import Registry


SENSOR = "sensor.datchik_temperatury_kabinet_temperature"
FAN = "fan.base_smart"
ROOM = "kabinet"
PRIORITY = 10
FSM_ID = f"{FAN}_ventilation_modes_{PRIORITY}"
AIRING_ENTITY = "input_boolean.provetrivanie"
AIRING_SECONDS = 1800

PARAMS: dict[str, Any] = {
    "ventilation_role": "supply",
    "mode_summer": "Рекуперация (лето)",
    "mode_winter": "Рекуперация (зима)",
    "mode_airing": "Приток MAX",
    "speed_normal": 43,
    "speed_min": 14,
    "speed_cold_reference": 5.0,
    "speed_cold_gain": 2.0,
    "airing_seconds": AIRING_SECONDS,
}


class _RecordingDispatcher:
    """Диспетчер, помнящий команды вместо отправки в HA."""

    def __init__(self) -> None:
        self.intents: list[Any] = []

    async def submit(self, intent: Any) -> bool:
        """Запомнить команду.

        Args:
            intent: Команда от действия шаблона.

        Returns:
            Всегда True.
        """
        self.intents.append(intent)
        return True


def _manifest() -> Manifest:
    """Манифест: комната, рекуператор и доменные сущности модификаторов.

    Returns:
        Модель манифеста.
    """
    rules = AutomationRules.model_validate(
        {
            "global_manual_lockout_min": 60,
            "ventilation": {"airing_entity": AIRING_ENTITY},
        }
    )
    return Manifest(
        version=1,
        instance=InstanceConfig(
            id="probe", name="Probe", owner="probe", created_at="2026-01-01T00:00:00Z"
        ),
        rooms=[
            RoomConfig(
                id=ROOM,
                name="Кабинет",
                sensors={"temperature": SENSOR},
                devices=[
                    DeviceConfig(
                        id=FAN,
                        type="fan",
                        behaviors=[
                            BehaviorConfig(
                                template="ventilation_modes",
                                priority=PRIORITY,
                                params=dict(PARAMS),
                            )
                        ],
                    )
                ],
            )
        ],
        automation_rules=rules,
    )


def _build() -> tuple[FSMEngine, EventRouter, _RecordingDispatcher]:
    """Собрать конвейер вентиляции с доменными правилами.

    Returns:
        Движок, роутер и помнящий команды диспетчер.
    """
    from core.action_handlers import register_all_actions
    from core.guards.builtin import register_all_guards

    manifest = _manifest()
    registry = Registry()
    register_all_guards(registry, None)
    register_all_actions(registry)
    engine = FSMEngine()
    dispatcher = _RecordingDispatcher()
    engine.set_command_dispatcher(dispatcher)  # type: ignore[arg-type]
    FSMFactory(engine=engine, registry=registry, event_bus=None).create_and_register(manifest)
    return engine, EventRouter(manifest, engine), dispatcher


class TestAiringStartsOnModifier:
    """Модификатор владельца включает проветривание."""

    @pytest.mark.asyncio
    async def test_airing_on_switches_to_max_supply(self) -> None:
        """``airing_on`` переводит рекуператор в AIRING и в режим «Приток MAX».

        Returns:
            Ничего.
        """
        engine, router, dispatcher = _build()

        await router.route_state_change(
            entity_id=SENSOR,
            new_state="20.0",
            old_state="19.0",
            context={"outside_temperature": 0.0, "is_winter": True, "airing_on": True},
        )

        assert engine.get_state(FSM_ID).current_state == "AIRING"  # type: ignore[union-attr]
        presets = [
            i.data.get("preset_mode") for i in dispatcher.intents if i.service == "set_preset_mode"
        ]
        assert presets == ["Приток MAX"], (
            f"в проветривании ушёл режим {presets!r}: MAX-режим форсирует скорость "
            "100 сам, и отдельная команда скорости была бы перезаписана (D15)"
        )

    @pytest.mark.asyncio
    async def test_airing_timer_comes_from_param(self) -> None:
        """Таймер состояния AIRING взят из ``airing_seconds`` (FR-025).

        Returns:
            Ничего.
        """
        engine, router, _ = _build()

        await router.route_state_change(
            entity_id=SENSOR,
            new_state="20.0",
            old_state="19.0",
            context={"outside_temperature": 0.0, "is_winter": True, "airing_on": True},
        )

        timeout = engine.expected_timeout_sec_in_state(FSM_ID, "AIRING")
        assert timeout == float(AIRING_SECONDS), (
            f"таймер проветривания {timeout!r} вместо {AIRING_SECONDS}: манифест "
            "задаёт получасовое проветривание, а получилось бы часовое"
        )


class TestAiringTimeoutRestoresMode:
    """По таймеру проветривание **возвращает обычный режим**, а не повторяет MAX.

    Боевой урок (research.md D17): контекст автомата накопительный, поэтому если
    имя режима проветривания подставить в контекст, оно переживёт проветривание и
    следующий переход поставит «Приток MAX» вместо обычного режима.
    """

    @pytest.mark.asyncio
    async def test_timeout_restores_weather_mode_and_clears_modifier(self) -> None:
        """Таймер AIRING возвращает режим по погоде и снимает модификатор.

        Returns:
            Ничего.
        """
        engine, router, dispatcher = _build()

        await router.route_state_change(
            entity_id=SENSOR,
            new_state="20.0",
            old_state="19.0",
            context={"outside_temperature": 17.0, "is_winter": True, "airing_on": True},
        )
        assert engine.get_state(FSM_ID).current_state == "AIRING"  # type: ignore[union-attr]

        dispatcher.intents.clear()
        await engine.trigger(FSM_ID, "timeout", respect_debounce=False)

        assert engine.get_state(FSM_ID).current_state == "SUPPLY"  # type: ignore[union-attr]
        presets = [
            i.data.get("preset_mode") for i in dispatcher.intents if i.service == "set_preset_mode"
        ]
        assert presets == ["Рекуперация (зима)"], (
            f"после проветривания ушёл режим {presets!r}: обычный режим должен "
            "восстанавливаться, а не повторять «Приток MAX» (контекст накопительный)"
        )
        assert any(
            i.domain == "input_boolean" and i.device_id == AIRING_ENTITY for i in dispatcher.intents
        ), "модификатор проветривания не снят: он продлил бы проветривание сам"


class TestAiringTimeoutActionResetsModifier:
    """Действие по таймеру возвращает режим и снимает модификатор (T085)."""

    def test_action_returns_mode_speed_and_modifier_off(self) -> None:
        """Действие возвращает режим, скорость и запись ``input_boolean`` в off.

        Returns:
            Ничего.
        """
        steps = ACTION_HANDLERS["airing_after_timeout"](
            None,
            {
                "entity_id": FAN,
                "preset_mode": "Рекуперация (зима)",
                "percentage": 43,
                "airing_entity": AIRING_ENTITY,
            },
        )

        assert [step.service for step in steps] == [
            "set_preset_mode",
            "set_percentage",
            "turn_off",
        ], (
            "по истечении проветривания должны уйти обычный режим, скорость и "
            "запись модификатора в off (T085)"
        )
        reset = steps[-1]
        assert (reset.domain, reset.device_id) == ("input_boolean", AIRING_ENTITY), (
            f"модификатор снимается командой {reset.domain}.{reset.service} по "
            f"{reset.device_id}: адресат должен быть сущностью модификатора"
        )

    def test_action_without_modifier_entity_still_restores_mode(self) -> None:
        """Сущность модификатора не прочитана — режим всё равно возвращается.

        Returns:
            Ничего.
        """
        steps = ACTION_HANDLERS["airing_after_timeout"](
            None,
            {"entity_id": FAN, "preset_mode": "Рекуперация (зима)", "percentage": 43},
        )

        assert [step.service for step in steps] == ["set_preset_mode", "set_percentage"], (
            "без сущности модификатора шаги снятия быть не может, но обычный режим вернуться обязан"
        )
