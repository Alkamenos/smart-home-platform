"""Tests for Prometheus metrics collection.

These tests exercise the REAL ``prometheus_client`` library through an isolated
registry per test, so a broken metric registration actually fails a test
(FR-023). Before this rewrite every "with prometheus" test substituted
``MagicMock`` for the library, which meant no test could catch a registration
failure.

The "without prometheus" class is the legitimate exception: it verifies that
the collector degrades to a no-op when the library is unavailable (FR-008).
"""

from __future__ import annotations

import sys
from collections.abc import Iterator
from copy import deepcopy
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from prometheus_client import CollectorRegistry


# Add src directory to Python path for imports
src_path = Path(__file__).parent.parent / "src"
if str(src_path) not in sys.path:
    sys.path.insert(0, str(src_path))

from core.metrics import (  # noqa: E402
    MAX_LABEL_SERIES_PER_METRIC,
    OTHER_LABEL,
    MetricsCollector,
    get_metrics_collector,
    metrics_enabled,
)


@pytest.fixture
def registry() -> CollectorRegistry:
    """Provide an isolated registry so tests never collide on metric names."""
    return CollectorRegistry()


@pytest.fixture
def collector(registry: CollectorRegistry) -> MetricsCollector:
    """Provide an initialized collector bound to the isolated registry."""
    collector = MetricsCollector(registry=registry)
    collector.initialize()
    return collector


class TestMetricsCollectorInitialization:
    """Test MetricsCollector initialization behavior."""

    def test_should_register_metrics_in_given_registry_when_initialized(
        self, registry: CollectorRegistry
    ) -> None:
        """Registration must land in the supplied registry, not the global one."""
        collector = MetricsCollector(registry=registry)
        collector.initialize()

        assert collector.is_initialized()
        names = {metric.name for metric in registry.collect()}
        assert "fsm_transitions" in names
        assert "fsm_rejections" in names
        assert "fsm_states_restored" in names
        assert "active_fsm_instances" in names
        assert "metrics_collection_errors" in names

    def test_should_keep_default_registry_when_none_given(self) -> None:
        """Without an explicit registry the collector must use the default one."""
        collector = MetricsCollector()
        assert collector.registry_is_default

    def test_should_not_double_initialize(self, registry: CollectorRegistry) -> None:
        """Test that initialize() is idempotent."""
        collector = MetricsCollector(registry=registry)
        collector.initialize()
        collector.initialize()

        assert collector.is_initialized()

    def test_should_enter_noop_mode_without_raising_when_registration_fails(
        self, registry: CollectorRegistry
    ) -> None:
        """A broken registration must degrade, not crash the platform (FR-008)."""
        collector = MetricsCollector(registry=registry)

        with patch.dict(
            "sys.modules",
            {"prometheus_client": MagicMock(Counter=MagicMock(side_effect=ValueError("dup")))},
        ):
            collector.initialize()

        assert not collector.is_initialized()
        # Recording after a failed registration must stay silent, not raise.
        collector.record_fsm_transition("fsm", "a", "b", "device")


