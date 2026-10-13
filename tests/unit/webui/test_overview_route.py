"""Агрегат первого экрана «Дом»: GET /api/v1/overview (спека 017, US1).

Проверяется то, ради чего эндпоинт заведён: одним запросом видно состояние дома —
локации со снимками, устройства и тревоги о молчащих/недоступных датчиках. Пустой
дом — это 200 с пустыми списками, недоступная платформа — 503: эти состояния
нельзя смешивать.

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.models.location import LocationRef, LocationSnapshot, Reading
from webui.routes.overview import router


ADMIN_HEADERS = {"X-User-ID": "admin_user", "X-Is-Admin": "true"}


class _FakeEngine:
    """Движок без автоматов: проверяется сборка ответа, а не FSM."""

    def get_all_states(self) -> dict[str, Any]:
        """Состояния автоматов (пусто)."""
        return {}

    def explain(self, entity_id: str) -> Any:
        """Решение автоматики по сущности.

        Args:
            entity_id: Сущность устройства.

        Returns:
            Решение либо ``None``.
        """
        if entity_id == "light.girlianda":
            return SimpleNamespace(
                at=1_700_000_000.0,
                outcome="on",
                reason_code="action_on",
                reason_text="включено по расписанию",
                trigger="schedule_start",
            )
        return None


class _FakeLocationState:
    """Наблюдение за локациями с одной доступной и одной молчащей ролью."""

    def locations(self) -> list[dict[str, Any]]:
        """Список локаций."""
        return [{"id": "spalnia", "name": "Спальня", "kind": "room"}]

    def snapshot(self, location_id: str) -> LocationSnapshot:
        """Снимок локации.

        Args:
            location_id: Идентификатор локации.

        Returns:
            Снимок с температурой и молчащим контактом.
        """
        stale_at = (datetime.now(UTC) - timedelta(hours=3)).isoformat()
        return LocationSnapshot(
            location=LocationRef(id=location_id, name="Спальня", kind="room"),
            at=datetime.now(UTC).isoformat(),
            available=True,
            readings={
                "temperature": [
                    Reading(
                        value="22.4",
                        unit="°C",
                        at=datetime.now(UTC).isoformat(),
                        entity_id="sensor.t_spalnia",
                    )
                ],
                "contact": [
                    Reading(
                        value="off",
                        unit=None,
                        at=stale_at,
                        stale=True,
                        entity_id="binary_sensor.window",
                    )
                ],
            },
            derived={"occupied": False, "sensor_count": 2},
        )


class _FakeDeviceService:
    """Сервис устройств с одним доступным и одним недоступным прибором."""

    async def get_all_devices(self) -> list[Any]:
        """Список устройств."""
        return [
            SimpleNamespace(
                id=uuid4(),
                name="Гирлянда",
                ha_entity_id="light.girlianda",
                device_type="light",
                status="available",
                state={"state": "on"},
                ha_area_id="garden",
            ),
            SimpleNamespace(
                id=uuid4(),
                name="Рекуператор",
                ha_entity_id="fan.rekuperator",
                device_type="fan",
                status="unavailable",
                state={"state": "off"},
                ha_area_id="spalnia",
            ),
        ]


def _client(container: Any) -> TestClient:
    """Клиент с маршрутом агрегата.

    Args:
        container: Контейнер платформы.

    Returns:
        Тестовый клиент.
    """
    app = FastAPI()
    app.include_router(router)
    app.state.container = container
    app.state.device_service = _FakeDeviceService()
    app.state.default_user_id = "admin_user"
    app.state.default_user_is_admin = True
    return TestClient(app)


def test_overview_should_return_state_and_alerts() -> None:
    """Ответ несёт локации, устройства и тревоги."""
    container = SimpleNamespace(fsm=_FakeEngine(), location_state=_FakeLocationState())

    response = _client(container).get("/api/v1/overview", headers=ADMIN_HEADERS)

    assert response.status_code == 200
    body = response.json()
    assert [loc["location"]["id"] for loc in body["locations"]] == ["spalnia"]
    assert {device["ha_entity_id"] for device in body["devices"]} == {
        "light.girlianda",
        "fan.rekuperator",
    }
    kinds = {alert["kind"] for alert in body["alerts"]}
    assert "stale_sensor" in kinds
    assert "unavailable_device" in kinds
    assert body["devices"][0]["fsm"] == []

    girlianda = next(d for d in body["devices"] if d["ha_entity_id"] == "light.girlianda")
    assert girlianda["decision"]["reason_text"] == "включено по расписанию"


def test_overview_should_limit_devices_to_manifest() -> None:
    """«Дом» показывает приборы манифеста, а не все импортированные сущности HA."""
    container = SimpleNamespace(
        fsm=_FakeEngine(),
        location_state=_FakeLocationState(),
        manifest=SimpleNamespace(
            rooms=[
                SimpleNamespace(
                    id="garden",
                    name="Сад",
                    devices=[SimpleNamespace(id="light.girlianda")],
                )
            ]
        ),
    )

    body = _client(container).get("/api/v1/overview", headers=ADMIN_HEADERS).json()

    assert {device["ha_entity_id"] for device in body["devices"]} == {"light.girlianda"}
    # Комната приходит из манифеста: по ней грид «Автоматика» группируется.
    assert body["devices"][0]["room_name"] == "Сад"
    assert body["devices"][0]["room_id"] == "garden"


def test_overview_should_report_503_without_engine() -> None:
    """Несобранный движок — 503, а не пустой дом."""
    container = SimpleNamespace(fsm=None, location_state=_FakeLocationState())

    response = _client(container).get("/api/v1/overview", headers=ADMIN_HEADERS)

    assert response.status_code == 503


def test_overview_should_require_identity() -> None:
    """Без идентичности чтение устройств запрещено (дефолт — отказ)."""
    container = SimpleNamespace(fsm=_FakeEngine(), location_state=_FakeLocationState())
    app = FastAPI()
    app.include_router(router)
    app.state.container = container
    app.state.device_service = _FakeDeviceService()
    app.state.default_user_id = ""
    app.state.default_user_is_admin = False

    response = TestClient(app).get("/api/v1/overview")

    assert response.status_code == 401


@pytest.mark.parametrize("field", ["locations", "devices", "alerts", "generated_at"])
def test_overview_should_include_contract_fields(field: str) -> None:
    """Контракт ответа содержит обязательные поля.

    Args:
        field: Проверяемое поле.
    """
    container = SimpleNamespace(fsm=_FakeEngine(), location_state=_FakeLocationState())

    body = _client(container).get("/api/v1/overview", headers=ADMIN_HEADERS).json()

    assert field in body
