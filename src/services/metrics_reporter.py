"""
Подписчик шины, переводящий события состояний автоматов в показатели.

События перехода, отказа и восстановления публикуются движком (F2), поэтому
показатели считаются подпиской на шину, а не правкой движка: ядро не должно
зависеть от наличия коллектора (конституция I, FR-001).

Сбор лучший по силам: ошибка записи фиксируется в журнале и не влияет ни на
переход, ни на доставку события остальным подписчикам (FR-003, FR-008).

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0
"""

from __future__ import annotations

from typing import Any, Protocol

from core.events.fsm_events import (
    EVENT_FSM_REJECTED,
    EVENT_FSM_RESTORED,
    EVENT_FSM_TRANSITIONED,
)
from core.logger import get_logger


logger = get_logger(__name__)


class MetricsProtocol(Protocol):
    """Минимальный контракт сборщика показателей, нужный подписчику."""

    def record_fsm_transition(
        self, fsm_name: str, from_state: str, to_state: str, device: str
    ) -> None: ...

    def record_fsm_rejection(self, fsm_name: str, reason: str) -> None: ...

    def record_fsm_state_restored(self, fsm_name: str) -> None: ...


class MetricsReporter:
    """Учёт событий автоматов в показателях платформы.

    Args:
        event_bus: Шина событий платформы.
        metrics: Сборщик показателей.
    """

    def __init__(self, event_bus: Any, metrics: MetricsProtocol) -> None:
        """Подписаться на события состояний автоматов."""
        self._metrics = metrics
        event_bus.subscribe(EVENT_FSM_TRANSITIONED, self.handle)
        event_bus.subscribe(EVENT_FSM_REJECTED, self.handle)
        event_bus.subscribe(EVENT_FSM_RESTORED, self.handle)

    async def handle(
        self, event_type: str, payload: dict[str, Any], trace_id: str | None = None
    ) -> None:
        """Обработать событие состояния автомата.

        Args:
            event_type: Тип события.
            payload: Полезная нагрузка события.
            trace_id: Идентификатор трассы для корреляции по журналу.
        """
        handlers = {
            EVENT_FSM_TRANSITIONED: self._record_transition,
            EVENT_FSM_REJECTED: self._record_rejection,
            EVENT_FSM_RESTORED: self._record_restored,
        }
        handler = handlers.get(event_type)
        if handler is None:
            return
        try:
            handler(payload)
        except Exception as exc:  # noqa: BLE001 - показатели не влияют на переход
            logger.warning(
                f"Failed to record metrics for {event_type} (trace_id={trace_id}): "
                f"{type(exc).__name__}: {exc}"
            )

    def _record_transition(self, payload: dict[str, Any]) -> None:
        """Записать выполненный переход.

        Args:
            payload: Полезная нагрузка события перехода.
        """
        fsm_id = self._require(payload, "fsm_id")
        self._metrics.record_fsm_transition(
            fsm_name=fsm_id,
            from_state=self._require(payload, "from_state"),
            to_state=self._require(payload, "to_state"),
            # Устройство берётся из полезной нагрузки: разбор идентификатора по
            # `_` даёт коллизию префиксов (Known Issue #20).
            device=str(payload.get("device_id") or "unknown"),
        )

    def _record_rejection(self, payload: dict[str, Any]) -> None:
        """Записать отклонённый переход с причиной отказа.

        Args:
            payload: Полезная нагрузка события отказа.
        """
        self._metrics.record_fsm_rejection(
            fsm_name=self._require(payload, "fsm_id"),
            reason=str(payload.get("reason") or "unknown"),
        )

    def _record_restored(self, payload: dict[str, Any]) -> None:
        """Записать восстановление состояния автомата.

        Args:
            payload: Полезная нагрузка события восстановления.
        """
        self._metrics.record_fsm_state_restored(fsm_name=self._require(payload, "fsm_id"))

    @staticmethod
    def _require(payload: dict[str, Any], field: str) -> str:
        """Извлечь обязательное поле полезной нагрузки.

        Args:
            payload: Полезная нагрузка события.
            field: Имя обязательного поля.

        Returns:
            Значение поля.

        Raises:
            ValueError: Если поле отсутствует или пустое.
        """
        value = payload.get(field)
        if not value:
            raise ValueError(f"{field} is required to record metrics")
        return str(value)
