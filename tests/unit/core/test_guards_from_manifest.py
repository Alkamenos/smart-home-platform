"""Срок ручной блокировки и суточное окно берутся из дома, а не из кода (аудит К-9, К-11).

Прежде сборка условий не получала настроек дома: срок блокировки был зашит (60
минут), а окно дня — «07:00–23:00» из константы. Правка манифеста действовала
наполовину: посредник ручного вмешательства разблокировал по новому сроку, а
условия света и декора продолжали отказывать по старому; окно тишины из манифеста
не влияло на возврат оверрайда вовсе (06:30 против зашитых 07:00).

Здесь проверяется решение: что именно берётся из правил дома и что остаётся
запасным значением.
"""

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from typing import Any

from core.control_tracker import ControlTracker
from core.guards.builtin import _day_range, _lockout_minutes, register_all_guards


class _Rules:
    """Правила дома в объёме, который нужен условиям."""

    def __init__(
        self,
        *,
        lockout: int | None = 60,
        quiet_from: str | None = "23:00",
        quiet_to: str | None = "06:30",
        morning_at: str | None = "07:00",
        night_off_at: str | None = "23:00",
    ) -> None:
        """Собрать правила.

        Args:
            lockout: Глобальный срок ручной блокировки.
            quiet_from: Начало тишины.
            quiet_to: Конец тишины.
            morning_at: Начало дня по суточному циклу.
            night_off_at: Конец дня по суточному циклу.
        """
        lighting = type(
            "Lighting",
            (),
            {
                "quiet_from": quiet_from,
                "quiet_to": quiet_to,
                "morning_at": morning_at,
                "night_off_at": night_off_at,
            },
        )
        self.global_manual_lockout_min = lockout
        self.lighting = lighting()


class _Registry:
    """Реестр условий, запоминающий имена."""

    def __init__(self) -> None:
        """Собрать пустой реестр."""
        self.names: list[str] = []

    def register_guard(self, name: str, guard: Any) -> None:
        """Запомнить условие.

        Args:
            name: Имя условия.
            guard: Само условие.
        """
        del guard
        self.names.append(name)


class TestLockoutComesFromTheHouse:
    """Срок блокировки — свойство дома, а не кода."""

    def test_lockout_is_taken_from_rules(self) -> None:
        """Срок из правил действует.

        Returns:
            Ничего.
        """
        assert _lockout_minutes(_Rules(lockout=30)) == 30

    def test_missing_rules_fall_back_to_default(self) -> None:
        """Без правил остаётся запасное значение.

        Returns:
            Ничего.
        """
        assert _lockout_minutes(None) == 60

    def test_non_positive_lockout_does_not_disable_the_wait(self) -> None:
        """Ноль или минус не отменяют блокировку: остаётся запасное значение.

        Returns:
            Ничего.
        """
        assert _lockout_minutes(_Rules(lockout=0)) == 60
        assert _lockout_minutes(_Rules(lockout=-5)) == 60


class TestDayWindowComesFromTheSchedule:
    """Окно дня — это то, что не тишина."""

    def test_day_window_is_built_from_the_day_cycle(self, monkeypatch: Any) -> None:
        """Границы дня берутся у суточного цикла, а не у тишины.

        Тем самым условие считает день так же, как события, которые получает свет.

        Args:
            monkeypatch: Подмена переменных окружения.

        Returns:
            Ничего.
        """
        monkeypatch.delenv("DAY_TIME_RANGE", raising=False)

        assert _day_range(_Rules()) == "07:00-23:00"

    def test_quiet_hours_are_used_without_the_cycle(self, monkeypatch: Any) -> None:
        """Без расписания дня берётся окно тишины — тоже свойство дома.

        Args:
            monkeypatch: Подмена переменных окружения.

        Returns:
            Ничего.
        """
        monkeypatch.delenv("DAY_TIME_RANGE", raising=False)

        rules = _Rules(morning_at=None, night_off_at=None)

        assert _day_range(rules) == "06:30-23:00"

    def test_environment_still_overrides(self, monkeypatch: Any) -> None:
        """Переменная окружения остаётся ручкой для разбора в доме.

        Args:
            monkeypatch: Подмена переменных окружения.

        Returns:
            Ничего.
        """
        monkeypatch.setenv("DAY_TIME_RANGE", "09:00-18:00")

        assert _day_range(_Rules()) == "09:00-18:00"

    def test_missing_schedule_falls_back_to_default(self, monkeypatch: Any) -> None:
        """Без расписания остаётся запасное окно.

        Args:
            monkeypatch: Подмена переменных окружения.

        Returns:
            Ничего.
        """
        monkeypatch.delenv("DAY_TIME_RANGE", raising=False)

        assert (
            _day_range(_Rules(quiet_from=None, quiet_to=None, morning_at=None, night_off_at=None))
            == "07:00-23:00"
        )


def test_registration_passes_house_settings(monkeypatch: Any) -> None:
    """Сборка реестра передаёт условия с настройками дома.

    Args:
        monkeypatch: Подмена переменных окружения.

    Returns:
        Ничего.
    """
    monkeypatch.delenv("DAY_TIME_RANGE", raising=False)
    registry = _Registry()

    register_all_guards(registry, ControlTracker(), automation_rules=_Rules(lockout=25))

    assert "is_manual_override_enabled" in registry.names
    assert "is_day_time" in registry.names
    assert len(registry.names) >= 30, (
        f"зарегистрировано подозрительно мало условий: {len(registry.names)}"
    )
