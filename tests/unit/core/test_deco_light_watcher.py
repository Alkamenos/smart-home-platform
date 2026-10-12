"""Сверка вечернего света: потерянный закат не оставляет дом тёмным.

Боевой случай 2026-10-09: закат в 18:32 прошёл, пока вечернего поведения в
манифесте ещё не было. Событие не повторилось, и ночное освещение не
загорелось — ждать следующего заката пришлось бы сутки.

Сверка спрашивает не «было ли событие», а «темно ли сейчас и горит ли нужный
свет». Важно, что она **молчит**, когда состояние совпадает с решением: иначе
в журнале каждые 15 минут появлялись бы пустые переходы и утренний разбор
захлебнулся бы шумом.
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


def _build(
    daylight: bool | None, sleeping: bool = False
) -> tuple[FSMEngine, DecorativeLightWatcher, _RecordingDispatcher]:
    """Собрать движок, сверку и помнящий команды диспетчер.

    Args:
        daylight: Что «видит» сверка: True — светло, False — темно,
            None — состояние солнца неизвестно.
        sleeping: Включён ли модификатор «мы спим».

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
    watcher = DecorativeLightWatcher(
        engine=engine, daylight_supplier=lambda: daylight, sleeping_supplier=lambda: sleeping
    )
    return engine, watcher, dispatcher


class TestLostSunsetIsCaught:
    """Потерянный закат: сверка включает свет сама."""

    @pytest.mark.asyncio
    async def test_dark_evening_turns_light_on(self) -> None:
        """Темно, а вечерний свет выключен — сверка его включает.

        Returns:
            Ничего.
        """
        _, watcher, dispatcher = _build(daylight=False)

        await watcher.check_once()

        assert GARLAND in dispatcher.devices(), (
            f"в темноте при выключенном свете сверка должна включить гирлянду, "
            f"а ушли команды: {dispatcher.devices()}"
        )

    @pytest.mark.asyncio
    async def test_bright_morning_turns_light_off(self) -> None:
        """Светло, а вечерний свет горит — сверка его гасит.

        Returns:
            Ничего.
        """
        engine, watcher, dispatcher = _build(daylight=True)
        # Сначала темно: свет включается и автомат считает себя включённым.
        watcher._daylight = lambda: False  # noqa: SLF001
        await watcher.check_once()
        dispatcher.intents.clear()

        watcher._daylight = lambda: True  # noqa: SLF001
        await watcher.check_once()

        assert "turn_off" in [intent.service for intent in dispatcher.intents], (
            f"утром вечерний свет должен погаснуть: {dispatcher.intents}"
        )
        assert engine.get_state("light.girlianda_terassa_deco_light_10") is not None


class TestQuietWhenNothingToDo:
    """Совпадает — молчит."""

    @pytest.mark.asyncio
    async def test_dark_and_lit_sends_nothing(self) -> None:
        """Темно, а свет уже горит — команд не отправляется.

        Returns:
            Ничего.
        """
        _, watcher, dispatcher = _build(daylight=False)
        watcher._daylight = lambda: False  # noqa: SLF001
        await watcher.check_once()
        dispatcher.intents.clear()

        await watcher.check_once()

        assert dispatcher.intents == [], (
            f"свет уже горит, а сверка всё равно вмешалась: {dispatcher.devices()}"
        )


class TestUnknownSunIsSilence:
    """Неизвестно — молчит, а не гасит."""

    @pytest.mark.asyncio
    async def test_unknown_daylight_sends_nothing(self) -> None:
        """Состояние солнца не прочитано — сверка не трогает свет.

        Returns:
            Ничего.
        """
        _, watcher, dispatcher = _build(daylight=None)

        await watcher.check_once()

        assert dispatcher.intents == [], (
            "при неизвестном состоянии солнца сверка обязана молчать: иначе она "
            "выключила бы свет среди ночи из-за молчания датчика"
        )


class TestSleepDoesNotRelight:
    """Отбой учитывается: свет, гаснущий по «мы спим», не возвращают."""

    @pytest.mark.asyncio
    async def test_garland_stays_off_while_sleeping(self) -> None:
        """Ночью при «мы спим» гирлянда не включается обратно.

        Боевой дефект 2026-10-13: сторож видел «темно, а света нет» и возвращал
        гирлянду через минуту после отбоя. Ночное освещение (`off_by: sunrise`)
        при этом гореть обязано.

        Returns:
            Ничего.
        """
        _, watcher, dispatcher = _build(daylight=False, sleeping=True)

        await watcher.check_once()

        assert GARLAND not in dispatcher.devices(), (
            f"гирлянда включилась ночью при отбое: {dispatcher.devices()} — "
            "её погасил модификатор «мы спим», и возвращать её нельзя"
        )
        assert NIGHT_LIGHT in dispatcher.devices(), (
            "ночное освещение должно гореть до рассвета, даже когда мы спим"
        )

    @pytest.mark.asyncio
    async def test_lit_garland_is_turned_off_when_sleep_starts(self) -> None:
        """Если гирлянда всё же горит при отбое — сторож её гасит.

        Returns:
            Ничего.
        """
        _, watcher, dispatcher = _build(daylight=False, sleeping=False)
        await watcher.check_once()  # темно, не спим — гирлянда включается
        assert GARLAND in dispatcher.devices()
        dispatcher.intents.clear()

        watcher._sleeping_supplier = lambda: True  # noqa: SLF001
        await watcher.check_once()

        garland_off = [
            intent
            for intent in dispatcher.intents
            if intent.device_id == GARLAND and intent.service == "turn_off"
        ]
        assert garland_off, (
            f"гирлянда горит при отбое, а сторож её не погасил: {dispatcher.intents}"
        )


class TestWatcherDescribe:
    """Описание сверки — для журнала и готовности."""

    def test_describe_reports_state(self) -> None:
        """Описание содержит интервал и признак «светло».

        Returns:
            Ничего.
        """
        _, watcher, _ = _build(daylight=False)

        described = watcher.describe()

        assert described["interval_minutes"] == 15.0
        assert described["daylight"] is False
        assert described["running"] is False
