"""Таксономия отказов платформы (спека 018, US5, T064)."""

from __future__ import annotations

from core.errors import (
    DomainDefectError,
    ExpectedConditionError,
    PlatformError,
    SafetyViolationError,
)


def test_expected_condition_is_not_fault() -> None:
    """Ожидаемое состояние — не дефект и не 500."""
    error = ExpectedConditionError("датчик молчит")

    assert error.is_fault is False
    assert error.code == "expected_condition"
    assert error.http_status == 400


def test_domain_defect_is_fault() -> None:
    """Непредвиденная ошибка кода — дефект и 500."""
    error = DomainDefectError("сломался расчёт")

    assert error.is_fault is True
    assert error.code == "internal_error"
    assert error.http_status == 500


def test_safety_violation_is_fault() -> None:
    """Нарушение безопасности — отдельный код и 409."""
    error = SafetyViolationError("нельзя открыть штору")

    assert error.is_fault is True
    assert error.code == "safety_violation"
    assert error.http_status == 409


def test_custom_code_overrides_class_code() -> None:
    """Машинный код можно уточнить, сохранив класс ошибки."""
    error = PlatformError("нет прав", code="forbidden")

    assert error.code == "forbidden"
    assert error.to_dict() == {"code": "forbidden", "message": "нет прав"}
