"""Тесты взвода таймера перехода — почему таймауты не срабатывали (Known Issue #66).

Дефект: движок взводил таймер по ``timeout_sec`` **сработавшего** перехода
(``src/core/fsm/engine.py``). Шаблоны же объявляют ``timeout_sec`` на
**исходящем** переходе: в ``lighting.yaml`` это
``ON_MOTION --[timeout]--> OFF, timeout_sec=30.0``, тогда как переход
``OFF --[motion_detected]--> ON_MOTION`` таймера не несёт. В итоге переход в
``ON_MOTION`` проходил без таймера, состояние жило вечно, а ``expected_timeout_sec``
(который читает исходящие переходы) возвращал 30.0 — то есть сторож видел
ожидание, которого движок не выполнял.

Смысл ``timeout_sec`` — «сколько можно находиться в состоянии до ухода», а это
свойство состояния, а не конкретного входа в него. Поэтому таймер должен
взводиться по исходящим переходам нового состояния, а ``expected_timeout_sec`` уже
считает именно так — два механизма обязаны читать одно и то же.

Файлы шаблонов не меняются: проверяется движок.
"""

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import asyncio

from core import FSMDefinition, FSMEngine, Transition


FSM_ID = "light.kitchen_lighting_10"


def template_definition() -> FSMDefinition:
    """Описание в форме реальных шаблонов: таймер на исходящем переходе.

    Именно так объявлен `lighting.yaml`, и именно такая форма не работала.

    Returns:
        Описание автомата света.
    """
    return FSMDefinition(
        entity_id=FSM_ID,
        initial_state="OFF",
        states=("OFF", "ON_MOTION", "ON_MANUAL"),
        transitions=(
            Transition(from_state="OFF", to_state="ON_MOTION", trigger="motion_detected"),
            Transition(
                from_state="ON_MOTION",
                to_state="OFF",
                trigger="timeout",
                timeout_sec=0.05,
            ),
        ),
    )


def _state_of(engine: FSMEngine, entity_id: str) -> str:
    """Возвращает имя текущего состояния автомата.

    Args:
        engine: Движок машин состояний.
        entity_id: Идентификатор автомата.

    Returns:
        Имя текущего состояния.
    """
    state = engine.get_state(entity_id)
    assert state is not None, "автомат не зарегистрирован"
    return state.current_state


class TestTimeoutScheduling:
    """Взвод таймера по исходящим переходам нового состояния.

    Часть проверок (отмена таймера прежнего состояния) описывает поведение,
    существовавшее и до починки: `trigger` снимает таймеры автомата в начале
    обработки. Они оставлены как защита от отката при будущих правках взвода.
    """

    async def test_should_fire_timeout_event_when_timer_armed(self) -> None:
        """Таймер, объявленный на исходящем переходе, действительно срабатывает."""
        engine = FSMEngine()
        engine.register_definition(template_definition())

        assert await engine.trigger(FSM_ID, "motion_detected", trace_id="t1") is True
        assert _state_of(engine, FSM_ID) == "ON_MOTION"

        await asyncio.sleep(0.2)

        assert _state_of(engine, FSM_ID) == "OFF", (
            "таймер не сработал: переход по триггеру 'timeout' не произошёл"
        )

    async def test_should_not_leave_timer_armed_after_timeout_fired(self) -> None:
        """После срабатывания таймер снят: повторных переходов не будет."""
        engine = FSMEngine()
        engine.register_definition(template_definition())
        await engine.trigger(FSM_ID, "motion_detected", trace_id="t1")

        await asyncio.sleep(0.2)
        assert _state_of(engine, FSM_ID) == "OFF"

        # Из OFF триггера 'timeout' нет: лишний таймер проявил бы себя падением
        # или повторным переходом при следующем движении.
        await engine.trigger(FSM_ID, "motion_detected", trace_id="t2")
        await asyncio.sleep(0.2)
        assert _state_of(engine, FSM_ID) == "OFF"

    async def test_should_arm_timer_matching_expected_timeout_sec(self) -> None:
        """Взведённый таймер и ожидание сторожа берутся из одного места.

        Расхождение этих двух величин и было дефектом: сторож ждал 30 секунд,
        а движок не взводил ничего.
        """
        engine = FSMEngine()
        engine.register_definition(template_definition())

        assert engine.expected_timeout_sec(FSM_ID) is None, "OFF ждёт события, не таймера"

        await engine.trigger(FSM_ID, "motion_detected", trace_id="t1")

        assert engine.expected_timeout_sec(FSM_ID) == 0.05
        await asyncio.sleep(0.2)
        assert _state_of(engine, FSM_ID) == "OFF"
        assert engine.expected_timeout_sec(FSM_ID) is None


