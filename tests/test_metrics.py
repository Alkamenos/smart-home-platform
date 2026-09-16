"""Tests for Prometheus metrics collection.

These tests verify that the MetricsCollector properly records metrics
when prometheus_client is available, and gracefully handles its absence.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


# Add src directory to Python path for imports
src_path = Path(__file__).parent.parent / "src"
if str(src_path) not in sys.path:
    sys.path.insert(0, str(src_path))

from core.metrics import MetricsCollector, get_metrics_collector  # noqa: E402


class TestMetricsCollectorInitialization:
    """Test MetricsCollector initialization behavior."""

    def test_should_create_collector_without_prometheus(self) -> None:
        """Test that collector can be created even without prometheus_client."""
        collector = MetricsCollector()
        assert not collector.is_initialized()

    @patch.dict("sys.modules", {"prometheus_client": MagicMock()})
    def test_should_initialize_with_prometheus(self) -> None:
        """Test that collector initializes when prometheus_client is available."""
        import prometheus_client

        prometheus_client.Counter = MagicMock()
        prometheus_client.Gauge = MagicMock()
        prometheus_client.Histogram = MagicMock()

        collector = MetricsCollector()
        collector.initialize()

        assert collector.is_initialized()

    def test_should_not_double_initialize(self) -> None:
        """Test that initialize() is idempotent."""
        collector = MetricsCollector()
        collector.initialize()
        collector.initialize()  # Should not raise or change state
        assert not collector.is_initialized()  # Still False without prometheus_client


class TestMetricsRecordingWithoutPrometheus:
    """Test that metrics recording is no-op when prometheus_client is unavailable."""

    def test_should_not_raise_when_recording_fsm_transition(self) -> None:
        """Test recording FSM transition without prometheus_client."""
        collector = MetricsCollector()
        # Should not raise any exception
        collector.record_fsm_transition("test_fsm", "off", "on", "light_1")

    def test_should_not_raise_when_recording_latency(self) -> None:
        """Test recording latency without prometheus_client."""
        collector = MetricsCollector()
        # Should not raise any exception
        collector.record_event_latency("motion_detected", "event_router", 0.05)

    def test_should_not_raise_when_recording_ha_error(self) -> None:
        """Test recording HA connection error without prometheus_client."""
        collector = MetricsCollector()
        # Should not raise any exception
        collector.record_ha_connection_error("timeout")

    def test_should_not_raise_when_recording_middleware_conflict(self) -> None:
        """Test recording middleware conflict without prometheus_client."""
        collector = MetricsCollector()
        # Should not raise any exception
        collector.record_middleware_conflict("manual_lockout", "conflict")

    def test_should_not_raise_when_recording_command_rejection(self) -> None:
        """Test recording command rejection without prometheus_client."""
        collector = MetricsCollector()
        # Should not raise any exception
        collector.record_command_rejection("low_priority", "turn_on")

    def test_should_not_raise_when_setting_fsm_count(self) -> None:
        """Test setting active FSM count without prometheus_client."""
        collector = MetricsCollector()
        # Should not raise any exception
        collector.set_active_fsm_count("leonids_house", 5)


class TestMetricsRecordingWithPrometheus:
    """Test metrics recording with mocked prometheus_client."""

    @pytest.fixture
    def mock_prometheus(self) -> MagicMock:
        """Create mock prometheus_client module."""
        mock = MagicMock()

        # Setup counter mock
        counter_mock = MagicMock()
        mock.Counter.return_value = counter_mock

        # Setup gauge mock
        gauge_mock = MagicMock()
        mock.Gauge.return_value = gauge_mock

        # Setup histogram mock
        histogram_mock = MagicMock()
        mock.Histogram.return_value = histogram_mock

        return mock

    def test_should_record_fsm_transition(
        self,
        mock_prometheus: MagicMock,
    ) -> None:
        """Test that FSM transitions are recorded with correct labels."""
        with patch.dict("sys.modules", {"prometheus_client": mock_prometheus}):
            collector = MetricsCollector()
            collector.initialize()

            collector.record_fsm_transition("night_light", "off", "on", "light.bedroom")

            counter = mock_prometheus.Counter.return_value
            counter.labels.assert_called_once_with(
                fsm_name="night_light",
                from_state="off",
                to_state="on",
                device="light.bedroom",
            )
            counter.labels.return_value.inc.assert_called_once()

    def test_should_record_event_latency(
        self,
        mock_prometheus: MagicMock,
    ) -> None:
        """Test that event latency is recorded with correct labels."""
        with patch.dict("sys.modules", {"prometheus_client": mock_prometheus}):
            collector = MetricsCollector()
            collector.initialize()

            collector.record_event_latency(
                "motion_detected",
                "event_router",
                0.05,
            )

            histogram = mock_prometheus.Histogram.return_value
            histogram.labels.assert_called_once_with(
                event_type="motion_detected",
                component="event_router",
            )
            histogram.labels.return_value.observe.assert_called_once_with(0.05)

    def test_should_record_ha_connection_error(
        self,
        mock_prometheus: MagicMock,
    ) -> None:
        """Test that HA connection errors are recorded with correct labels."""
        with patch.dict("sys.modules", {"prometheus_client": mock_prometheus}):
            collector = MetricsCollector()
            collector.initialize()

            collector.record_ha_connection_error("timeout")

            counter = mock_prometheus.Counter.return_value
            counter.labels.assert_called_with(error_type="timeout")
            counter.labels.return_value.inc.assert_called()

    def test_should_record_middleware_conflict(
        self,
        mock_prometheus: MagicMock,
    ) -> None:
        """Test that middleware conflicts are recorded with correct labels."""
        with patch.dict("sys.modules", {"prometheus_client": mock_prometheus}):
            collector = MetricsCollector()
            collector.initialize()

            collector.record_middleware_conflict(
                "manual_lockout_middleware",
                "priority_conflict",
            )

            counter = mock_prometheus.Counter.return_value
            counter.labels.assert_called_with(
                middleware_name="manual_lockout_middleware",
                conflict_type="priority_conflict",
            )
            counter.labels.return_value.inc.assert_called()

    def test_should_record_command_rejection(
        self,
        mock_prometheus: MagicMock,
    ) -> None:
        """Test that command rejections are recorded with correct labels."""
        with patch.dict("sys.modules", {"prometheus_client": mock_prometheus}):
            collector = MetricsCollector()
            collector.initialize()

            collector.record_command_rejection("low_priority", "turn_on")

            counter = mock_prometheus.Counter.return_value
            counter.labels.assert_called_with(
                reason="low_priority",
                command_type="turn_on",
            )
            counter.labels.return_value.inc.assert_called()

    def test_should_set_active_fsm_count(
        self,
        mock_prometheus: MagicMock,
    ) -> None:
        """Test that active FSM count is set with correct labels."""
        with patch.dict("sys.modules", {"prometheus_client": mock_prometheus}):
            collector = MetricsCollector()
            collector.initialize()

            collector.set_active_fsm_count("leonids_house", 7)

            gauge = mock_prometheus.Gauge.return_value
            gauge.labels.assert_called_with(manifest_name="leonids_house")
            gauge.labels.return_value.set.assert_called_once_with(7)


class TestGetMetricsCollector:
    """Test the get_metrics_collector singleton function."""

    def test_should_return_same_instance(self) -> None:
        """Test that get_metrics_collector returns the same instance."""
        collector1 = get_metrics_collector()
        collector2 = get_metrics_collector()
        assert collector1 is collector2

    def test_should_create_new_instance_if_none(self) -> None:
        """Test that get_metrics_collector creates instance if none exists."""
        # Reset the singleton
        import core.metrics as metrics_module

        metrics_module._metrics_collector = None

        collector = get_metrics_collector()
        assert isinstance(collector, MetricsCollector)
