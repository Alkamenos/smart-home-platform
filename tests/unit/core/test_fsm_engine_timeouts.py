"""
Тесты ``expected_timeout_sec`` — допустимого времени пребывания в состоянии.

Метод нужен сторожу, чтобы отличить зависший автомат от нормального состояния
(FR-013). Значение выводится из описания автомата: движок взводит таймер
таймаута при переходе, поэтому «правильное» время ожидания уже описано, а
ручной порог в конфигурации был бы вторым источником правды.

Принцип проверки: ни выбор перехода, ни дебаунс, ни сам механизм таймаутов не
меняются — добавляется только чтение.

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0
"""

from __future__ import annotations

from core import FSMDefinition, FSMEngine, Transition


FSM_ID = "light.kitchen_lighting_10"


def make_engine() -> FSMEngine:
    """Движок без хранилища и шины: проверяется только чтение описания."""
    return FSMEngine()


def timed_definition() -> FSMDefinition:
    """Описание, у которого переход из начального состояния имеет таймаут."""
    return FSMDefinition(
        entity_id=FSM_ID,
        initial_state="off",
        states=("off", "on", "standby"),
        transitions=(
            Transition(from_state="off", to_state="on", trigger="motion_detected"),
            Transition(
                from_state="on",
                to_state="standby",
                trigger="motion_cleared",
                timeout_sec=30.0,
            ),
            Transition(from_state="standby", to_state="off", trigger="timeout"),
        ),
    )


class TestDeviceIdOf:
    """Проверки определения устройства по описанию автомата."""

    def test_should_return_device_from_definition_when_registered(self) -> None:
        """Устройство берётся из описания, а не разбирается из имени."""
        engine = make_engine()
        engine.register_definition(
            FSMDefinition(
                entity_id="fan.bathroom_humidity_ventilation_5",
                initial_state="idle",
                states=("idle", "on"),
                transitions=(Transition(from_state="idle", to_state="on", trigger="humid"),),
                target_device_id="fan.bathroom",
            ),
            restore_state=False,
        )

        # Имя шаблона содержит подчёркивание, поэтому разбор идентификатора
        # относил бы часть имени устройства к шаблону.
        assert engine.device_id_of("fan.bathroom_humidity_ventilation_5") == "fan.bathroom"

    def test_should_return_none_when_entity_not_registered(self) -> None:
        """Незарегистрированный автомат устройства не имеет."""
        assert make_engine().device_id_of("light.absent_10") is None


class TestExpectedTimeoutSec:
    """Проверки вывода допустимого времени пребывания."""

    def test_should_return_none_when_entity_not_registered(self) -> None:
        """Незарегистрированный автомат проверять нечего."""
        engine = make_engine()

        assert engine.expected_timeout_sec("light.absent_10") is None

    def test_should_return_none_when_current_state_has_no_transitions(self) -> None:
        """Конечное состояние стабильно по построению и не считается зависшим."""
        engine = make_engine()
        engine.register_definition(
            FSMDefinition(
                entity_id=FSM_ID,
                initial_state="done",
                states=("done",),
                transitions=(Transition(from_state="done", to_state="done", trigger="noop"),),
            ),
            restore_state=False,
        )

        assert engine.expected_timeout_sec(FSM_ID) is None

    def test_should_return_none_when_outgoing_transitions_have_no_timeout(self) -> None:
        """Состояние без таймингованных переходов ждёт события, а не времени."""
        engine = make_engine()
        engine.register_definition(timed_definition(), restore_state=False)

        # Начальное состояние — off, из него переход без таймаута.
        assert engine.expected_timeout_sec(FSM_ID) is None

    def test_should_return_timeout_of_outgoing_timed_transition_when_in_state(self) -> None:
        """Из состояния берётся таймаут ведущего из него перехода."""
        engine = make_engine()
        engine.register_definition(timed_definition(), restore_state=False)
        engine.reset_state(FSM_ID, "on")

        assert engine.expected_timeout_sec(FSM_ID) == 30.0

    def test_should_return_maximum_when_several_timed_transitions_leave_state(self) -> None:
        """При нескольких таймингованных переходах берётся самый долгий."""
        engine = make_engine()
        engine.register_definition(
            FSMDefinition(
                entity_id=FSM_ID,
                initial_state="off",
                states=("off", "on", "standby", "eco"),
                transitions=(
                    Transition(
                        from_state="off",
                        to_state="on",
                        trigger="motion_detected",
                        timeout_sec=10.0,
                    ),
                    Transition(
                        from_state="off",
                        to_state="standby",
                        trigger="presence",
                        timeout_sec=90.0,
                    ),
                    Transition(
                        from_state="off",
                        to_state="eco",
                        trigger="nobody",
                    ),
                    Transition(from_state="on", to_state="off", trigger="timeout"),
                ),
            ),
            restore_state=False,
        )

        assert engine.expected_timeout_sec(FSM_ID) == 90.0

    def test_should_ignore_timeouts_of_transitions_from_other_states(self) -> None:
        """Таймауты переходов из других состояний не влияют на текущее."""
        engine = make_engine()
        engine.register_definition(timed_definition(), restore_state=False)
        engine.reset_state(FSM_ID, "standby")

        assert engine.expected_timeout_sec(FSM_ID) is None

    def test_should_return_none_when_timeout_not_positive(self) -> None:
        """Нулевой таймаут не является ожиданием состояния."""
        engine = make_engine()
        engine.register_definition(
            FSMDefinition(
                entity_id=FSM_ID,
                initial_state="off",
                states=("off", "on"),
                transitions=(
                    Transition(
                        from_state="off",
                        to_state="on",
                        trigger="motion_detected",
                        timeout_sec=0.0,
                    ),
                ),
            ),
            restore_state=False,
        )

        assert engine.expected_timeout_sec(FSM_ID) is None

    def test_should_not_change_transition_behaviour_when_reading(self) -> None:
        """Чтение не влияет ни на переходы, ни на таймеры (конституция I)."""
        import asyncio

        async def run() -> None:
            engine = make_engine()
            engine.register_definition(timed_definition(), restore_state=False)

            assert await engine.trigger(FSM_ID, "motion_detected") is True
            assert engine.get_state(FSM_ID) is not None
            assert engine.get_state(FSM_ID).current_state == "on"
            # Таймер взведён только на переход с таймаутом, а не на чтение.
            assert engine.expected_timeout_sec(FSM_ID) == 30.0
            assert FSM_ID not in engine._timers
            await engine.shutdown()

        asyncio.run(run())
