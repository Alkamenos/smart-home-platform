"""
Tests for Prometheus metrics collection and server.
"""

import time

import pytest

from smart_home.core.metrics import (
    MetricsCollector,
    MetricsRegistry,
    get_metrics_registry,
    reset_global_metrics,
    track_latency,
)
from smart_home.services.metrics_server import create_metrics_app


@pytest.fixture
def metrics_registry():
    """Create a fresh metrics registry for each test."""
    registry = MetricsRegistry()
    yield registry
    registry.reset()


@pytest.fixture
def metrics_collector(metrics_registry):
    """Create a metrics collector with a fresh registry."""
    return MetricsCollector(registry=metrics_registry)


class TestMetricsRegistry:
    """Tests for MetricsRegistry class."""

    def test_initialization(self, metrics_registry):
        """Test that metrics registry initializes correctly."""
        assert metrics_registry._initialized is False
        # Accessing registry should trigger initialization
        _ = metrics_registry.registry
        assert metrics_registry._initialized is True

    def test_metrics_creation(self, metrics_registry):
        """Test that all expected metrics are created."""
        _ = metrics_registry.registry  # Trigger initialization

        assert hasattr(metrics_registry, "fsm_transitions_total")
        assert hasattr(metrics_registry, "event_processing_latency_seconds")
        assert hasattr(metrics_registry, "ha_adapter_connection_errors_total")
        assert hasattr(metrics_registry, "middleware_conflicts_total")
        assert hasattr(metrics_registry, "command_dispatcher_rejections_total")
        assert hasattr(metrics_registry, "active_fsm_instances")
        assert hasattr(metrics_registry, "http_requests_total")
        assert hasattr(metrics_registry, "http_request_latency_seconds")

    def test_reset(self, metrics_registry):
        """Test that reset clears all metrics."""
        _ = metrics_registry.registry  # Trigger initialization
        assert metrics_registry._initialized is True

        metrics_registry.reset()
        # After reset, should be re-initialized with new registry
        assert metrics_registry._initialized is True
        # Verify we can still access metrics after reset
        assert hasattr(metrics_registry, "fsm_transitions_total")


class TestMetricsCollector:
    """Tests for MetricsCollector class."""

    def test_record_fsm_transition(self, metrics_collector):
        """Test recording FSM transitions."""
        metrics_collector.record_fsm_transition(
            fsm_id="light_fsm_1",
            device_id="light.bedroom",
            from_state="off",
            to_state="on",
        )

        # Verify metric was recorded by checking no exception raised
        # In real scenario, we'd scrape the registry to verify
        metrics_data = metrics_collector.get_latest_metrics()
        assert b"fsm_transitions_total" in metrics_data
        assert b'fsm_id="light_fsm_1"' in metrics_data

    def test_record_event_latency(self, metrics_collector):
        """Test recording event processing latency."""
        metrics_collector.record_event_latency(
            event_type="motion_detected",
            handler="light_handler",
            duration=0.05,
        )

        metrics_data = metrics_collector.get_latest_metrics()
        assert b"event_processing_latency_seconds" in metrics_data

    def test_record_ha_error(self, metrics_collector):
        """Test recording Home Assistant adapter errors."""
        metrics_collector.record_ha_error(
            error_type="connection_timeout",
            endpoint="/api/states",
        )

        metrics_data = metrics_collector.get_latest_metrics()
        assert b"ha_adapter_connection_errors_total" in metrics_data
        assert b'error_type="connection_timeout"' in metrics_data

    def test_record_middleware_conflict(self, metrics_collector):
        """Test recording middleware conflicts."""
        metrics_collector.record_middleware_conflict(
            middleware_name="guard_middleware",
            conflict_type="state_conflict",
        )

        metrics_data = metrics_collector.get_latest_metrics()
        assert b"middleware_conflicts_total" in metrics_data

    def test_record_command_rejection(self, metrics_collector):
        """Test recording command rejections."""
        metrics_collector.record_command_rejection(
            reason="invalid_state",
            command_type="turn_on",
        )

        metrics_data = metrics_collector.get_latest_metrics()
        assert b"command_dispatcher_rejections_total" in metrics_data

    def test_active_fsm_instances_gauge(self, metrics_collector):
        """Test setting active FSM instances."""
        metrics_collector.set_active_fsm_instances(count=5, fsm_type="automation")

        metrics_data = metrics_collector.get_latest_metrics()
        assert b"active_fsm_instances" in metrics_data
        assert b'fsm_type="automation"' in metrics_data

    def test_increment_decrement_fsm_instances(self, metrics_collector):
        """Test incrementing and decrementing FSM instances."""
        metrics_collector.increment_active_fsm_instances(fsm_type="default")
        metrics_collector.increment_active_fsm_instances(fsm_type="default")
        metrics_collector.decrement_active_fsm_instances(fsm_type="default")

        metrics_data = metrics_collector.get_latest_metrics()
        assert b"active_fsm_instances" in metrics_data

    def test_record_http_request(self, metrics_collector):
        """Test recording HTTP requests."""
        metrics_collector.record_http_request(
            method="GET",
            endpoint="/metrics",
            status_code=200,
            latency=0.01,
        )

        metrics_data = metrics_collector.get_latest_metrics()
        assert b"http_requests_total" in metrics_data
        assert b"http_request_latency_seconds" in metrics_data


