"""
Тесты healthcheck-модуля контейнера (FR-001, FR-002; contracts/operational-contracts.md §1).

Модуль `src/cli/health_check.py` вызывается Docker healthcheck-ом:
`python -m src.cli.health_check` → exit 0 (проба /health вернула 200) /
exit 1 (недоступность, таймаут, не-200). Порт — из WEBUI_PORT (дефолт 8125).
"""

from __future__ import annotations

import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest
from src.cli.health_check import build_url, run_health_check


class _HealthHandler(BaseHTTPRequestHandler):
    """Обработчик /health для тестового HTTP-сервера."""

    status_code = 200
    delay = 0.0

    def do_GET(self) -> None:  # noqa: N802 (API BaseHTTPRequestHandler)
        if self.delay:
            time.sleep(self.delay)
        self.send_response(self.status_code)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        if self.path == "/health":
            self.wfile.write(b'{"status": "ok"}')

    def log_message(self, *args: object) -> None:
        """Подавить вывод запросов в stderr."""


def _serve(status_code: int = 200, delay: float = 0.0) -> tuple[HTTPServer, int]:
    """Запустить тестовый сервер, вернуть (сервер, порт)."""
    handler = type("Handler", (_HealthHandler,), {"status_code": status_code, "delay": delay})
    server = HTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, server.server_address[1]


def test_probe_live_server_returns_zero(monkeypatch: pytest.MonkeyPatch) -> None:
    """Живой сервер с /health 200 → exit 0."""
    server, port = _serve(status_code=200)
    try:
        monkeypatch.setenv("WEBUI_PORT", str(port))
        assert run_health_check(timeout=2.0) == 0
    finally:
        server.shutdown()


def test_unreachable_port_returns_one(monkeypatch: pytest.MonkeyPatch) -> None:
    """Недоступный порт (соединение отклонено) → exit 1."""
    server, port = _serve(status_code=200)
    server.shutdown()
    server.server_close()
    monkeypatch.setenv("WEBUI_PORT", str(port))
    assert run_health_check(timeout=1.0) == 1


def test_timeout_returns_one(monkeypatch: pytest.MonkeyPatch) -> None:
    """Сервер не отвечает дольше таймаута → exit 1."""
    server, port = _serve(status_code=200, delay=2.0)
    try:
        monkeypatch.setenv("WEBUI_PORT", str(port))
        assert run_health_check(timeout=0.2) == 1
    finally:
        server.shutdown()


def test_non_200_returns_one(monkeypatch: pytest.MonkeyPatch) -> None:
    """Сервер отвечает не-200 → exit 1."""
    server, port = _serve(status_code=500)
    try:
        monkeypatch.setenv("WEBUI_PORT", str(port))
        assert run_health_check(timeout=2.0) == 1
    finally:
        server.shutdown()


def test_build_url_default_port(monkeypatch: pytest.MonkeyPatch) -> None:
    """Без WEBUI_PORT используется дефолт 8125."""
    monkeypatch.delenv("WEBUI_PORT", raising=False)
    assert build_url() == "http://127.0.0.1:8125/health"


def test_build_url_reads_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """WEBUI_PORT переопределяет порт."""
    monkeypatch.setenv("WEBUI_PORT", "9999")
    assert build_url() == "http://127.0.0.1:9999/health"
