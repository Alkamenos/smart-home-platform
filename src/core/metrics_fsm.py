"""FSM and watchdog metrics for the platform (spec 018, T059).

Extracted from MetricsCollector: observations about automata and the watchdog.
"""

# mypy: disable-error-code="attr-defined"

from __future__ import annotations


class MetricsFsmMixin:
    """Record FSM transitions, refusals and watchdog checks."""

    def record_fsm_transition(
        self,
        fsm_name: str,
        from_state: str,
        to_state: str,
        device: str,
    ) -> None:
        """Record an FSM state transition.

        Args:
            fsm_name: Name of the FSM instance.
            from_state: The previous state.
            to_state: The new state.
            device: Device associated with the transition.
        """
        series = self._bounded_labels(
            "fsm_transitions_total",
            self._fsm_transitions_total,
            fsm_name=fsm_name,
            from_state=from_state,
            to_state=to_state,
            device=device,
        )
        if series is not None:
            series.inc()

    def record_fsm_rejection(self, fsm_name: str, reason: str) -> None:
        """Записать отклонённый переход с причиной отказа.

        Отказ считается отдельно от выполненного перехода: смешивать их в одной
        величине нельзя, иначе требование различать успех и отказ (FR-004) не
        проверяемо.

        Args:
            fsm_name: Идентификатор автомата.
            reason: Причина отказа из констант ``REASON_*``.
        """
        if not self._initialized or self._fsm_rejections_total is None:
            return
        self._fsm_rejections_total.labels(fsm_name=fsm_name, reason=reason).inc()

    def record_fsm_state_restored(self, fsm_name: str) -> None:
        """Записать восстановление состояния автомата после перезапуска.

        Args:
            fsm_name: Идентификатор автомата.
        """
        if not self._initialized or self._fsm_states_restored_total is None:
            return
        self._fsm_states_restored_total.labels(fsm_name=fsm_name).inc()

    def record_collection_error(self, stage: str) -> None:
        """Записать сбой самого сбора показателей.

        Args:
            stage: Этап сбора, на котором произошёл сбой
                (``initialize``, ``scrape``).
        """
        if not self._initialized or self._metrics_collection_errors_total is None:
            return
        self._metrics_collection_errors_total.labels(stage=stage).inc()

    def record_watchdog_check(self, result: str) -> None:
        """Записать результат одной проверки сторожа.

        Args:
            result: ``ok``, ``degraded`` или ``failed``.
        """
        if not self._initialized or self._watchdog_checks_total is None:
            return
        self._watchdog_checks_total.labels(result=result).inc()

    def record_fsm_stuck(self, fsm_name: str, state: str) -> None:
        """Записать обнаружение зависшего автомата.

        Args:
            fsm_name: Идентификатор автомата.
            state: Состояние, в котором он застрял.
        """
        if not self._initialized or self._fsm_stuck_total is None:
            return
        self._fsm_stuck_total.labels(fsm_name=fsm_name, state=state).inc()

    def set_fsm_stuck(self, fsm_name: str, count: int) -> None:
        """Отметить, застрял ли автомат прямо сейчас.

        Args:
            fsm_name: Идентификатор автомата.
            count: 1, если автомат завис, иначе 0.
        """
        if not self._initialized or self._fsm_stuck_current is None:
            return
        self._fsm_stuck_current.labels(fsm_name=fsm_name).set(count)

    def set_ha_connection_lost(self, lost: bool) -> None:
        """Отметить потерю связи с внешней системой.

        Args:
            lost: True, если связь потеряна сверх порога.
        """
        if not self._initialized or self._ha_connection_lost is None:
            return
        self._ha_connection_lost.set(1 if lost else 0)

    def set_watchdog_snapshot_timestamp(self, timestamp: float) -> None:
        """Записать время последнего снимка состояний.

        Args:
            timestamp: Монотонное время последней проверки.
        """
        if not self._initialized or self._watchdog_last_snapshot_timestamp is None:
            return
        self._watchdog_last_snapshot_timestamp.set(timestamp)
