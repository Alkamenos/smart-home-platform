"""Watchdog problems and metrics (spec 018, T058).

Extracted from WatchdogService: tracking active problems and publishing their
appearance/resolution is a journal concern, separate from checks.
"""

# mypy: disable-error-code="attr-defined"

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

from core.events.fsm_events import (
    EVENT_PLATFORM_PROBLEM,
    PROBLEM_DEVICE_MISMATCH,
    PROBLEM_FSM_STUCK,
    PROBLEM_HA_DISCONNECTED,
)
from core.logger import get_logger
from services.watchdog_models import STUCK_LABEL_VALUE, FsmSnapshot, _now_timestamp


logger = get_logger(__name__)


@dataclass
class _TrackedProblem:
    """Активная проблема, ожидающая устранения.

    Attributes:
        kind: Вид проблемы.
        entity_id: Автомат либо ``None`` для потери связи.
        detected_at: Настенное время обнаружения.
        detected_monotonic: Монотонное время обнаружения.
    """

    kind: str
    entity_id: str | None
    detected_at: str
    detected_monotonic: float


class WatchdogProblemsMixin:
    """Track active problems, publish events and record metrics."""

    _problems: dict[tuple[str, str | None], _TrackedProblem]
    _publish_tasks: set[asyncio.Task[None]]
    metrics: Any
    clock: Any
    event_bus: Any

    def _record_metrics(self, snapshot: FsmSnapshot) -> None:
        """Записать результат проверки в показатели.

        Args:
            snapshot: Снимок после проверки.
        """
        if self.metrics is None:
            return
        now = self.clock()
        self.metrics.record_watchdog_check(snapshot.result)
        self.metrics.set_watchdog_snapshot_timestamp(now)
        self.metrics.set_ha_connection_lost(snapshot.ha_disconnected)
        for entry in snapshot.entries:
            was_stuck = (PROBLEM_FSM_STUCK, entry.entity_id) in self._problems
            if entry.stuck and not was_stuck:
                self.metrics.record_fsm_stuck(entry.entity_id, entry.state)
            self.metrics.set_fsm_stuck(
                entry.entity_id,
                int(STUCK_LABEL_VALUE) if entry.stuck else 0,
            )

    def _publish_problems(self, snapshot: FsmSnapshot) -> None:
        """Опубликовать появление и устранение проблем.

        Публикуется только при смене состояния проблемы: повторные проверки
        зависшего автомата новых событий не порождают (FR-016).

        Args:
            snapshot: Снимок после проверки.
        """
        self._sync_fsm_problems(snapshot)
        self._sync_connection_problem(snapshot)
        self._sync_device_problems(snapshot)

    def _sync_device_problems(self, snapshot: FsmSnapshot) -> None:
        """Согласовать проблемы расхождения «автомат ↔ прибор» со снимком.

        Публикация идёт только при появлении и устранении расхождения: повторная
        проверка того же прибора новых событий не порождает (FR-016). Уступка
        ручному действию проблемой не считается — она видна в снимке и тревогой
        уровня «знать», но прибора чинить нечего.

        Args:
            snapshot: Снимок после проверки.
        """
        for entry in snapshot.entries:
            key = (PROBLEM_DEVICE_MISMATCH, entry.entity_id)
            if entry.mismatch_is_fault and key not in self._problems:
                self._problems[key] = self._start_problem(PROBLEM_DEVICE_MISMATCH, entry.entity_id)
                self._publish(PROBLEM_DEVICE_MISMATCH, entry.entity_id, entry.state, resolved=False)
            elif not entry.mismatch_is_fault and key in self._problems:
                self._resolve_problem(key, state=entry.state)

    def _sync_fsm_problems(self, snapshot: FsmSnapshot) -> None:
        """Согласовать активные проблемы зависания со снимком.

        Args:
            snapshot: Снимок после проверки.
        """
        stuck_ids = {entry.entity_id for entry in snapshot.entries if entry.stuck}
        for entity_id in stuck_ids:
            key = (PROBLEM_FSM_STUCK, entity_id)
            if key in self._problems:
                continue
            state = next(
                (entry.state for entry in snapshot.entries if entry.entity_id == entity_id),
                "",
            )
            self._problems[key] = self._start_problem(PROBLEM_FSM_STUCK, entity_id)
            self._publish(PROBLEM_FSM_STUCK, entity_id, state, resolved=False)

        for entry in snapshot.entries:
            key = (PROBLEM_FSM_STUCK, entry.entity_id)
            if not entry.stuck and key in self._problems:
                self._resolve_problem(key, state=entry.state)

    def _sync_connection_problem(self, snapshot: FsmSnapshot) -> None:
        """Согласовать проблему потери связи со снимком.

        Args:
            snapshot: Снимок после проверки.
        """
        key = (PROBLEM_HA_DISCONNECTED, None)
        if snapshot.ha_disconnected and key not in self._problems:
            self._problems[key] = self._start_problem(PROBLEM_HA_DISCONNECTED, None)
            self._publish(PROBLEM_HA_DISCONNECTED, None, None, resolved=False)
        elif not snapshot.ha_disconnected and key in self._problems:
            self._resolve_problem(key, state=None)

    def _start_problem(self, kind: str, entity_id: str | None) -> _TrackedProblem:
        """Зафиксировать начало проблемы.

        Args:
            kind: Вид проблемы.
            entity_id: Автомат либо ``None``.

        Returns:
            Запись о проблеме.
        """
        problem = _TrackedProblem(
            kind=kind,
            entity_id=entity_id,
            detected_at=_now_timestamp(),
            detected_monotonic=self.clock(),
        )
        return problem

    def _resolve_problem(self, key: tuple[str, str | None], state: str | None) -> None:
        """Зафиксировать устранение проблемы и опубликовать событие.

        Args:
            key: Ключ проблемы.
            state: Состояние автомата на момент устранения.
        """
        problem = self._problems.pop(key, None)
        if problem is None:
            return
        duration = max(0.0, self.clock() - problem.detected_monotonic)
        self._publish(
            problem.kind,
            problem.entity_id,
            state,
            resolved=True,
            resolved_at=_now_timestamp(),
            duration_sec=round(duration, 3),
        )

    def _publish(
        self,
        kind: str,
        entity_id: str | None,
        state: str | None,
        resolved: bool,
        resolved_at: str | None = None,
        duration_sec: float | None = None,
    ) -> None:
        """Опубликовать событие проблемы, если шина подключена.

        Args:
            kind: Вид проблемы.
            entity_id: Автомат либо ``None``.
            state: Состояние автомата.
            resolved: Устранена ли проблема.
            resolved_at: Время устранения.
            duration_sec: Длительность проблемы.
        """
        if self.event_bus is None:
            return
        problem = self._problems.get((kind, entity_id))
        payload = {
            "kind": kind,
            "entity_id": entity_id,
            "state": state,
            "resolved": resolved,
            "detected_at": problem.detected_at if problem else _now_timestamp(),
            "resolved_at": resolved_at,
            "duration_sec": duration_sec,
        }
        coroutine = self.event_bus.publish(EVENT_PLATFORM_PROBLEM, payload)
        if not asyncio.iscoroutine(coroutine):
            return
        # Ссылка на задачу хранится до завершения: без неё сборщик мусора
        # может удалить задачу на середине, и событие пропадёт.
        task = asyncio.create_task(coroutine)
        self._publish_tasks.add(task)
        task.add_done_callback(self._publish_tasks.discard)
