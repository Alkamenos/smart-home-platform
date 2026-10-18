"""Сводка проблем: читаемый текст и проблемы автоматов (B79).

Владелец смотрит дом с телефона: «4» в карточке ничего не говорит, нужно «что
именно и где». Поэтому проверки держат две вещи:

* проблемы автоматов (зависание, расхождение «модель ↔ прибор», потеря связи)
  попадают в ту же сводку, что и проблемы датчиков;
* формулировка человеческая: место, имя и причина, а не код вида `fsm_stuck`.
"""

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from dataclasses import dataclass

from core.services.problems import (
    PROBLEM_DEVICE_MISMATCH,
    PROBLEM_FSM_STUCK,
    PROBLEM_HA_DISCONNECTED,
    compose_report,
    summary_text,
    watchdog_problems,
)


AREAS = {"light.svet_nad_stolom": ("комната", "Гостиная")}
NAMES = {"light.svet_nad_stolom": "Свет над столом"}


@dataclass
class Entry:
    """Запись снимка сторожа, нужная сводке."""

    entity_id: str = "light.svet_nad_stolom_lighting_10"
    device: str = "light.svet_nad_stolom"
    state: str = "ON_MOTION"
    stuck: bool = False
    expected_timeout_sec: float | None = None
    device_state: str | None = None
    mismatch_reason: str | None = None

    @property
    def mismatch_is_fault(self) -> bool:
        """Считать ли расхождение отказом.

        Returns:
            True для отказа прибора.
        """
        return self.mismatch_reason in {"device_unavailable", "command_not_applied"}


@dataclass
class Snapshot:
    """Снимок сторожа."""

    entries: list[Entry]
    taken_at: str = "2026-10-18T09:00:00"
    ha_disconnected: bool = False


class TestWatchdogProblems:
    """Сторож отдаёт проблемы автоматов человеческим языком."""

    def test_stuck_fsm_is_a_problem(self) -> None:
        """Зависший автомат назван местом и временем удержания."""
        snapshot = Snapshot([Entry(stuck=True, expected_timeout_sec=600)])

        problems = watchdog_problems(snapshot, device_names=NAMES, areas=AREAS)

        assert len(problems) == 1
        assert problems[0]["kind"] == PROBLEM_FSM_STUCK
        assert problems[0]["area"] == "Гостиная"
        assert problems[0]["name"] == "Свет над столом"
        assert "ON_MOTION" in problems[0]["detail"]
        assert "10 мин" in problems[0]["detail"]

    def test_mismatch_fault_is_a_problem(self) -> None:
        """Расхождение-отказ названо моделью и прибором."""
        snapshot = Snapshot(
            [
                Entry(
                    device_state="off",
                    mismatch_reason="command_not_applied",
                )
            ]
        )

        problems = watchdog_problems(snapshot, device_names=NAMES, areas=AREAS)

        assert len(problems) == 1
        assert problems[0]["kind"] == PROBLEM_DEVICE_MISMATCH
        assert "модель ON_MOTION" in problems[0]["detail"]
        assert "прибор off" in problems[0]["detail"]

    def test_manual_yield_is_not_a_fault(self) -> None:
        """Уступка человеку (прибор выключен вручную) тревогой не считается."""
        snapshot = Snapshot([Entry(device_state="off", mismatch_reason="device_off_decision_on")])

        assert watchdog_problems(snapshot, device_names=NAMES, areas=AREAS) == []

    def test_ha_disconnected_is_a_problem(self) -> None:
        """Потеря связи с домом — отдельная проблема."""
        snapshot = Snapshot([], ha_disconnected=True)

        problems = watchdog_problems(snapshot)

        assert [item["kind"] for item in problems] == [PROBLEM_HA_DISCONNECTED]

    def test_no_snapshot_means_no_problems(self) -> None:
        """Сторож ещё не проверял — проблем автоматов нет."""
        assert watchdog_problems(None) == []


class TestComposeReport:
    """Обход дома и сторож сводятся в один снимок."""

    def test_health_and_watchdog_are_merged(self) -> None:
        """Оба источника в одной сводке, счётчик — число проблем."""
        health = {
            "generated_at": "2026-10-18T08:30:00",
            "sensor_count": 139,
            "problems": [
                {"kind": "low_battery", "name": "Батарейка", "area": "Терраса", "detail": ""}
            ],
        }
        snapshot = Snapshot([Entry(stuck=True, expected_timeout_sec=300)])

        report = compose_report(health, snapshot, device_names=NAMES, areas=AREAS)

        assert report["count"] == 2
        assert report["sensor_count"] == 139
        assert report["generated_at"] == "2026-10-18T08:30:00"
        kinds = [item["kind"] for item in report["problems"]]
        assert kinds == ["low_battery", PROBLEM_FSM_STUCK]

    def test_health_absent_is_tolerated(self) -> None:
        """Обход ещё не проходил — сводка всё равно собирается."""
        report = compose_report(None, Snapshot([], ha_disconnected=True))

        assert report["count"] == 1


class TestSummaryText:
    """Состояние сущности — читаемая строка, а не число."""

    def test_no_problems_says_so(self) -> None:
        """«Проблем нет» честнее нуля."""
        assert summary_text([]) == "Проблем нет"

    def test_problems_are_named_with_place_and_reason(self) -> None:
        """Видно место, имя и причину — то, что владелец и просил."""
        text = summary_text(
            [
                {"kind": "unavailable", "name": "Батарея", "area": "Грядки"},
                {"kind": PROBLEM_FSM_STUCK, "name": "Свет над столом", "area": "Гостиная"},
            ]
        )

        assert text.startswith("2: ")
        assert "Грядки: Батарея — не отвечает" in text
        assert "Гостиная: Свет над столом — автомат завис" in text

    def test_long_summary_is_cut(self) -> None:
        """Слишком длинная строка обрезается, а не ломает состояние."""
        problems = [
            {"kind": "stale", "name": f"Датчик {index}", "area": "Комната"} for index in range(60)
        ]

        text = summary_text(problems)

        assert len(text) <= 240
        assert text.endswith("…")
