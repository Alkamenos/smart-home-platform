"""Режим и скорость рекуператора — независимые оси (спека 014, US3, T051, FR-021).

Проверка идёт на настоящих объектах движка, как в
``tests/integration/climate/test_heating_by_sensor.py``: ``EventRouter`` кладёт
показание датчика комнаты в контекст под именем роли (``temperature``) →
условие ``mode_for_weather`` выбирает режим, ``speed_within_limits`` считает
скорость → действие создаёт намерения → диспетчер их получает.

Ключевая мысль: смена скорости не должна пересылать режим. Иначе рекуператор
на каждом показании датчика щёлкал бы режимом, и это выглядело бы как поломка
(research.md D7). Режим меняется только по модификатору «зима», а при жаре —
переходом в `AIRING` («Приток MAX»).

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0
"""

from __future__ import annotations

from typing import Any

import pytest

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

#: Режимы и коэффициенты — как в манифесте дома (data-model.md §5).
SUPPLY_PARAMS: dict[str, Any] = {
    "ventilation_role": "supply",
    "mode_summer": "Рекуперация (лето)",
    "mode_winter": "Рекуперация (зима)",
    "mode_airing": "Приток MAX",
    "speed_normal": 42,
    "speed_min": 14,
    "speed_cold_reference": 5.0,
    "speed_cold_gain": 2.0,
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

    def services(self) -> list[str]:
        """Сервисы всех команд, что дошли до диспетчера.

        Returns:
            Список имён сервисов.
        """
        return [intent.service for intent in self.intents]


def _manifest() -> Manifest:
    """Манифест из одной комнаты: датчик температуры и рекуператор.

    Returns:
        Модель манифеста.
    """
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
                                params=dict(SUPPLY_PARAMS),
                            )
                        ],
                    )
                ],
            )
        ],
        automation_rules=AutomationRules(global_manual_lockout_min=60),
    )


