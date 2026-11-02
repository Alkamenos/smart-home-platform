"""Проверки классов отказов (спека 018, D5).

Три класса должны различаться без чтения кода: ожидаемое состояние не тревога,
дефект — тревога, авария — отдельный приоритет.

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0
"""

from __future__ import annotations

from core.errors import (
    DomainDefectError,
    ExpectedConditionError,
    PlatformError,
    SafetyViolationError,
)


class TestFailureTaxonomy:
    """Классы отказов не смешиваются."""

    def test_expected_condition_is_not_a_fault(self) -> None:
        """Нет данных — не дефект."""
        error = ExpectedConditionError("датчик молчит")

        assert error.is_fault is False
        assert error.code == "expected_condition"
        assert error.to_dict()["message"] == "датчик молчит"

    def test_domain_defect_is_a_fault(self) -> None:
        """Непредвиденная ошибка — дефект."""
        error = DomainDefectError("деление на ноль в расчёте")

        assert error.is_fault is True
        assert error.code == "internal_error"

    def test_safety_violation_is_a_fault(self) -> None:
        """Нарушение безопасности — отказ с отдельным кодом."""
        error = SafetyViolationError("обогреватель оставлен включённым")

        assert error.is_fault is True
        assert error.code == "safety_violation"

    def test_code_can_be_overridden(self) -> None:
        """Код можно уточнить, не меняя класс."""
        error = ExpectedConditionError("уставка вне диапазона", code="setpoint_unavailable")

        assert error.code == "setpoint_unavailable"
        assert error.is_fault is False

    def test_all_inherit_platform_error(self) -> None:
        """Все классы — одна база, чтобы граница ловила их вместе."""
        for cls in (ExpectedConditionError, DomainDefectError, SafetyViolationError):
            assert issubclass(cls, PlatformError)
