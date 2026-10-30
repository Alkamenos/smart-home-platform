"""Вечерняя яркость без движения: переход в DIM, а не выключение (B104).

Свет над столом вечером не гаснет по таймауту: он остаётся на 3 % с общей
температурой дома, а новое движение снова даёт полную яркость. Утром условие
не срабатывает — до полудня темнота предрассветная, и свет должен гаснуть:
именно из-за этого утреннего 3 % и появилась задача (боевая находка 27.10).
"""

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from core.action_handlers import register_all_actions
from core.control_tracker import ControlTracker
from core.events.event_router import EventRouter
from core.fsm.engine import FSMEngine
from core.fsm.factory import FSMFactory
from core.guards.builtin import make_may_turn_on, register_all_guards
from core.guards.lighting import make_dims_when_idle
from core.models.manifest import (
    AutomationRules,
    BehaviorConfig,
    DeviceConfig,
    InstanceConfig,
    Manifest,
    RoomConfig,
)
from core.registry import Registry


ROOM = "gostinaia"
MOTION = "binary_sensor.gostinaia_motion"
LIGHT = "light.stol"
FSM = f"{LIGHT}_lighting_10"
HOLD_SEC = 600
GAP_SEC = 0.6
TZ = ZoneInfo("Asia/Yekaterinburg")
EVENING = datetime(2026, 10, 27, 20, 0, tzinfo=TZ)
MORNING = datetime(2026, 10, 28, 8, 0, tzinfo=TZ)


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
    """Манифест с одной лампой и её вечерней яркостью."""
    return Manifest(
        version=1,
        instance=InstanceConfig(
            id="probe", name="Probe", owner="probe", created_at="2026-01-01T00:00:00Z"
        ),
        rooms=[
            RoomConfig(
                id=ROOM,
                name="Гостиная",
                sensors={"motion": MOTION},
                devices=[
                    DeviceConfig(
                        id=LIGHT,
                        type="light",
                        behaviors=[
                            BehaviorConfig(
                                template="lighting",
                                priority=10,
                                params={
                                    "motion_timeout_sec": HOLD_SEC,
                                    "brightness_pct": 100,
                                    "dim_when_idle": True,
                                    "dim_brightness_pct": 3,
                                },
                            )
                        ],
                    )
                ],
            )
        ],
        automation_rules=AutomationRules(global_manual_lockout_min=60),
    )


def _build(at: datetime) -> tuple[FSMEngine, EventRouter, _RecordingDispatcher, dict[str, Any]]:
    """Собрать конвейер с закреплённым временем условия DIM."""
    registry = Registry()
    register_all_actions(registry)
    register_all_guards(registry, ControlTracker())
    # Условие включения и условие DIM закреплены: проверка про поведение, а не
    # про время запуска теста.
    registry.register_guard(
        "may_turn_on", make_may_turn_on(now=lambda _tz: datetime(2026, 10, 8, 12, 0, tzinfo=UTC))
    )
    registry.register_guard("dims_when_idle", make_dims_when_idle(now=lambda tz: at.astimezone(tz)))
    engine = FSMEngine()
    dispatcher = _RecordingDispatcher()
    engine.set_command_dispatcher(dispatcher)  # type: ignore[arg-type]
    context: dict[str, Any] = {"daylight": False}
    manifest = _manifest()
    FSMFactory(engine=engine, registry=registry, event_bus=None).create_and_register(manifest)
    return engine, EventRouter(manifest, engine), dispatcher, context


def _state(engine: FSMEngine) -> str | None:
    """Текущее состояние автомата."""
    found = engine.get_state(FSM)
    return found.current_state if found is not None else None


def _last_intent(dispatcher: _RecordingDispatcher) -> Any:
    """Последняя команда, отправленная в дом."""
    assert dispatcher.intents, "в дом не ушло ни одной команды"
    return dispatcher.intents[-1]


async def _reach_hold(engine: FSMEngine, router: EventRouter, context: dict[str, Any]) -> None:
    """Довести автомат до удержания после движения."""
    await router.route_state_change(MOTION, "on", "off", context=context)
    await asyncio.sleep(GAP_SEC)
    await router.route_state_change(MOTION, "off", "on", context=context)
    # Дебаунс шаблона: событие timeout сразу после motion_cleared было бы
    # отброшено, а проверка ждёт именно истечения удержания.
    await asyncio.sleep(GAP_SEC)