def _build() -> tuple[FSMEngine, EventRouter, _RecordingDispatcher]:
    """Собрать боевой конвейер вентиляции.

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


def _context(**params: Any) -> dict[str, Any]:
    """Контекст события датчика температуры.

    Args:
        params: Глобальные ключи (улица, сезон). Показание комнаты едет в само
            событие (`new_state`), а не в контекст.

    Returns:
        Словарь контекста.
    """
    return {"outside_temperature": 0.0, "is_winter": True, **params}


class TestModeAndSpeedAreIndependent:
    """Режим и скорость — две независимые оси устройства (FR-021)."""

    @pytest.mark.asyncio
    async def test_presets_and_speed_are_two_separate_commands(self) -> None:
        """Первый переход в SUPPLY шлёт режим и скорость двумя командами.

        Returns:
            Ничего.
        """
        _, router, dispatcher = _build()

        await router.route_state_change(
            entity_id=SENSOR,
            new_state="20.0",
            old_state="19.0",
            context=_context(outside_temperature=17.0),
        )

        assert dispatcher.services() == ["set_preset_mode", "turn_on"], (
            f"команды вентиляции {dispatcher.services()} вместо «режим, затем "
            "скорость»: у рекуператора это две независимые оси, и одна команда "
            "не может задать обе (FR-021); скорость не должна теряться, потому "
            "что в накопленном контексте её ещё не было"
        )
        preset = dispatcher.intents[0]
        assert preset.data["preset_mode"] == "Рекуперация (зима)", (
            f"модификатор «зима» включён, а выбран режим {preset.data.get('preset_mode')!r}"
        )

    @pytest.mark.asyncio
    async def test_speed_change_does_not_resend_mode(self) -> None:
        """Новое показание меняет скорость, но не пересылает режим.

        Returns:
            Ничего.
        """
        engine, router, dispatcher = _build()

        await router.route_state_change(
            entity_id=SENSOR,
            new_state="20.0",
            old_state="19.0",
            context=_context(outside_temperature=17.0),
        )
        assert engine.get_state(FSM_ID).current_state == "SUPPLY"  # type: ignore[union-attr]

        dispatcher.intents.clear()
        await router.route_state_change(
            entity_id=SENSOR,
            new_state="20.5",
            old_state="20.0",
            context=_context(outside_temperature=-5.0),
        )

        assert dispatcher.services() == ["turn_on"], (
            f"на показании датчика ушло {dispatcher.services()} вместо одной "
            "команды скорости: режим должен меняться по «зиме», а не на каждое "
            "показание (research.md D7)"
        )
        # 42 − (5 − (−5)) × 2 = 22
        assert dispatcher.intents[0].data["percentage"] == 22, (
            f"скорость {dispatcher.intents[0].data.get('percentage')!r} при улице "
            "−5 °C: холоднее — тише (FR-052)"
        )


class TestSupplyModeFollowsWinterModifier:
    """Режим рекуперации задаёт модификатор «зима», а не только порог (T087)."""

    @pytest.mark.asyncio
    async def test_winter_modifier_off_picks_summer_mode(self) -> None:
        """Модификатор «зима» снят — выбран режим лета.

        Returns:
            Ничего.
        """
        _, router, dispatcher = _build()

        await router.route_state_change(
            entity_id=SENSOR,
            new_state="20.0",
            old_state="19.0",
            context=_context(is_winter=False, outside_temperature=20.0),
        )

        assert dispatcher.intents[0].data["preset_mode"] == "Рекуперация (лето)"

    @pytest.mark.asyncio
    async def test_hot_room_switches_to_max_supply(self) -> None:
        """Комната выше потолка комфорта — переход в AIRING и «Приток MAX».

        Returns:
            Ничего.
        """
        engine, router, dispatcher = _build()

        # Комната 28 выше потолка комфорта 25 → максимальный приток.
        await router.route_state_change(
            entity_id=SENSOR,
            new_state="28.0",
            old_state="27.0",
            context=_context(outside_temperature=0.0, comfort_max=25.0),
        )

        assert engine.get_state(FSM_ID).current_state == "AIRING"  # type: ignore[union-attr]
        presets = [
            i.data.get("preset_mode") for i in dispatcher.intents if i.service == "set_preset_mode"
        ]
        assert presets == ["Приток MAX"], (
            "комната выше потолка комфорта — должен включаться «Приток MAX»: "
            "свежий воздух охлаждает быстрее рекуперации (FR-051)"
        )

    @pytest.mark.asyncio
    async def test_hot_airing_reasserts_max_supply_on_next_reading(self) -> None:
        """Уже в «Притоке MAX» и всё ещё жарко — режим подтверждается прибору.

        Перехода из AIRING в AIRING не было, и команда не уходила: прибор
        оставался на прежнем режиме (в бою 2026-10-13 — «Рекуперация (зима)» на
        минимуме 14 % при 27 °C в комнате).

        Returns:
            Ничего.
        """
        engine, router, dispatcher = _build()

        await router.route_state_change(
            entity_id=SENSOR,
            new_state="28.0",
            old_state="27.0",
            context=_context(outside_temperature=0.0, comfort_max=25.0),
        )
        assert engine.get_state(FSM_ID).current_state == "AIRING"  # type: ignore[union-attr]
        dispatcher.intents.clear()

        await router.route_state_change(
            entity_id=SENSOR,
            new_state="28.5",
            old_state="28.0",
            context=_context(outside_temperature=0.0, comfort_max=25.0),
        )

        assert dispatcher.services() == ["turn_on", "set_preset_mode"], (
            f"на новом показании ушло {dispatcher.services()} вместо подтверждения "
            "режима: прибор при жаре должен оставаться в «Притоке MAX» (и включён)"
        )
        assert dispatcher.intents[-1].data["preset_mode"] == "Приток MAX"

    @pytest.mark.asyncio
    async def test_cool_room_returns_from_max_supply(self) -> None:
        """Комната остыла — привычный режим возвращается, не дожидаясь таймера.

        Returns:
            Ничего.
        """
        engine, router, dispatcher = _build()

        await router.route_state_change(
            entity_id=SENSOR,
            new_state="28.0",
            old_state="27.0",
            context=_context(outside_temperature=0.0, comfort_max=25.0),
        )
        assert engine.get_state(FSM_ID).current_state == "AIRING"  # type: ignore[union-attr]
        dispatcher.intents.clear()

        await router.route_state_change(
            entity_id=SENSOR,
            new_state="22.0",
            old_state="28.0",
            context=_context(outside_temperature=0.0, comfort_max=25.0),
        )

        assert engine.get_state(FSM_ID).current_state == "SUPPLY"  # type: ignore[union-attr]
        presets = [
            i.data.get("preset_mode") for i in dispatcher.intents if i.service == "set_preset_mode"
        ]
        assert presets == ["Рекуперация (зима)"], (
            f"остывшая комната вернула {presets} вместо обычного режима: "
            "«Приток MAX» нельзя держать до часового таймера"
        )

    @pytest.mark.asyncio
    async def test_winter_delta_alone_does_not_pick_supply(self) -> None:
        """Зимой дельта сама по себе приток не включает (регрессия 2026-10-12).

        Returns:
            Ничего.
        """
        _, router, dispatcher = _build()

        # Комната 22 при потолке 25 — не жарко; дельта 22 ≥ 5, но зима важнее.
        await router.route_state_change(
            entity_id=SENSOR,
            new_state="22.0",
            old_state="21.9",
            context=_context(outside_temperature=0.0, comfort_max=25.0),
        )

        assert dispatcher.intents[0].data["preset_mode"] == "Рекуперация (зима)", (
            "зимой большая дельта включила сырой приток и рекуператор остужал дом "
            "(боевой разбор 2026-10-12)"
        )
