"""Интеграционный тест применения устройств из мастера (spec 006, US2).

Сценарий пользователя: мастер находит устройства источника, пользователь
выбирает часть из них и нажимает «Применить». Проверяем сквозной путь:
источник → данные мастера → применение → список → машины состояний.

Раньше применение обрабатывалось функцией чтения списка и всегда
возвращало пустой массив, поэтому мастер не мог добавить устройства.
"""

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0

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


@pytest.fixture
def client() -> Iterator[TestClient]:
    """Приложение на временной копии манифеста и в изолированном каталоге данных.

    Yields:
        HTTP-клиент теста.
    """
    project_root = Path(__file__).resolve().parent.parent.parent
    work_dir = tempfile.mkdtemp(prefix="discovery_apply_")
    previous_cwd = os.getcwd()
    try:
        shutil.copy(
            os.path.join(project_root, "instances", "leonids_house", "manifest.yaml"),
            os.path.join(work_dir, "manifest.yaml"),
        )
        os.chdir(work_dir)

        from src.webui.app import create_app

        app = create_app(os.path.join(work_dir, "manifest.yaml"))
        yield TestClient(app, headers={"X-User-ID": "admin_user", "X-Is-Admin": "true"})
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
            "name": "Wizard HA",
            "url": "http://192.168.1.88:8123",
            "token": "wizard_token_123",
        },
    )
    assert response.status_code == 201
    return str(response.json()["id"])


def _ha_states() -> list[dict[str, Any]]:
    """Состояния Home Assistant для подмены источника.

    Returns:
        Список состояний сущностей.
    """
    return [
        {
            "entity_id": "light.wizard_hall",
            "state": "on",
            "attributes": {"friendly_name": "Hall Light", "area_id": "hall"},
        },
        {
            "entity_id": "switch.wizard_pump",
            "state": "off",
            "attributes": {"friendly_name": "Pump", "area_id": "garage"},
        },
    ]


