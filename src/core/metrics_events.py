"""Event and command metrics for the platform (spec 018, T059).

Extracted from MetricsCollector: observations about events, websocket and commands.
"""

# mypy: disable-error-code="attr-defined"

from __future__ import annotations


class MetricsEventsMixin:
    """Record event latency, websocket and command observations."""

    def record_event_latency(
        self,
        event_type: str,
        component: str,
        latency_seconds: float,
    ) -> None:
        """Record event processing latency.

        Args:
            event_type: Type of event being processed.
            component: Component that processed the event.
            latency_seconds: Processing time in seconds.
        """
        if self._initialized and self._event_processing_latency:
            self._event_processing_latency.labels(
                event_type=event_type,
                component=component,
            ).observe(latency_seconds)

    def record_ha_connection_error(self, error_type: str) -> None:
        """Record a Home Assistant adapter connection error.

        Args:
            error_type: Type of connection error (e.g., 'timeout', 'refused').
        """
        if self._initialized and self._ha_connection_errors_total:
            self._ha_connection_errors_total.labels(error_type=error_type).inc()

    def record_websocket_disconnect(self) -> None:
        """Record a WebSocket disconnect that triggered a reconnect attempt."""
        if self._initialized and self._websocket_disconnects_total:
            self._websocket_disconnects_total.inc()

    def record_websocket_filtered_event(self) -> None:
        """Засчитать событие, отброшенное локальным фильтром сущностей.

        Фильтр работает молча по построению: отброшенное событие не доходит
        ни до обработчика, ни до журнала. Без счётчика невозможно отличить
        «фильтр отсекает лишнее» от «события не приходят вовсе» (Known Issue
        #83: ровно так и выглядела слепота по добавленному устройству).

        Returns:
            Ничего.
        """
        if self._initialized and self._websocket_filtered_events_total:
            self._websocket_filtered_events_total.inc()

    def record_middleware_conflict(
        self,
        middleware_name: str,
        conflict_type: str,
    ) -> None:
        """Record a middleware conflict detection.

        Args:
            middleware_name: Name of the middleware that detected the conflict.
            conflict_type: Type of conflict detected.
        """
        if self._initialized and self._middleware_conflicts_total:
            self._middleware_conflicts_total.labels(
                middleware_name=middleware_name,
                conflict_type=conflict_type,
            ).inc()

    def record_command_rejection(
        self,
        reason: str,
        command_type: str,
    ) -> None:
        """Record a command rejection by the dispatcher.

        Args:
            reason: Reason for rejection (e.g., 'low_priority', 'manual_lockout').
            command_type: Type of command that was rejected.
        """
        if self._initialized and self._command_rejections_total:
            self._command_rejections_total.labels(
                reason=reason,
                command_type=command_type,
            ).inc()

    def set_active_fsm_count(self, manifest_name: str, count: int) -> None:
        """Set the number of active FSM instances for a manifest.

        Args:
            manifest_name: Name of the manifest.
            count: Number of active FSM instances.
        """
        if self._initialized and self._active_fsm_instances:
            self._active_fsm_instances.labels(manifest_name=manifest_name).set(count)

    def is_initialized(self) -> bool:
        """Check if the metrics collector is initialized.

        Returns:
            True if prometheus_client is available and metrics are registered.
        """
        return self._initialized