class TestEveningDim:
    """Вечером таймаут оставляет 3 %, движение возвращает полный свет."""

    @pytest.mark.asyncio
    async def test_timeout_keeps_dim_instead_of_off(self) -> None:
        """Вечером без движения свет не гаснет, а остаётся на 3 %."""
        engine, router, dispatcher, context = _build(EVENING)
        await _reach_hold(engine, router, context)
        assert _state(engine) == "ON_HOLD"

        await engine.trigger(FSM, "timeout")

        assert _state(engine) == "DIM", "вечером свет должен остаться тусклым"
        intent = _last_intent(dispatcher)
        assert intent.service == "turn_on"
        assert intent.data["brightness_pct"] == 3
        assert "rgb_color" not in intent.data, "это не красный ночник"
        assert intent.data["transition"] == 2, "затухание должно быть плавным"

    @pytest.mark.asyncio
    async def test_motion_returns_full_brightness_from_dim(self) -> None:
        """Новое движение из DIM снова включает полную яркость."""
        engine, router, dispatcher, context = _build(EVENING)
        await _reach_hold(engine, router, context)
        await engine.trigger(FSM, "timeout")
        assert _state(engine) == "DIM"
        await asyncio.sleep(GAP_SEC)

        await router.route_state_change(MOTION, "on", "off", context=context)

        assert _state(engine) == "ON_MOTION"
        intent = _last_intent(dispatcher)
        assert intent.service == "turn_on"
        assert intent.data["brightness_pct"] == 100

    @pytest.mark.asyncio
    async def test_day_started_turns_dim_off(self) -> None:
        """Утреннее событие гасит вечернюю яркость, а не оставляет её на день."""
        engine, router, dispatcher, context = _build(EVENING)
        await _reach_hold(engine, router, context)
        await engine.trigger(FSM, "timeout")
        assert _state(engine) == "DIM"
        await asyncio.sleep(GAP_SEC)

        await engine.trigger(FSM, "day_started")

        assert _state(engine) == "OFF"
        assert _last_intent(dispatcher).service == "turn_off"

    @pytest.mark.asyncio
    async def test_morning_timeout_turns_off(self) -> None:
        """Утром таймаут гасит свет: 3 % на всё утро — тот самый дефект."""
        engine, router, dispatcher, context = _build(MORNING)
        await _reach_hold(engine, router, context)
        assert _state(engine) == "ON_HOLD"

        await engine.trigger(FSM, "timeout")

        assert _state(engine) == "OFF", "до полудня вечерняя яркость не включается"
        assert _last_intent(dispatcher).service == "turn_off"

    @pytest.mark.asyncio
    async def test_quiet_hours_does_not_change_a_just_lit_light(self) -> None:
        """В 23:00 свет над столом не меняется — только таймаут даёт 3 %.

        Боевая находка 30.10: движение в 22:59:58 включало полный свет, а
        `quiet_hours_started` в 23:00:02 принудительно переводил его в DIM.
        Человек ещё в комнате, поэтому 23:00 для такой лампы — пустое событие.
        """
        engine, router, dispatcher, context = _build(EVENING)
        await router.route_state_change(MOTION, "on", "off", context=context)
        assert _state(engine) == "ON_MOTION"
        await asyncio.sleep(GAP_SEC)

        dispatcher.intents.clear()
        await engine.trigger(
            FSM,
            "quiet_hours_started",
            respect_debounce=False,
        )

        assert _state(engine) == "ON_MOTION", "23:00 не должно менять только что включённый свет"
        assert dispatcher.intents == [], "23:00 не должно отправлять команду свету"

        await asyncio.sleep(GAP_SEC)
        await router.route_state_change(MOTION, "off", "on", context=context)
        await asyncio.sleep(GAP_SEC)
        await engine.trigger(FSM, "timeout")

        assert _state(engine) == "DIM", "3 % должны прийти по таймауту, а не в 23:00"
