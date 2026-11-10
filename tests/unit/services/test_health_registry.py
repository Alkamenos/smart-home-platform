"""Реестр проблем: first_seen, закрытие, группы и сохранение."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from core.persistence.health_store import HealthStore
from core.services.health_registry import HealthRegistry


TZ = timezone(timedelta(hours=5))
BASE = datetime(2026, 11, 9, 12, 0, tzinfo=TZ)


class _Clock:
    """Часы, которые двигает тест."""

    def __init__(self, moment: datetime) -> None:
        self.moment = moment

    def __call__(self) -> datetime:
        return self.moment

    def advance(self, **kwargs: int) -> None:
        self.moment += timedelta(**kwargs)


def _problem(kind: str = "stale", subject: str = "sensor.temperature") -> dict:
    return {
        "kind": kind,
        "subject": subject,
        "name": "Температура",
        "area": "Спальня",
        "detail": "молчит 2 ч",
        "source": "health",
        "value": "21.4",
    }


def _registry(tmp_path, clock: _Clock) -> HealthRegistry:
    return HealthRegistry(HealthStore(tmp_path / "health.json"), clock=clock)


def test_open_problem_gets_id_and_first_seen(tmp_path) -> None:
    """Новая проблема получает идентификатор и время обнаружения."""
    clock = _Clock(BASE)
    registry = _registry(tmp_path, clock)

    grouped = registry.observe_report([_problem()], BASE.isoformat())

    assert registry.snapshot()["count"] == 1
    group = grouped[0]
    assert group["subject"] == "sensor.temperature"
    assert group["first_seen"] == BASE.isoformat()
    assert group["reasons"][0]["kind"] == "stale"
    assert group["level"] == "warning"


def test_repeated_observation_keeps_first_seen(tmp_path) -> None:
    """Повторный обход обновляет last_seen, но не first_seen."""
    clock = _Clock(BASE)
    registry = _registry(tmp_path, clock)
    registry.observe_report([_problem()], BASE.isoformat())

    clock.advance(minutes=15)
    later = clock().isoformat()
    registry.observe_report([_problem()], later)

    group = registry.snapshot()["problems"][0]
    assert group["first_seen"] == BASE.isoformat()
    assert group["last_seen"] == later


def test_missing_problem_is_closed(tmp_path) -> None:
    """Проблема, которой нет в новом снимке, закрывается."""
    clock = _Clock(BASE)
    registry = _registry(tmp_path, clock)
    registry.observe_report([_problem()], BASE.isoformat())

    clock.advance(minutes=15)
    registry.observe_report([], clock().isoformat())

    assert registry.snapshot()["count"] == 0
    assert registry.active == ()


def test_problem_reappears_after_close_with_new_first_seen(tmp_path) -> None:
    """Вернувшаяся проблема — новое occurrence, а не старая запись."""
    clock = _Clock(BASE)
    registry = _registry(tmp_path, clock)
    registry.observe_report([_problem()], BASE.isoformat())
    clock.advance(minutes=15)
    registry.observe_report([], clock().isoformat())

    clock.advance(hours=2)
    again = clock().isoformat()
    registry.observe_report([_problem()], again)

    group = registry.snapshot()["problems"][0]
    assert group["first_seen"] == again


def test_two_reasons_of_one_subject_are_grouped(tmp_path) -> None:
    """Две причины одной сущности — одна строка с двумя reasons."""
    registry = _registry(tmp_path, _Clock(BASE))

    grouped = registry.observe_report(
        [
            _problem("device_mismatch"),
            _problem("command_not_applied"),
        ],
        BASE.isoformat(),
    )

    assert len(grouped) == 1
    assert len(grouped[0]["reasons"]) == 2


def test_health_report_does_not_close_command_problem(tmp_path) -> None:
    """Снимок здоровья закрывает только свои проблемы, не чужие."""
    clock = _Clock(BASE)
    registry = _registry(tmp_path, clock)
    command = _problem("command_not_applied", "light.probe")
    command["source"] = "command"
    registry.observe_report([_problem()], BASE.isoformat(), source="health")
    registry.observe_report([command], BASE.isoformat(), source="command")

    clock.advance(minutes=1)
    registry.observe_report([_problem()], clock().isoformat(), source="health")

    kinds = {
        reason["kind"] for group in registry.snapshot()["problems"] for reason in group["reasons"]
    }
    assert "stale" in kinds
    assert "command_not_applied" in kinds

    clock.advance(minutes=1)
    registry.observe_report([_problem()], clock().isoformat())

    kinds = {group["reasons"][0]["kind"] for group in registry.snapshot()["problems"]}
    assert "command_not_applied" not in kinds


def test_fingerprint_is_stable_and_changes_with_set(tmp_path) -> None:
    """Отпечаток не зависит от порядка и меняется при новой проблеме."""
    registry = _registry(tmp_path, _Clock(BASE))
    registry.observe_report([_problem()], BASE.isoformat())
    first = registry.fingerprint()

    registry.observe_report([_problem()], BASE.isoformat())
    assert registry.fingerprint() == first

    registry.observe_report(
        [_problem(), _problem("low_battery", "sensor.temperature_battery")],
        BASE.isoformat(),
    )
    assert registry.fingerprint() != first


def test_registry_survives_reload(tmp_path) -> None:
    """Активная проблема и first_seen переживают перезапуск."""
    clock = _Clock(BASE)
    registry = _registry(tmp_path, clock)
    registry.observe_report([_problem()], BASE.isoformat())

    clock.advance(minutes=15)
    later = clock().isoformat()
    restored = _registry(tmp_path, clock)
    restored.observe_report([_problem()], later)

    group = restored.snapshot()["problems"][0]
    assert group["first_seen"] == BASE.isoformat()
    assert group["last_seen"] == later
