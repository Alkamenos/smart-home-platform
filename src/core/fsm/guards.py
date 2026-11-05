"""Guard evaluation for the FSM engine (spec 018, US4).

Extracted from FSMEngine: checking guard data, calling the condition and naming
the reason for a denial are one responsibility, separate from transitions.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from loguru import logger

from core.events.fsm_events import (
    GUARD_DENIAL_REASONS,
    REASON_GUARD_DATA_MISSING,
    REASON_GUARD_FAILED,
)
from core.fsm.models import is_measurement


if TYPE_CHECKING:
    from core.fsm.models import State


class GuardMixin:
    """Evaluate guards and explain why a guard denied a transition."""

    _guards: dict[str, Callable[..., bool]]
    _states: dict[str, State]

    def _guard_rejection_reason(
        self,
        guard: str | Callable[..., bool] | None,
        entity_id: str,
        context: dict[str, Any],
    ) -> str | None:
        """Определить причину отказа по условию, не вызывая само условие.

        Наличие данных проверяется **до** вызова условия, иначе пришлось бы
        разбирать результат условия, а это изменило бы контракт всех условий и
        затронуло работающий код. Отсутствие данных — не «значение не
        подходит», а отдельная причина: по ней видно, что молчит датчик, а не
        что состояние штатное.

        Args:
            guard: Имя условия либо сама функция.
            entity_id: Идентификатор автомата.
            context: Контекст перехода.

        Returns:
            `None`, если данные на месте; иначе причина отказа.
        """
        if guard is None:
            return None

        guard_fn = self._guards.get(guard) if isinstance(guard, str) else guard
        if guard_fn is None:
            return REASON_GUARD_FAILED

        required = getattr(guard_fn, "requires", ())
        # Нечитаемое значение — тоже отсутствие данных. Контракт наблюдаемых
        # сигналов различает «датчик молчит или значение нечитаемо» (проблема
        # данных) и «значение не подходит» (штатная работа), а `unavailable`
        # раньше попадал во второе: молчащий датчик выглядел как исправно
        # работающая вентиляция, у которой «просто не набралось влажности».
        # Проверка числовая, а не сравнение с None: иначе отказ получает чужое
        # имя, и оператору остаётся гадать, где искать.
        missing = [key for key in required if not is_measurement(context.get(key))]
        if missing:
            logger.debug(
                f"Entity {entity_id}: guard {getattr(guard_fn, '__name__', guard)} "
                f"denied — no data for {', '.join(missing)}"
            )
            return REASON_GUARD_DATA_MISSING

        return None

    def _evaluate_guard(
        self,
        guard: str | Callable[..., bool] | None,
        entity_id: str,
        context: dict[str, Any],
        log: Any | None = None,
    ) -> bool:
        """Evaluate a guard condition. Passes both State and external context."""
        if log is None:
            log = logger

        if guard is None:
            return True

        guard_fn = self._guards.get(guard) if isinstance(guard, str) else guard
        if guard_fn is None:
            log.error(f"Guard '{guard}' not found in registry, denying transition")
            return False

        state = self._states.get(entity_id)
        try:
            # ПЕРЕДАЕМ ОБА АРГУМЕНТА: state и context
            result = guard_fn(state, context)
            name = guard_fn.__name__ if hasattr(guard_fn, "__name__") else str(guard_fn)
            log.debug(f"Guard '{name}' evaluated to {result}")
            return bool(result)
        except Exception as e:
            name = guard_fn.__name__ if hasattr(guard_fn, "__name__") else str(guard_fn)
            log.error(f"Guard '{name}' raised exception: {e}, denying transition")
            return False

    @staticmethod
    def _guard_denial_reason(
        guard: str | Callable[..., bool] | None,
        state: Any,
        context: dict[str, Any],
    ) -> str | None:
        """Имя причины, которым условие само называет свой отказ.

        Условие остаётся функцией «да/нет»: поднимать из него исключение или
        менять контракт значило бы тронуть все существующие условия. Вместо
        этого условие может объявить помощника ``deny_reason`` — функцию
        ``(state, context) -> str | None``. Возвращается только причина из
        ограниченного словаря: показатели не должны набирать произвольные
        метки из текста шаблонов.

        Args:
            guard: Имя условия либо сама функция.
            state: Текущее состояние автомата.
            context: Контекст перехода.

        Returns:
            Имя причины либо None.
        """
        guard_fn = guard if callable(guard) else None
        explain = getattr(guard_fn, "deny_reason", None)
        if explain is None:
            return None
        try:
            reason = explain(state, context)
        except Exception as exc:  # noqa: BLE001 — объяснение не должно ломать отказ
            logger.debug(f"Условие не смогло назвать причину отказа: {exc}")
            return None
        return reason if reason in GUARD_DENIAL_REASONS else None