class TestIncomingTransitionTimeoutStillWorks:
    """Совместимость: таймер на входящем переходе тоже должен работать."""

    async def test_should_fire_when_timeout_declared_on_taken_transition(self) -> None:
        """Обе формы объявления приводят к срабатыванию.

        Раньше работала только форма «таймер на входящем переходе» — её и
        использовали тесты движка, поэтому дефект шаблонов не был виден.

        Переход по триггеру `timeout` должен быть объявлен явно: сам таймер лишь
        порождает событие, а что из него выйдет — решает описание автомата.
        """
        engine = FSMEngine()
        engine.register_definition(
            FSMDefinition(
                entity_id=FSM_ID,
                initial_state="OFF",
                states=("OFF", "ON_MOTION"),
                transitions=(
                    Transition(
                        from_state="OFF",
                        to_state="ON_MOTION",
                        trigger="motion_detected",
                        timeout_sec=0.05,
                    ),
                    Transition(from_state="ON_MOTION", to_state="OFF", trigger="timeout"),
                ),
            )
        )

        await engine.trigger(FSM_ID, "motion_detected", trace_id="t1")
        assert _state_of(engine, FSM_ID) == "ON_MOTION"

        await asyncio.sleep(0.2)
        assert _state_of(engine, FSM_ID) == "OFF"

    async def test_should_use_largest_timeout_when_several_leave_state(self) -> None:
        """Из состояния уходит несколько переходов — берётся наибольший таймер."""
        engine = FSMEngine()
        engine.register_definition(
            FSMDefinition(
                entity_id=FSM_ID,
                initial_state="OFF",
                states=("OFF", "ON", "STANDBY"),
                transitions=(
                    Transition(from_state="OFF", to_state="ON", trigger="start"),
                    Transition(
                        from_state="ON", to_state="OFF", trigger="timeout", timeout_sec=0.05
                    ),
                    Transition(
                        from_state="ON",
                        to_state="STANDBY",
                        trigger="short",
                        timeout_sec=0.01,
                    ),
                ),
            )
        )

        await engine.trigger(FSM_ID, "start", trace_id="t1")
        assert engine.expected_timeout_sec(FSM_ID) == 0.05

        await asyncio.sleep(0.25)
        assert _state_of(engine, FSM_ID) == "OFF"


class TestNoSpuriousTimer:
    """Состояния без таймеров не должны получать таймер."""

    async def test_should_not_arm_timer_when_no_outgoing_transition_has_timeout(self) -> None:
        """Обычный переход без таймеров не оставляет задачу в движке."""
        engine = FSMEngine()
        engine.register_definition(
            FSMDefinition(
                entity_id=FSM_ID,
                initial_state="OFF",
                states=("OFF", "ON"),
                transitions=(
                    Transition(from_state="OFF", to_state="ON", trigger="start"),
                    Transition(from_state="ON", to_state="OFF", trigger="stop"),
                ),
            )
        )

        await engine.trigger(FSM_ID, "start", trace_id="t1")

        assert engine.expected_timeout_sec(FSM_ID) is None
        assert not engine._timers, "взведён таймер там, где таймаут не объявлен"

        await asyncio.sleep(0.1)
        assert _state_of(engine, FSM_ID) == "ON"

    async def test_should_cancel_previous_timer_when_leaving_state_early(self) -> None:
        """Ранний уход из состояния отменяет его таймер."""
        engine = FSMEngine()
        engine.register_definition(
            FSMDefinition(
                entity_id=FSM_ID,
                initial_state="OFF",
                states=("OFF", "ON", "MANUAL"),
                transitions=(
                    Transition(from_state="OFF", to_state="ON", trigger="start"),
                    Transition(from_state="ON", to_state="OFF", trigger="timeout", timeout_sec=0.2),
                    Transition(from_state="ON", to_state="MANUAL", trigger="manual"),
                ),
            )
        )

        await engine.trigger(FSM_ID, "start", trace_id="t1")
        await asyncio.sleep(0.02)
        original_task = engine._timers[FSM_ID]

        await engine.trigger(FSM_ID, "manual", trace_id="t2")
        assert _state_of(engine, FSM_ID) == "MANUAL"
        # У MANUAL нет исходящего перехода по триггеру timeout, поэтому таймер
        # не взводится вовсе — из реестра движка он должен исчезнуть.
        assert FSM_ID not in engine._timers

        # Проверяется именно отмена задачи, а не только итоговое состояние:
        # из MANUAL триггера 'timeout' нет, поэтому осиротевший таймер просто не
        # нашёл бы перехода и состояние всё равно осталось бы MANUAL. Прежняя
        # редакция проверки проходила при незаведённой отмене.
        await asyncio.sleep(0.05)
        assert original_task.cancelled() or original_task.done(), (
            "таймер прежнего состояния не отменён и сработает вхолостую"
        )

        await asyncio.sleep(0.3)
        assert _state_of(engine, FSM_ID) == "MANUAL"
