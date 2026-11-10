"""Плановый свет: флаг владельца, закат и ручные действия.

Владелец, 2026-11-01: основное уличное освещение включается вручную, но
платформа должна уметь включить его по закату, если в Home Assistant включён
флаг «Включать основное освещение». Флаг — разрешение, а не выключатель
группы: ручное управление работает всегда.

Шаблон `scheduled_light` — отдельный, не `deco_light`: основное освещение не
декор, и у него другой сценарий выключения (сон, рассвет) и ручное удержание.
"""

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from typing import Any

import pytest

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
from core.services.deco_light_watcher import DecorativeLightWatcher


GROUP = "light.vse_fonari"
GROUP_FSM = "light.vse_fonari_scheduled_light_10"
FEATURE = "input_boolean.vkliuchat_osnovnoe_osveshchenie"


class _RecordingDispatcher:
    """Диспетчер, запоминающий команды вместо отправки в Home Assistant."""

    def __init__(self) -> None:
        self.intents: list[Any] = []

    async def submit(self, intent: Any) -> bool:
        """Запомнить команду.

        Args:
            intent: Команда действия.

        Returns:
            Всегда True.
        """
        self.intents.append(intent)
        return True

    def services(self) -> list[str]:
        """Сервисы отправленных команд.

        Returns:
            Список имён сервисов.
        """
        return [intent.service for intent in self.intents]