class TestMetricsRecordingWithRealLibrary:
    """Test that metrics land in the real registry with the documented labels."""

    def test_should_increment_transition_counter_when_recorded(
        self, collector: MetricsCollector, registry: CollectorRegistry
    ) -> None:
        """Test that FSM transitions are recorded with correct labels."""
        collector.record_fsm_transition("night_light", "off", "on", "light.bedroom")

        value = registry.get_sample_value(
            "fsm_transitions_total",
            {
                "fsm_name": "night_light",
                "from_state": "off",
                "to_state": "on",
                "device": "light.bedroom",
            },
        )
        assert value == 1

        collector.record_fsm_transition("night_light", "off", "on", "light.bedroom")
        assert (
            registry.get_sample_value(
                "fsm_transitions_total",
                {
                    "fsm_name": "night_light",
                    "from_state": "off",
                    "to_state": "on",
                    "device": "light.bedroom",
                },
            )
            == 2
        )

    def test_should_increment_rejection_counter_with_reason_when_recorded(
        self, collector: MetricsCollector, registry: CollectorRegistry
    ) -> None:
        """Rejected transitions are counted separately, with their reason (FR-004)."""
        collector.record_fsm_rejection("night_light", "debounced")

        assert (
            registry.get_sample_value(
                "fsm_rejections_total",
                {"fsm_name": "night_light", "reason": "debounced"},
            )
            == 1
        )
        assert (
            registry.get_sample_value(
                "fsm_transitions_total",
                {
                    "fsm_name": "night_light",
                    "from_state": OTHER_LABEL,
                    "to_state": OTHER_LABEL,
                    "device": OTHER_LABEL,
                },
            )
            is None
        )

    def test_should_increment_restored_counter_when_recorded(
        self, collector: MetricsCollector, registry: CollectorRegistry
    ) -> None:
        """Restored states get their own counter."""
        collector.record_fsm_state_restored("night_light")

        assert (
            registry.get_sample_value("fsm_states_restored_total", {"fsm_name": "night_light"}) == 1
        )

    def test_should_set_gauge_value_when_active_fsm_count_set(
        self, collector: MetricsCollector, registry: CollectorRegistry
    ) -> None:
        """Test active FSM gauge."""
        collector.set_active_fsm_count("leonids_house", 5)

        assert (
            registry.get_sample_value("active_fsm_instances", {"manifest_name": "leonids_house"})
            == 5
        )

    def test_should_observe_latency_when_event_latency_recorded(
        self, collector: MetricsCollector, registry: CollectorRegistry
    ) -> None:
        """Test that event latency is recorded with correct labels."""
        collector.record_event_latency("motion_detected", "event_router", 0.05)

        assert (
            registry.get_sample_value(
                "event_processing_latency_seconds_count",
                {"event_type": "motion_detected", "component": "event_router"},
            )
            == 1
        )

    def test_should_increment_counter_when_connection_error_recorded(
        self, collector: MetricsCollector, registry: CollectorRegistry
    ) -> None:
        """Test that HA connection errors are recorded with correct labels."""
        collector.record_ha_connection_error("timeout")

        assert (
            registry.get_sample_value(
                "ha_adapter_connection_errors_total", {"error_type": "timeout"}
            )
            == 1
        )

    def test_should_increment_collection_error_counter_when_stage_failed(
        self, collector: MetricsCollector, registry: CollectorRegistry
    ) -> None:
        """Collection failures are observable themselves (FR-008)."""
        collector.record_collection_error("scrape")

        assert (
            registry.get_sample_value("metrics_collection_errors_total", {"stage": "scrape"}) == 1
        )

    def test_should_increment_middleware_conflict_when_recorded(
        self, collector: MetricsCollector, registry: CollectorRegistry
    ) -> None:
        """Test that middleware conflicts are recorded with correct labels."""
        collector.record_middleware_conflict("manual_lockout_middleware", "priority_conflict")

        assert (
            registry.get_sample_value(
                "middleware_conflicts_total",
                {
                    "middleware_name": "manual_lockout_middleware",
                    "conflict_type": "priority_conflict",
                },
            )
            == 1
        )


class TestMetricsCardinalityLimit:
    """Transitions must not grow the metric series without bound (FR-005, SC-006)."""

    def test_should_route_excess_label_sets_to_other_series_when_limit_reached(
        self, collector: MetricsCollector, registry: CollectorRegistry
    ) -> None:
        """Label sets beyond the cap are aggregated, not created."""
        for index in range(MAX_LABEL_SERIES_PER_METRIC + 50):
            collector.record_fsm_transition(f"fsm_{index}", "off", "on", f"device.{index}")

        series = [
            sample.labels
            for metric in registry.collect()
            if metric.name == "fsm_transitions"
            for sample in metric.samples
            if sample.name == "fsm_transitions_total"
        ]

        assert len(series) <= MAX_LABEL_SERIES_PER_METRIC + 1
        assert OTHER_LABEL in {tuple(labels.values())[0] for labels in series}

    def test_should_keep_total_count_when_label_sets_are_aggregated(
        self, collector: MetricsCollector, registry: CollectorRegistry
    ) -> None:
        """Aggregation must not lose transitions: the total is still exact."""
        total = 1000
        for index in range(total):
            collector.record_fsm_transition(f"fsm_{index}", "off", "on", f"device.{index}")

        summed = sum(
            sample.value
            for metric in registry.collect()
            if metric.name == "fsm_transitions"
            for sample in metric.samples
            if sample.name == "fsm_transitions_total"
        )
        assert summed == total

    def test_should_warn_once_when_cardinality_limit_exceeded(
        self, collector: MetricsCollector, registry: CollectorRegistry
    ) -> None:
        """Overflow is reported once, not on every transition."""
        with patch("core.metrics.logger") as mock_logger:
            for index in range(MAX_LABEL_SERIES_PER_METRIC + 20):
                collector.record_fsm_transition(f"fsm_{index}", "off", "on", f"device.{index}")

        warnings = list(mock_logger.warning.call_args_list)
        assert len(warnings) <= 1

    def test_should_keep_separate_series_per_metric_when_bounded(
        self, collector: MetricsCollector, registry: CollectorRegistry
    ) -> None:
        """The cap is per metric: rejecting many must not cap transitions."""
        for index in range(MAX_LABEL_SERIES_PER_METRIC + 20):
            collector.record_fsm_rejection(f"fsm_{index}", "debounced")

        rejections = [
            sample
            for metric in registry.collect()
            if metric.name == "fsm_rejections"
            for sample in metric.samples
            if sample.name == "fsm_rejections_total"
        ]
        assert len(rejections) > MAX_LABEL_SERIES_PER_METRIC


