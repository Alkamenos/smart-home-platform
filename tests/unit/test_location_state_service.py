"""Наблюдение за локациями: сбор показаний и производные (спека 016, FR-001…FR-012).

Проверяется конвейер от события шины до снимка: событие ``state_change`` о
привязанном датчике обновляет показание, чужая сущность игнорируется, а снимок
показывает значения, молчание и производные. Отдельно — порог молчания локации:
у зон с батарейными датчиками он свой, иначе грядки считались бы молчащими
постоянно.

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0
"""

from __future__ import annotations

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
from core.services.location_state import LocationStateService


NOW = datetime(2026, 10, 13, 9, 0, 0, tzinfo=UTC)


def _manifest() -> Manifest:
    """Дом из одной комнаты и двух особых зон.

    Returns:
        Модель манифеста.
    """
    return Manifest(
        instance=InstanceConfig(
            id="probe", name="Probe", owner="probe", created_at="2026-01-01T00:00:00Z"
        ),
        rooms=[
            RoomConfig(
                id="spalnia",
                name="Спальня",
                sensors={
                    "temperature": "sensor.t_spalnia",
                    "motion": "binary_sensor.m_spalnia",
                    "contact": "binary_sensor.okno_spalnia",
                },
            )
        ],
        locations=[
            LocationConfig(
                id="ulitsa",
                name="Улица",
                kind="outdoor",
                sensors={"temperature": "sensor.t_ulitsa"},
                stale_after_sec=86400,
            ),
            LocationConfig(
                id="gryadki",
                name="Грядки",
                kind="garden",
                sensors={"soil_moisture": "sensor.pochva"},
                stale_after_sec=86400,
            ),
        ],
        automation_rules=AutomationRules(),
    )


def _service(units: dict[str, str] | None = None) -> LocationStateService:
    """Наблюдение за локациями с единицами из словаря.

    Args:
        units: Сущность → единица измерения.

    Returns:
        Сервис наблюдения.
    """
    mapping = units or {}
    return LocationStateService(_manifest(), unit_provider=lambda entity: mapping.get(entity))


class TestLocationInventory:
    """Локации собираются из комнат и особых зон (FR-004)."""

    def test_rooms_and_zones_are_locations(self) -> None:
        """Комнаты и особые зоны — в одном наборе."""
        service = _service()

        assert service.location_ids() == ["spalnia", "ulitsa", "gryadki"]

    def test_short_description_counts_sensors(self) -> None:
        """Краткое описание даёт имя, вид и число датчиков."""
        described = {item["id"]: item for item in _service().locations()}

        assert described["spalnia"]["kind"] == "room"
        assert described["spalnia"]["sensor_count"] == 3
        assert described["gryadki"]["kind"] == "garden"
        assert described["gryadki"]["sensor_count"] == 1

    def test_unknown_location_has_no_snapshot(self) -> None:
        """Неизвестная локация не выдумывается."""
        assert _service().snapshot("takogo_net") is None


class TestRecording:
    """Показания приходят из событий и запоминаются (FR-001, FR-002)."""

    def test_bound_sensor_updates_snapshot(self) -> None:
        """Показание привязанного датчика попадает в снимок."""
        service = _service({"sensor.t_spalnia": "°C"})

        service.record("sensor.t_spalnia", "22.4", at=NOW)

        reading = service.snapshot("spalnia", now=NOW).readings["temperature"][0]
        assert reading.value == 22.4
        assert reading.unit == "°C"
        assert reading.at == NOW.isoformat()

    def test_unbound_entity_is_ignored(self) -> None:
        """Сущность вне манифеста снимок не меняет (FR-010)."""
        service = _service()

        service.record("sensor.chuzhoi", "99", at=NOW)

        assert service.describe()["seen"] == 0

    def test_same_sensor_updates_two_locations(self) -> None:
        """Один датчик может быть привязан к двум локациям."""
        manifest = _manifest()
        manifest.locations.append(
            LocationConfig(
                id="ulitsa_povtor",
                name="Улица (дубль)",
                sensors={"temperature": "sensor.t_ulitsa"},
            )
        )
        service = LocationStateService(manifest)

        service.record("sensor.t_ulitsa", "14.4", at=NOW)

        assert service.snapshot("ulitsa", now=NOW).readings["temperature"]
        assert service.snapshot("ulitsa_povtor", now=NOW).readings["temperature"]

    def test_event_handler_records_reading(self) -> None:
        """Событие шины обновляет показание."""
        service = _service()

        import asyncio

        asyncio.run(
            service.on_state_change(
                "state_change",
                {"entity_id": "sensor.t_ulitsa", "new_state": "14.4"},
            )
        )

        snapshot = service.snapshot("ulitsa")
        assert snapshot.readings["temperature"][0].value == 14.4

    def test_unavailable_state_is_marked(self) -> None:
        """``unavailable`` — недоступное показание, а не значение."""
        service = _service()

        service.record("sensor.pochva", "unavailable", at=NOW)

        reading = service.snapshot("gryadki", now=NOW).readings["soil_moisture"][0]
        assert reading.available is False


class TestMotionMemory:
    """Время последнего срабатывания движения переживает возврат в off."""

    def test_last_motion_survives_value_change(self) -> None:
        """Датчик сработал и погас — время срабатывания сохраняется."""
        service = _service()

        service.record("binary_sensor.m_spalnia", "on", at=NOW - timedelta(seconds=120))
        service.record("binary_sensor.m_spalnia", "off", at=NOW - timedelta(seconds=60))

        snapshot = service.snapshot("spalnia", now=NOW)
        assert snapshot.derived["occupied"] is True
        assert snapshot.derived["last_motion_ago_sec"] == 120

    def test_motion_never_seen_is_not_presence(self) -> None:
        """Движение не срабатывало — локация пуста."""
        service = _service()

        service.record("binary_sensor.m_spalnia", "off", at=NOW)

        assert service.snapshot("spalnia", now=NOW).derived["occupied"] is False


