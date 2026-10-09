"""Суточный цикл доходит до автоматов и гасит свет в назначенный час.

Проверяется связка целиком: часы отдают событие по расписанию дома, цикл
находит только те автоматы, у которых переход на это событие есть, и отправляет
им команду. Свет гаснет сам — в комнатах без датчиков движения иначе он
остался бы гореть всю ночь.
"""

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import asyncio
import datetime as dt
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from core.action_handlers import register_all_actions
from core.control_tracker import ControlTracker
from core.events.event_router import EventRouter
from core.fsm.engine import FSMEngine
from core.fsm.factory import FSMFactory
from core.guards.builtin import make_may_turn_on, register_all_guards
from core.models.manifest import (
    BehaviorConfig,
    DeviceConfig,
    InstanceConfig,
    Manifest,
    RoomConfig,
)
from core.registry import Registry
from core.scheduling.daily import DailyClock
from core.services.day_cycle import DayCycleService


HOUSE = ZoneInfo("Asia/Yekaterinburg")


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


def _engine() -> tuple[FSMEngine, _RecordingDispatcher, Any]:
    """Движок с двумя автоматами света и записывающим команды диспетчером.

    Returns:
        Движок, диспетчер и роутер.
    """
    registry = Registry()
    register_all_actions(registry)
    register_all_guards(registry, ControlTracker())
    engine = FSMEngine()
    dispatcher = _RecordingDispatcher()
    engine.set_command_dispatcher(dispatcher)  # type: ignore[arg-type]
    manifest = Manifest(
        version=1,
        instance=InstanceConfig(
            id="probe", name="Probe", owner="probe", created_at="2026-01-01T00:00:00Z"
        ),
        rooms=[
            RoomConfig(
                id=room_id,
                name=room_id,
                sensors={"motion": f"binary_sensor.{room_id}_motion"},
                devices=[
                    DeviceConfig(
                        id=device_id,
                        type="light",
                        behaviors=[BehaviorConfig(template="lighting", priority=10, params={})],
                    )
                ],
            )
            for room_id, device_id in (("sad", "light.vse_fonari"), ("ulitsa", "light.nochnoe"))
        ],
    )
    # Часы условия закреплены на дневное время, а «темнота» передаётся в
    # движении явно: иначе включение не произойдёт и гасить будет нечего.
    registry.register_guard(
        "may_turn_on",
        make_may_turn_on(now=lambda _tz: dt.datetime(2026, 10, 9, 22, 0, tzinfo=HOUSE)),
    )
    manifest = _with_motion_sensors(manifest)
    FSMFactory(engine=engine, registry=registry, event_bus=None).create_and_register(manifest)
    return engine, dispatcher, EventRouter(manifest, engine)


def _service(now: dt.datetime) -> DayCycleService:
    """Цикл с фиксированным временем и расписанием 23:00/07:00.

    Args:
        now: Значение «сейчас».

    Returns:
        Готовый сервис.
    """
    clock = DailyClock(
        {dt.time(23, 0): "quiet_hours_started", dt.time(7, 0): "day_started"},
        timezone=HOUSE,
        now=lambda: now,
        sleep=lambda _s: __import__("asyncio").sleep(0),
    )
    engine, dispatcher, router = _engine()
    service = DayCycleService(clock=clock, engine=engine)
    service.dispatcher = dispatcher  # type: ignore[attr-defined]
    service.router = router  # type: ignore[attr-defined]
    return service


