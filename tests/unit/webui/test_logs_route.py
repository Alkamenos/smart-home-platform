"""Технические логи в интерфейсе: GET /api/v1/logs (спека 017, US6, FR-028).

Проверяется то, ради чего маршрут заведён: свежие технические сообщения с
уровнем, а не пустой ответ; недоступное хранилище — 503, а не «логов нет».

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from webui.app import LogStore
from webui.routes.logs import router


def _client(store: object | None) -> TestClient:
    """Клиент с маршрутом логов.

    Args:
        store: Хранилище логов либо ``None``.

    Returns:
        Тестовый клиент.
    """
    app = FastAPI()
    app.include_router(router)
    if store is not None:
        app.state.log_store = store
    return TestClient(app)


def test_logs_should_return_recent_messages() -> None:
    """Свежие сообщения отдаются вместе с уровнем."""
    store = LogStore()
    store.add("INFO", "Старт")
    store.add("ERROR", "Ошибка синхронизации")

    body = _client(store).get("/api/v1/logs").json()

    assert body["count"] == 2
    assert body["logs"][0]["message"] == "Ошибка синхронизации"
    assert body["logs"][0]["level"] == "ERROR"


def test_logs_should_respect_limit() -> None:
    """Число сообщений ограничивается запросом."""
    store = LogStore()
    for index in range(10):
        store.add("INFO", f"сообщение {index}")

    body = _client(store).get("/api/v1/logs", params={"limit": 3}).json()

    assert len(body["logs"]) == 3


def test_logs_should_report_503_without_store() -> None:
    """Недоступное хранилище — 503, а не пустой список."""
    response = _client(None).get("/api/v1/logs")

    assert response.status_code == 503