class TestWizardApply:
    """Сквозной путь мастера: поиск → выбор → применение."""

    def test_wizard_should_show_real_devices_then_apply_selected(
        self, client: TestClient, source_id: str
    ) -> None:
        """Выбранные устройства применяются, невыбранные — нет (FR-012)."""
        with (
            patch(
                "src.adapters.home_assistant.rest_client.HARestClient.connect_to_ha",
                return_value=True,
            ),
            patch(
                "src.adapters.home_assistant.rest_client.HARestClient.fetch_devices",
                return_value=_ha_states(),
            ),
            patch(
                "src.adapters.home_assistant.rest_client.HARestClient.fetch_areas",
                return_value=[
                    {"area_id": "hall", "name": "Hall"},
                    {"area_id": "garage", "name": "Garage"},
                ],
            ),
        ):
            discovered = client.get(f"/api/v1/devices/sources/{source_id}/discovery-data")

        assert discovered.status_code == 200
        data = discovered.json()
        assert data["available_device_count"] == 2

        # Пользователь выбрал только одно устройство
        selected = next(
            device
            for device in data["available_devices"]
            if device["entity_id"] == "light.wizard_hall"
        )
        apply_response = client.post(
            "/api/v1/devices/apply",
            json={
                "source_id": source_id,
                "selections": [
                    {
                        "device_entity_id": selected["entity_id"],
                        "device_type": selected["device_type"],
                        "name": selected["friendly_name"],
                        "target_room": "living_room",
                        "behaviors": [{"template": "lighting", "priority": 10, "params": {}}],
                    }
                ],
            },
        )

        assert apply_response.status_code == 201
        result = apply_response.json()
        assert result["success"] is True
        assert result["devices_added"] == 1
        assert result["failed"] == 0

        devices = client.get("/api/v1/devices").json()
        entity_ids = {device["ha_entity_id"] for device in devices}
        assert "light.wizard_hall" in entity_ids
        assert "switch.wizard_pump" not in entity_ids, "Невыбранное устройство не применяется"

    def test_apply_should_activate_device_without_restart(
        self, client: TestClient, source_id: str
    ) -> None:
        """Применённое устройство сразу получает автоматику (FR-014, SC-002)."""
        client.post(
            "/api/v1/devices/apply",
            json={
                "source_id": source_id,
                "selections": [
                    {
                        "device_entity_id": "light.wizard_hall",
                        "device_type": "light",
                        "name": "Hall Light",
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

        device_service = client.app.state.device_service
        devices = _run(device_service.get_all_devices())
        assert [device.ha_entity_id for device in devices] == ["light.wizard_hall"]

        fsm_ids = client.app.state.container.fsm.get_all_states()
        assert "light.wizard_hall_lighting_10" in fsm_ids

        mapping = client.app.state.container.event_router.get_mapping_for_sensor(
            "binary_sensor.living_room_motion"
        )
        assert "light.wizard_hall_lighting_10" in {fsm_id for fsm_id, _event in mapping}

    def test_repeated_apply_should_not_duplicate_device(
        self, client: TestClient, source_id: str
    ) -> None:
        """Повторное применение того же набора не создаёт дублей (FR-008, SC-005)."""
        payload = {
            "source_id": source_id,
            "selections": [
                {
                    "device_entity_id": "light.wizard_hall",
                    "device_type": "light",
                    "name": "Hall Light",
                    "target_room": "living_room",
                    "behaviors": [{"template": "lighting", "priority": 10, "params": {}}],
                }
            ],
        }

        first = client.post("/api/v1/devices/apply", json=payload)
        second = client.post("/api/v1/devices/apply", json=payload)

        assert first.status_code == 201
        assert second.status_code == 201
        assert second.json()["devices_added"] == 0
        assert second.json()["devices_updated"] == 1

        devices = client.get("/api/v1/devices").json()
        assert len(devices) == 1

    def test_dry_run_should_not_change_anything(self, client: TestClient, source_id: str) -> None:
        """Тестовый запуск не меняет манифест и список (contracts)."""
        response = client.post(
            "/api/v1/devices/apply",
            json={
                "source_id": source_id,
                "selections": [
                    {
                        "device_entity_id": "light.wizard_hall",
                        "device_type": "light",
                        "name": "Hall Light",
                        "target_room": "living_room",
                    }
                ],
                "dry_run": True,
            },
        )

        assert response.status_code == 201
        assert response.json()["would_add"] == 1
        assert client.get("/api/v1/devices").json() == []

    def test_apply_should_report_failure_reason_for_unknown_room(
        self, client: TestClient, source_id: str
    ) -> None:
        """Несуществующая комната отклоняется с причиной (FR-007)."""
        response = client.post(
            "/api/v1/devices/apply",
            json={
                "source_id": source_id,
                "selections": [
                    {
                        "device_entity_id": "light.wizard_hall",
                        "device_type": "light",
                        "name": "Hall Light",
                        "target_room": "no_such_room",
                    }
                ],
            },
        )

        assert response.status_code == 201
        result = response.json()
        assert result["success"] is False
        assert result["failed"] == 1
        assert "омната" in result["failed_devices"][0]["reason"]

    def test_apply_should_remain_possible_without_house_assistant(
        self, client: TestClient, source_id: str
    ) -> None:
        """В автономном режиме применение работает без живого HA (конституция VI)."""
        response = client.post(
            "/api/v1/devices/apply",
            json={
                "source_id": source_id,
                "selections": [
                    {
                        "device_entity_id": "light.standalone",
                        "device_type": "light",
                        "name": "Standalone Light",
                        "target_room": "bedroom",
                        "behaviors": [{"template": "lighting", "priority": 10, "params": {}}],
                    }
                ],
            },
        )

        assert response.status_code == 201
        assert response.json()["success"] is True
        devices = client.get("/api/v1/devices").json()
        assert [device["ha_entity_id"] for device in devices] == ["light.standalone"]


def _run(coroutine: Any) -> Any:
    """Выполняет корутину из синхронного теста.

    Args:
        coroutine: Корутина для выполнения.

    Returns:
        Результат корутины.
    """
    import asyncio

    return asyncio.run(coroutine)
