"""Локации в манифесте и роли датчиков наблюдения (спека 016, FR-004, FR-005, FR-010).

Локация — комната манифеста либо особая зона (улица, грядки), заданная вручную.
Привязка датчиков явная (FR-010): угадывание роли по имени сущности не
применяется — имя в Home Assistant меняет владелец, и роль по нему поехала бы.

Роль обязана быть известна маршрутизатору: неизвестная роль не попадает в
маршруты, а её датчик — в подписку HA, поэтому датчик молчал бы, хотя описан в
манифесте (research.md D5).

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from core.events.event_router import EventRouter, collect_subscribed_entities
from core.models.manifest import (
    AutomationRules,
    InstanceConfig,
    LocationConfig,
    Manifest,
)


def _instance() -> InstanceConfig:
    """Описание дома для манифеста.

    Returns:
        Модель дома.
    """
    return InstanceConfig(
        id="probe", name="Probe", owner="probe", created_at="2026-01-01T00:00:00Z"
    )


class TestManifestLocations:
    """Секция ``locations:`` читается и не ломает дома без неё."""

    def test_locations_default_to_empty(self) -> None:
        """Манифест без локаций собирается: секция необязательна."""
        manifest = Manifest(instance=_instance())

        assert manifest.locations == []

    def test_location_carries_name_kind_and_sensors(self) -> None:
        """Локация хранит имя, вид и привязку датчиков."""
        manifest = Manifest(
            instance=_instance(),
            locations=[
                LocationConfig(
                    id="ulitsa",
                    name="Улица",
                    kind="outdoor",
                    sensors={
                        "temperature": "sensor.temperatura_na_ulitse_srednee",
                        "rain": "binary_sensor.datchik_dozhdia_water_leak",
                    },
                )
            ],
        )

        [location] = manifest.locations
        assert location.id == "ulitsa"
        assert location.kind == "outdoor"
        assert location.sensors["rain"] == "binary_sensor.datchik_dozhdia_water_leak"

    def test_empty_sensor_entity_is_rejected(self) -> None:
        """Пустая сущность у роли — ошибка манифеста, а не тихий пропуск."""
        with pytest.raises(ValidationError):
            LocationConfig(id="ulitsa", name="Улица", sensors={"temperature": "  "})

    def test_location_may_override_stale_threshold(self) -> None:
        """У локации бывает свой порог молчания (батарейные датчики)."""
        location = LocationConfig(id="gryadki", name="Грядки", stale_after_sec=86400)

        assert location.stale_after_sec == 86400

    def test_stale_threshold_defaults_to_home_rule(self) -> None:
        """Порог молчания по умолчанию — параметр дома."""
        rules = AutomationRules()

        assert rules.locations.stale_after_sec == 3600
        assert rules.locations.presence_window_sec == 600
        assert LocationConfig(id="x", name="X").stale_after_sec is None


class TestSensorRoles:
    """Роли наблюдения известны маршрутизатору (FR-005, D5)."""

    @pytest.mark.parametrize(
        "role",
        [
            "illuminance",
            "pressure",
            "wind_speed",
            "wind_gust",
            "rain",
            "uv_index",
            "co2",
            "soil_moisture",
            "soil_temperature",
            "soil_ph",
            "soil_ec",
        ],
    )
    def test_role_is_known_to_router(self, role: str) -> None:
        """Каждая роль наблюдения описана в карте событий.

        Args:
            role: Роль датчика.

        Returns:
            Ничего.
        """
        assert role in EventRouter.SENSOR_EVENT_MAP, (
            f"роль {role} неизвестна маршрутизатору: её датчик не попадёт в "
            "подписку HA и не пришлёт ни одного события"
        )

    def test_illuminance_keeps_light_working(self) -> None:
        """Синоним ``illuminance`` шлёт то же событие, что ``lux``."""
        assert "brightness_changed" in EventRouter.SENSOR_EVENT_MAP["illuminance"], (
            "светильник комнаты с привязкой illuminance молчал бы: шаблоны света "
            "слушают brightness_changed"
        )
        assert "brightness_changed" in EventRouter.SENSOR_EVENT_MAP["lux"]


class TestSubscription:
    """Подписка HA включает датчики особых зон (иначе снимок пуст)."""

    def test_location_sensors_are_subscribed(self) -> None:
        """Датчики локаций попадают в список подписки."""
        manifest = Manifest(
            instance=_instance(),
            locations=[
                LocationConfig(
                    id="ulitsa",
                    name="Улица",
                    sensors={"temperature": "sensor.ulitsa_t"},
                ),
                LocationConfig(
                    id="gryadki",
                    name="Грядки",
                    sensors={"soil_moisture": "sensor.pochva_vlazhnost"},
                ),
            ],
        )

        subscribed = collect_subscribed_entities(manifest)

        assert "sensor.ulitsa_t" in subscribed
        assert "sensor.pochva_vlazhnost" in subscribed

    def test_duplicates_are_removed(self) -> None:
        """Повтор той же сущности не дублируется в подписке."""
        manifest = Manifest(
            instance=_instance(),
            locations=[
                LocationConfig(id="a", name="A", sensors={"temperature": "sensor.t"}),
                LocationConfig(id="b", name="B", sensors={"temperature": "sensor.t"}),
            ],
        )

        assert collect_subscribed_entities(manifest).count("sensor.t") == 1
