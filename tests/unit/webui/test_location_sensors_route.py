"""Роли датчиков локаций: чтение и правка (спека 017, US5, FR-026).

Проверяется то, ради чего эндпоинт заведён: интерфейс видит привязку
«роль → сущность» и может её изменить, причём правка ложится туда, где локация
объявлена — в комнату или в особую зону.

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.models.manifest import Manifest
from core.persistence.manifest_store import ManifestStore
from webui.routes.locations import router
from webui.routes.manifest import router as manifest_router


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
    sensors:
      temperature: sensor.t_spalnia
    devices: []
locations:
  - id: ulitsa
    name: Улица
    kind: outdoor
    sensors:
      temperature: sensor.t_ulitsa
"""


class _LocationState:
    """Наблюдение за локациями: только то, что нужно маршруту чтения."""

    def locations(self) -> list[dict[str, Any]]:
        """Краткое описание локаций."""
        return [
            {"id": "spalnia", "name": "Спальня", "kind": "room", "sensor_count": 1},
            {"id": "ulitsa", "name": "Улица", "kind": "outdoor", "sensor_count": 1},
        ]

    def sensor_entities(self, location_id: str) -> list[str]:
        """Сущности локации."""
        return {
            "spalnia": ["sensor.t_spalnia"],
            "ulitsa": ["sensor.t_ulitsa"],
        }.get(location_id, [])

    def role_of(self, location_id: str, entity_id: str) -> str | None:
        """Роль сущности."""
        return {"sensor.t_spalnia": "temperature", "sensor.t_ulitsa": "temperature"}.get(entity_id)


def _client(tmp_path: Path, *, with_store: bool = True) -> TestClient:
    """Клиент с маршрутами локаций и хранилищем манифеста.

    Args:
        tmp_path: Временный каталог теста.
        with_store: Кладывать ли хранилище манифеста в состояние.

    Returns:
        Тестовый клиент.
    """
    path = tmp_path / "manifest.yaml"
    path.write_text(MANIFEST_YAML, encoding="utf-8")

    app = FastAPI()
    app.include_router(router)
    app.include_router(manifest_router)
    app.state.container = SimpleNamespace(location_state=_LocationState())
    app.state.default_user_id = "admin_user"
    app.state.default_user_is_admin = True
    if with_store:
        store = ManifestStore(str(path), Manifest)
        store.load()
        app.state.manifest_store = store
    return TestClient(app)


def test_list_should_include_sensor_roles(tmp_path: Path) -> None:
    """Список локаций несёт привязку «роль → сущности»."""
    body = _client(tmp_path).get("/api/v1/locations").json()

    by_id = {item["id"]: item for item in body["locations"]}
    assert by_id["spalnia"]["sensors"] == {"temperature": ["sensor.t_spalnia"]}
    assert by_id["ulitsa"]["sensors"] == {"temperature": ["sensor.t_ulitsa"]}


def test_update_should_accept_list_of_entities(tmp_path: Path) -> None:
    """Роль может закрываться несколькими сущностями (две камеры)."""
    client = _client(tmp_path)

    response = client.put(
        "/api/v1/locations/spalnia",
        json={"sensors": {"person": ["binary_sensor.a", "binary_sensor.b"]}},
    )

    assert response.status_code == 200
    sensors = client.get("/api/v1/manifest").json()["manifest"]["rooms"][0]["sensors"]
    assert sensors["person"] == ["binary_sensor.a", "binary_sensor.b"]


def test_update_should_write_room_sensors(tmp_path: Path) -> None:
    """Правка комнаты ложится в rooms[].sensors."""
    client = _client(tmp_path)

    response = client.put(
        "/api/v1/locations/spalnia",
        json={"sensors": {"temperature": "sensor.t_new", "humidity": "sensor.h_new"}},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "saved"
    sensors = client.get("/api/v1/manifest").json()["manifest"]["rooms"][0]["sensors"]
    assert sensors == {"temperature": "sensor.t_new", "humidity": "sensor.h_new"}


def test_update_should_write_location_sensors(tmp_path: Path) -> None:
    """Правка особой зоны ложится в locations[].sensors."""
    client = _client(tmp_path)

    response = client.put(
        "/api/v1/locations/ulitsa",
        json={"sensors": {"rain": "binary_sensor.rain"}},
    )

    assert response.status_code == 200
    locations = client.get("/api/v1/manifest").json()["manifest"]["locations"]
    assert locations[0]["sensors"] == {"rain": "binary_sensor.rain"}


def test_update_should_404_for_unknown_location(tmp_path: Path) -> None:
    """Неизвестная локация — 404."""
    response = _client(tmp_path).put("/api/v1/locations/nope", json={"sensors": {}})

    assert response.status_code == 404


def test_update_should_reject_bad_entity(tmp_path: Path) -> None:
    """Некорректная сущность — 400."""
    response = _client(tmp_path).put(
        "/api/v1/locations/spalnia",
        json={"sensors": {"temperature": "не сущность"}},
    )

    assert response.status_code == 400


def test_update_should_503_without_store(tmp_path: Path) -> None:
    """Без хранилища манифеста — 503."""
    response = _client(tmp_path, with_store=False).put(
        "/api/v1/locations/spalnia", json={"sensors": {}}
    )

    assert response.status_code == 503
