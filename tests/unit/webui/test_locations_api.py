"""HTTP-доступ к состоянию и истории локаций (спека 016, FR-006, FR-007).

Проверяется то, ради чего эндпоинты и заведены: по одному запросу видно всё,
что известно о локации сейчас (значения с временем и молчащие датчики), а по
журналу за интервал восстанавливается, как менялись показатели, — без обращения
к коду и без внешней базы.

Журнал подменяется файлом во временном каталоге: тест не должен читать боевую
историю дома.

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import webui.routes.locations as locations_module
from core.models.manifest import (
    AutomationRules,
    InstanceConfig,
    LocationConfig,
    Manifest,
    RoomConfig,
)
from core.persistence.event_store import EventStore, SensorEvent
from core.services.location_state import LocationStateService
from webui.routes.locations import router


NOW = datetime(2026, 10, 13, 9, 0, 0, tzinfo=UTC)


def _manifest() -> Manifest:
    """Дом из комнаты и особой зоны (улицы).

    Returns:
        Модель манифеста.
    """
    return Manifest(
        instance=InstanceConfig(
            id="probe", name="Probe", owner="probe", created_at="2026-01-01T00:00:00Z"
        ),
        rooms=[
            RoomConfig(
                id="spalnia",
                name="Спальня",
                sensors={
                    "temperature": "sensor.t_spalnia",
                    "motion": "binary_sensor.m_spalnia",
                },
            )
        ],
        locations=[
            LocationConfig(
                id="ulitsa",
                name="Улица",
                kind="outdoor",
                sensors={"temperature": "sensor.t_ulitsa"},
            )
        ],
        automation_rules=AutomationRules(),
    )


def _service() -> LocationStateService:
    """Наблюдение за локациями с показаниями.

    Returns:
        Сервис наблюдения.
    """
    service = LocationStateService(_manifest(), unit_provider=lambda _: "°C")
    # Момент — настоящий: маршрут читает снимок по своим часам, и фиксированное
    # время сделало бы показания устаревшими (молчание и присутствие посчитались
    # бы по разнице с «сейчас»).
    moment = datetime.now(UTC)
    service.record("sensor.t_spalnia", "22.4", at=moment - timedelta(seconds=30))
    service.record("binary_sensor.m_spalnia", "on", at=moment - timedelta(seconds=120))
    service.record("binary_sensor.m_spalnia", "off", at=moment - timedelta(seconds=60))
    service.record("sensor.t_ulitsa", "14.4", at=moment - timedelta(seconds=10))
    return service


def _client(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    service: Any | None,
) -> Iterator[TestClient]:
    """Клиент приложения с подменённым журналом и указанным наблюдением.

    Args:
        monkeypatch: Подмена модульных зависимостей.
        tmp_path: Временный каталог для журнала.
        service: Наблюдение за локациями (или ``None`` — платформа не собрана).

    Yields:
        Клиент FastAPI.
    """
    store = EventStore(str(tmp_path / "history.db"))
    monkeypatch.setattr(locations_module, "event_store", store)

    app = FastAPI()
    app.include_router(router)
    app.state.container = SimpleNamespace(location_state=service)
    yield TestClient(app)


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[TestClient]:
    """Клиент с собранным наблюдением за локациями.

    Args:
        monkeypatch: Подмена журнала.
        tmp_path: Временный каталог.

    Yields:
        Клиент FastAPI.
    """
    yield from _client(monkeypatch, tmp_path, _service())


class TestLocationList:
    """Список локаций."""

    def test_lists_rooms_and_zones(self, client: TestClient) -> None:
        """Комнаты и особые зоны в одном списке (FR-004)."""
        response = client.get("/api/v1/locations")

        assert response.status_code == 200
        payload = response.json()
        assert payload["count"] == 2
        assert {item["id"] for item in payload["locations"]} == {"spalnia", "ulitsa"}

    def test_reports_unavailable_without_platform(self, monkeypatch: Any, tmp_path: Path) -> None:
        """Без платформы эндпоинт говорит об этом, а не отдаёт пустоту."""
        client = next(_client(monkeypatch, tmp_path, None))

        response = client.get("/api/v1/locations")

        assert response.status_code == 503


class TestLocationState:
    """Снимок локации (US1)."""

    def test_snapshot_has_readings_and_derived(self, client: TestClient) -> None:
        """Снимок отдаёт значения с временем и производные."""
        response = client.get("/api/v1/locations/spalnia/state")

        assert response.status_code == 200
        payload = response.json()
        assert payload["location"]["name"] == "Спальня"
        temperature = payload["readings"]["temperature"][0]
        assert temperature["value"] == 22.4
        assert temperature["unit"] == "°C"
        assert payload["derived"]["occupied"] is True
        assert payload["derived"]["sensor_count"] == 2

    def test_zone_snapshot_includes_outdoor_reading(self, client: TestClient) -> None:
        """Особая зона отдаёт свои датчики (US1, сценарий 3)."""
        response = client.get("/api/v1/locations/ulitsa/state")

        payload = response.json()
        assert payload["location"]["kind"] == "outdoor"
        assert payload["readings"]["temperature"][0]["value"] == 14.4

    def test_unknown_location_is_404(self, client: TestClient) -> None:
        """Неизвестная локация — 404, а не пустой снимок."""
        response = client.get("/api/v1/locations/takogo_net/state")

        assert response.status_code == 404


class TestLocationHistory:
    """Журнал изменений локации (US2)."""

    def test_history_returns_records_with_role(self, monkeypatch: Any, tmp_path: Path) -> None:
        """Изменения показателей видны с ролью и временем."""
        store = EventStore(str(tmp_path / "history.db"))
        store.save_sensor_event(
            SensorEvent(
                entity_id="sensor.t_spalnia",
                old_state="22.0",
                new_state="22.4",
                event_type="state_changed",
                trace_id=None,
                timestamp=NOW.timestamp() - 60,
            )
        )
        monkeypatch.setattr(locations_module, "event_store", store)
        app = FastAPI()
        app.include_router(router)
        app.state.container = SimpleNamespace(location_state=_service())
        client = TestClient(app)

        response = client.get("/api/v1/locations/spalnia/history")

        assert response.status_code == 200
        payload = response.json()
        assert payload["count"] == 1
        [record] = payload["records"]
        assert record["role"] == "temperature"
        assert record["old_value"] == "22.0"
        assert record["value"] == "22.4"

    def test_history_ignores_other_locations(self, monkeypatch: Any, tmp_path: Path) -> None:
        """В журнал локации не попадают датчики других локаций."""
        store = EventStore(str(tmp_path / "history.db"))
        store.save_sensor_event(
            SensorEvent(
                entity_id="sensor.t_ulitsa",
                old_state="14.0",
                new_state="14.4",
                event_type="state_changed",
                trace_id=None,
                timestamp=NOW.timestamp() - 60,
            )
        )
        monkeypatch.setattr(locations_module, "event_store", store)
        app = FastAPI()
        app.include_router(router)
        app.state.container = SimpleNamespace(location_state=_service())
        client = TestClient(app)

        response = client.get("/api/v1/locations/spalnia/history")

        assert response.json()["count"] == 0

    def test_history_window_filters_old_records(self, monkeypatch: Any, tmp_path: Path) -> None:
        """Интервал отсекает старые записи."""
        store = EventStore(str(tmp_path / "history.db"))
        store.save_sensor_event(
            SensorEvent(
                entity_id="sensor.t_spalnia",
                old_state="21.0",
                new_state="21.4",
                event_type="state_changed",
                trace_id=None,
                timestamp=NOW.timestamp() - 7200,
            )
        )
        monkeypatch.setattr(locations_module, "event_store", store)
        app = FastAPI()
        app.include_router(router)
        app.state.container = SimpleNamespace(location_state=_service())
        client = TestClient(app)

        response = client.get(
            "/api/v1/locations/spalnia/history",
            params={"from": (NOW - timedelta(hours=1)).isoformat()},
        )

        assert response.json()["count"] == 0

    def test_bad_time_is_rejected(self, client: TestClient) -> None:
        """Непонятное время — ошибка 400, а не тихий пропуск фильтра."""
        response = client.get("/api/v1/locations/spalnia/history", params={"from": "не время"})

        assert response.status_code == 400

    def test_unknown_location_history_is_404(self, client: TestClient) -> None:
        """История неизвестной локации — 404."""
        response = client.get("/api/v1/locations/takogo_net/history")

        assert response.status_code == 404
