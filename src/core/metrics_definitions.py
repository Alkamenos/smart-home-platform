"""Prometheus metric definitions for the platform (spec 018, T059).

Extracted from MetricsCollector: creating and registering metric families is a
separate concern from recording observations.
"""

# mypy: disable-error-code="attr-defined"

from __future__ import annotations

from typing import Any

from loguru import logger


class MetricsDefinitionsMixin:
    """Create and register Prometheus metrics."""

    _initialized: bool
    _registry: Any

    def initialize(self) -> None:
        """Initialize Prometheus metrics collectors.

        This method is called once at application startup. It imports
        prometheus_client and registers all metrics in the configured registry.

        A missing library or a failed registration leaves the collector in
        no-op mode with a warning: observation must never break the platform
        (FR-008).
        """
        if self._initialized:
            return

        try:
            from prometheus_client import REGISTRY, Counter, Gauge, Histogram

            registry: Any = REGISTRY if self._registry is None else self._registry

            # Локальные фабрики: все метрики регистрируются в одном реестре, и
            # вызывающий код не должен повторять аргумент в каждом месте.
            def counter(name: str, documentation: str, labelnames: tuple[str, ...] = ()) -> Counter:
                """Создать счётчик в настроенном реестре."""
                return Counter(name, documentation, labelnames, registry=registry)

            def gauge(name: str, documentation: str, labelnames: tuple[str, ...] = ()) -> Gauge:
                """Создать шкалу в настроенном реестре."""
                return Gauge(name, documentation, labelnames, registry=registry)

            def histogram(
                name: str, documentation: str, labelnames: tuple[str, ...] = (), buckets: Any = None
            ) -> Histogram:
                """Создать гистограмму в настроенном реестре."""
                if buckets is None:
                    return Histogram(name, documentation, labelnames, registry=registry)
                return Histogram(
                    name, documentation, labelnames, buckets=buckets, registry=registry
                )

            # FSM transitions counter
            self._fsm_transitions_total = counter(
                "fsm_transitions_total",
                "Total number of FSM state transitions",
                ("fsm_name", "from_state", "to_state", "device"),
            )

            # Отказы: переход не выполнен, указана причина (FR-004). Набор
            # значений конечен — причины заданы константами REASON_*.
            self._fsm_rejections_total = counter(
                "fsm_rejections_total",
                "Total number of rejected FSM transitions by reason",
                ("fsm_name", "reason"),
            )

            # Восстановления состояний из хранилища после перезапуска.
            self._fsm_states_restored_total = counter(
                "fsm_states_restored_total",
                "Total number of FSM states restored from persistence",
                ("fsm_name",),
            )

            # Сбои самого сбора показателей — наблюдаемость должна быть
            # наблюдаемой (FR-008).
            self._metrics_collection_errors_total = counter(
                "metrics_collection_errors_total",
                "Total number of metrics collection failures by stage",
                ("stage",),
            )

            # ===== Метрики сторожа (US2) =====
            # Зависшие автоматы: счётчик обнаружений и шкала «зависло сейчас».
            # Шкала нужна, чтобы «всё в порядке» отличалось от «никто не
            # проверялся» (FR-016).
            self._fsm_stuck_total = counter(
                "fsm_stuck_total",
                "Total number of detected stuck FSM instances by state",
                ("fsm_name", "state"),
            )
            self._fsm_stuck_current = gauge(
                "fsm_stuck_current",
                "Number of FSM instances currently stuck",
                ("fsm_name",),
            )

            # Результаты проверок сторожа: ok / degraded / failed (FR-018).
            self._watchdog_checks_total = counter(
                "watchdog_checks_total",
                "Total number of watchdog checks by result",
                ("result",),
            )
            self._watchdog_last_snapshot_timestamp = gauge(
                "watchdog_last_snapshot_timestamp",
                "Unix timestamp of the last watchdog state snapshot",
            )

            # 1, пока связь с внешней системой потеряна; 0 — иначе, включая
            # автономный режим, где внешней системы нет (FR-014).
            self._ha_connection_lost = gauge(
                "ha_connection_lost",
                "1 while the connection to the external system is lost, 0 otherwise",
            )

            # Event processing latency histogram
            self._event_processing_latency = histogram(
                "event_processing_latency_seconds",
                "Latency of event processing in seconds",
                ("event_type", "component"),
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
            self._ha_connection_errors_total = counter(
                "ha_adapter_connection_errors_total",
                "Total number of Home Assistant adapter connection errors",
                ("error_type",),
            )

            # WebSocket disconnections requiring reconnect
            self._websocket_disconnects_total = counter(
                "websocket_disconnects_total",
                "Total number of WebSocket disconnects that triggered reconnect",
            )

            # События, отброшенные локальным фильтром сущностей
            self._websocket_filtered_events_total = counter(
                "websocket_filtered_events_total",
                "Total number of WebSocket events dropped by the local entity filter",
            )

            # Middleware conflicts counter
            self._middleware_conflicts_total = counter(
                "middleware_conflicts_total",
                "Total number of middleware conflict detections",
                ("middleware_name", "conflict_type"),
            )

            # Command dispatcher rejections counter
            self._command_rejections_total = counter(
                "command_dispatcher_rejections_total",
                "Total number of commands rejected by the dispatcher",
                ("reason", "command_type"),
            )

            # Active FSM instances gauge
            self._active_fsm_instances = gauge(
                "active_fsm_instances",
                "Number of active FSM instances",
                ("manifest_name",),
            )

            # ============ Device Integration Metrics ============

            # 1. SYNC DURATION METRICS
            # Histogram для отслеживания времени синхронизации на устройство
            self._device_sync_duration_seconds = histogram(
                "device_integration_device_sync_duration_seconds",
                "Время синхронизации устройства в секундах",
                ("source_id", "device_type"),
                buckets=(0.1, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0),
            )

            # Histogram для общего времени синхронизации источника
            self._source_sync_total_seconds = histogram(
                "device_integration_source_sync_total_seconds",
                "Общее время синхронизации источника в секундах",
                ("source_id",),
                buckets=(0.5, 1.0, 5.0, 10.0, 30.0, 60.0, 120.0),
            )

            # 2. COMMAND METRICS
            # Counter для всех отправленных команд
            self._device_commands_total = counter(
                "device_integration_device_commands_total",
                "Всего отправлено команд на устройства",
                ("source_id", "device_type", "command_type"),
            )

            # Counter для успешных команд
            self._device_commands_success = counter(
                "device_integration_device_commands_success",
                "Количество успешно выполненных команд",
                ("source_id", "device_type", "command_type"),
            )

            # Counter для неудачных команд
            self._device_commands_failed = counter(
                "device_integration_device_commands_failed",
                "Количество неудачных команд",
                ("source_id", "device_type", "command_type", "error_type"),
            )

            # Counter для отказов по ручной блокировке. Без него сценарий «свет не
            # включается» нечем объяснить: отказ в журнале выглядит так же, как
            # любой другой, и оператор ищет поломку там, где автоматика выключена
            # намеренно — потому что человек сам выключил свет.
            self._manual_lockout_blocks_total = counter(
                "manual_lockout_blocks_total",
                "Количество автоматических команд, отклонённых по ручной блокировке",
                ("device_id",),
            )

            # 3. ERROR METRICS
            # Counter для ошибок соединения
            self._device_connection_errors_total = counter(
                "device_integration_device_connection_errors_total",
                "Всего ошибок соединения с устройствами",
                ("source_id", "error_type"),
            )

            # Counter для ошибок синхронизации
            self._device_sync_errors_total = counter(
                "device_integration_device_sync_errors_total",
                "Всего ошибок синхронизации устройств",
                ("source_id", "error_type"),
            )

            # 4. DEVICE STATE METRICS
            # Gauge для количества доступных устройств
            self._devices_available = gauge(
                "device_integration_devices_available",
                "Количество доступных устройств",
                ("source_id", "device_type"),
            )

            # Gauge для количества недоступных устройств
            self._devices_unavailable = gauge(
                "device_integration_devices_unavailable",
                "Количество недоступных устройств",
                ("source_id", "device_type"),
            )

            # Gauge для количества подключенных источников
            self._sources_connected = gauge(
                "device_integration_sources_connected",
                "Количество подключенных источников",
            )

            # 5. CACHE METRICS
            # Gauge для размера кэша
            self._cache_size = gauge(
                "device_integration_cache_size",
                "Размер кэша в байтах",
            )

            # Counter для попаданий в кэш
            self._cache_hits = counter(
                "device_integration_cache_hits",
                "Количество попаданий в кэш",
                ("cache_type",),
            )

            # Counter для промахов кэша
            self._cache_misses = counter(
                "device_integration_cache_misses",
                "Количество промахов кэша",
                ("cache_type",),
            )

            self._initialized = True
        except ImportError:
            # prometheus_client not installed, metrics will be no-op
            logger.warning("prometheus_client is not installed; metrics collection disabled")
            self._initialized = False
        except Exception as exc:  # noqa: BLE001 - наблюдаемость не должна ронять платформу
            # Регистрация может не удаться, например при повторной регистрации
            # имён в общем реестре. Сбор показателей — вспомогательная
            # функция: платформа продолжает работать без метрик (FR-008).
            logger.warning(f"Metrics registration failed ({type(exc).__name__}: {exc}); no-op mode")
            self._initialized = False
