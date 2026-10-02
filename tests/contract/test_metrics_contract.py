"""
Контрактные тесты диагностической точки ``GET /metrics``.

Форма ответа зафиксирована в ``contracts/metrics-api.md``: текстовый документ
показателей, а не JSON. Отдельный вызов намеренно отличается от ``/health``:
показатели скрейпит система мониторинга, а не браузер панели (FR-002, FR-011).

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from prometheus_client import CollectorRegistry
from src.core.events.event_bus import EventBus

from core.events.fsm_events import OUTCOME_TRANSITIONED, build_transition_payload
from core.metrics import MetricsCollector, get_metrics_collector
from services.metrics_reporter import MetricsReporter


REQUIRED_METRIC_NAMES = (
    "fsm_transitions_total",
    "fsm_rejections_total",
    "fsm_states_restored_total",
    "active_fsm_instances",
    "fsm_stuck_current",
    "watchdog_checks_total",
    "watchdog_last_snapshot_timestamp",
    "ha_connection_lost",
    "metrics_collection_errors_total",
)


@pytest.fixture
def registry() -> CollectorRegistry:
    """Изолированный реестр измерений."""
    return CollectorRegistry()


@pytest.fixture
def client(registry: CollectorRegistry) -> TestClient:
    """Приложение с подключённым сборщиком показателей."""
    from src.webui.routes import router

    metrics = MetricsCollector(registry=registry)
    metrics.initialize()
    MetricsReporter(EventBus(), metrics)

    app = FastAPI()
    app.include_router(router)
    app.state.metrics = metrics
    return TestClient(app)


class TestMetricsEndpointShape:
    """Форма ответа диагностической точки."""

    def test_should_return_text_when_requested(self, client: TestClient) -> None:
        """Ответ — текстовый документ показателей, а не JSON."""
        response = client.get("/metrics")

        assert response.status_code == 200
        assert "text/plain" in response.headers["content-type"]
        assert not response.headers["content-type"].startswith("application/json")

    def test_should_start_with_help_comment_when_requested(self, client: TestClient) -> None:
        """Тело начинается с ``# HELP``, а не с ``{``."""
        body = client.get("/metrics").text

        assert body.startswith("# HELP")
        assert not body.lstrip().startswith("{")

    def test_should_be_open_like_health_endpoint(self, client: TestClient) -> None:
        """Маршрут открыт, как ``/health``: аутентификации у диагностики нет."""
        assert client.get("/metrics").status_code == 200

    def test_should_expose_required_metric_families_when_empty(self, client: TestClient) -> None:
        """До первого события метрики присутствуют, а не отсутствуют.

        Отсутствие событий не должно означать отсутствие метрик: мониторинг
        отличает «счётчик равен нулю» от «счётчика нет» (FR-002, SC-004).
        """
        body = client.get("/metrics").text

        for name in REQUIRED_METRIC_NAMES:
            assert f"# TYPE {name} " in body, f"{name} missing from /metrics"


class TestMetricsEndpointContent:
    """Содержимое ответа после событий."""

    def test_should_reflect_recorded_transition(self, client: TestClient) -> None:
        """Переход, записанный подписчиком, виден в ответе."""
        payload = build_transition_payload(
            fsm_id="light.kitchen_lighting_10",
            device_id="light.kitchen",
            from_state="off",
            to_state="on",
            event="motion_detected",
            outcome=OUTCOME_TRANSITIONED,
        )
        client.app.state.metrics.record_fsm_transition(
            fsm_name=payload["fsm_id"],
            from_state=payload["from_state"],
            to_state=payload["to_state"],
            device=payload["device_id"],
        )

        body = client.get("/metrics").text

        assert 'fsm_transitions_total{device="light.kitchen"' in body
        assert 'to_state="on"' in body


class TestMetricsEndpointDegradation:
    """Поведение при недоступной или отключённой сборе метрик."""

    def test_should_return_service_unavailable_when_not_initialized(
        self, registry: CollectorRegistry
    ) -> None:
        """Неинициализированный сборщик — это 503, а не пустой документ.

        Пустой ответ 200 мониторинг принял бы за «показатели собираются и их
        ноль» (FR-002, контракт §1.5).
        """
        from src.webui.routes import router

        app = FastAPI()
        app.include_router(router)
        app.state.metrics = MetricsCollector(registry=registry)
        client = TestClient(app)

        response = client.get("/metrics")

        assert response.status_code == 503
        assert "reason" in response.json() or "detail" in response.json()

    def test_should_explain_when_collection_disabled(self) -> None:
        """Отключённая настройка — 200 с пояснением, а не тишина."""
        from src.webui.routes import router

        metrics = MetricsCollector()
        app = FastAPI()
        app.include_router(router)
        app.state.metrics = metrics
        client = TestClient(app)

        with pytest.MonkeyPatch.context() as monkeypatch:
            monkeypatch.setattr("core.metrics.metrics_enabled", lambda: False)
            response = client.get("/metrics")

        assert response.status_code == 200
        assert "disabled" in response.text.lower() or "disabled" in response.text


class TestMetricsEndpointCollectionError:
    """Ошибка формирования документа."""

    def test_should_report_error_instead_of_silent_success(
        self, registry: CollectorRegistry
    ) -> None:
        """Сбой выдачи не приводит к молчаливому успеху (FR-008)."""
        from src.webui.routes import router

        metrics = MetricsCollector(registry=registry)
        metrics.initialize()
        app = FastAPI()
        app.include_router(router)
        app.state.metrics = metrics
        client = TestClient(app)

        # Подменяем именно формирование документа, а не сборщик целиком.
        with pytest.MonkeyPatch.context() as monkeypatch:
            monkeypatch.setattr(
                "src.webui.routes.generate_latest",
                lambda *a, **k: (_ for _ in ()).throw(RuntimeError()),
            )
            response = client.get("/metrics")

        assert response.status_code == 500


class TestMetricsSingletonWiring:
    """Платформа использует один сборщик показателей."""

    def test_should_return_same_global_collector(self) -> None:
        """Глобальный сборщик — синглтон (R-01)."""
        assert get_metrics_collector() is get_metrics_collector()
