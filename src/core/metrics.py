"""Prometheus metrics collection for the smart home FSM platform.

This module provides metrics instrumentation for key components:
- FSM transitions
- Event processing latency
- Adapter connection errors
- Middleware conflicts
- Command dispatcher rejections
- Active FSM instances
"""

from __future__ import annotations

from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from prometheus_client import Counter, Gauge, Histogram

__all__ = [
    "MetricsCollector",
    "get_metrics_collector",
]


class MetricsCollector:
    """Collects and exports Prometheus metrics for the platform."""

    def __init__(self) -> None:
        """Initialize the metrics collector with default values."""
        self._initialized: bool = False
        self._fsm_transitions_total: Counter | None = None
        self._event_processing_latency: Histogram | None = None
        self._ha_connection_errors_total: Counter | None = None
        self._middleware_conflicts_total: Counter | None = None
        self._command_rejections_total: Counter | None = None
        self._active_fsm_instances: Gauge | None = None

    def initialize(self) -> None:
        """Initialize Prometheus metrics collectors.

        This method should be called once at application startup.
        It imports prometheus_client and registers all metrics.
        """
        if self._initialized:
            return

        try:
            from prometheus_client import Counter, Gauge, Histogram

            # FSM transitions counter
            self._fsm_transitions_total = Counter(
                "fsm_transitions_total",
                "Total number of FSM state transitions",
                ["fsm_name", "from_state", "to_state", "device"],
            )

            # Event processing latency histogram
            self._event_processing_latency = Histogram(
                "event_processing_latency_seconds",
                "Latency of event processing in seconds",
                ["event_type", "component"],
                buckets=(
                    0.001,
                    0.005,
                    0.01,
                    0.025,
                    0.05,
                    0.1,
                    0.25,
                    0.5,
                    1.0,
                    2.5,
                    5.0,
                    10.0,
                ),
            )

            # HA adapter connection errors counter
            self._ha_connection_errors_total = Counter(
                "ha_adapter_connection_errors_total",
                "Total number of Home Assistant adapter connection errors",
                ["error_type"],
            )

            # Middleware conflicts counter
            self._middleware_conflicts_total = Counter(
                "middleware_conflicts_total",
                "Total number of middleware conflict detections",
                ["middleware_name", "conflict_type"],
            )

            # Command dispatcher rejections counter
            self._command_rejections_total = Counter(
                "command_dispatcher_rejections_total",
                "Total number of commands rejected by the dispatcher",
                ["reason", "command_type"],
            )

            # Active FSM instances gauge
            self._active_fsm_instances = Gauge(
                "active_fsm_instances",
                "Number of active FSM instances",
                ["manifest_name"],
            )

            self._initialized = True
        except ImportError:
            # prometheus_client not installed, metrics will be no-op
            self._initialized = False

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
        if self._initialized and self._fsm_transitions_total:
            self._fsm_transitions_total.labels(
                fsm_name=fsm_name,
                from_state=from_state,
                to_state=to_state,
                device=device,
            ).inc()

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


# Global singleton instance
_metrics_collector: MetricsCollector | None = None


def get_metrics_collector() -> MetricsCollector:
    """Get the global metrics collector instance.

    Returns:
        The global MetricsCollector instance, creating it if necessary.
    """
    global _metrics_collector
    if _metrics_collector is None:
        _metrics_collector = MetricsCollector()
    return _metrics_collector
