"""Журнал интерфейса: GET /api/v1/events (спека 017, US4, FR-020, FR-021).

Проверяется то, на что опирается страница журнала: одна лента событий и
переходов, фильтры (сущность/локация/трассировка), курсор для подгрузки старше
и честные ошибки вместо пустоты.

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import webui.routes.events as events_module
from webui.routes.events import router


def _row(timestamp: float, kind: str = "event") -> dict[str, Any]:
    """Строка журнала для подменённого хранилища.

    Args:
        timestamp: Время записи.
        kind: Вид записи (``event`` или ``transition``).

    Returns:
        Словарь записи.
    """
    return {
        "timestamp": timestamp,
        "kind": kind,
        "entity_id": "sensor.t_spalnia",
        "old_state": "21.0",
        "new_state": "22.4",
        "detail": "state_change",
        "trace_id": "trace-1",
        "from_state": "OFF" if kind == "transition" else None,
        "to_state": "ON" if kind == "transition" else None,
        "trigger_name": "motion_detected" if kind == "transition" else None,
    }


class _FakeStore:
    """Подменённое хранилище журнала с записью вызовов."""

    def __init__(self, rows: list[dict[str, Any]], calls: list[dict[str, Any]]) -> None:
        self._rows = rows
        self._calls = calls

    def query_journal(self, **kwargs: Any) -> list[dict[str, Any]]:
        """Вернуть заранее заданные записи, запомнив аргументы."""
        self._calls.append(kwargs)
        return self._rows


def _client(rows: list[dict[str, Any]], monkeypatch: pytest.MonkeyPatch) -> tuple[TestClient, list]:
    """Клиент с маршрутом журнала.

    Args:
        rows: Записи, которые вернёт хранилище.
        monkeypatch: Фикстура подмены.

    Returns:
        Тестовый клиент и список вызовов хранилища.
    """
    calls: list[dict[str, Any]] = []
    monkeypatch.setattr(events_module, "event_store", _FakeStore(rows, calls))
    app = FastAPI()
    app.include_router(router)
    app.state.container = None
    return TestClient(app), calls


def test_events_should_return_records(monkeypatch: pytest.MonkeyPatch) -> None:
    """Лента отдаёт записи с человекочитаемым текстом и временем."""
    client, _ = _client([_row(1_700_000_000.0), _row(1_700_000_100.0, "transition")], monkeypatch)

    response = client.get("/api/v1/events")

    assert response.status_code == 200
    body = response.json()
    assert body["count"] == 2
    assert body["records"][0]["kind"] == "event"
    assert "→" in body["records"][0]["message"]
    assert body["records"][0]["at"].startswith("2023-11-14")


def test_events_should_return_empty_list_on_no_data(monkeypatch: pytest.MonkeyPatch) -> None:
    """Отсутствие записей — это 200 с пустой лентой, а не ошибка."""
    client, _ = _client([], monkeypatch)

    response = client.get("/api/v1/events")

    assert response.status_code == 200
    assert response.json()["records"] == []
    assert response.json()["next_cursor"] is None


def test_events_should_pass_filters_and_cursor(monkeypatch: pytest.MonkeyPatch) -> None:
    """Фильтры и курсор уходят в хранилище."""
    client, calls = _client([_row(1.0)], monkeypatch)

    client.get("/api/v1/events", params={"device": "light.x", "trace": "t1", "before": "100"})

    assert calls[0]["entity_ids"] == ["light.x"]
    assert calls[0]["trace_id"] == "t1"
    assert calls[0]["before_ts"] == 100.0


def test_events_should_set_cursor_when_page_is_full(monkeypatch: pytest.MonkeyPatch) -> None:
    """Заполненная страница отдаёт курсор для подгрузки старше."""
    client, _ = _client([_row(10.0), _row(5.0)], monkeypatch)

    body = client.get("/api/v1/events", params={"limit": 2}).json()

    assert body["next_cursor"] == 5.0


def test_events_should_reject_bad_time(monkeypatch: pytest.MonkeyPatch) -> None:
    """Непонятное время — 400, а не молчаливое игнорирование."""
    client, _ = _client([], monkeypatch)

    response = client.get("/api/v1/events", params={"from": "вчера"})

    assert response.status_code == 400


def test_events_should_404_for_unknown_location(monkeypatch: pytest.MonkeyPatch) -> None:
    """Неизвестная локация — 404."""
    client, _ = _client([], monkeypatch)
    service = SimpleNamespace(location_ids=lambda: ["spalnia"], sensor_entities=lambda _: [])
    client.app.state.container = SimpleNamespace(location_state=service)

    response = client.get("/api/v1/events", params={"location": "нетакой"})

    assert response.status_code == 404
