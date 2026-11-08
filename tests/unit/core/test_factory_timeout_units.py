"""Параметр поведения в минутах становится сроком автомата в секундах.

Обогреватель живёт по ``run_minutes`` (требование владельца, FR-004): манифест
гостевой спальни задаёт 20 минут, и собственный таймер розетки получает 1200 с.
Страховочный таймер автомата обязан истекать в тот же срок, иначе платформа
выключит прибор раньше, чем просил владелец.

Раньше ``run_minutes`` доходил только до ``number.set_value``, а срок автомата
оставался 900 с из шаблона. Этот тест держит связь: имена, оканчивающиеся на
``_min``/``_minutes``, переводятся в секунды; ``*_sec`` остаются как есть.

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0
"""

from __future__ import annotations

from core.definitions import YAMLTransition
from core.fsm.factory_loading import _timeout_from_params


def _transition(**kwargs: object) -> YAMLTransition:
    """Переход по таймеру с заданным именем параметра.

    Args:
        **kwargs: Поля YAML-перехода.

    Returns:
        Разобранный переход.
    """
    values = {
        "from_state": "HEATING",
        "to_state": "IDLE",
        "trigger": "timeout",
        "timeout_sec": 900.0,
        **kwargs,
    }
    return YAMLTransition(**values)  # type: ignore[arg-type]


def test_run_minutes_should_override_timeout_in_seconds() -> None:
    """``run_minutes: 20`` даёт срок автомата 1200 с, а не 20 и не 900."""
    result = _timeout_from_params(
        _transition(timeout_param="run_minutes"),
        {"run_minutes": 20},
        timeout_params_declared=True,
    )

    assert result == 1200.0


def test_manual_lockout_minutes_should_override_timeout_in_seconds() -> None:
    """Час ручной блокировки — 3600 с страховочного ожидания."""
    result = _timeout_from_params(
        _transition(timeout_param="manual_lockout_min"),
        {"manual_lockout_min": 60},
        timeout_params_declared=True,
    )

    assert result == 3600.0


def test_seconds_parameter_should_not_be_multiplied() -> None:
    """Параметр в секундах остаётся секундами."""
    result = _timeout_from_params(
        _transition(timeout_param="motion_timeout_sec"),
        {"motion_timeout_sec": 30},
        timeout_params_declared=True,
    )

    assert result == 30.0


def test_missing_minutes_parameter_should_keep_template_default() -> None:
    """Нет значения в манифесте — действует срок из шаблона."""
    result = _timeout_from_params(
        _transition(timeout_param="run_minutes"),
        {},
        timeout_params_declared=True,
    )

    assert result == 900.0


def test_extends_timeout_flag_should_reach_the_engine_transition() -> None:
    """Фабрика переносит запрет продления срока в описание перехода."""
    from core.fsm.engine import FSMEngine
    from core.fsm.factory import FSMFactory
    from core.registry import Registry

    factory = FSMFactory(engine=FSMEngine(), registry=Registry())
    transition = factory._yaml_to_transition(  # noqa: SLF001
        _transition(
            from_state="HEATING",
            to_state="HEATING",
            trigger="temperature_changed",
            timeout_sec=None,
            extends_timeout=False,
        ),
        params={},
    )

    assert transition.extends_timeout is False
