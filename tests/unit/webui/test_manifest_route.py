"""Правка манифеста через интерфейс (спека 017, US5, FR-027).

Проверяется то, ради чего маршрут заведён: текущий манифест читается, правка
проходит проверку до записи, ошибка называет поле, а запись, теряющая комнаты,
отклоняется — молчаливая потеря части дома недопустима (Known Issue #88).

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.models.manifest import Manifest
from core.persistence.manifest_store import ManifestStore
from webui.routes.manifest import router


MANIFEST_YAML = """
instance:
  id: probe
  name: Probe
  owner: probe
  created_at: "2026-01-01T00:00:00Z"
version: 1
rooms:
  - id: spalnia
    name: Спальня
    sensors: {}
    devices: []
"""


def _client(tmp_path: Path) -> TestClient:
    """Клиент с хранилищем манифеста из временного файла.

    Args:
        tmp_path: Временный каталог теста.

    Returns:
        Тестовый клиент.
    """
    path = tmp_path / "manifest.yaml"
    path.write_text(MANIFEST_YAML, encoding="utf-8")
    store = ManifestStore(str(path), Manifest)
    store.load()

    app = FastAPI()
    app.include_router(router)
    app.state.manifest_store = store
    return TestClient(app)


def test_get_manifest_should_return_current(tmp_path: Path) -> None:
    """Текущий манифест отдаётся целиком."""
    response = _client(tmp_path).get("/api/v1/manifest")

    assert response.status_code == 200
    body = response.json()
    assert body["manifest"]["instance"]["id"] == "probe"
    assert body["manifest"]["rooms"][0]["id"] == "spalnia"


def test_put_manifest_should_reject_invalid_with_fields(tmp_path: Path) -> None:
    """Невалидный манифест — 400 с ошибкой по полю."""
    response = _client(tmp_path).put("/api/v1/manifest", json={"version": 1})

    assert response.status_code == 400
    body = response.json()
    assert body["error"]
    assert any("instance" in field["loc"] for field in body["fields"])


def test_put_manifest_should_refuse_shrinking(tmp_path: Path) -> None:
    """Запись, теряющая комнаты, отклоняется (409)."""
    client = _client(tmp_path)
    body = client.get("/api/v1/manifest").json()["manifest"]
    body["rooms"] = []

    response = client.put("/api/v1/manifest", json=body)

    assert response.status_code == 409
    assert "spalnia" in response.json()["error"]


def test_put_manifest_should_save_valid(tmp_path: Path) -> None:
    """Корректная правка сохраняется."""
    client = _client(tmp_path)
    body = client.get("/api/v1/manifest").json()["manifest"]
    body["rooms"][0]["name"] = "Спальня (переименована)"

    response = client.put("/api/v1/manifest", json=body)

    assert response.status_code == 200
    assert response.json()["status"] == "saved"
    assert client.get("/api/v1/manifest").json()["manifest"]["rooms"][0]["name"] == (
        "Спальня (переименована)"
    )