class TestLightsGoOutOnSchedule:
    """В назначенный час свет гаснет сам."""

    @pytest.mark.asyncio
    async def test_quiet_hours_turns_lights_off(self) -> None:
        """В 23:00 по-домашнему уходит команда выключения.

        Свет сперва включается движением — гасить нечего, если он выключен, и
        проверка на пустом состоянии ничего бы не доказывала.

        Returns:
            Ничего.
        """
        service = _service(dt.datetime(2026, 10, 9, 22, 59, tzinfo=HOUSE))
        dispatcher = service.dispatcher  # type: ignore[attr-defined]
        await _turn_lights_on(service)

        dispatcher.intents.clear()
        await service.handle("quiet_hours_started")

        services = [intent.service for intent in dispatcher.intents]
        assert services, "в час X никто не погас: команда выключения не ушла"
        assert all(item == "turn_off" for item in services), f"ушли не те команды: {services}"
        assert len(services) == 2, f"погас не весь свет: {services}"

    @pytest.mark.asyncio
    async def test_hold_state_is_extinguished_too(self) -> None:
        """Свет в состоянии ожидания (человек ушёл) тоже гаснет.

        Returns:
            Ничего.
        """
        service = _service(dt.datetime(2026, 10, 9, 22, 59, tzinfo=HOUSE))
        dispatcher = service.dispatcher  # type: ignore[attr-defined]
        router = service.router  # type: ignore[attr-defined]
        await _turn_lights_on(service)
        await asyncio.sleep(0.6)  # дебаунс шаблона
        for motion in ("binary_sensor.sad_motion", "binary_sensor.ulitsa_motion"):
            await router.route_state_change(motion, "off", "on", context={"daylight": False})
        holding = [
            key
            for key, value in service.engine.get_all_states().items()
            if value.current_state == "ON_HOLD"
        ]
        assert holding, (
            f"автоматы не дошли до состояния ожидания: {service.engine.get_all_states()}"
        )

        dispatcher.intents.clear()
        await service.handle("quiet_hours_started")

        assert [intent.service for intent in dispatcher.intents] == ["turn_off"] * len(holding)

    @pytest.mark.asyncio
    async def test_day_start_does_not_touch_devices(self) -> None:
        """Утреннее событие команд не отправляет: свет уже выключен.

        Returns:
            Ничего.
        """
        service = _service(dt.datetime(2026, 10, 10, 7, 0, tzinfo=HOUSE))

        await service.handle("day_started")

        assert service.dispatcher.intents == []  # type: ignore[attr-defined]

    def test_only_automat_that_can_extinguish_is_touched(self) -> None:
        """Событие получают только те автоматы, где переход на него есть.

        Returns:
            Ничего.
        """
        engine, _dispatcher, _router = _engine()

        affected = engine.entities_with_trigger("quiet_hours_started")
        ignored = engine.entities_with_trigger("day_started_tomorrow")

        assert affected == ["light.vse_fonari_lighting_10", "light.nochnoe_lighting_10"]
        assert ignored == [], f"несуществующее событие нашло адресатов: {ignored}"


class TestScheduleSurvivesDebounce:
    """Расписание применяется, даже если только что было движение.

    Дебаунс шаблона нужен, чтобы датчик не дрожал: два события подряд — отсечка.
    Но для события по часам это превращается в «свет не погас»: датчик зафиксировал
    движение, через 0.1 с наступило 23:00, событие отброшено как дребезг, и свет
    горит до утра — ровно то, ради чего расписание и писалось.
    """

    @pytest.mark.asyncio
    async def test_quiet_hours_applies_right_after_motion(self) -> None:
        """Событие по часам не отбрасывается дебаунсом.

        Returns:
            Ничего.
        """
        service = _service(dt.datetime(2026, 10, 9, 22, 59, tzinfo=HOUSE))
        dispatcher = service.dispatcher  # type: ignore[attr-defined]
        await _turn_lights_on(service)

        # без паузы: событие приходит в пределах окна дебаунса
        await service.handle("quiet_hours_started")

        states = {
            key: value.current_state for key, value in service.engine.get_all_states().items()
        }
        assert set(states.values()) == {"OFF"}, f"свет не погас: {states}"
        assert [intent.service for intent in dispatcher.intents[-2:]] == ["turn_off", "turn_off"], (
            "команды выключения не ушли"
        )


class TestScheduleFollowsHouseClock:
    """Час расписания — час дома."""

    def test_evening_off_is_house_2300(self) -> None:
        """Расписание строится по часам дома, а не контейнера.

        Returns:
            Ничего.
        """
        clock = DailyClock(
            {dt.time(23, 0): "quiet_hours_started"},
            timezone=HOUSE,
            now=lambda: dt.datetime(2026, 10, 9, 14, 0, tzinfo=HOUSE),
        )

        when, event = clock.next_occurrence(  # type: ignore[misc]
            dt.datetime(2026, 10, 9, 14, 0, tzinfo=HOUSE)
        )

        assert event == "quiet_hours_started"
        assert when.hour == 23


async def _turn_lights_on(service: DayCycleService) -> None:
    """Включить оба автомата движением — как это делает дом днём.

    Args:
        service: Сервис суточного цикла.
    """
    router = service.router  # type: ignore[attr-defined]
    for motion in ("binary_sensor.sad_motion", "binary_sensor.ulitsa_motion"):
        await router.route_state_change(motion, "on", "off", context={"daylight": False})


def _with_motion_sensors(manifest: Manifest) -> Manifest:
    """Оставить манифест как есть: датчики уже прописаны при сборке.

    Args:
        manifest: Модель манифеста.

    Returns:
        Тот же манифест.
    """
    return manifest
