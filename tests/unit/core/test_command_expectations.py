"""Трекер ожиданий: команда записана, применена или провалена."""

from __future__ import annotations

from core.commands.expectations import CommandExpectationTracker


NOW = 1_800_000_000.0


class _Clock:
    def __init__(self, moment: float) -> None:
        self.moment = moment

    def __call__(self) -> float:
        return self.moment


def test_turn_on_is_recorded_as_on() -> None:
    """Команда включения ждёт состояние on."""
    tracker = CommandExpectationTracker(clock=lambda: NOW)

    expectation = tracker.record("light.x", "light", "turn_on")

    assert expectation is not None
    assert expectation.expected_state == "on"
    assert tracker.pending(NOW) == (expectation,)


def test_command_without_state_is_ignored() -> None:
    """Таймер и текст не меняют состояние — ожидания нет."""
    tracker = CommandExpectationTracker(clock=lambda: NOW)

    assert tracker.record("number.timer", "number", "set_value") is None
    assert tracker.pending(NOW) == ()


def test_new_command_replaces_previous_expectation() -> None:
    """Повторная команда по прибору заменяет прежнее ожидание."""
    tracker = CommandExpectationTracker(clock=lambda: NOW)

    tracker.record("cover.x", "cover", "open_cover")
    tracker.record("cover.x", "cover", "close_cover")

    pending = tracker.pending(NOW)
    assert len(pending) == 1
    assert pending[0].expected_state == "closed"


def test_applied_and_transitional_checks() -> None:
    """Совпадение и переходные состояния распознаются."""
    tracker = CommandExpectationTracker(clock=lambda: NOW)
    expectation = tracker.record("light.x", "light", "turn_on")

    assert expectation is not None
    assert tracker.is_applied(expectation, "on") is True
    assert tracker.is_applied(expectation, "off") is False
    assert tracker.is_transitional("closing") is True
    assert tracker.is_transitional("on") is False


def test_expired_expectation_is_dropped() -> None:
    """Просроченное ожидание не копится вечно."""
    clock = _Clock(NOW)
    tracker = CommandExpectationTracker(clock=clock, ttl_sec=600)
    tracker.record("light.x", "light", "turn_on")

    clock.moment = NOW + 601

    assert tracker.pending() == ()


def test_reaching_expected_state_clears_expectation() -> None:
    """Прибор дошёл до ожидаемого состояния — ожидание снято."""
    tracker = CommandExpectationTracker(clock=lambda: NOW)
    tracker.record("light.x", "light", "turn_on")

    tracker.observe_state("light.x", "off", "on")

    assert tracker.pending(NOW) == ()


def test_leaving_expected_state_clears_stale_expectation() -> None:
    """Прибор был в ожидаемом состоянии и ушёл из него — это не отказ команды.

    Событие ``on`` могло прийти до записи ожидания; уход ``on`` → ``off``
    всё равно доказывает, что команда когда-то применилась.
    """
    tracker = CommandExpectationTracker(clock=lambda: NOW)
    tracker.record("light.x", "light", "turn_on")

    tracker.observe_state("light.x", "on", "off")

    assert tracker.pending(NOW) == ()


def test_unrelated_state_change_keeps_expectation() -> None:
    """Постороннее изменение состояния не снимает ожидание."""
    tracker = CommandExpectationTracker(clock=lambda: NOW)
    tracker.record("light.x", "light", "turn_on")

    tracker.observe_state("light.x", "unavailable", "off")

    assert len(tracker.pending(NOW)) == 1


def test_problem_names_command_and_actual_state() -> None:
    """Проблема объясняет, какая команда и что ответил прибор."""
    tracker = CommandExpectationTracker(clock=lambda: NOW)
    expectation = tracker.record("light.x", "light", "turn_on")

    assert expectation is not None
    problem = tracker.problem(
        expectation,
        actual="off",
        area="Спальня",
        name="Свет",
        now=NOW + 360,
    )

    assert problem["kind"] == "command_not_applied"
    assert "turn_on" in problem["detail"]
    assert "off" in problem["detail"]
