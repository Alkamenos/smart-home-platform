"""Вечерний свет по «мы спим»: гирлянда не должна гореть после отбоя.

Боевой дефект 2026-10-10 (контейнер, ночь → утро):

    02:00:13  Entity light.girlianda_terassa_deco_light_10:
              Transition 'ON_DECO' -> 'OFF' triggered by 'day_started'
    02:12:28  WARNING  Вечерний свет не соответствует времени суток
              (sunset_started): исправляю ['light.girlianda_terassa_deco_light_10']
    02:12:28  Entity light.girlianda_terassa_deco_light_10:
              Transition 'OFF' -> 'ON_DECO' triggered by 'sunset_started'
    04:27:27  WARNING  Вечерний свет не соответствует времени суток
              (sunrise_started): исправляю ['light.girlianda_terassa_deco_light_10']
    ...       (тот же WARNING каждые 15 минут до сих пор)

Что здесь не так, по частям:

1. **Рассвет не гасит гирлянду.** Переход `ON_DECO -> OFF` по `sunrise_started`
   закрыт условием `stops_on_sunrise`, а оно истинно только для
   `off_by: "sunrise"`. Гирлянда объявлена как `off_by: "sleep"`, поэтому
   рассвет для неё — отказ `guard_failed`, и сверка повторяет его каждые
   15 минут, не сходясь никогда.

2. **Солнце в HA отстаёт от рассвета платформы.** `day_started` в 07:00 по
   часам дома погасил гирлянду, а через 12 минут сверка решила, что «темно»
   (солнце ещё `below_horizon`), и включила её обратно. Свет включился среди
   дня — то есть ровно то, чего сверка обязана не допускать.

Правильный порядок для гирлянды (`off_by: "sleep"`): гаснуть и по рассвету,
и по «мы спим». Иначе «гаснет по отбою» на практике означает «горит до
следующего перезапуска платформы».
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


GARLAND = "light.girlianda_terassa"
GARLAND_FSM = "light.girlianda_terassa_deco_light_10"
NIGHT_FSM = "light.group_nochnoe_osveshcheni_deco_light_10"
NIGHT_LIGHT = "light.group_nochnoe_osveshcheni"


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

    def devices(self) -> list[str]:
        """Устройства, для которых ушли команды.

        Returns:
            Список идентификаторов.
        """
        return [intent.device_id for intent in self.intents]

    def services(self) -> list[str]:
        """Сервисы команд, отправленных устройствам.

        Returns:
            Список сервисов.
        """
        return [intent.service for intent in self.intents]


def _manifest() -> Manifest:
    """Манифест с гирляндой и ночным освещением.

    Returns:
        Модель манифеста.
    """

    def _device(entity_id: str, name: str, off_by: str) -> DeviceConfig:
        return DeviceConfig(
            id=entity_id,
            type="light",
            behaviors=[
                BehaviorConfig(template="deco_light", priority=10, params={"off_by": off_by})
            ],
            name=name,
        )

    return Manifest(
        version=1,
        instance=InstanceConfig(
            id="probe", name="Probe", owner="probe", created_at="2026-01-01T00:00:00Z"
        ),
        rooms=[
            RoomConfig(
                id="terassa",
                name="Терраса",
                sensors={},
                devices=[_device(GARLAND, "Гирлянда", "sleep")],
            ),
            RoomConfig(
                id="noch",
                name="Ночное освещение",
                sensors={},
                devices=[_device(NIGHT_LIGHT, "Ночное освещение", "sunrise")],
            ),
        ],
        automation_rules=AutomationRules(global_manual_lockout_min=60),
    )


def _build(daylight: bool | None) -> tuple[FSMEngine, DecorativeLightWatcher, _RecordingDispatcher]:
    """Собрать движок, сверку и помнящий команды диспетчер.

    Args:
        daylight: Что «видит» сверка: True — светло, False — темно,
            None — состояние солнца неизвестно.

    Returns:
        Движок, сверка и диспетчер.
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
    watcher = DecorativeLightWatcher(engine=engine, daylight_supplier=lambda: daylight)
    return engine, watcher, dispatcher


