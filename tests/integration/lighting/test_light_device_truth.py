"""Модель света уступает прибору, когда свет погасили вне платформы (B89).

Боевой разбор 2026-10-17, гостиная. Свет над столом погасил кто-то вне
платформы — в контексте изменения Home Assistant **не было пользователя**
(автоматизация дома или выключатель), поэтому ручным действием платформа его не
признала. Автомат остался в «горит» (`ON_HOLD`), а:

* движение в «горит» команду не шлёт — шаблон исходит из того, что включать
  нечего;
* повтор решения запрещён: мы прибору не приказывали, а спорить с чужим
  действием хуже, чем оставить расхождение (B86).

Каждое движение продлевало удержание, поэтому автомат никогда не доходил до
`OFF`, и свет не включался, пока по комнате ходили чаще, чем раз в 10 минут.

Здесь проверяется, что модель уступает прибору: сторож сообщает факт «прибор
выключен» одноразовым признаком `_device_is_off`, автомат переходит в `OFF` и
перестаёт утверждать неправду. Дальше решение принимается обычным путём —
следующее движение включает свет через `may_turn_on`, то есть с уважением к
тихим часам и «мы спим». С человеком платформа не спорит: она не включает свет
силой.

Проверка собирает настоящие фабрику, движок и роутер, как
`test_lighting_hold_after_motion_clears.py`, и смотрит на то, что видит дом.

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
import yaml

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

#: Событие сторожа о расхождении прибора и решения.
DIVERGED = "device_state_diverged"

#: Пауза между событиями: дебаунс шаблона отбрасывает всё, что чаще.
GAP_SEC = 0.6

#: Шаблоны света, которым адресован признак «прибор выключен».
LIGHT_TEMPLATES = ("lighting", "deco_light", "night_light")


class _RecordingDispatcher:
    """Диспетчер, помнящий команды вместо отправки в Home Assistant."""

    def __init__(self) -> None:
        """Создать пустой диспетчер."""
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
                                params={"motion_timeout_sec": 600},
                            )
                        ],
                    )
                ],
            )
        ],
        automation_rules=AutomationRules(global_manual_lockout_min=60),
    )


def _build() -> tuple[FSMEngine, EventRouter, _RecordingDispatcher, dict[str, Any]]:
    """Собрать боевой конвейер освещения.

    Returns:
        Движок, роутер, помнящий команды диспетчер и контекст «темно».
    """
    registry = Registry()
    register_all_actions(registry)
    register_all_guards(registry, ControlTracker())
    # День закреплён неподвижно: проверка про расхождение, а не про ночное окно.
    registry.register_guard(
        "may_turn_on", make_may_turn_on(now=lambda _tz: datetime(2026, 10, 8, 12, 0, tzinfo=UTC))
    )
    engine = FSMEngine()
    dispatcher = _RecordingDispatcher()
    engine.set_command_dispatcher(dispatcher)  # type: ignore[arg-type]
    day_context: dict[str, Any] = {"daylight": False}
    manifest = _manifest()
    FSMFactory(engine=engine, registry=registry, event_bus=None).create_and_register(manifest)
    return engine, EventRouter(manifest, engine), dispatcher, day_context


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


async def _lit_but_holding() -> tuple[FSMEngine, EventRouter, _RecordingDispatcher, dict[str, Any]]:
    """Довести свет до удержания: движение было, свет горит.

    Returns:
        Движок, роутер, диспетчер и контекст.
    """
    engine, router, dispatcher, context = _build()
    await router.route_state_change(MOTION, "on", "off", context=context)
    await asyncio.sleep(GAP_SEC)
    await router.route_state_change(MOTION, "off", "on", context=context)
    await asyncio.sleep(GAP_SEC)
    return engine, router, dispatcher, context


class TestModelYieldsToDevice:
    """Прибор выключен, а автомат считает свет горящим — модель уступает."""

    @pytest.mark.asyncio
    async def test_light_that_was_turned_off_outside_becomes_off(self) -> None:
        """Факт «прибор выключен» переводит автомат в OFF, а не в повтор решения."""
        engine, _router, dispatcher, _context = await _lit_but_holding()
        assert _state(engine) == "ON_HOLD"
        before = _services(dispatcher)

        await engine.trigger(FSM, DIVERGED, {"_device_is_off": True}, respect_debounce=False)

        assert _state(engine) == "OFF", (
            f"модель осталась в {_state(engine)!r}, хотя прибор выключен: "
            "автомат продолжит считать свет горящим, и движение его не включит"
        )
        assert _services(dispatcher) == before, (
            "в дом ушла команда: прибор уже выключен, приводить в соответствие нечего"
        )

    @pytest.mark.asyncio
    async def test_divergence_without_the_fact_still_repeats_the_decision(self) -> None:
        """Без признака поведение прежнее: решение повторяется (B64).

        Признак одноразовый и приходит только от сторожа, когда команды от нас не
        было. Обычный повтор «прибор разошёлся» обязан работать как раньше.
        """
        engine, _router, dispatcher, _context = await _lit_but_holding()
        before = len(dispatcher.intents)

        await engine.trigger(FSM, DIVERGED, None, respect_debounce=False)

        assert _state(engine) == "ON_HOLD", "автомат сменил состояние без признака прибора"
        assert len(dispatcher.intents) > before, (
            "решение не повторено: свет, который решено держать горящим, погас молча"
        )


class TestAdoptionTransitionsComeFirst:
    """У одной пары (состояние, событие) побеждает первое прошедшее условие."""

    @pytest.mark.parametrize("name", LIGHT_TEMPLATES)
    def test_adoption_is_declared_and_precedes_the_repeat(self, name: str) -> None:
        """Признание правды объявлено и стоит до повтора решения.

        Иначе повтор («свет включить») выигрывал бы у признания правды, и
        расхождение оставалось бы навсегда — ровно боевой случай 2026-10-17.
        """
        template = yaml.safe_load(Path(f"src/features/{name}.yaml").read_text(encoding="utf-8"))
        transitions = template["transitions"]

        adoption = [
            index
            for index, transition in enumerate(transitions)
            if transition.get("trigger") == DIVERGED and transition.get("guard") == "device_is_off"
        ]
        assert adoption, f"{name}: перехода «модель уступает прибору» нет"
        assert all(transitions[index].get("action") is None for index in adoption), (
            f"{name}: приведение модели в соответствие не должно командовать прибором"
        )

        for index in adoption:
            adopted = transitions[index]
            repeat = [
                other
                for other in range(len(transitions))
                if other != index
                and transitions[other].get("trigger") == DIVERGED
                and transitions[other].get("from_state") == adopted.get("from_state")
                and transitions[other].get("guard") != "device_is_off"
            ]
            assert repeat, f"{name}: у {adopted.get('from_state')!r} нет повтора решения"
            assert index < min(repeat), (
                f"{name}: повтор решения для {adopted.get('from_state')!r} стоит "
                f"раньше ({min(repeat)}) признания правды ({index}) — признак "
                "никогда не сработает"
            )