def _manifest() -> Manifest:
    """Манифест с группой фонарей и плановым поведением.

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
                id="sad",
                name="Сад",
                sensors={},
                devices=[
                    DeviceConfig(
                        id=GROUP,
                        type="light",
                        name="Основное освещение сада",
                        behaviors=[
                            BehaviorConfig(
                                template="scheduled_light",
                                priority=10,
                                params={"off_by": "sleep"},
                            )
                        ],
                    )
                ],
            )
        ],
        automation_rules=AutomationRules(
            global_manual_lockout_min=60,
            scheduled_light_feature_entity=FEATURE,
        ),
    )


def _build() -> tuple[FSMEngine, _RecordingDispatcher]:
    """Собрать движок с настоящими условиями и действиями.

    Returns:
        Движок и записывающий диспетчер.
    """
    from core.action_handlers import register_all_actions
    from core.control_tracker import ControlTracker
    from core.guards.builtin import register_all_guards

    registry = Registry()
    register_all_guards(registry, ControlTracker())
    register_all_actions(registry)
    engine = FSMEngine()
    dispatcher = _RecordingDispatcher()
    engine.set_command_dispatcher(dispatcher)  # type: ignore[arg-type]
    FSMFactory(engine=engine, registry=registry, event_bus=None).create_and_register(_manifest())
    return engine, dispatcher


def _ctx(
    *,
    enabled: bool | None = True,
    sleeping: bool | None = False,
    daylight: bool | None = False,
    changed_role: str | None = None,
    startup: bool = False,
    device_is_on: bool = False,
    device_is_off: bool = False,
) -> dict[str, Any]:
    """Собрать контекст события для планового света.

    Returns:
        Внешний контекст перехода.
    """
    context: dict[str, Any] = {
        "scheduled_light_enabled": enabled,
        "sleep_modifier_on": sleeping,
        "daylight": daylight,
    }
    if changed_role is not None:
        context["_changed_role"] = changed_role
    if startup:
        context["_startup_reapply"] = True
    if device_is_on:
        context["_device_is_on"] = True
    if device_is_off:
        context["_device_is_off"] = True
    return context


@pytest.mark.asyncio
async def test_sunset_turns_group_on_when_feature_enabled() -> None:
    """Флаг включён — закат включает группу."""
    engine, dispatcher = _build()

    await engine.trigger(GROUP_FSM, "sunset_started", external_ctx=_ctx(), respect_debounce=False)

    assert engine.get_state(GROUP_FSM).current_state == "ON_SCHEDULED"
    assert "turn_on" in dispatcher.services()
    assert dispatcher.intents[0].bypass_lockout is True, (
        "флаг владельца — не удобство автоматики: ручная блокировка не должна "
        "отменять команду планового света"
    )


@pytest.mark.asyncio
async def test_sunset_does_nothing_when_feature_disabled() -> None:
    """Флаг выключен — автоматика не включает группу."""
    engine, dispatcher = _build()

    await engine.trigger(
        GROUP_FSM,
        "sunset_started",
        external_ctx=_ctx(enabled=False),
        respect_debounce=False,
    )

    assert engine.get_state(GROUP_FSM).current_state == "OFF"
    assert dispatcher.intents == []


@pytest.mark.asyncio
async def test_sunset_does_nothing_while_sleeping() -> None:
    """Даже с включённым флагом спящий дом свет не зажигает."""
    engine, dispatcher = _build()

    await engine.trigger(
        GROUP_FSM,
        "sunset_started",
        external_ctx=_ctx(sleeping=True),
        respect_debounce=False,
    )

    assert engine.get_state(GROUP_FSM).current_state == "OFF"
    assert dispatcher.intents == []


@pytest.mark.asyncio
async def test_sleep_turns_scheduled_light_off() -> None:
    """«Мы спим» гасит свет, включённый по закату."""
    engine, dispatcher = _build()
    await engine.trigger(GROUP_FSM, "sunset_started", external_ctx=_ctx(), respect_debounce=False)
    dispatcher.intents.clear()

    await engine.trigger(GROUP_FSM, "sleep_started", external_ctx=_ctx(), respect_debounce=False)

    assert engine.get_state(GROUP_FSM).current_state == "OFF"
    assert "turn_off" in dispatcher.services()


@pytest.mark.asyncio
async def test_sunrise_turns_scheduled_light_off() -> None:
    """Рассвет — запасной выключатель, если «мы спим» не наступило."""
    engine, dispatcher = _build()
    await engine.trigger(GROUP_FSM, "sunset_started", external_ctx=_ctx(), respect_debounce=False)
    dispatcher.intents.clear()

    await engine.trigger(
        GROUP_FSM, "sunrise_started", external_ctx=_ctx(daylight=True), respect_debounce=False
    )

    assert engine.get_state(GROUP_FSM).current_state == "OFF"
    assert "turn_off" in dispatcher.services()


@pytest.mark.asyncio
async def test_manual_off_holds_through_sunset_until_morning() -> None:
    """Ручное выключение не отменяется вечерней сверкой в тот же вечер."""
    engine, dispatcher = _build()
    await engine.trigger(GROUP_FSM, "sunset_started", external_ctx=_ctx(), respect_debounce=False)
    await engine.trigger(
        GROUP_FSM, "manual_switch_off", external_ctx=_ctx(), respect_debounce=False
    )
    dispatcher.intents.clear()

    await engine.trigger(GROUP_FSM, "sunset_started", external_ctx=_ctx(), respect_debounce=False)

    assert engine.get_state(GROUP_FSM).current_state == "OFF_MANUAL"
    assert dispatcher.intents == []

    await engine.trigger(
        GROUP_FSM, "sunrise_started", external_ctx=_ctx(daylight=True), respect_debounce=False
    )
    dispatcher.intents.clear()
    await engine.trigger(GROUP_FSM, "sunset_started", external_ctx=_ctx(), respect_debounce=False)

    assert engine.get_state(GROUP_FSM).current_state == "ON_SCHEDULED"
    assert "turn_on" in dispatcher.services()


@pytest.mark.asyncio
async def test_feature_off_turns_manual_light_off_on_its_own_change() -> None:
    """Выключение флага гасит и свет, включённый вручную."""
    engine, dispatcher = _build()
    await engine.trigger(
        GROUP_FSM, "manual_switch_on", external_ctx=_ctx(enabled=False), respect_debounce=False
    )
    dispatcher.intents.clear()

    await engine.trigger(
        GROUP_FSM,
        "settings_changed",
        external_ctx=_ctx(enabled=False, changed_role="scheduled_feature"),
        respect_debounce=False,
    )

    assert engine.get_state(GROUP_FSM).current_state == "OFF"
    assert "turn_off" in dispatcher.services()


@pytest.mark.asyncio
async def test_other_settings_change_does_not_turn_manual_light_off() -> None:
    """Чужая настройка дома не трогает ручное включение при выключенном флаге."""
    engine, dispatcher = _build()
    await engine.trigger(
        GROUP_FSM, "manual_switch_on", external_ctx=_ctx(enabled=False), respect_debounce=False
    )
    dispatcher.intents.clear()

    await engine.trigger(
        GROUP_FSM,
        "settings_changed",
        external_ctx=_ctx(enabled=False, changed_role="covers_feature"),
        respect_debounce=False,
    )

    assert engine.get_state(GROUP_FSM).current_state == "ON_MANUAL"
    assert dispatcher.intents == []


@pytest.mark.asyncio
async def test_feature_on_after_sunset_turns_light_on_immediately() -> None:
    """Флаг включили после заката — свет зажигается сразу, если не спим."""
    engine, dispatcher = _build()

    await engine.trigger(
        GROUP_FSM,
        "settings_changed",
        external_ctx=_ctx(enabled=True, daylight=False, changed_role="scheduled_feature"),
        respect_debounce=False,
    )

    assert engine.get_state(GROUP_FSM).current_state == "ON_SCHEDULED"
    assert "turn_on" in dispatcher.services()


@pytest.mark.asyncio
async def test_feature_on_before_sunset_waits_for_sunset() -> None:
    """Днём включение флага не зажигает уличный свет."""
    engine, dispatcher = _build()

    await engine.trigger(
        GROUP_FSM,
        "settings_changed",
        external_ctx=_ctx(enabled=True, daylight=True, changed_role="scheduled_feature"),
        respect_debounce=False,
    )

    assert engine.get_state(GROUP_FSM).current_state == "OFF"
    assert dispatcher.intents == []


@pytest.mark.asyncio
async def test_startup_reapply_turns_light_off_when_feature_disabled() -> None:
    """После рестарта флаг выключен — восстановленный свет гасится."""
    engine, dispatcher = _build()
    await engine.trigger(GROUP_FSM, "sunset_started", external_ctx=_ctx(), respect_debounce=False)
    dispatcher.intents.clear()

    await engine.trigger(
        GROUP_FSM,
        "settings_changed",
        external_ctx=_ctx(enabled=False, startup=True),
        respect_debounce=False,
    )

    assert engine.get_state(GROUP_FSM).current_state == "OFF"
    assert "turn_off" in dispatcher.services()


@pytest.mark.asyncio
async def test_startup_reapply_does_not_extinguish_manual_light() -> None:
    """Рестарт не гасит свет, включённый вручную при выключенном флаге."""
    engine, dispatcher = _build()
    await engine.trigger(
        GROUP_FSM,
        "manual_switch_on",
        external_ctx=_ctx(enabled=False),
        respect_debounce=False,
    )
    dispatcher.intents.clear()

    await engine.trigger(
        GROUP_FSM,
        "settings_changed",
        external_ctx=_ctx(enabled=False, startup=True),
        respect_debounce=False,
    )

    assert engine.get_state(GROUP_FSM).current_state == "ON_MANUAL"
    assert dispatcher.intents == [], (
        "перезапуск погасил ручное включение: стартовая сверка не должна "
        "спорить с человеком, только реальное выключение флага"
    )


@pytest.mark.asyncio
async def test_watcher_does_not_repeat_sunset_when_feature_disabled() -> None:
    """Сверка молчит, когда флаг выключен: это штатное «света нет»."""
    engine, dispatcher = _build()
    watcher = DecorativeLightWatcher(
        engine=engine,
        daylight_supplier=lambda: False,
        sleeping_supplier=lambda: False,
        scheduled_light_feature_supplier=lambda: False,
        scheduled_light_entities={GROUP_FSM},
    )

    await watcher.check_once()

    assert engine.get_state(GROUP_FSM).current_state == "OFF"
    assert dispatcher.intents == []


@pytest.mark.asyncio
async def test_watcher_does_not_extinguish_manual_light_when_feature_disabled() -> None:
    """Ручное включение при выключенном флаге сверка не трогает."""
    engine, dispatcher = _build()
    await engine.trigger(
        GROUP_FSM,
        "manual_switch_on",
        external_ctx=_ctx(enabled=False),
        respect_debounce=False,
    )
    dispatcher.intents.clear()
    watcher = DecorativeLightWatcher(
        engine=engine,
        daylight_supplier=lambda: False,
        sleeping_supplier=lambda: False,
        scheduled_light_feature_supplier=lambda: False,
        scheduled_light_entities={GROUP_FSM},
    )

    await watcher.check_once()

    assert engine.get_state(GROUP_FSM).current_state == "ON_MANUAL"
    assert dispatcher.intents == [], (
        "флаг — только разрешение автоматике; ручное включение при выключенном "
        "флаге должно оставаться в силе"
    )


@pytest.mark.asyncio
async def test_device_turned_off_outside_platform_holds_manual_off() -> None:
    """Внешнее выключение группы — ручное, держим до утра."""
    engine, _ = _build()
    await engine.trigger(GROUP_FSM, "sunset_started", external_ctx=_ctx(), respect_debounce=False)

    await engine.trigger(
        GROUP_FSM,
        "device_state_diverged",
        external_ctx=_ctx(device_is_off=True),
        respect_debounce=False,
    )

    assert engine.get_state(GROUP_FSM).current_state == "OFF_MANUAL"
