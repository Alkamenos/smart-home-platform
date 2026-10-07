"""Условие перехода должно получать данные, которых ждёт.

Третий случай того же класса, что ручная блокировка и доставка состояний:
**механизм есть, выглядит исправным, а данных ему никто не передаёт**.
Описанное в манифесте поведение вентиляции по влажности не может сработать:
условие читает `humidity` из контекста перехода, куда его не кладёт ни один
модуль production-кода. Отказ при этом честный — «нет данных, запрет» — и
неотличим от «данные есть, значение не подходит».

Почему это важно именно сейчас
------------------------------

Владелец описал вентиляцию с порогом и ждёт включения вентилятора. Он не может
отличить «влажность ниже порога» от «влажности не было никогда». Первый случай —
штатная работа, второй — молчащая поломка, и оба выглядят одинаково.

Что проверяется
---------------

1. Значение выше порога даёт переход, ниже — отказ.
2. Нечисловое значение («unavailable») даёт отказ, а не сравнение с нулём.
3. Данных нет — отказ с отдельной причиной, отличимой от «условие не прошло».
4. Условие объявляет требуемые данные; проверка наличия идёт **до** вызова.
5. Причина видна и в счётчике отказов, и в записи о переходах.

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from core.fsm.engine import FSMEngine
from core.guards.builtin import build_guards, with_requirements


#: Порог из манифеста — в бою 65, а имя условия содержит 60.
THRESHOLD = 65.0


class _Subscribers:
    """Движок, собирающий отказы, чтобы причина была наблюдаемой."""

    def __init__(self) -> None:
        """Создать пустой сборщик."""
        self.reasons: list[str] = []

    def record(self, reasons: dict[str, int]) -> None:
        """Принять счётчик причин от движка.

        Args:
            reasons: Счётчик «причина → число».
        """
        self.reasons.extend(reasons)


def _engine_with_guard(guard_name: str = "humidity_above_60") -> tuple[FSMEngine, _Subscribers]:
    """Движок с одним условием и подменой счётчика причин.

    Args:
        guard_name: Имя регистрируемого условия.

    Returns:
        Движок и сборщик причин отказа.
    """
    engine = FSMEngine()
    tracker = MagicMock()
    tracker.was_manual_within.return_value = False
    for name, guard in build_guards(tracker).items():
        engine.register_guard(name, guard)
    assert guard_name in engine._guards
    return engine, _Subscribers()


def _context(humidity: Any) -> dict[str, Any]:
    """Контекст перехода с заданной влажностью и порогом.

    Args:
        humidity: Значение влажности; ``None`` — ключа нет вовсе.

    Returns:
        Контекст, как его видит условие.
    """
    context: dict[str, Any] = {"entity_id": "fan.bathroom", "humidity_threshold": THRESHOLD}
    if humidity is not None:
        context["humidity"] = humidity
    return context


class TestGuardReadsThresholdFromManifest:
    """Порог берётся из манифеста, а не из имени условия."""

    @pytest.mark.parametrize("value", [66.0, 70.5, "70.5"])
    def test_above_manifest_threshold_passes(self, value: Any) -> None:
        """Выше порога из манифеста — переход разрешён."""
        engine, _ = _engine_with_guard()

        assert engine._evaluate_guard("humidity_above_60", "fan.bathroom", _context(value))

    @pytest.mark.parametrize("value", [64.9, 50.0, "50"])
    def test_below_manifest_threshold_denies(self, value: Any) -> None:
        """Ниже порога — переход запрещён, и это штатная работа."""
        engine, _ = _engine_with_guard()

        assert not engine._evaluate_guard("humidity_above_60", "fan.bathroom", _context(value))

    def test_threshold_in_manifest_wins_over_guard_name(self) -> None:
        """Значение 61 не проходит: порог манифеста 65, а не 60 из имени.

        Имя `humidity_above_60` содержит 60, и при пороге 65 значение 61 должно
        отклониться. Если бы условие читало число из имени, проверка прошла бы.
        """
        engine, _ = _engine_with_guard()

        assert not engine._evaluate_guard("humidity_above_60", "fan.bathroom", _context(61))


class TestMissingDataIsNotZero:
    """Нечисловое значение не превращается в ноль молча."""

    @pytest.mark.parametrize("value", ["unavailable", "", "нет данных"])
    def test_non_numeric_value_denies(self, value: str) -> None:
        """Ноль — это число, и молчаливое сравнение выдало бы его за честное."""
        engine, _ = _engine_with_guard()

        assert not engine._evaluate_guard("humidity_above_60", "fan.bathroom", _context(value))

    def test_missing_key_denies(self) -> None:
        """Ключа нет вовсе — переход не выполняется."""
        engine, _ = _engine_with_guard()

        assert not engine._evaluate_guard("humidity_above_60", "fan.bathroom", _context(None))


class TestMissingDataIsDistinguishable:
    """«Данных не было» и «значение не подходит» — разные причины."""

    def test_missing_data_has_its_own_reason(self) -> None:
        """Отказ по отсутствию данных называется иначе, чем отказ условия.

        Без этого владелец не может ответить на вопрос «почему вентиляция не
        включилась»: оба случая дают одну и ту же формулировку.
        """
        engine, _ = _engine_with_guard()

        reason = engine._guard_rejection_reason("humidity_above_60", "fan.bathroom", _context(None))

        assert reason == "guard_data_missing", (
            f"отказ по отсутствию данных не отличим от отказа условия: {reason!r}"
        )

    def test_below_threshold_leaves_verdict_to_guard(self) -> None:
        """Данные на месте — вердикт выносит само условие.

        Проверка наличия данных отвечает только «есть или нет». Значение 50 ниже
        порога — это работа условия, и причина отказа будет «условие не прошло».
        """
        engine, _ = _engine_with_guard()

        reason = engine._guard_rejection_reason("humidity_above_60", "fan.bathroom", _context(50))

        assert reason is None, (
            f"при наличии данных проверка требований молчит, а не отказывает: {reason}"
        )
        assert not engine._evaluate_guard("humidity_above_60", "fan.bathroom", _context(50)), (
            "условие обязано отказать при значении ниже порога"
        )

    def test_reason_reaches_rejection_counter(self) -> None:
        """Причина попадает в счётчик отказов, а не остаётся в тексте.

        Счётчик — то, что оператор читает, не открывая журнал.
        """
        engine, _ = _engine_with_guard()

        engine._record_rejection(
            "fan.bathroom_humidity_ventilation_5",
            "humidity_changed",
            "guard_data_missing",
        )

        assert engine.rejection_counts().get("guard_data_missing") == 1, (
            f"причина не учтена в счётчике отказов: {engine.rejection_counts()}"
        )


class TestGuardDeclaresItsData:
    """Условие объявляет, какие данные ему нужны."""

    def test_requirements_are_declared(self) -> None:
        """Требования объявляются при регистрации, а не выводятся из тела."""
        guard = with_requirements(lambda _state, _ctx: True, "humidity")

        assert guard.requires == ("humidity",)

    def test_guard_without_requirements_stays_compatible(self) -> None:
        """Условие без объявления не ломает переходы неожиданным отказом.

        Обратная совместимость: условие, добавленное позже и забывшее объявить
        требования, должно вести себя как раньше, а не отказывать всегда.
        """
        engine, _ = _engine_with_guard()

        assert engine._guard_rejection_reason("is_day_time", "light.kitchen_lighting_5", {}) is None

    def test_missing_required_key_is_detected(self) -> None:
        """Движок находит недостающий ключ до вызова условия."""
        engine = FSMEngine()

        guard = with_requirements(lambda _state, _ctx: True, "humidity")
        engine.register_guard("needs_humidity", guard)

        assert (
            engine._guard_rejection_reason("needs_humidity", "fan.bathroom", {})
            == "guard_data_missing"
        )

    def test_present_key_passes_requirement_check(self) -> None:
        """Есть данные — проверка требований проходит."""
        engine = FSMEngine()

        guard = with_requirements(lambda _state, _ctx: True, "humidity")
        engine.register_guard("needs_humidity", guard)

        assert (
            engine._guard_rejection_reason("needs_humidity", "fan.bathroom", {"humidity": 70})
            is None
        )


class TestConditionalGuardsAreExempt:
    """Условие без данных не должно отказывать само по себе."""

    def test_humidity_guard_declares_humidity(self) -> None:
        """Встроенное условие влажности объявляет свою зависимость.

        Иначе проверка требований ничего о нём не знает, и влажность снова будет
        молчаливо отсутствовать.
        """
        tracker = MagicMock()
        guards = build_guards(tracker)

        assert getattr(guards["humidity_above_60"], "requires", ()) == ("humidity",)
        assert getattr(guards["humidity_below_60"], "requires", ()) == ("humidity",)

    def test_day_time_guard_needs_no_data(self) -> None:
        """Условие «дневное время» данных не требует: оно читает часы.

        Объявлять ему зависимость не от чего — иначе оно отказывало бы всегда.
        """
        tracker = MagicMock()
        guards = build_guards(tracker)

        assert getattr(guards["is_day_time"], "requires", ()) == ()
