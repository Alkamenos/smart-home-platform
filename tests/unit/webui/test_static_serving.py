"""Раздача собранного фронтенда (спека 017, FR-005, R-02).

Проверяется приоритет маршрутов: API отвечает сам, статика раздаёт страницы, а
неизвестный путь даёт 404, а не пустую страницу.

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from webui.static_serving import mount_frontend, should_serve_frontend


def _build_out(root: Path) -> Path:
    """Создать каталог сборки с двумя страницами.

    Args:
        root: Временный корень.

    Returns:
        Путь каталога сборки.
    """
    out = root / "out"
    (out / "devices").mkdir(parents=True)
    (out / "index.html").write_text("SPA-HOME", encoding="utf-8")
    (out / "devices" / "index.html").write_text("SPA-DEVICES", encoding="utf-8")
    return out


def test_static_serving_should_not_shadow_api(tmp_path: Path) -> None:
    """API-маршрут отвечает сам, статика раздаёт страницы."""
    app = FastAPI()

    @app.get("/api/v1/ping")
    async def ping() -> dict[str, bool]:
        return {"ok": True}

    assert mount_frontend(app, _build_out(tmp_path)) is True
    client = TestClient(app)

    assert client.get("/api/v1/ping").json() == {"ok": True}
    assert client.get("/").text == "SPA-HOME"
    assert client.get("/devices/").text == "SPA-DEVICES"


def test_static_serving_should_return_404_for_unknown_path(tmp_path: Path) -> None:
    """Неизвестный путь — 404, а не выдуманная страница."""
    app = FastAPI()

    assert mount_frontend(app, _build_out(tmp_path)) is True
    client = TestClient(app)

    assert client.get("/nope/").status_code == 404


def test_mount_should_be_noop_without_build(tmp_path: Path) -> None:
    """Без сборки раздача не добавляется — платформа работает как раньше."""
    app = FastAPI()

    assert mount_frontend(app, tmp_path / "missing") is False


def test_serving_should_be_on_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """Раздача статики — обычное поведение после удаления старого интерфейса."""
    monkeypatch.delenv("WEBUI_SERVE_FRONTEND", raising=False)

    assert should_serve_frontend() is True


def test_serving_should_be_off_when_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    """Переменной раздачу можно выключить (например, режим «только API»)."""
    monkeypatch.setenv("WEBUI_SERVE_FRONTEND", "0")

    assert should_serve_frontend() is False


@pytest.mark.parametrize("value", ["1", "true", "ON", "yes"])
def test_serving_should_be_on_when_enabled(monkeypatch: pytest.MonkeyPatch, value: str) -> None:
    """Раздача включается явной переменной.

    Args:
        value: Значение переменной.
    """
    monkeypatch.setenv("WEBUI_SERVE_FRONTEND", value)

    assert should_serve_frontend() is True
