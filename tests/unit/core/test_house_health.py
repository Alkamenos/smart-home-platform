"""Обход дома: проблемы и реестр показаний по локациям и комнатам (F6).

Задача владельца 2026-10-15: «система должна считывать все возможные сенсоры по
локациям и комнатам — что-то вроде машинного зрения для ИИ», плюс обход дома с
сообщением о проблемах.

Две выдачи не смешиваются:

* реестр показаний (`areas`) — всё, что дом отдаёт, по местам манифеста; локации
  и комнаты названы **разными видами** и не путаются;
* проблемы (`problems`) — только то, что требует внимания. И только у датчиков,
  которые обязаны шлать показания сами: датчик движения молчит сутками, и это
  норма, а не проблема.

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from core.services.house_health import HouseHealthService


NOW = datetime(2026, 10, 15, 12, 0, tzinfo=UTC)


@dataclass
class FakeAdapter:
    """Адаптер-двойник: состояния всех сущностей.

    Attributes:
        states: Список состояний.
        fail: Бросать ли ошибку на чтении.
    """

    states: list[dict[str, Any]] = field(default_factory=list)
    fail: bool = False

    async def get_all_states(self) -> list[dict[str, Any]]:
        """Отдать состояния.

        Returns:
            Список состояний.

        Raises:
            RuntimeError: Если задан сбой чтения.
        """
        if self.fail:
            raise RuntimeError("связи нет")
        return self.states


def _state(
    entity_id: str,
    state: str,
    *,
    device_class: str | None = None,
    hours_ago: float = 0.0,
    unit: str | None = None,
) -> dict[str, Any]:
    """Собрать состояние сущности.

    Args:
        entity_id: Идентификатор сущности.
        state: Значение.
        device_class: Класс прибора.
        hours_ago: Сколько часов назад обновлялось.
        unit: Единица измерения.

    Returns:
        Словарь состояния.
    """
    updated = NOW - timedelta(hours=hours_ago)
    attributes: dict[str, Any] = {"friendly_name": entity_id}
    if device_class:
        attributes["device_class"] = device_class
    if unit:
        attributes["unit_of_measurement"] = unit
    return {
        "entity_id": entity_id,
        "state": state,
        "attributes": attributes,
        "last_updated": updated.isoformat(),
        "last_changed": updated.isoformat(),
    }


def _service(adapter: FakeAdapter, areas: dict[str, tuple[str, str]] | None = None) -> Any:
    """Собрать обход дома.

    Args:
        adapter: Адаптер-двойник.
        areas: Карта мест.

    Returns:
        Служба обхода.
    """
    return HouseHealthService(adapter=adapter, areas=areas or {}, clock=lambda: NOW)


@pytest.mark.asyncio
async def test_readings_are_grouped_by_room_and_location() -> None:
    """Реестр разделяет комнаты и локации: их нельзя путать."""
    adapter = FakeAdapter(
        [
            _state(
                "sensor.datchik_temperatury_sad_temperature",
                "30.2",
                device_class="temperature",
                unit="°C",
            ),
            _state(
                "sensor.datchik_temperatury_spalnia_temperature",
                "22.5",
                device_class="temperature",
                unit="°C",
            ),
        ]
    )
    areas = {
        "sensor.datchik_temperatury_sad_temperature": ("локация", "Грядки"),
        "sensor.datchik_temperatury_spalnia_temperature": ("комната", "Спальня"),
    }

    report = await _service(adapter, areas).sweep()

    assert set(report["areas"]) == {"локация:Грядки", "комната:Спальня"}
    assert report["areas"]["локация:Грядки"][0]["area_kind"] == "локация"
    assert report["areas"]["комната:Спальня"][0]["area_kind"] == "комната"
    assert report["sensor_count"] == 2


@pytest.mark.asyncio
async def test_unavailable_sensor_is_a_problem() -> None:
    """Прибор дома не отвечает — проблема."""
    adapter = FakeAdapter(
        [_state("sensor.ulitsa_temperature", "unavailable", device_class="temperature")]
    )
    areas = {"sensor.ulitsa_temperature": ("локация", "Улица")}

    report = await _service(adapter, areas).sweep()

    assert [p["kind"] for p in report["problems"]] == ["unavailable"]
    assert report["problems"][0]["subject"] == "sensor.ulitsa_temperature"


@pytest.mark.asyncio
async def test_quiet_sensor_is_named_stale() -> None:
    """Датчик, который обязан шлать показания, молчит — проблема (§7, п. 4)."""
    adapter = FakeAdapter(
        [_state("sensor.kabinet_temperature", "21.9", device_class="temperature", hours_ago=10)]
    )
    areas = {"sensor.kabinet_temperature": ("комната", "Кабинет")}

    report = await _service(adapter, areas).sweep()

    assert [p["kind"] for p in report["problems"]] == ["stale"]
    assert "молчит" in report["problems"][0]["detail"]


@pytest.mark.asyncio
async def test_motion_sensor_silence_is_not_a_problem() -> None:
    """Молчание датчика движения — норма: он и должен молчать сутками."""
    adapter = FakeAdapter(
        [_state("binary_sensor.konteiner_motion", "off", device_class="motion", hours_ago=72)]
    )
    areas = {"binary_sensor.konteiner_motion": ("комната", "Контейнер")}

    report = await _service(adapter, areas).sweep()

    assert report["problems"] == []
    assert report["areas"]["комната:Контейнер"][0]["stale"] is True, (
        "молчание остаётся видно в реестре"
    )


@pytest.mark.asyncio
async def test_low_battery_is_a_problem() -> None:
    """Батарейка на исходе — проблема (порог 20 %)."""
    adapter = FakeAdapter(
        [
            _state(
                "sensor.datchik_temperatury_terassa_battery", "1", device_class="battery", unit="%"
            )
        ]
    )
    areas = {"sensor.datchik_temperatury_terassa_battery": ("комната", "Терраса")}

    report = await _service(adapter, areas).sweep()

    assert [p["kind"] for p in report["problems"]] == ["low_battery"]
    assert "заряд 1 %" in report["problems"][0]["detail"]


@pytest.mark.asyncio
async def test_silent_battery_is_not_a_problem() -> None:
    """Батарейка молчит сутками — это норма: у неё важен заряд, а не регулярность."""
    adapter = FakeAdapter(
        [
            _state(
                "sensor.datchik_temperatury_kabinet_battery",
                "100",
                device_class="battery",
                unit="%",
                hours_ago=89,
            )
        ]
    )
    areas = {"sensor.datchik_temperatury_kabinet_battery": ("комната", "Кабинет")}

    report = await _service(adapter, areas).sweep()

    assert report["problems"] == []
    assert report["areas"]["комната:Кабинет"][0]["stale"] is True, "молчание видно в реестре"


@pytest.mark.asyncio
async def test_healthy_sensor_has_no_problem() -> None:
    """Живой датчик с нормальным зарядом проблем не рождает."""
    adapter = FakeAdapter(
        [
            _state("sensor.sad_temperature", "30.1", device_class="temperature", unit="°C"),
            _state("sensor.sad_battery", "92", device_class="battery", unit="%"),
        ]
    )

    report = await _service(adapter).sweep()

    assert report["problems"] == []


@pytest.mark.asyncio
async def test_imported_sensor_outside_the_house_is_not_an_alarm() -> None:
    """Импортированный датчик без места в манифесте — не «проблема дома».

    Дом импортирует телефоны, прогнозы и шаблоны: их «недоступность» не требует
    вмешательства. В реестре они остаются (чтение для ИИ), но тревог не дают —
    иначе настоящие проблемы тонули бы в 82 из 139.
    """
    adapter = FakeAdapter(
        [_state("sensor.iphone_battery_level", "unavailable", device_class="battery", unit="%")]
    )

    report = await _service(adapter).sweep()

    assert report["problems"] == []
    assert report["areas"]["без места"][0]["entity_id"] == "sensor.iphone_battery_level"


@pytest.mark.asyncio
async def test_service_entities_are_not_swept() -> None:
    """Служебные сущности в обход не попадают: их «недоступность» — не проблема."""
    adapter = FakeAdapter(
        [
            _state("update.datchik_temperatury_sad", "on"),
            _state("button.kalitka_sad_reboot", "unavailable"),
            _state("automation.zima", "off"),
        ]
    )

    report = await _service(adapter).sweep()

    assert report["problems"] == []
    assert report["sensor_count"] == 0


@pytest.mark.asyncio
async def test_read_failure_gives_empty_report() -> None:
    """Нет связи — пустой снимок, а не падение."""
    report = await _service(FakeAdapter(fail=True)).sweep()

    assert report["problems"] == []
    assert report["areas"] == {}


@pytest.mark.asyncio
async def test_last_report_is_cached() -> None:
    """Последний снимок доступен интерфейсу без нового обхода."""
    service = _service(FakeAdapter([]))

    assert service.last_report is None
    await service.sweep()

    assert service.last_report is not None
    assert service.last_report["problems"] == []
