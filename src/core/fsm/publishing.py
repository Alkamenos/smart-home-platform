"""Event publication for the FSM engine (spec 018, US4).

Extracted from FSMEngine: publishing transitions and refusals to the event bus is
a journal concern, not part of the transition decision logic.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any, Final

from loguru import logger

from core.events.fsm_events import (
    EVENT_FSM_REJECTED,
    EVENT_FSM_TRANSITIONED,
    OUTCOME_REJECTED,
    OUTCOME_TRANSITIONED,
    REASON_NO_TRANSITION,
    build_transition_payload,
)


# ??????? ????? ?????????? ????? ?????????? ??? ????????? ??????, ?????? ???
# ???????? ?? (FR-012).
PUBLISH_DRAIN_TIMEOUT_SEC = 1.0

#: ????? ??????? ?????? ????????? ? ??????? ???? ? ??? ?? ????? (???????,
#: ???????, ???????). ???: ???????? ?????? ????? ????????? ??? ????????, ? ?????
#: ???????? ? `rejection_counts()`. ??? ????? ??????, ???????????? ????
#: (`modifier_off`), ? ??????????, ???????? ?? ??????? ??????????, ?????? ?????
#: 1400 ??????? ? ????? ? ?????? ????? ? ???????? (B67).
REFUSAL_REPEAT_WINDOW_SEC: Final[float] = 3600.0


class PublishingMixin:
    """Publish FSM events without blocking the transition itself."""

    _event_bus: Any
    _publish_tasks: set[asyncio.Task[None]]
    _definitions: dict[str, Any]
    _published_noops: set[tuple[str, str]]
    _published_refusals: dict[tuple[str, str, str], float]

    def _schedule_publish(self, event_type: str, payload: dict[str, Any], trace_id: str) -> None:
        """Запланировать публикацию события перехода отдельной задачей.

        Доставка неблокирующая: медленный подписчик не задерживает выполнение
        перехода (FR-014, SC-015). Задача отслеживается, чтобы остановка движка
        не оставляла висящих задач.

        Args:
            event_type: Имя события (`fsm.transitioned` или `fsm.rejected`).
            payload: Полезная нагрузка события.
            trace_id: Идентификатор трассы текущего срабатывания.
        """
        if self._event_bus is None:
            return

        bus = self._event_bus
        task = asyncio.create_task(bus.publish(event_type, payload, trace_id))
        self._publish_tasks.add(task)
        task.add_done_callback(self._publish_tasks.discard)

    def _publish_transition(
        self,
        entity_id: str,
        event: str,
        from_state: str | None,
        to_state: str,
        trace_id: str,
    ) -> None:
        """Опубликовать выполненный переход.

        Args:
            entity_id: Идентификатор автомата.
            event: Событие-триггер.
            from_state: Предыдущее состояние.
            to_state: Новое состояние.
            trace_id: Идентификатор трассы.
        """
        definition = self._definitions.get(entity_id)
        device_id = definition.target_device_id if definition else None
        payload = build_transition_payload(
            fsm_id=entity_id,
            device_id=device_id or entity_id,
            from_state=from_state,
            to_state=to_state,
            event=event,
            outcome=OUTCOME_TRANSITIONED,
            trace_id=trace_id,
        )
        self._schedule_publish(EVENT_FSM_TRANSITIONED, payload, trace_id)

    def _publish_rejection(
        self,
        entity_id: str,
        event: str,
        from_state: str | None,
        reason: str,
        trace_id: str,
    ) -> None:
        """Опубликовать отказ в переходе с указанием причины (FR-004).

        Args:
            entity_id: Идентификатор автомата.
            event: Событие-триггер.
            from_state: Состояние, из которого переход не состоялся.
            reason: Причина отказа.
            trace_id: Идентификатор трассы.
        """
        if reason == REASON_NO_TRANSITION:
            # «Нет подходящего перехода» — это «повода не было», а не отказ
            # решения: событие пришло, когда автомату нечего на него ответить
            # (свет выключен, а датчик прислал `motion_cleared`; рекуператор
            # притока не слушает влажность). За сутки таких записей набегало 389,
            # и утренний разбор читал «не хотел» наравне с настоящими отказами.
            # Первый факт виден, повторы остаются в `rejection_counts()` — тот же
            # приём, что и у повторных отказов в журнале платформы (B65).
            key = (entity_id, event)
            if key in self._published_noops:
                return
            self._published_noops.add(key)
        else:
            # Повтор одного и того же отказа — раз в `REFUSAL_REPEAT_WINDOW_SEC`:
            # журнал отвечает на вопрос «что случилось», а не «сколько раз одно и
            # то же не случилось». Объём не теряется — он в `rejection_counts()`,
            # а ряд повторов виден почасовыми записями (B67).
            repeat_key = (entity_id, event, reason)
            seen_at = self._published_refusals.get(repeat_key)
            moment = time.monotonic()
            if seen_at is not None and moment - seen_at < REFUSAL_REPEAT_WINDOW_SEC:
                return
            self._published_refusals[repeat_key] = moment

        definition = self._definitions.get(entity_id)
        device_id = definition.target_device_id if definition else None
        payload = build_transition_payload(
            fsm_id=entity_id,
            device_id=device_id or entity_id,
            from_state=from_state,
            to_state=None,
            event=event,
            outcome=OUTCOME_REJECTED,
            trace_id=trace_id,
            reason=reason,
        )
        self._schedule_publish(EVENT_FSM_REJECTED, payload, trace_id)

    async def _drain_publish_tasks(self) -> None:
        """Дождаться или отменить задачи публикации событий (FR-012)."""
        tasks = list(self._publish_tasks)
        if not tasks:
            return

        done, pending = await asyncio.wait(tasks, timeout=PUBLISH_DRAIN_TIMEOUT_SEC)
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
        logger.debug(f"Drained {len(done)} publish tasks, cancelled {len(pending)}")