class TestTrackLatency:
    """Tests for track_latency context manager."""

    def test_track_latency_context_manager(self, metrics_registry):
        """Test tracking latency with context manager."""
        collector = MetricsCollector(registry=metrics_registry)

        with track_latency(
            metrics_registry.event_processing_latency_seconds,
            "test_event",
            "test_handler",
        ):
            time.sleep(0.01)  # Simulate some work

        metrics_data = collector.get_latest_metrics()
        assert b"event_processing_latency_seconds" in metrics_data


class TestGlobalRegistry:
    """Tests for global registry functions."""

    def test_get_metrics_registry_singleton(self):
        """Test that get_metrics_registry returns singleton."""
        reset_global_metrics()
        registry1 = get_metrics_registry()
        registry2 = get_metrics_registry()
        assert registry1 is registry2

    def test_reset_global_metrics(self):
        """Test resetting global metrics."""
        reset_global_metrics()
        registry1 = get_metrics_registry()
        reset_global_metrics()
        registry2 = get_metrics_registry()
        assert registry1 is not registry2


class TestMetricsServer:
    """Tests for metrics server."""

    @pytest.mark.asyncio
    async def test_metrics_endpoint(self):
        """Test /metrics endpoint returns Prometheus format."""
        app = create_metrics_app(prefix="")

        from starlette.testclient import TestClient

        with TestClient(app) as client:
            response = client.get("/metrics")

            assert response.status_code == 200
            assert "text/plain" in response.headers["content-type"]
            assert b"fsm_transitions_total" in response.content

    @pytest.mark.asyncio
    async def test_health_endpoint(self):
        """Test /health endpoint."""
        app = create_metrics_app(prefix="")

        from starlette.testclient import TestClient

        with TestClient(app) as client:
            response = client.get("/health")

            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "healthy"
            assert data["service"] == "metrics-server"

    @pytest.mark.asyncio
    async def test_ready_endpoint(self):
        """Test /ready endpoint."""
        app = create_metrics_app(prefix="")

        from starlette.testclient import TestClient

        with TestClient(app) as client:
            response = client.get("/ready")

            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "ready"

    @pytest.mark.asyncio
    async def test_metrics_with_prefix(self):
        """Test metrics endpoint with URL prefix."""
        app = create_metrics_app(prefix="/api/v1")

        from starlette.testclient import TestClient

        with TestClient(app) as client:
            response = client.get("/api/v1/metrics")

            assert response.status_code == 200
            assert b"fsm_transitions_total" in response.content
