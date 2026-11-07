"""Связь trace_id ответа и журнала (спека 018, US5, T065)."""

from __future__ import annotations

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from webui.errors import install_error_handlers
from webui.middleware_request_id import RequestIdMiddleware


def _client() -> TestClient:
    app = FastAPI()
    app.add_middleware(RequestIdMiddleware)
    install_error_handlers(app)

    @app.get("/fail")
    async def fail() -> None:
        raise HTTPException(status_code=400, detail="Неверный запрос")

    return TestClient(app)


def test_trace_id_is_in_body_and_header() -> None:
    """Один и тот же trace_id в теле ошибки и заголовке ответа."""
    response = _client().get("/fail")

    assert response.status_code == 400
    body_trace = response.json()["error"]["trace_id"]
    assert body_trace == response.headers["X-Trace-ID"]


def test_external_trace_id_is_accepted() -> None:
    """Внешний безопасный trace_id сохраняется."""
    response = _client().get("/fail", headers={"X-Trace-ID": "abc_123"})

    assert response.json()["error"]["trace_id"] == "abc_123"
    assert response.headers["X-Trace-ID"] == "abc_123"


def test_unsafe_trace_id_is_replaced() -> None:
    """Небезопасный внешний trace_id заменяется своим."""
    response = _client().get("/fail", headers={"X-Trace-ID": "bad id!"})

    trace = response.json()["error"]["trace_id"]
    assert trace != "bad id!"
    assert trace.isalnum()
