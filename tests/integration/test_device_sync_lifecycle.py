"""Интеграционные тесты синхронизации источника и списка устройств (spec 006, US3).

Проверяем сквозной путь: синхронизация → список → машины состояний.
До spec 006 каждая синхронизация создавала новые записи устройств с новыми
идентификаторами (дубли), исчезнувшие устройства навсегда оставались в
списке как обычные, а сбой подключения мог привести к потере данных.

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0
"""

from __future__ import annotations

import os
import shutil
import tempfile
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient


HEADERS = {"X-User-ID": "admin_user", "X-Is-Admin": "true"}


def _state(
    entity_id: str, name: str, state: str = "on", area_id: str | None = None
) -> dict[str, Any]:
    """Строит состояние сущности Home Assistant.

    Args:
        entity_id: Идентификатор сущности.
        name: Человекочитаемое имя.
        state: Состояние сущности.
        area_id: Идентификатор области.

    Returns:
        Состояние сущности в формате HA.
    """
    attributes: dict[str, Any] = {"friendly_name": name}
    if area_id:
        attributes["area_id"] = area_id
    return {"entity_id": entity_id, "state": state, "attributes": attributes}


class _HAStub:
    """Подмена HARestClient: отдаёт заданные состояния."""

    def __init__(self, states: list[dict[str, Any]] | None, connected: bool = True) -> None:
        """Инициализирует подмену.

        Args:
            states: Состояния источника; None — подключение не удалось.
            connected: Удалось ли подключиться.
        """
        self.states = states
        self.connected = connected


@pytest.fixture
def client() -> Iterator[TestClient]:
    """Приложение на временной копии манифеста.

    Yields:
        HTTP-клиент теста.
    """
    project_root = Path(__file__).resolve().parent.parent.parent
    work_dir = tempfile.mkdtemp(prefix="sync_lifecycle_")
    previous_cwd = os.getcwd()
    try:
        manifest = Path(work_dir) / "manifest.yaml"
        shutil.copy(project_root / "instances" / "leonids_house" / "manifest.yaml", manifest)
        os.chdir(work_dir)

        from src.webui.app import create_app

        app = create_app(str(manifest))
        yield TestClient(app, headers=HEADERS)
    finally:
        os.chdir(previous_cwd)
        shutil.rmtree(work_dir, ignore_errors=True)


@pytest.fixture
def source_id(client: TestClient) -> str:
    """Создаёт источник Home Assistant.

    Args:
        client: HTTP-клиент теста.

    Returns:
        Идентификатор источника.
    """
    response = client.post(
        "/api/v1/devices/sources",
        json={
            "name": "Sync HA",
            "url": "http://192.168.1.99:8123",
            "token": "sync_token_12345",
        },
    )
    assert response.status_code == 201
    return str(response.json()["id"])


def _sync(client: TestClient, source_id: str, stub: _HAStub) -> Any:
    """Выполняет синхронизацию источника с подменой Home Assistant.

    Args:
        client: HTTP-клиент теста.
        source_id: Идентификатор источника.
        stub: Подмена состояний источника.

    Returns:
        Ответ сервера.
    """
    with (
        patch(
            "src.adapters.home_assistant.rest_client.HARestClient.connect_to_ha",
            new=_async_value(stub.connected),
        ),
        patch(
            "src.adapters.home_assistant.rest_client.HARestClient.fetch_devices",
            new=_async_value(stub.states or []),
        ),
        patch(
            "src.adapters.home_assistant.rest_client.HARestClient.fetch_areas",
            new=_async_value([{"area_id": "kitchen", "name": "Kitchen"}]),
        ),
    ):
        return client.post(f"/api/v1/devices/sources/{source_id}/sync")


def _async_value(value: Any) -> Any:
    """Создаёт асинхронную функцию, всегда возвращающую значение.

    Args:
        value: Значение результата.

    Returns:
        Асинхронная функция без аргументов.
    """

    async def _call(*args: Any, **kwargs: Any) -> Any:
        return value

    return _call


def _entities(client: TestClient) -> dict[str, str]:
    """Возвращает идентификаторы устройств и их статусы из списка.

    Args:
        client: HTTP-клиент теста.

    Returns:
        Соответствие entity_id → статус.
    """
    return {
        device["ha_entity_id"]: device.get("status", "")
        for device in client.get("/api/v1/devices").json()
    }


