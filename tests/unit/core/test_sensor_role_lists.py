"""Роль датчика может закрываться несколькими сущностями (спека 017).

Нужно там, где одну роль дают разные устройства: две камеры на террасе —
движение и детекции «человек/животное/машина». Снимок локации и раньше умел
«роль → список показаний»; схема манифеста теперь тоже.

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from core.events.event_router import collect_subscribed_entities
from core.models.manifest import (
    InstanceConfig,
    Manifest,
    RoomConfig,
    all_sensor_entities,
    iter_role_entities,
    role_entities,
)
from core.services.location_state import LocationStateService


def _manifest(sensors: dict) -> Manifest:
    """Дом из одной комнаты с заданными привязками.

    Args:
        sensors: Привязки «роль → сущность или список».

    Returns:
        Модель манифеста.
    """
    return Manifest(
        instance=InstanceConfig(id="p", name="P", owner="p", created_at=""),
        rooms=[RoomConfig(id="terassa", name="Терраса", sensors=sensors)],
    )


def test_helpers_should_flatten_role_lists() -> None:
    """Хелперы разворачивают роль в пары «роль — сущность»."""
    sensors = {"motion": ["binary_sensor.a", "binary_sensor.b"], "temperature": "sensor.t"}

    assert sorted(iter_role_entities(sensors)) == [
        ("motion", "binary_sensor.a"),
        ("motion", "binary_sensor.b"),
        ("temperature", "sensor.t"),
    ]
    assert role_entities(sensors, "motion") == ["binary_sensor.a", "binary_sensor.b"]
    assert all_sensor_entities(sensors) == ["binary_sensor.a", "binary_sensor.b", "sensor.t"]


def test_manifest_should_accept_list_and_single() -> None:
    """Манифест принимает и строку, и список для одной роли."""
    manifest = _manifest({"motion": ["binary_sensor.a", "binary_sensor.b"], "rain": "sensor.r"})

    assert role_entities(manifest.rooms[0].sensors, "motion") == [
        "binary_sensor.a",
        "binary_sensor.b",
    ]
    assert role_entities(manifest.rooms[0].sensors, "rain") == ["sensor.r"]


def test_subscription_should_include_all_entities_of_role() -> None:
    """В подписку HA попадают обе сущности роли."""
    manifest = _manifest({"motion": ["binary_sensor.a", "binary_sensor.b"]})

    assert collect_subscribed_entities(manifest) == ["binary_sensor.a", "binary_sensor.b"]


def test_snapshot_should_group_multiple_readings_under_role() -> None:
    """Снимок показывает несколько показаний одной роли."""
    manifest = _manifest({"person": ["binary_sensor.main_person", "binary_sensor.terassa_person"]})
    service = LocationStateService(manifest)
    moment = datetime.now(UTC)
    service.record("binary_sensor.main_person", "on", at=moment - timedelta(seconds=5))
    service.record("binary_sensor.terassa_person", "off", at=moment - timedelta(seconds=5))

    snapshot = service.snapshot("terassa")

    assert snapshot is not None
    persons = snapshot.readings["person"]
    assert [reading.entity_id for reading in persons] == [
        "binary_sensor.main_person",
        "binary_sensor.terassa_person",
    ]
