"""Контракт единого конверта ошибок API (спека 018, US5, T063)."""

from __future__ import annotations

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from webui.errors import install_error_handlers
from webui.middleware_request_id import RequestIdMiddleware


def _client() -> TestClient:
    app = FastAPI()
    app.add_middleware(RequestIdMiddleware)
    install_error_handlers(app)

    @app.get("/forbidden")
    async def forbidden() -> None:
        raise HTTPException(status_code=403, detail="Недостаточно прав")

    @app.get("/missing")
    async def missing() -> None:
        raise HTTPException(status_code=404, detail="Объект не найден")

    @app.get("/boom")
    async def boom() -> None:
        raise RuntimeError("секретный внутренний путь /srv/private")

    return TestClient(app, raise_server_exceptions=False)


def test_error_envelope_has_code_message_fields_and_trace_id() -> None:
    """Любая ошибка API несёт код, сообщение, поля и trace_id."""
    response = _client().get("/forbidden")

    assert response.status_code == 403
    body = response.json()
    assert set(body) == {"error"}
    error = body["error"]
    assert error["code"] == "forbidden"
    assert error["message"]
    assert error["fields"] == []
    assert error["trace_id"]
    assert response.headers["X-Trace-ID"] == error["trace_id"]


def test_not_found_uses_stable_code() -> None:
    """404 называется not_found, а не текстом исключения."""
    response = _client().get("/missing")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


def test_internal_error_does_not_leak_details() -> None:
    """500 не отдаёт внутренний текст и путь."""
    response = _client().get("/boom")

    assert response.status_code == 500
    error = response.json()["error"]
    assert error["code"] == "internal_error"
    assert "/srv/private" not in error["message"]
    assert "секретный" not in error["message"]


def test_error_is_json_not_html() -> None:
    """Для API ошибка остаётся JSON-конвертом."""
    response = _client().get("/forbidden")

    assert response.headers["content-type"].startswith("application/json")
    assert "<html" not in response.text.lower()