class TestSyncAppearsInList:
    """Синхронизация и список дают одну картину."""

    def test_synced_devices_should_appear_in_list(self, client: TestClient, source_id: str) -> None:
        """Устройства источника видны в списке сразу после синхронизации."""
        response = _sync(
            client,
            source_id,
            _HAStub([_state("light.sync_a", "Sync A"), _state("switch.sync_b", "Sync B", "off")]),
        )

        assert response.status_code == 200
        assert set(_entities(client)) == {"light.sync_a", "switch.sync_b"}

    def test_repeated_sync_should_not_create_duplicates(
        self, client: TestClient, source_id: str
    ) -> None:
        """Три синхронизации подряд не плодят дубли (FR-015, quickstart 5)."""
        stub = _HAStub([_state("light.sync_a", "Sync A"), _state("switch.sync_b", "Sync B", "off")])

        for _ in range(3):
            assert _sync(client, source_id, stub).status_code == 200

        devices = client.get("/api/v1/devices").json()
        assert len(devices) == 2
        assert len({device["id"] for device in devices}) == 2

    def test_sync_should_refresh_state_of_existing_device(
        self, client: TestClient, source_id: str
    ) -> None:
        """Повторная синхронизация обновляет состояние, а не создаёт новую запись."""
        _sync(client, source_id, _HAStub([_state("light.sync_a", "Sync A", "on")]))
        device_id = client.get("/api/v1/devices").json()[0]["id"]

        _sync(client, source_id, _HAStub([_state("light.sync_a", "Sync A", "off")]))

        devices = client.get("/api/v1/devices").json()
        assert [device["id"] for device in devices] == [device_id]
        assert devices[0]["state"] == {"state": "off"}


class TestRemovedDevices:
    """Исчезнувшие устройства помечаются, а не удаляются молча."""

    def test_missing_device_should_be_marked_removed(
        self, client: TestClient, source_id: str
    ) -> None:
        """Исчезнувший в HA прибор получает статус removed_from_ha (FR-016)."""
        _sync(
            client,
            source_id,
            _HAStub([_state("light.sync_a", "Sync A"), _state("light.sync_gone", "Sync Gone")]),
        )

        _sync(client, source_id, _HAStub([_state("light.sync_a", "Sync A")]))

        statuses = _entities(client)
        assert statuses["light.sync_gone"] == "removed_from_ha"
        assert statuses["light.sync_a"] == "available"

    def test_removed_device_should_lose_its_fsm(self, client: TestClient, source_id: str) -> None:
        """Активная автоматика исчезнувшего устройства снимается."""
        _sync(client, source_id, _HAStub([_state("light.sync_a", "Sync A")]))
        client.post(
            "/api/v1/devices/apply",
            json={
                "source_id": source_id,
                "selections": [
                    {
                        "device_entity_id": "light.sync_a",
                        "device_type": "light",
                        "name": "Sync A",
                        "target_room": "living_room",
                        "behaviors": [
                            {
                                "template": "lighting",
                                "priority": 10,
                                "params": {"motion_sensor": "binary_sensor.living_room_motion"},
                            }
                        ],
                    }
                ],
            },
        )
        engine = client.app.state.container.fsm
        assert engine.get_entities_by_device("light.sync_a"), "Автоматика должна была создаться"

        _sync(client, source_id, _HAStub([]))

        assert engine.get_entities_by_device("light.sync_a") == []

    def test_reappearing_device_should_restore_status(
        self, client: TestClient, source_id: str
    ) -> None:
        """Вернувшееся устройство снова становится доступным."""
        stub = _HAStub([_state("light.sync_a", "Sync A"), _state("light.sync_gone", "Gone")])
        _sync(client, source_id, stub)
        _sync(client, source_id, _HAStub([_state("light.sync_a", "Sync A")]))
        assert _entities(client)["light.sync_gone"] == "removed_from_ha"

        _sync(client, source_id, stub)

        assert _entities(client)["light.sync_gone"] == "available"

    def test_list_should_keep_removed_devices_with_status(self, client: TestClient) -> None:
        """Список не выбрасывает removed_from_ha, а показывает статус."""
        devices = client.get("/api/v1/devices").json()
        for device in devices:
            assert device["status"] in {"available", "unavailable", "removed_from_ha"}


class TestSyncFailureKeepsData:
    """Сбой подключения не уничтожает ранее загруженные устройства."""

    def test_connection_error_should_keep_devices(self, client: TestClient, source_id: str) -> None:
        """Неудачное подключение возвращает 500, но устройства остаются в списке."""
        _sync(client, source_id, _HAStub([_state("light.sync_a", "Sync A")]))

        response = _sync(client, source_id, _HAStub(None, connected=False))

        assert response.status_code == 500
        assert _entities(client) == {"light.sync_a": "available"}

    def test_connection_error_should_record_source_error(
        self, client: TestClient, source_id: str
    ) -> None:
        """Причина сбоя сохраняется в источнике (FR-017)."""
        _sync(client, source_id, _HAStub([_state("light.sync_a", "Sync A")]))
        _sync(client, source_id, _HAStub(None, connected=False))

        source = client.get(f"/api/v1/devices/sources/{source_id}").json()

        assert source["last_error"], "Причина сбоя должна быть видна в источнике"

    def test_successful_sync_should_clear_source_error(
        self, client: TestClient, source_id: str
    ) -> None:
        """Успешная синхронизация очищает прошлую ошибку и обновляет время."""
        _sync(client, source_id, _HAStub(None, connected=False))

        _sync(client, source_id, _HAStub([_state("light.sync_a", "Sync A")]))

        source = client.get(f"/api/v1/devices/sources/{source_id}").json()
        assert source["last_error"] is None
        assert source["last_sync"], "Время последней синхронизации должно быть заполнено"
