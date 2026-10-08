"""Снятие движения не гасит свет: он держится и продлевается.

До этого шага шаблон выключал свет сразу по `motion_cleared`, а таймер в
`ON_MOTION` стоял 30 секунд. Человек встал с дивана — и свет гас, хотя в комнате
всё ещё кто-то есть. Требование владельца: «не выключать, если движение было
десять минут назад», то есть удержание после последнего движения и продление на
каждое следующее.

Проверка собирает настоящие фабрику, движок и роутер и кормит их событиями
датчика ровно так, как это делает Home Assistant. Ожидания поведения, а не
внутренних переменных: каждое состояние и каждая команда проверяются тем, что
видит дом.
"""

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any

import pytest

from core.action_handlers import register_all_actions
from core.control_tracker import ControlTracker
from core.events.event_router import EventRouter
from core.fsm.engine import FSMEngine
from core.fsm.factory import FSMFactory
from core.guards.builtin import make_may_turn_on, register_all_guards
from core.models.manifest import (
    AutomationRules,
    BehaviorConfig,
    DeviceConfig,
    InstanceConfig,
    Manifest,
    RoomConfig,
)
from core.registry import Registry


#: Комната и её датчик движения.
ROOM = "gostinaia"
MOTION = "binary_sensor.gostinaia_motion"

#: Светильник под проверкой.
LIGHT = "light.stol"

#: Автомат освещения.
FSM = f"{LIGHT}_lighting_10"

#: Сколько свет держится после последнего движения (задаётся манифестом).
HOLD_SEC = 600

#: Пауза между событиями: дебаунс шаблона отбрасывает всё, что чаще.
GAP_SEC = 0.6


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
    """Манифест с одной комнатой: датчик движения и свет.

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
                                params={"motion_timeout_sec": HOLD_SEC},
                            )
                        ],
                    )
                ],
            )
        ],
        automation_rules=AutomationRules(global_manual_lockout_min=60),
    )


def _build() -> tuple[FSMEngine, EventRouter, _RecordingDispatcher]:
    """Собрать боевой конвейер освещения.

    Returns:
        Движок, роутер и помнящий команды диспетчер.
    """
    registry = Registry()
    register_all_actions(registry)
    register_all_guards(registry, ControlTracker())
    # Часы условия «можно ли включать» закреплены на дневное время: проверка
    # про удержание, а не про ночное окно, и без закрепления она зависела бы от
    # времени запуска — после полуночи свет не включился бы и проверка про
    # удержание падала бы сама по себе.
    registry.register_guard(
        "may_turn_on", make_may_turn_on(now=lambda _tz: datetime(2026, 10, 8, 12, 0, tzinfo=UTC))
    )
    engine = FSMEngine()
    dispatcher = _RecordingDispatcher()
    engine.set_command_dispatcher(dispatcher)  # type: ignore[arg-type]
    manifest = _manifest()
    FSMFactory(engine=engine, registry=registry, event_bus=None).create_and_register(manifest)
    return engine, EventRouter(manifest, engine), dispatcher


def _state(engine: FSMEngine) -> str | None:
    """Текущее состояние автомата.

    Args:
        engine: Движок с зарегистрированным автоматом.

    Returns:
        Имя состояния либо None.
    """
    found = engine.get_state(FSM)
    return found.current_state if found is not None else None


def _services(dispatcher: _RecordingDispatcher) -> list[str]:
    """Список сервисов команд, отправленных в дом.

    Args:
        dispatcher: Помнящий команды диспетчер.

    Returns:
        Сервисы по порядку.
    """
    return [intent.service for intent in dispatcher.intents]


class TestHoldAfterMotionClears:
    """Снятие движения запускает удержание, а не выключение."""

    @pytest.mark.asyncio
    async def test_light_stays_on_when_motion_clears(self) -> None:
        """После снятия движения свет горит и команда выключения не уходит."""
        engine, router, dispatcher = _build()

        await router.route_state_change(MOTION, "on", "off")
        await asyncio.sleep(GAP_SEC)
        await router.route_state_change(MOTION, "off", "on")

        assert _state(engine) != "OFF", (
            "снятие движения выключило свет сразу: человек ещё в комнате, а "
            "свет погас — это ровно то поведение, которое запрещено"
        )
        assert "turn_off" not in _services(dispatcher), (
            f"в дом ушла команда выключения: {_services(dispatcher)}"
        )

    @pytest.mark.asyncio
    async def test_new_motion_extends_the_hold(self) -> None:
        """Новое движение возвращает автомат в режим движения и продлевает горение."""
        engine, router, dispatcher = _build()

        await router.route_state_change(MOTION, "on", "off")
        await asyncio.sleep(GAP_SEC)
        await router.route_state_change(MOTION, "off", "on")
        await asyncio.sleep(GAP_SEC)
        await router.route_state_change(MOTION, "on", "off")

        assert _state(engine) == "ON_MOTION", (
            f"новое движение должно вернуть автомат в режим движения, а он в "
            f"{_state(engine)!r} — удержание не продлевается"
        )
        # Повторно включать нечего: свет горел всё это время. Важно обратное —
        # за время удержания и нового движения ни одной команды выключения.
        assert _services(dispatcher) == ["turn_on"], (
            "пока движение продолжается, свет не должен выключаться; команды в "
            f"дом: {_services(dispatcher)}"
        )

    @pytest.mark.asyncio
    async def test_hold_expires_and_turns_the_light_off(self) -> None:
        """По истечении удержания свет выключается сам."""
        engine, router, dispatcher = _build()

        await router.route_state_change(MOTION, "on", "off")
        await asyncio.sleep(GAP_SEC)
        await router.route_state_change(MOTION, "off", "on")
        await asyncio.sleep(GAP_SEC)
        # Таймер удержания в бою прожит бы десять минут; здесь событие
        # `timeout` приходит само — так же, как его порождает движок по таймеру.
        await engine.trigger(FSM, "timeout")

        assert _state(engine) == "OFF", (
            f"по истечении удержания свет должен погаснуть, автомат в {_state(engine)!r}"
        )
        assert _services(dispatcher)[-1] == "turn_off", (
            f"после удержания ушла не команда выключения: {_services(dispatcher)}"
        )

    @pytest.mark.asyncio
    async def test_hold_duration_comes_from_manifest(self) -> None:
        """Срок удержания задаёт манифест, а не шаблон.

        Args:
            Ничего.
        """
        engine, _, _ = _build()
        definition = engine._definitions.get(FSM)  # noqa: SLF001
        assert definition is not None, "автомат не создан"

        holds = [
            transition.timeout_sec
            for transition in definition.transitions
            if transition.trigger == "timeout" and transition.timeout_sec is not None
        ]

        assert holds, "у автомата нет перехода по таймауту — удержание не чем гасить"
        assert all(value == HOLD_SEC for value in holds), (
            f"срок удержания взят не из манифеста: {holds} вместо {HOLD_SEC}"
        )