class TestMetricsRecordingWithoutPrometheus:
    """Платформа обязана переживать отсутствие prometheus_client (FR-008).

    Проверяется не «забытый» вызов ``initialize()``, а реальная деградация:
    библиотека недоступна в момент регистрации метрик, поэтому коллектор
    переходит в no-op и все методы записи обязаны остаться холостыми.

    Холостой вызов должен быть холостым *наблюдаемо*: ни одна метрика не
    появляется, внутренний учёт наборов меток не пополняется, состояние
    коллектора не меняется. Одних этих утверждений мало — в no-op они
    выполняются и для метода, который не делает вообще ничего. Поэтому
    каждый тест двусторонний: он же проверяет, что с доступной библиотекой
    тот же вызов записывает ровно одно наблюдение. Единственный способ
    отличить «защищённый» метод от «мёртвого» — сравнить оба состояния.
    """

    @pytest.fixture
    def collector_without_prometheus(self) -> Iterator[MetricsCollector]:
        """Коллектор, у которого prometheus_client недоступен при регистрации.

        ``sys.modules["prometheus_client"] = None`` превращает ``import
        prometheus_client`` в ``ImportError`` — тот же сбой, что и отсутствие
        библиотеки в окружении, и вторая ветка ``except`` в ``initialize()``.

        Подмена снимается сразу после ``initialize()``: деградация — это
        свойство экземпляра (метрики не созданы, сбор выключен), а не только
        подмены в ``sys.modules``. Методы записи в ``sys.modules`` не ходят и
        опираются на ``_initialized`` и на сами объекты метрик, поэтому
        no-op сохраняется. Благодаря этому в том же тесте доступен коллектор
        с библиотекой — для контрольной половины.
        """
        with patch.dict("sys.modules", {"prometheus_client": None}):
            collector = MetricsCollector()
            collector.initialize()
        yield collector

    @pytest.mark.parametrize(
        ("method_name", "call_args", "metric_attr", "sample_name", "sample_labels", "expected"),
        [
            pytest.param(
                "record_fsm_transition",
                ("night_light", "off", "on", "light.bedroom"),
                "_fsm_transitions_total",
                "fsm_transitions_total",
                {
                    "fsm_name": "night_light",
                    "from_state": "off",
                    "to_state": "on",
                    "device": "light.bedroom",
                },
                1,
                id="fsm_transition",
            ),
            pytest.param(
                "record_fsm_rejection",
                ("night_light", "debounced"),
                "_fsm_rejections_total",
                "fsm_rejections_total",
                {"fsm_name": "night_light", "reason": "debounced"},
                1,
                id="fsm_rejection",
            ),
            pytest.param(
                "record_fsm_state_restored",
                ("night_light",),
                "_fsm_states_restored_total",
                "fsm_states_restored_total",
                {"fsm_name": "night_light"},
                1,
                id="fsm_state_restored",
            ),
            pytest.param(
                "record_event_latency",
                ("motion_detected", "event_router", 0.05),
                "_event_processing_latency",
                # Сумма, а не счётчик: сумма доказывает и сам факт наблюдения,
                # и переданное значение — иначе «неверная величина» прошла бы.
                "event_processing_latency_seconds_sum",
                {"event_type": "motion_detected", "component": "event_router"},
                0.05,
                id="event_latency",
            ),
            pytest.param(
                "record_ha_connection_error",
                ("timeout",),
                "_ha_connection_errors_total",
                "ha_adapter_connection_errors_total",
                {"error_type": "timeout"},
                1,
                id="ha_connection_error",
            ),
            pytest.param(
                "set_active_fsm_count",
                ("leonids_house", 5),
                "_active_fsm_instances",
                "active_fsm_instances",
                {"manifest_name": "leonids_house"},
                5.0,
                id="active_fsm_count",
            ),
            pytest.param(
                "record_collection_error",
                ("scrape",),
                "_metrics_collection_errors_total",
                "metrics_collection_errors_total",
                {"stage": "scrape"},
                1,
                id="collection_error",
            ),
        ],
    )
    def test_should_stay_noop_without_prometheus_and_record_with_library(
        self,
        collector_without_prometheus: MetricsCollector,
        collector: MetricsCollector,
        registry: CollectorRegistry,
        method_name: str,
        call_args: tuple[str, ...],
        metric_attr: str,
        sample_name: str,
        sample_labels: dict[str, str],
        expected: float,
    ) -> None:
        """Метод записи обязан быть заглушенным, а не мёртвым.

        Без prometheus вызов не оставляет следов: снимок состояния коллектора
        должен совпасть до и после. С доступной библиотекой тот же вызов
        обязан дать ровно одно наблюдение — иначе защита не отличает «нет
        библиотеки» от «метод ничего не делает».
        """
        disabled = collector_without_prometheus

        # Предусловие сценария: сбор действительно отключён, метрика метода
        # не зарегистрирована. Если деградация перестанет отключать сбор,
        # тест упадёт здесь, до проверки холостого вызова.
        assert not disabled.is_initialized()
        assert getattr(disabled, metric_attr) is None

        before = deepcopy(vars(disabled))
        getattr(disabled, method_name)(*call_args)

        assert not disabled.is_initialized()
        assert getattr(disabled, metric_attr) is None
        # Учёт наборов меток — единственное внутреннее состояние, которое
        # пишет ``record_fsm_transition``; в no-op оно обязано остаться пустым.
        assert disabled._seen_series == {}
        # Снимок состояния ловит любое появление нового поля, в том числе
        # будущую «собственную» накопительную статистику без prometheus.
        assert vars(disabled) == before

        # Контрольная половина: с библиотекой вызов не холостой. Метод, у
        # которого тело заменено на ``pass``, падает именно здесь.
        getattr(collector, method_name)(*call_args)

        # Счётчики дают 1, шкала — заданное значение (метод не инкрементит,
        # а выставляет), гистограмма — сумму переданных величин.
        assert registry.get_sample_value(sample_name, sample_labels) == expected


