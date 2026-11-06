"""Prometheus metrics collection for the smart home FSM platform.

This module provides metrics instrumentation for key components:
- FSM transitions
- FSM rejections (a transition that did not happen, with its reason)
- FSM states restored from persistence
- Event processing latency
- Adapter connection errors
- Middleware conflicts
- Command dispatcher rejections
- Active FSM instances
- Device integration metrics (sync duration, commands, errors, device state, cache stats)

Collection is best-effort by design (FR-008): a missing library or a failed
registration degrades every ``record_*`` method into a silent no-op instead of
breaking the platform.
"""

# mypy: disable-error-code="assignment"

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any

from loguru import logger

from core.metrics_definitions import MetricsDefinitionsMixin
from core.metrics_devices import MetricsDevicesMixin
from core.metrics_events import MetricsEventsMixin
from core.metrics_fsm import MetricsFsmMixin


if TYPE_CHECKING:
    from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram

__all__ = [
    "MAX_LABEL_SERIES_PER_METRIC",
    "OTHER_LABEL",
    "MetricsCollector",
    "get_metrics_collector",
    "metrics_enabled",
]


# Предел числа различных наборов меток для метрики переходов (FR-005).
# Метки `from_state`/`to_state` приходят из описания автомата, поэтому их число
# сверху не ограничено, а каждый новый набор создаёт серию в реестре. Сверх
# предела значения агрегируются в серию `__other__`: сумма переходов не теряется,
# ограничивается только память.
MAX_LABEL_SERIES_PER_METRIC = 2000

# Значение метки, в которое агрегируются наборы сверх предела.
OTHER_LABEL = "__other__"

# Настройка сбора показателей. По умолчанию включено: сбор — штатная часть
# работы платформы, а не опциональный режим (FR-001).
_METRICS_ENABLED_ENV = "METRICS_ENABLED"
_FALSY_VALUES = ("0", "false", "no", "off")


def metrics_enabled() -> bool:
    """Проверить, включён ли сбор показателей.

    Настройка объявлена в ``deploy/.env.example`` и обязана читаться кодом
    (FR-024). Значение по умолчанию — включено.

    Returns:
        True, если показатели собираются.
    """
    raw = os.environ.get(_METRICS_ENABLED_ENV)
    if raw is None:
        return True
    return raw.strip().lower() not in _FALSY_VALUES


class MetricsCollector(
    MetricsDefinitionsMixin,
    MetricsFsmMixin,
    MetricsEventsMixin,
    MetricsDevicesMixin,
):
    """Collects and exports Prometheus metrics for the platform.

    Args:
        registry: Реестр измерений, в который регистрируются метрики. ``None``
            означает общий реестр prometheus_client. Тесты передают отдельный
            реестр на тест: иначе вторая регистрация тех же имён в общем
            реестре приводит к ошибке (R-08).
    """

    def __init__(self, registry: CollectorRegistry | None = None) -> None:
        """Initialize the metrics collector with default values."""
        self._initialized: bool = False
        self._registry: CollectorRegistry | None = registry
        self._registry_is_default: bool = registry is None
        # Уже встреченные наборы меток по именам метрик: ограничивают рост
        # числа серий (FR-005).
        self._seen_series: dict[str, set[tuple[tuple[str, str], ...]]] = {}
        self._overflow_reported: set[str] = set()
        self._fsm_transitions_total: Counter | None = None
        self._fsm_rejections_total: Counter | None = None
        self._fsm_states_restored_total: Counter | None = None
        self._metrics_collection_errors_total: Counter | None = None
        self._fsm_stuck_total: Counter | None = None
        self._fsm_stuck_current: Gauge | None = None
        self._watchdog_checks_total: Counter | None = None
        self._watchdog_last_snapshot_timestamp: Gauge | None = None
        self._ha_connection_lost: Gauge | None = None
        self._event_processing_latency: Histogram | None = None
        self._ha_connection_errors_total: Counter | None = None
        self._websocket_disconnects_total: Counter | None = None
        # События, отброшенные локальным фильтром сущностей. Фильтр невидим
        # по построению (он молчит об отбракованном), поэтому его работа
        # обязана быть видна в /metrics иначе «приходят все 1502» снова
        # станет недоказуемым (Known Issue #83).
        self._websocket_filtered_events_total: Counter | None = None
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
        # Отказы по ручной блокировке: автоматика выключена намеренно, и это
        # должно отличаться от поломки в показателях, а не только в журнале.
        self._manual_lockout_blocks_total: Counter | None = None

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

    @property
    def registry_is_default(self) -> bool:
        """Используется ли общий реестр prometheus_client.

        Returns:
            True, если реестр не был передан явно.
        """
        return self._registry_is_default

    @property
    def registry(self) -> Any:
        """Реестр измерений, в котором зарегистрированы метрики.

        Нужен выдаче документа показателей: без него счётчики есть, а отдать
        их нечем.

        Returns:
            Реестр измерений; общий реестр prometheus_client, если он не был
            передан явно.
        """
        if self._registry is None:
            from prometheus_client import REGISTRY

            return REGISTRY
        return self._registry

    def _bounded_labels(
        self,
        metric_name: str,
        metric: Any | None,
        **labels: str,
    ) -> Any | None:
        """Получить серию метрики с ограничением числа наборов меток.

        Первые ``MAX_LABEL_SERIES_PER_METRIC`` различных наборов создают свои
        серии; наборы сверх предела агрегируются в серию ``__other__``, чтобы
        произвольные имена состояний не приводили к неограниченному росту
        памяти (FR-005, R-04). Переполнение сообщается один раз на метрику.

        Args:
            metric_name: Имя метрики, для которого ведётся учёт наборов.
            metric: Зарегистрированная метрика либо ``None``.
            **labels: Значения меток.

        Returns:
            Серия метрики либо ``None``, если метрика не зарегистрирована или
            сбор недоступен.
        """
        if not self._initialized or metric is None:
            return None

        key = tuple(sorted(labels.items()))
        seen = self._seen_series.setdefault(metric_name, set())
        if key not in seen:
            if len(seen) >= MAX_LABEL_SERIES_PER_METRIC:
                if metric_name not in self._overflow_reported:
                    logger.warning(
                        f"Metrics cardinality limit reached for {metric_name}; "
                        f"further label sets aggregate into {OTHER_LABEL!r}"
                    )
                    self._overflow_reported.add(metric_name)
                labels = dict.fromkeys(labels, OTHER_LABEL)
            else:
                seen.add(key)
        return metric.labels(**labels)

    # ============ Device Integration Metrics Methods ============


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
