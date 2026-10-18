"""Правка мест и перенос приборов через API (B93).

Интерфейс мест должен уметь то, ради чего он заведён: переименовать место,
сменить вид и родителя, завести новое, удалить пустое и перенести прибор в другое
место. Проверки держат и границы: правка идёт через модель, поэтому неверный
родитель не уезжает в файл, а удаление непустого места запрещено — иначе часть
дома молча выпала бы из автоматики.

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
    kind: room
    sensors:
      temperature: sensor.t_spalnia
    devices:
      - id: light.spalnia
        type: light
        name: Свет спальни
        behaviors: []
locations:
  - id: ulitsa
    name: Улица
    kind: outdoor
    sensors:
      temperature: sensor.t_ulitsa
  - id: sad
    name: Сад
    kind: garden
    parent: ulitsa
"""


class _LocationState:
    """Наблюдение за локациями: только то, что нужно маршруту чтения."""

    def locations(self) -> list[dict[str, Any]]:
        """Краткое описание локаций."""
        return [
            {"id": "spalnia", "name": "Спальня", "kind": "room", "sensor_count": 1},
            {"id": "ulitsa", "name": "Улица", "kind": "outdoor", "sensor_count": 1},
            {"id": "sad", "name": "Сад", "kind": "garden", "sensor_count": 0},
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
    """Клиент с маршрутами мест и хранилищем манифеста.

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


def _manifest(client: TestClient) -> dict[str, Any]:
    """Текущий манифест как словарь.

    Args:
        client: Тестовый клиент.

    Returns:
        Манифест.
    """
    return client.get("/api/v1/manifest").json()["manifest"]


def _place(client: TestClient, place_id: str) -> dict[str, Any]:
    """Место манифеста по идентификатору.

    Args:
        client: Тестовый клиент.
        place_id: Идентификатор места.

    Returns:
        Словарь места.
    """
    manifest = _manifest(client)
    return next(
        place for place in [*manifest["rooms"], *manifest["locations"]] if place["id"] == place_id
    )


class TestListCarriesTree:
    """Список мест несёт дерево и состав."""

    def test_parent_and_devices_are_returned(self, tmp_path: Path) -> None:
        """Видны родитель места и его приборы."""
        body = _client(tmp_path).get("/api/v1/locations").json()

        by_id = {item["id"]: item for item in body["locations"]}
        assert by_id["sad"]["parent"] == "ulitsa"
        assert by_id["ulitsa"]["parent"] is None
        assert [device["id"] for device in by_id["spalnia"]["devices"]] == ["light.spalnia"]
        assert by_id["spalnia"]["devices"][0]["behaviors"] == 0


class TestUpdatePlace:
    """Правка имени, вида и родителя."""

    def test_rename_and_kind(self, tmp_path: Path) -> None:
        """Имя и вид меняются, датчики не трогаются."""
        client = _client(tmp_path)

        response = client.put(
            "/api/v1/locations/sad", json={"name": "Большой сад", "kind": "garden"}
        )

        assert response.status_code == 200
        place = _place(client, "sad")
        assert place["name"] == "Большой сад"
        assert place["parent"] == "ulitsa"

    def test_parent_can_be_cleared(self, tmp_path: Path) -> None:
        """`parent: null` делает место верхнего уровня."""
        client = _client(tmp_path)

        response = client.put("/api/v1/locations/sad", json={"parent": None})

        assert response.status_code == 200
        assert _place(client, "sad")["parent"] is None

    def test_absent_fields_are_untouched(self, tmp_path: Path) -> None:
        """Поле, которого нет в теле, не трогается."""
        client = _client(tmp_path)

        client.put("/api/v1/locations/spalnia", json={"name": "Спальня №1"})

        place = _place(client, "spalnia")
        assert place["name"] == "Спальня №1"
        assert place["sensors"] == {"temperature": "sensor.t_spalnia"}

    def test_unknown_parent_is_rejected(self, tmp_path: Path) -> None:
        """Родителя нет — правка не уезжает в файл."""
        client = _client(tmp_path)

        response = client.put("/api/v1/locations/sad", json={"parent": "nope"})

        assert response.status_code == 400
        assert _place(client, "sad")["parent"] == "ulitsa"

    def test_location_inside_room_is_rejected(self, tmp_path: Path) -> None:
        """Локацию нельзя вложить в комнату."""
        client = _client(tmp_path)

        response = client.put("/api/v1/locations/sad", json={"parent": "spalnia"})

        assert response.status_code == 400
        assert _place(client, "sad")["parent"] == "ulitsa"

    def test_empty_name_is_rejected(self, tmp_path: Path) -> None:
        """Пустое имя — ошибка, а не пустая подпись на панели."""
        response = _client(tmp_path).put("/api/v1/locations/sad", json={"name": "   "})

        assert response.status_code == 400

    def test_unknown_place_is_404(self, tmp_path: Path) -> None:
        """Неизвестное место — 404."""
        assert (
            _client(tmp_path).put("/api/v1/locations/nope", json={"name": "X"}).status_code == 404
        )

    def test_without_store_is_503(self, tmp_path: Path) -> None:
        """Без хранилища манифеста — 503."""
        response = _client(tmp_path, with_store=False).put(
            "/api/v1/locations/sad", json={"name": "X"}
        )

        assert response.status_code == 503


class TestCreateAndDeletePlace:
    """Новое место и удаление пустого."""

    def test_location_is_created(self, tmp_path: Path) -> None:
        """Новая локация появляется в разделе локаций."""
        client = _client(tmp_path)

        response = client.post(
            "/api/v1/locations",
            json={"id": "gazon", "name": "Газон", "kind": "lawn", "parent": "ulitsa"},
        )

        assert response.status_code == 201
        assert _place(client, "gazon")["kind"] == "lawn"
        assert _place(client, "gazon")["parent"] == "ulitsa"

    def test_room_is_created_in_rooms(self, tmp_path: Path) -> None:
        """Вид `room` создаёт комнату, а не локацию."""
        client = _client(tmp_path)

        response = client.post(
            "/api/v1/locations", json={"id": "sauna", "name": "Сауна", "kind": "room"}
        )

        assert response.status_code == 201
        assert response.json()["section"] == "rooms"

    def test_duplicate_id_is_409(self, tmp_path: Path) -> None:
        """Место с таким идентификатором уже есть."""
        response = _client(tmp_path).post("/api/v1/locations", json={"id": "sad", "name": "Сад"})

        assert response.status_code == 409

    def test_bad_id_is_400(self, tmp_path: Path) -> None:
        """Кириллица и дефис в идентификаторе не годятся."""
        response = _client(tmp_path).post("/api/v1/locations", json={"id": "Сад-1", "name": "Сад"})

        assert response.status_code == 400

    def test_empty_place_is_deleted(self, tmp_path: Path) -> None:
        """Пустое место удаляется."""
        client = _client(tmp_path)
        client.post("/api/v1/locations", json={"id": "gazon", "name": "Газон", "kind": "lawn"})

        response = client.delete("/api/v1/locations/gazon")

        assert response.status_code == 200
        manifest = _manifest(client)
        assert all(place["id"] != "gazon" for place in manifest["locations"])

    def test_non_empty_place_is_not_deleted(self, tmp_path: Path) -> None:
        """Место с приборами или детьми не удаляется."""
        client = _client(tmp_path)

        response = client.delete("/api/v1/locations/ulitsa")

        assert response.status_code == 409
        body = response.json()
        assert body["children"] == ["Сад"]


class TestMoveDevice:
    """Перенос прибора между местами."""

    def test_device_moves_to_another_place(self, tmp_path: Path) -> None:
        """Прибор уходит из прежнего места и появляется в новом."""
        client = _client(tmp_path)

        response = client.post(
            "/api/v1/locations/ulitsa/devices", json={"device_id": "light.spalnia"}
        )

        assert response.status_code == 200
        assert response.json() == {
            "status": "saved",
            "moved": True,
            "device_id": "light.spalnia",
            "from": "spalnia",
            "to": "ulitsa",
            "warnings": [],
        }
        assert _place(client, "spalnia")["devices"] == []
        assert [device["id"] for device in _place(client, "ulitsa")["devices"]] == ["light.spalnia"]

    def test_move_to_same_place_is_unchanged(self, tmp_path: Path) -> None:
        """Перенос туда же ничего не меняет."""
        client = _client(tmp_path)

        response = client.post(
            "/api/v1/locations/spalnia/devices", json={"device_id": "light.spalnia"}
        )

        assert response.status_code == 200
        assert response.json()["moved"] is False

    def test_unknown_device_is_404(self, tmp_path: Path) -> None:
        """Прибора нет в манифесте — 404."""
        response = _client(tmp_path).post(
            "/api/v1/locations/ulitsa/devices", json={"device_id": "light.nope"}
        )

        assert response.status_code == 404

    def test_unknown_place_is_404(self, tmp_path: Path) -> None:
        """Места нет — 404."""
        response = _client(tmp_path).post(
            "/api/v1/locations/nope/devices", json={"device_id": "light.spalnia"}
        )

        assert response.status_code == 404