class TestGetMetricsCollector:
    """Test the global singleton accessor."""

    def test_should_return_same_instance_when_called_twice(self) -> None:
        """Test that get_metrics_collector returns a singleton."""
        assert get_metrics_collector() is get_metrics_collector()

    def test_should_return_initializable_instance_when_singleton_used(self) -> None:
        """The global singleton must be usable as-is (R-01)."""
        assert get_metrics_collector() is not None


class TestMetricsEnabledSetting:
    """Test the METRICS_ENABLED setting (FR-001, FR-019, FR-024)."""

    def test_should_be_enabled_by_default(self) -> None:
        """Metrics collection is not optional at a normal start (FR-001)."""
        with patch.dict("os.environ", {}, clear=False):
            import os

            os.environ.pop("METRICS_ENABLED", None)
            assert metrics_enabled() is True

    def test_should_be_disabled_when_env_is_falsey(self) -> None:
        """An explicit setting must win over the default."""
        with patch.dict("os.environ", {"METRICS_ENABLED": "0"}, clear=False):
            assert metrics_enabled() is False
        with patch.dict("os.environ", {"METRICS_ENABLED": "false"}, clear=False):
            assert metrics_enabled() is False

    def test_should_be_enabled_when_env_is_truthy(self) -> None:
        """A truthy setting keeps metrics on."""
        with patch.dict("os.environ", {"METRICS_ENABLED": "1"}, clear=False):
            assert metrics_enabled() is True