class TestStaleThreshold:
    """Порог молчания у локации свой (медленные батарейные датчики)."""

    def test_zone_threshold_keeps_battery_sensor_fresh(self) -> None:
        """Датчик почвы молчит два часа — для грядок это норма."""
        service = _service()

        service.record("sensor.pochva", "30", at=NOW - timedelta(hours=2))
        service.record("sensor.t_spalnia", "22.0", at=NOW - timedelta(hours=2))

        garden = service.snapshot("gryadki", now=NOW)
        room = service.snapshot("spalnia", now=NOW)

        assert garden.readings["soil_moisture"][0].stale is False
        assert room.readings["temperature"][0].stale is True, (
            "у комнаты порог дома (час): два часа молчания — молчание"
        )

    def test_describe_names_silent_sensors(self) -> None:
        """Описание для утреннего разбора называет молчащие датчики (FR-012)."""
        service = _service()

        service.record("sensor.t_spalnia", "22.0", at=NOW - timedelta(hours=3))

        described = service.describe()

        assert described["locations"] == 3
        assert "sensor.t_spalnia" in described["silent"]


class TestPrime:
    """Первичное чтение показаний (FR-001): снимок не пуст на старте."""

    @pytest.mark.asyncio
    async def test_prime_reads_all_bound_sensors(self) -> None:
        """Чтение заполняет снимок значениями датчиков."""
        states = {
            "sensor.t_spalnia": "22.0",
            "binary_sensor.m_spalnia": "off",
            "binary_sensor.okno_spalnia": "on",
            "sensor.t_ulitsa": "14.4",
            "sensor.pochva": "unavailable",
        }

        async def reader(entity_id: str) -> str | None:
            return states.get(entity_id)

        service = LocationStateService(_manifest(), state_reader=reader)

        read = await service.prime()

        assert read == len(states)
        snapshot = service.snapshot("spalnia")
        assert snapshot.readings["temperature"][0].value == 22.0
        assert snapshot.derived["contacts_open"] == ["binary_sensor.okno_spalnia"]

    @pytest.mark.asyncio
    async def test_prime_without_reader_reads_nothing(self) -> None:
        """Без чтения состояний снимок остаётся пустым, ошибки нет."""
        assert await LocationStateService(_manifest()).prime() == 0

    @pytest.mark.asyncio
    async def test_prime_survives_broken_sensor(self) -> None:
        """Отказ одного датчика не отменяет остальные."""
        called: list[str] = []

        async def reader(entity_id: str) -> str | None:
            called.append(entity_id)
            if entity_id == "sensor.t_spalnia":
                raise RuntimeError("нет связи")
            return "off"

        service = LocationStateService(_manifest(), state_reader=reader)

        read = await service.prime()

        assert read == len(called) - 1, "отказ одного датчика остановил чтение остальных"

    @pytest.mark.asyncio
    async def test_prime_skips_missing_values(self) -> None:
        """Неизвестное значение не записывается выдуманным."""

        async def reader(_: str) -> str | None:
            return None

        service = LocationStateService(_manifest(), state_reader=reader)

        assert await service.prime() == 0


class TestUnitProvider:
    """Единицы берутся у адаптера и не ломают снимок при отказе."""

    def test_unit_failure_does_not_break_reading(self) -> None:
        """Отказ чтения единицы не отменяет показание."""

        def broken(_: str) -> str | None:
            raise RuntimeError("нет связи")

        service = LocationStateService(_manifest(), unit_provider=broken)

        service.record("sensor.t_spalnia", "22.0", at=NOW)

        reading = service.snapshot("spalnia", now=NOW).readings["temperature"][0]
        assert reading.value == 22.0
        assert reading.unit is None

    def test_without_provider_units_are_empty(self) -> None:
        """Без адаптера снимок собирается, единицы пусты."""
        service = LocationStateService(_manifest())

        service.record("sensor.t_spalnia", "22.0", at=NOW)
        reading = service.snapshot("spalnia", now=NOW).readings["temperature"][0]

        assert reading.unit is None


class TestHelpers:
    """Роли и сущности локации — для запроса истории и зеркала."""

    def test_sensor_entities_and_roles(self) -> None:
        """Локация знает свои сущности и их роли."""
        service = _service()

        assert service.sensor_entities("spalnia") == [
            "binary_sensor.m_spalnia",
            "binary_sensor.okno_spalnia",
            "sensor.t_spalnia",
        ]
        assert service.role_of("spalnia", "sensor.t_spalnia") == "temperature"
        assert service.role_of("spalnia", "sensor.chuzhoi") is None
        assert service.sensor_entities("takogo_net") == []

    def test_bound_entities_lists_all_sensors(self) -> None:
        """Сервис называет все привязанные сущности — для чтения единиц."""
        assert _service().bound_entities() == [
            "binary_sensor.m_spalnia",
            "binary_sensor.okno_spalnia",
            "sensor.pochva",
            "sensor.t_spalnia",
            "sensor.t_ulitsa",
        ]

    def test_subscribe_registers_handler(self) -> None:
        """Подписка на шину регистрирует обработчик."""

        class _Bus:
            def __init__(self) -> None:
                self.handlers: list[Any] = []

            def subscribe(self, event_type: str, handler: Any) -> None:
                self.handlers.append((event_type, handler))

        bus = _Bus()
        service = _service()

        service.subscribe(bus)

        assert bus.handlers and bus.handlers[0][0] == "state_change"
