"""Prometheus metrics collection for the smart home FSM platform.

This module provides metrics instrumentation for key components:
- FSM transitions
- Event processing latency
- Adapter connection errors
- Middleware conflicts
- Command dispatcher rejections
- Active FSM instances
- Device integration metrics (sync duration, commands, errors, device state, cache stats)
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
        self._websocket_disconnects_total: Counter | None = None
        self._middleware_conflicts_total: Counter | None = None
        self._command_rejections_total: Counter | None = None
        self._active_fsm_instances: Gauge | None = None

        # Device integration metrics
        # Sync duration metrics
        self._device_sync_duration_seconds: Histogram | None = None
        self._source_sync_total_seconds: Histogram | None = None

        # Command metrics
        self._device_commands_total: Counter | None = None
        self._device_commands_success: Counter | None = None
        self._device_commands_failed: Counter | None = None

        # Error metrics
        self._device_connection_errors_total: Counter | None = None
        self._device_sync_errors_total: Counter | None = None

        # State metrics
        self._devices_available: Gauge | None = None
        self._devices_unavailable: Gauge | None = None
        self._sources_connected: Gauge | None = None

        # Cache metrics
        self._cache_size: Gauge | None = None
        self._cache_hits: Counter | None = None
        self._cache_misses: Counter | None = None

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

            # WebSocket disconnections requiring reconnect
            self._websocket_disconnects_total = Counter(
                "websocket_disconnects_total",
                "Total number of WebSocket disconnects that triggered reconnect",
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

            # ============ Device Integration Metrics ============

            # 1. SYNC DURATION METRICS
            # Histogram для отслеживания времени синхронизации на устройство
            self._device_sync_duration_seconds = Histogram(
                "device_integration_device_sync_duration_seconds",
                "Время синхронизации устройства в секундах",
                ["source_id", "device_type"],
                buckets=(0.1, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0),
            )

            # Histogram для общего времени синхронизации источника
            self._source_sync_total_seconds = Histogram(
                "device_integration_source_sync_total_seconds",
                "Общее время синхронизации источника в секундах",
                ["source_id"],
                buckets=(0.5, 1.0, 5.0, 10.0, 30.0, 60.0, 120.0),
            )

            # 2. COMMAND METRICS
            # Counter для всех отправленных команд
            self._device_commands_total = Counter(
                "device_integration_device_commands_total",
                "Всего отправлено команд на устройства",
                ["source_id", "device_type", "command_type"],
            )

            # Counter для успешных команд
            self._device_commands_success = Counter(
                "device_integration_device_commands_success",
                "Количество успешно выполненных команд",
                ["source_id", "device_type", "command_type"],
            )

            # Counter для неудачных команд
            self._device_commands_failed = Counter(
                "device_integration_device_commands_failed",
                "Количество неудачных команд",
                ["source_id", "device_type", "command_type", "error_type"],
            )

            # 3. ERROR METRICS
            # Counter для ошибок соединения
            self._device_connection_errors_total = Counter(
                "device_integration_device_connection_errors_total",
                "Всего ошибок соединения с устройствами",
                ["source_id", "error_type"],
            )

            # Counter для ошибок синхронизации
            self._device_sync_errors_total = Counter(
                "device_integration_device_sync_errors_total",
                "Всего ошибок синхронизации устройств",
                ["source_id", "error_type"],
            )

            # 4. DEVICE STATE METRICS
            # Gauge для количества доступных устройств
            self._devices_available = Gauge(
                "device_integration_devices_available",
                "Количество доступных устройств",
                ["source_id", "device_type"],
            )

            # Gauge для количества недоступных устройств
            self._devices_unavailable = Gauge(
                "device_integration_devices_unavailable",
                "Количество недоступных устройств",
                ["source_id", "device_type"],
            )

            # Gauge для количества подключенных источников
            self._sources_connected = Gauge(
                "device_integration_sources_connected",
                "Количество подключенных источников",
            )

            # 5. CACHE METRICS
            # Gauge для размера кэша
            self._cache_size = Gauge(
                "device_integration_cache_size",
                "Размер кэша в байтах",
            )

            # Counter для попаданий в кэш
            self._cache_hits = Counter(
                "device_integration_cache_hits",
                "Количество попаданий в кэш",
                ["cache_type"],
            )

            # Counter для промахов кэша
            self._cache_misses = Counter(
                "device_integration_cache_misses",
                "Количество промахов кэша",
                ["cache_type"],
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

    def record_websocket_disconnect(self) -> None:
        """Record a WebSocket disconnect that triggered a reconnect attempt."""
        if self._initialized and self._websocket_disconnects_total:
            self._websocket_disconnects_total.inc()

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

    # ============ Device Integration Metrics Methods ============

    def record_device_sync_duration(
        self,
        source_id: str,
        device_type: str,
        duration_seconds: float,
    ) -> None:
        """Записывает время синхронизации для отдельного устройства.

        Args:
            source_id: Идентификатор источника (например, UUID как строка)
            device_type: Тип устройства (например, "light", "switch", "sensor")
            duration_seconds: Время синхронизации в секундах
        """
        if self._initialized and self._device_sync_duration_seconds:
            self._device_sync_duration_seconds.labels(
                source_id=source_id,
                device_type=device_type,
            ).observe(duration_seconds)

    def record_source_sync_duration(
        self,
        source_id: str,
        total_duration_seconds: float,
    ) -> None:
        """Записывает общее время синхронизации для всех устройств источника.

        Args:
            source_id: Идентификатор источника
            total_duration_seconds: Общее время синхронизации в секундах
        """
        if self._initialized and self._source_sync_total_seconds:
            self._source_sync_total_seconds.labels(
                source_id=source_id,
            ).observe(total_duration_seconds)

    def record_command_sent(
        self,
        source_id: str,
        device_type: str,
        command_type: str,
    ) -> None:
        """Записывает отправку команды на устройство.

        Args:
            source_id: Идентификатор источника
            device_type: Тип устройства
            command_type: Тип команды (например, "turn_on", "turn_off")
        """
        if self._initialized and self._device_commands_total:
            self._device_commands_total.labels(
                source_id=source_id,
                device_type=device_type,
                command_type=command_type,
            ).inc()

    def record_command_success(
        self,
        source_id: str,
        device_type: str,
        command_type: str,
    ) -> None:
        """Записывает успешное выполнение команды.

        Args:
            source_id: Идентификатор источника
            device_type: Тип устройства
            command_type: Тип команды
        """
        if self._initialized and self._device_commands_success:
            self._device_commands_success.labels(
                source_id=source_id,
                device_type=device_type,
                command_type=command_type,
            ).inc()

    def record_command_failed(
        self,
        source_id: str,
        device_type: str,
        command_type: str,
        error_type: str,
    ) -> None:
        """Записывает ошибку при выполнении команды.

        Args:
            source_id: Идентификатор источника
            device_type: Тип устройства
            command_type: Тип команды
            error_type: Тип ошибки (например, "timeout", "connection_error")
        """
        if self._initialized and self._device_commands_failed:
            self._device_commands_failed.labels(
                source_id=source_id,
                device_type=device_type,
                command_type=command_type,
                error_type=error_type,
            ).inc()

    def record_connection_error(
        self,
        source_id: str,
        error_type: str,
    ) -> None:
        """Записывает ошибку соединения с источником.

        Args:
            source_id: Идентификатор источника
            error_type: Тип ошибки (например, "timeout", "refused", "dns_failed")
        """
        if self._initialized and self._device_connection_errors_total:
            self._device_connection_errors_total.labels(
                source_id=source_id,
                error_type=error_type,
            ).inc()

    def record_sync_error(
        self,
        source_id: str,
        error_type: str,
    ) -> None:
        """Записывает ошибку синхронизации.

        Args:
            source_id: Идентификатор источника
            error_type: Тип ошибки (например, "invalid_response", "parse_error")
        """
        if self._initialized and self._device_sync_errors_total:
            self._device_sync_errors_total.labels(
                source_id=source_id,
                error_type=error_type,
            ).inc()

    def set_devices_available(
        self,
        source_id: str,
        device_type: str,
        count: int,
    ) -> None:
        """Устанавливает количество доступных устройств.

        Args:
            source_id: Идентификатор источника
            device_type: Тип устройства
            count: Количество доступных устройств
        """
        if self._initialized and self._devices_available:
            self._devices_available.labels(
                source_id=source_id,
                device_type=device_type,
            ).set(count)

    def set_devices_unavailable(
        self,
        source_id: str,
        device_type: str,
        count: int,
    ) -> None:
        """Устанавливает количество недоступных устройств.

        Args:
            source_id: Идентификатор источника
            device_type: Тип устройства
            count: Количество недоступных устройств
        """
        if self._initialized and self._devices_unavailable:
            self._devices_unavailable.labels(
                source_id=source_id,
                device_type=device_type,
            ).set(count)

    def set_sources_connected_count(self, count: int) -> None:
        """Устанавливает количество подключенных источников.

        Args:
            count: Количество подключенных источников
        """
        if self._initialized and self._sources_connected:
            self._sources_connected.set(count)

    def set_cache_size(self, size_bytes: int) -> None:
        """Устанавливает размер кэша.

        Args:
            size_bytes: Размер кэша в байтах
        """
        if self._initialized and self._cache_size:
            self._cache_size.set(size_bytes)

    def record_cache_hit(self, cache_type: str) -> None:
        """Записывает попадание в кэш.

        Args:
            cache_type: Тип кэша (например, "device", "config")
        """
        if self._initialized and self._cache_hits:
            self._cache_hits.labels(cache_type=cache_type).inc()

    def record_cache_miss(self, cache_type: str) -> None:
        """Записывает промах кэша.

        Args:
            cache_type: Тип кэша (например, "device", "config")
        """
        if self._initialized and self._cache_misses:
            self._cache_misses.labels(cache_type=cache_type).inc()


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
