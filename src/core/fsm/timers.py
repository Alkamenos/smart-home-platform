"""Timer scheduling for the FSM engine (spec 018, US4).

Extracted from FSMEngine: transition timeouts, restored-state timers and the
timeout handler are one responsibility and do not belong in the transition core.
"""

# mypy: disable-error-code="attr-defined"

from __future__ import annotations

import asyncio
import contextlib
import time
from typing import TYPE_CHECKING, Any

from loguru import logger


if TYPE_CHECKING:
    from core.fsm.models import FSMDefinition, Transition


class TimerMixin:
    """Schedule and cancel transition/restored-state timers."""

    async def _cancel_timers(self, entity_id: str, log: Any | None = None) -> None:
        """Cancel any pending timers for an entity.

        Текущая задача не отменяется. Обработчик таймаута сам зовёт `trigger`,
        а тот на выполненном переходе отменяет прежние таймеры — включая тот,
        который его и вызвал. Без этого таймер отменял сам себя на середине
        срабатывания: переход начинал выполняться и обрывался, состояние
        оставалось прежним (найдено на стенде 2026-10-07, отложенный переход
        не наступал никогда).

        Args:
            entity_id: ID of the entity whose timers should be cancelled.
            log: Optional logger instance with trace_id bound.
        """
        if log is None:
            log = logger
        if entity_id in self._timers:
            timer_task = self._timers[entity_id]
            # Порядок обязателен: запись снимается ДО отмены. Иначе обработчик,
            # добравшись до конца перехода, запишет новый таймер — и следующая
            # отмена снимет уже не тот.
            del self._timers[entity_id]
            if timer_task is not asyncio.current_task() and not timer_task.done():
                timer_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await timer_task
            log.debug(f"Cancelled timers for entity {entity_id}")

    def _schedule_transition_timeout(
        self,
        entity_id: str,
        definition: FSMDefinition,
        transition: Transition,
        new_context: dict[str, Any],
        trace_id: str,
        log: Any,
    ) -> None:
        """Взвести отложенный переход по новому состоянию.

        Таймер взводится по новому состоянию, а не по сработавшему переходу:
        `timeout_sec` означает «сколько можно находиться в состоянии», и шаблоны
        объявляют его на исходящем переходе. Прежний код смотрел на сработавший
        переход, где таймера нет, поэтому таймауты не срабатывали никогда, а
        `expected_timeout_sec` видел ожидание, которого движок не выполнял
        (Known Issue #66). `timeout_sec` сработавшего перехода учитывается тоже —
        иначе сломалась бы форма «таймер на входящем переходе», на которой
        написаны существующие тесты.

        Args:
            entity_id: Идентификатор автомата.
            definition: Описание автомата.
            transition: Сработавший переход.
            new_context: Контекст нового состояния.
            trace_id: Идентификатор трассировки.
            log: Журнал с привязанным trace_id.

        Returns:
            Ничего.
        """
        declared = [
            value
            for value in (
                self._incoming_timeout(definition, transition),
                self._outgoing_timeout(entity_id, transition.to_state, new_context),
            )
            if value is not None
        ]
        timeout_sec = max(declared) if declared else None
        if timeout_sec is not None:
            self._timers[entity_id] = asyncio.create_task(
                self._timeout_handler(entity_id, timeout_sec, trace_id)
            )
            log.debug(
                f"Entity {entity_id}: Scheduled timeout transition in {timeout_sec}s "
                f"for state '{transition.to_state}'"
            )

    def _schedule_restored_timeout(
        self,
        definition: FSMDefinition,
        state: str,
        age: float,
        context: dict[str, Any] | None = None,
    ) -> None:
        """Взвести отложенный переход для восстановленного состояния.

        Остаток считается от фактического времени в состояние, а не от старта
        контейнера. Иначе перезапуск продлевал бы свечение: состояние, пролежав
        25 с из 30, получало бы ещё 30 вместо оставшихся 5, и с каждым
        перезапуском расхождение росло бы.

        Args:
            definition: Определение автомата.
            state: Восстановленное имя состояния.
            age: Сколько секунд состояние уже пролежало, сек.
        """
        timeout_sec = self._outgoing_timeout(definition.entity_id, state, context)
        if timeout_sec is None:
            return

        remaining = max(0.0, timeout_sec - age)
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            # Без работающего цикла таймер взвести нечем: задачу создать негде.
            # Сборка контейнера в тестах проходит без цикла, и это не должно
            # быть отказом регистрации автомата (ср. FR-016).
            logger.warning(
                f"Entity {definition.entity_id}: restored state '{state}' has a "
                f"{timeout_sec}s timeout, but no running event loop — timer not armed"
            )
            return

        self._timers[definition.entity_id] = asyncio.create_task(
            self._timeout_handler(definition.entity_id, remaining, "restored")
        )
        logger.warning(
            f"Entity {definition.entity_id}: restored state '{state}', timer armed for "
            f"{remaining:.1f}s of {timeout_sec:.1f}s (state held for {age:.1f}s)"
        )

    def _restored_state_age(self, entity_id: str) -> float:
        """Сколько секунд восстановленное состояние уже пролежало.

        Время входа хранится настенным (`time.time()`), потому что монотонные
        часы цикла после перезапуска бессмысленны: они отсчитываются заново от
        старта процесса и ничего не говорят о том, сколько автомат пролежал в
        состоянии до остановки.

        Args:
            entity_id: Идентификатор автомата.

        Returns:
            Возраст состояния в секундах; 0.0, если время входа не сохранено
            (состояния, записанные прежней версией платформы).
        """
        if self._persistence is None:
            return 0.0

        loader = getattr(self._persistence, "load_state_entry", None)
        if loader is None:
            return 0.0

        entry = loader(entity_id) or {}
        entered_at = entry.get("entered_at")
        if not isinstance(entered_at, (int, float)) or entered_at <= 0:
            return 0.0

        age = time.time() - float(entered_at)
        # Метка из будущего означает рассинхронизацию часов, а не состояние,
        # которое пролежало отрицательное время.
        return max(0.0, age)

    @staticmethod
    def _incoming_timeout(definition: FSMDefinition, transition: Transition) -> float | None:
        """Возвращает ``timeout_sec`` сработавшего перехода, если он задан.

        Args:
            definition: Описание автомата.
            transition: Сработавший переход.

        Returns:
            Время ожидания или None.
        """
        value = transition.timeout_sec
        if value is not None and value > 0:
            return value
        return None

    def _outgoing_timeout(
        self, entity_id: str, state: str, context: dict[str, Any] | None = None
    ) -> float | None:
        """Возвращает ожидание по исходящим переходам по триггеру ``timeout``.

        Фильтр по триггеру обязателен. Шаблоны объявляют ожидание так:
        ``ON_MOTION --[timeout]--> OFF, timeout_sec=30`` — то есть на том самом
        переходе, который таймер и должен вызвать. Но встречается и форма
        ``OFF --[manual_override]--> ON_MANUAL, timeout_sec=3600``, где тот же
        параметр описывает уже достигнутое состояние, а из ``OFF`` события
        ``timeout`` никто не слушает. Взводить таймер по таким переходам нельзя:
        он истечёт вхолостую.

        Args:
            entity_id: Идентификатор автомата.
            state: Имя состояния.

        Returns:
            Время ожидания либо None, если из состояния нечему ждать.
        """
        definition = self._definitions.get(entity_id)
        if definition is None:
            return None

        # Условия переходов решают, какой из сроков действует: у ручного света
        # их два — короткий при «мы спим» и стандартный оверрайд в остальное
        # время. Переход, условие которого не прошло, таймер не взводит;
        # иначе побеждал бы самый долгий срок и короткий не сработал бы никогда.
        context = context or {}
        timeouts = [
            transition.timeout_sec
            for transition in definition.transitions
            if transition.from_state == state
            and transition.trigger == "timeout"
            and transition.timeout_sec is not None
            and transition.timeout_sec > 0
            and (
                transition.guard is None
                or self._evaluate_guard(transition.guard, entity_id, context)
            )
        ]
        return max(timeouts) if timeouts else None

    async def _timeout_handler(self, entity_id: str, timeout_sec: float, trace_id: str) -> None:
        """Handle timeout-based transitions.

        Args:
            entity_id: ID of the entity whose timeout is being handled.
            timeout_sec: Timeout duration in seconds.
            trace_id: Trace ID for logging correlation.
        """
        log = logger.bind(trace_id=trace_id)
        try:
            await asyncio.sleep(timeout_sec)
            log.debug(f"Entity {entity_id}: Timeout expired, triggering 'timeout' event")
            await self.trigger(entity_id, "timeout", trace_id=trace_id)
        except asyncio.CancelledError:
            log.debug(f"Entity {entity_id}: Timeout cancelled")
            raise
