"""Зеркало локаций в Home Assistant через MQTT-автообнаружение (спека 016, FR-008, FR-009).

Платформа не умеет создавать сущности в Home Assistant, поэтому публикует в MQTT
конфигурацию обнаружения и значения, а сущности создаёт HA сам. Проверяется то,
ради чего зеркало и сделано: объявление уходит один раз, значения и полный снимок
публикуются с `retain`, а отказ публикации не ломает наблюдение.

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from core.models.manifest import (
    AutomationRules,
    InstanceConfig,
    LocationConfig,
    Manifest,
    RoomConfig,
)
from core.services.location_mirror import LocationMirror
from core.services.location_state import LocationStateService


def _service() -> LocationStateService:
    """Наблюдение с одной комнатой и улицей.

    Returns:
        Сервис наблюдения.
    """
    manifest = Manifest(
        instance=InstanceConfig(
            id="probe", name="Probe", owner="probe", created_at="2026-01-01T00:00:00Z"
        ),
        rooms=[
            RoomConfig(
                id="spalnia",
                name="Спальня",
                sensors={
                    "temperature": "sensor.t",
                    "motion": "binary_sensor.m",
                    "contact": "binary_sensor.okno",
                },
            )
        ],
        locations=[
            LocationConfig(
                id="ulitsa",
                name="Улица",
                kind="outdoor",
                sensors={"rain": "binary_sensor.dozhd"},
            )
        ],
        automation_rules=AutomationRules(),
    )
    service = LocationStateService(
        manifest, unit_provider=lambda entity: "°C" if entity == "sensor.t" else None
    )
    moment = datetime.now(UTC) - timedelta(seconds=5)
    service.record("sensor.t", "22.4", at=moment)
    service.record("binary_sensor.m", "on", at=moment)
    service.record("binary_sensor.okno", "off", at=moment)
    service.record("binary_sensor.dozhd", "on", at=moment)
    return service


class _Publisher:
    """Подменный публикатор: помнит топики и умеет отказывать."""

    def __init__(self, ok: bool = True) -> None:
        self.ok = ok
        self.sent: list[tuple[str, str, bool]] = []

    async def __call__(self, topic: str, payload: str, retain: bool) -> bool:
        """Запомнить публикацию.

        Args:
            topic: Топик.
            payload: Полезная нагрузка.
            retain: Хранить ли сообщение.

        Returns:
            Успех публикации.
        """
        self.sent.append((topic, payload, retain))
        return self.ok

    def topics(self) -> list[str]:
        """Топики публикаций.

        Returns:
            Список топиков.
        """
        return [topic for topic, _, _ in self.sent]

    def payload(self, topic: str) -> str:
        """Полезная нагрузка последней публикации в топик.

        Args:
            topic: Топик.

        Returns:
            Полезная нагрузка.
        """
        return next(payload for name, payload, _ in reversed(self.sent) if name == topic)


def _mirror(publisher: Any, *, enabled: bool = True) -> LocationMirror:
    """Зеркало с подменным публикатором.

    Args:
        publisher: Публикатор.
        enabled: Включено ли зеркало.

    Returns:
        Зеркало локаций.
    """
    return LocationMirror(state=_service(), publish=publisher, enabled=enabled)


class TestDiscovery:
    """Объявление сущностей в Home Assistant."""

    @pytest.mark.asyncio
    async def test_locality_and_readings_are_announced(self) -> None:
        """Объявляется сводная сущность локации и каждый показатель."""
        publisher = _Publisher()

        await _mirror(publisher).publish("spalnia")

        topics = publisher.topics()
        assert "homeassistant/sensor/behavioral_spalnia/config" in topics
        assert "homeassistant/sensor/behavioral_spalnia_temperature/config" in topics
        assert "homeassistant/binary_sensor/behavioral_spalnia_motion/config" in topics

    @pytest.mark.asyncio
    async def test_binary_role_is_binary_sensor(self) -> None:
        """Движение, контакт и дождь создаются бинарными датчиками."""
        publisher = _Publisher()

        await _mirror(publisher).publish("ulitsa")

        assert "homeassistant/binary_sensor/behavioral_ulitsa_rain/config" in publisher.topics()
        config = json.loads(
            publisher.payload("homeassistant/binary_sensor/behavioral_ulitsa_rain/config")
        )
        assert config["payload_on"] == "on"

    @pytest.mark.asyncio
    async def test_number_role_carries_unit(self) -> None:
        """Числовой показатель уезжает с единицей измерения."""
        publisher = _Publisher()

        await _mirror(publisher).publish("spalnia")

        config = json.loads(
            publisher.payload("homeassistant/sensor/behavioral_spalnia_temperature/config")
        )
        assert config["unit_of_measurement"] == "°C"

    @pytest.mark.asyncio
    async def test_discovery_is_sent_once(self) -> None:
        """Повторная публикация не повторяет объявление."""
        publisher = _Publisher()
        mirror = _mirror(publisher)

        await mirror.publish("spalnia")
        publisher.sent.clear()
        await mirror.publish("spalnia")

        assert not [t for t in publisher.topics() if t.endswith("/config")], (
            "объявление повторяется на каждой публикации: это лишний вызов сервиса "
            "и лишние записи в брокере"
        )


class TestValues:
    """Значения и полный снимок в топиках."""

    @pytest.mark.asyncio
    async def test_values_and_snapshot_are_published_with_retain(self) -> None:
        """Значение показателя и полный снимок публикуются с retain."""
        publisher = _Publisher()

        await _mirror(publisher).publish("spalnia")

        assert publisher.payload("behavioral/location/spalnia/temperature/state") == "22.4"
        snapshots = [
            payload
            for topic, payload, _ in publisher.sent
            if topic == "behavioral/location/spalnia/attributes"
        ]
        snapshot = json.loads(snapshots[-1])
        assert snapshot["location"]["name"] == "Спальня"
        assert snapshot["derived"]["occupied"] is True
        assert all(retain for _, _, retain in publisher.sent), "без retain HA не восстановит снимок"

    @pytest.mark.asyncio
    async def test_reading_attributes_carry_time_and_signs(self) -> None:
        """Атрибуты показателя несут время, молчание и доступность."""
        publisher = _Publisher()

        await _mirror(publisher).publish("spalnia")

        attributes = json.loads(
            publisher.payload("behavioral/location/spalnia/temperature/attributes")
        )
        assert attributes["unit"] == "°C"
        assert attributes["stale"] is False
        assert attributes["available"] is True
        assert attributes["entity_id"] == "sensor.t"

    @pytest.mark.asyncio
    async def test_whole_number_has_no_decimal_tail(self) -> None:
        """Целое число публикуется без хвоста «.0»."""
        service = _service()
        service.record("sensor.t", 22, at=datetime.now(UTC))
        publisher = _Publisher()
        mirror = LocationMirror(state=service, publish=publisher)

        await mirror.publish("spalnia")

        assert publisher.payload("behavioral/location/spalnia/temperature/state") == "22"

    @pytest.mark.asyncio
    async def test_publish_all_covers_every_location(self) -> None:
        """После старта публикуются все локации."""
        publisher = _Publisher()
        mirror = _mirror(publisher)

        published = await mirror.publish_all()

        assert published == 2
        assert "behavioral/location/ulitsa/attributes" in publisher.topics()


class TestFailureAndSwitch:
    """Отказ публикации не ломает наблюдение (FR-009)."""

    @pytest.mark.asyncio
    async def test_refused_publish_is_counted_not_raised(self) -> None:
        """Отказ Home Assistant виден в описании, но не бросается наружу."""
        publisher = _Publisher(ok=False)
        mirror = _mirror(publisher)

        result = await mirror.publish("spalnia")

        assert result is False
        described = mirror.describe()
        assert described["failed"] > 0
        assert described["published"] == 0

    @pytest.mark.asyncio
    async def test_exception_does_not_escape(self) -> None:
        """Исключение публикатора не выходит наружу."""

        async def broken(_: str, __: str, ___: bool) -> bool:
            raise RuntimeError("MQTT недоступен")

        mirror = _mirror(broken)

        assert await mirror.publish("spalnia") is False
        assert mirror.describe()["failed"] > 0

    @pytest.mark.asyncio
    async def test_disabled_mirror_publishes_nothing(self) -> None:
        """Выключенное зеркало молчит."""
        publisher = _Publisher()
        mirror = _mirror(publisher, enabled=False)

        assert await mirror.publish("spalnia") is False
        assert await mirror.publish_all() == 0
        assert publisher.sent == []

    @pytest.mark.asyncio
    async def test_event_publishes_only_affected_location(self) -> None:
        """Изменение датчика публикует только его локацию."""
        publisher = _Publisher()
        mirror = _mirror(publisher)

        await mirror.on_state_change(
            "state_change", {"entity_id": "binary_sensor.dozhd", "new_state": "off"}
        )

        topics = publisher.topics()
        assert "behavioral/location/ulitsa/attributes" in topics
        assert "behavioral/location/spalnia/attributes" not in topics

    @pytest.mark.asyncio
    async def test_unbound_entity_publishes_nothing(self) -> None:
        """Чужая сущность ничего не публикует."""
        publisher = _Publisher()
        mirror = _mirror(publisher)

        await mirror.on_state_change(
            "state_change", {"entity_id": "sensor.chuzhoi", "new_state": "1"}
        )

        assert publisher.sent == []