class TestSunriseTurnsGarlandOff:
    """Рассвет гасит гирлянду, а не отказывает 15 минут подряд."""

    @pytest.mark.asyncio
    async def test_sunrise_event_turns_garland_off(self) -> None:
        """Событие рассвета переводит гирлянду в OFF.

        Returns:
            Ничего.
        """
        engine, _, dispatcher = _build(daylight=False)

        # Темно: гирлянда включается, автомат считает себя включённым.
        await engine.trigger(GARLAND_FSM, "sunset_started", respect_debounce=False)
        dispatcher.intents.clear()

        await engine.trigger(GARLAND_FSM, "sunrise_started", respect_debounce=False)

        assert engine.get_state(GARLAND_FSM).current_state == "OFF", (
            "гирлянда объявлена как off_by: sleep, но рассвет не должен оставлять "
            "её гореть: свет на террасе нужен вечером, а не утром"
        )
        assert "turn_off" in dispatcher.services(), (
            f"по рассвету должна уйти команда выключения, а ушли: {dispatcher.services()}"
        )

    @pytest.mark.asyncio
    async def test_watcher_converges_after_sunrise(self) -> None:
        """Сверка сходится за один проход, а не повторяет отказ каждые 15 минут.

        Returns:
            Ничего.
        """
        engine, watcher, dispatcher = _build(daylight=False)
        watcher._daylight = lambda: False  # noqa: SLF001
        await watcher.check_once()
        dispatcher.intents.clear()

        # Наступило утро: солнце над горизонтом.
        watcher._daylight = lambda: True  # noqa: SLF001
        await watcher.check_once()

        assert engine.get_state(GARLAND_FSM).current_state == "OFF", (
            "после рассвета гирлянда должна быть выключена"
        )

        # Второй проход подряд: расхождения больше нет — значит и повторов нет.
        dispatcher.intents.clear()
        await watcher.check_once()

        assert dispatcher.intents == [], (
            f"сверка не сошлась и продолжает слать команды каждые 15 минут: {dispatcher.services()}"
        )

    @pytest.mark.asyncio
    async def test_night_light_still_stops_on_sleep_ignored(self) -> None:
        """Ночное освещение (`off_by: sunrise`) по рассвету тоже гаснет.

        Returns:
            Ничего.
        """
        engine, _, _ = _build(daylight=False)
        await engine.trigger(NIGHT_FSM, "sunset_started", respect_debounce=False)
        await engine.trigger(NIGHT_FSM, "sunrise_started", respect_debounce=False)

        state = engine.get_state(NIGHT_FSM)
        assert state.current_state == "OFF", "ночное освещение горит до рассвета, не после"


class TestGarlandStopsOnSleep:
    """Гирлянда гаснет по модификатору «мы спим» — как и объявлено."""

    @pytest.mark.asyncio
    async def test_sleep_turns_garland_off(self) -> None:
        """`sleep_started` гасит гирлянду.

        Returns:
            Ничего.
        """
        engine, _, dispatcher = _build(daylight=False)
        await engine.trigger(GARLAND_FSM, "sunset_started", respect_debounce=False)
        dispatcher.intents.clear()

        await engine.trigger(GARLAND_FSM, "sleep_started", respect_debounce=False)

        assert engine.get_state(GARLAND_FSM).current_state == "OFF", (
            "гирлянда объявлена как гаснущая по «мы спим» — событие должно гасить её"
        )
        assert "turn_off" in dispatcher.services()

    @pytest.mark.asyncio
    async def test_sleep_does_not_stop_night_light(self) -> None:
        """Ночное освещение по «мы спим» не гаснет — так и задумано.

        Returns:
            Ничего.
        """
        engine, _, _ = _build(daylight=False)
        night = NIGHT_FSM
        await engine.trigger(night, "sunset_started", respect_debounce=False)

        await engine.trigger(night, "sleep_started", respect_debounce=False)

        assert engine.get_state(night).current_state == "ON_DECO", (
            "ночное освещение живёт до рассвета и модификатором «мы спим» не гасится"
        )
