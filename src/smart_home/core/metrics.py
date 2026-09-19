"""
Prometheus metrics collection for Smart Home FSM Platform.

Provides counters, gauges, and histograms for monitoring system health,
FSM transitions, event processing latency, and adapter errors.
"""

import threading
import time
from contextlib import contextmanager
from typing import Any

from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram, generate_latest


class MetricsRegistry:
    """Central registry for all Prometheus metrics."""

    def __init__(self, registry: CollectorRegistry | None = None):
        self._registry = registry or CollectorRegistry()
        self._lock = threading.Lock()
        self._initialized = False
        self._metrics: dict[str, Any] = {}

    def _initialize_metrics(self) -> None:
        """Initialize all Prometheus metrics."""
        if self._initialized:
            return

        with self._lock:
            if self._initialized:
                return

            # Counter: Total FSM transitions
            self.fsm_transitions_total = Counter(
                "fsm_transitions_total",
                "Total number of FSM state transitions",
                ["fsm_id", "device_id", "from_state", "to_state"],
                registry=self._registry,
            )

            # Histogram: Event processing latency
            self.event_processing_latency_seconds = Histogram(
                "event_processing_latency_seconds",
                "Latency of event processing in seconds",
                ["event_type", "handler"],
                buckets=(0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0),
                registry=self._registry,
            )

            # Counter: HA adapter connection errors
            self.ha_adapter_connection_errors_total = Counter(
                "ha_adapter_connection_errors_total",
                "Total number of Home Assistant adapter connection errors",
                ["error_type", "endpoint"],
                registry=self._registry,
            )

            # Counter: Middleware conflicts
            self.middleware_conflicts_total = Counter(
                "middleware_conflicts_total",
                "Total number of middleware conflict detections",
                ["middleware_name", "conflict_type"],
                registry=self._registry,
            )

            # Counter: Command dispatcher rejections
            self.command_dispatcher_rejections_total = Counter(
                "command_dispatcher_rejections_total",
                "Total number of commands rejected by dispatcher",
                ["reason", "command_type"],
                registry=self._registry,
            )

            # Gauge: Active FSM instances
            self.active_fsm_instances = Gauge(
                "active_fsm_instances",
                "Number of active FSM instances",
                ["fsm_type"],
                registry=self._registry,
            )

            # Histogram: HTTP request latency (for metrics server)
            self.http_request_latency_seconds = Histogram(
                "http_request_latency_seconds",
                "HTTP request latency in seconds",
                ["method", "endpoint", "status_code"],
                buckets=(0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0),
                registry=self._registry,
            )

            # Counter: HTTP requests total
            self.http_requests_total = Counter(
                "http_requests_total",
                "Total HTTP requests",
                ["method", "endpoint", "status_code"],
                registry=self._registry,
            )

            self._initialized = True

    @property
    def registry(self) -> CollectorRegistry:
        """Get the Prometheus collector registry."""
        self._initialize_metrics()
        return self._registry

    def get_metrics(self) -> dict[str, Any]:
        """Get all metric objects."""
        self._initialize_metrics()
        return self._metrics

    def reset(self) -> None:
        """Reset all metrics (useful for testing)."""
        # Don't hold the lock during re-initialization to avoid deadlocks
        self._registry = CollectorRegistry()
        self._initialized = False
        self._metrics.clear()
        # Re-initialize metrics with the new registry
        self._initialize_metrics()


# Global default registry
_default_registry: MetricsRegistry | None = None
_registry_lock = threading.Lock()


def get_metrics_registry() -> MetricsRegistry:
    """Get the global default metrics registry."""
    global _default_registry
    with _registry_lock:
        if _default_registry is None:
            _default_registry = MetricsRegistry()
        return _default_registry


def reset_global_metrics() -> None:
    """Reset the global metrics registry (for testing)."""
    global _default_registry
    with _registry_lock:
        _default_registry = None


@contextmanager
def track_latency(metric: Any, *labels: str):
    """Context manager to track latency for a histogram metric."""
    start_time = time.perf_counter()
    try:
        yield
    finally:
        duration = time.perf_counter() - start_time
        metric.labels(*labels).observe(duration)


class MetricsCollector:
    """High-level interface for recording metrics."""

    def __init__(self, registry: MetricsRegistry | None = None):
        self._registry = registry or get_metrics_registry()
        # Ensure metrics are initialized
        _ = self._registry.registry

    def record_fsm_transition(
        self,
        fsm_id: str,
        device_id: str,
        from_state: str,
        to_state: str,
    ) -> None:
        """Record an FSM state transition."""
        self._registry.fsm_transitions_total.labels(
            fsm_id=fsm_id,
            device_id=device_id,
            from_state=from_state,
            to_state=to_state,
        ).inc()

    def record_event_latency(
        self,
        event_type: str,
        handler: str,
        duration: float,
    ) -> None:
        """Record event processing latency."""
        self._registry.event_processing_latency_seconds.labels(
            event_type=event_type,
            handler=handler,
        ).observe(duration)

    def record_ha_error(
        self,
        error_type: str,
        endpoint: str,
    ) -> None:
        """Record a Home Assistant adapter error."""
        self._registry.ha_adapter_connection_errors_total.labels(
            error_type=error_type,
            endpoint=endpoint,
        ).inc()

    def record_middleware_conflict(
        self,
        middleware_name: str,
        conflict_type: str,
    ) -> None:
        """Record a middleware conflict."""
        self._registry.middleware_conflicts_total.labels(
            middleware_name=middleware_name,
            conflict_type=conflict_type,
        ).inc()

    def record_command_rejection(
        self,
        reason: str,
        command_type: str,
    ) -> None:
        """Record a command rejection."""
        self._registry.command_dispatcher_rejections_total.labels(
            reason=reason,
            command_type=command_type,
        ).inc()

    def set_active_fsm_instances(
        self,
        count: int,
        fsm_type: str = "default",
    ) -> None:
        """Set the number of active FSM instances."""
        self._registry.active_fsm_instances.labels(fsm_type=fsm_type).set(count)

    def increment_active_fsm_instances(
        self,
        fsm_type: str = "default",
    ) -> None:
        """Increment the number of active FSM instances."""
        self._registry.active_fsm_instances.labels(fsm_type=fsm_type).inc()

    def decrement_active_fsm_instances(
        self,
        fsm_type: str = "default",
    ) -> None:
        """Decrement the number of active FSM instances."""
        self._registry.active_fsm_instances.labels(fsm_type=fsm_type).dec()

    def record_http_request(
        self,
        method: str,
        endpoint: str,
        status_code: int,
        latency: float,
    ) -> None:
        """Record an HTTP request."""
        self._registry.http_requests_total.labels(
            method=method,
            endpoint=endpoint,
            status_code=status_code,
        ).inc()
        self._registry.http_request_latency_seconds.labels(
            method=method,
            endpoint=endpoint,
            status_code=status_code,
        ).observe(latency)

    def get_latest_metrics(self) -> bytes:
        """Get the latest metrics in Prometheus format."""
        return generate_latest(self._registry.registry)
