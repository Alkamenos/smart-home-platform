"""Снимок локации: показания, молчание и производные (спека 016, FR-001…FR-003).

Снимок — единственное место, откуда видно «что сейчас в комнате / на улице /
на грядках». Проверяется то, ради чего он задуман: значение с временем и
единицей, различие «датчик молчит» и «значение не изменилось», недоступность
отдельно от значения, и производные, которые считаются **на чтение** из
сохранённых показаний (research.md D6).

Отдельно проверяется, что производные не считаются по мёртвому датчику:
«человек в комнате», посчитанный по недоступному датчику движения, — это ложь,
а не удобное умолчание (edge case спеки).

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from core.models.location import SensorReading, build_snapshot


NOW = datetime(2026, 10, 13, 9, 0, 0, tzinfo=UTC)
STALE_AFTER = 3600
PRESENCE_WINDOW = 600


def _reading(
    entity_id: str,
    role: str,
    value: object,
    *,
    ago_sec: float = 0.0,
    unit: str | None = None,
    available: bool = True,
    last_on_ago_sec: float | None = None,
) -> SensorReading:
    """Показание датчика с временем «сколько секунд назад».

    Args:
        entity_id: Сущность.
        role: Роль датчика.
        value: Значение.
        ago_sec: Сколько секунд назад пришло показание.
        unit: Единица измерения.
        available: Доступно ли состояние.
        last_on_ago_sec: Сколько секунд назад датчик был «включён».

    Returns:
        Модель показания.
    """
    return SensorReading(
        entity_id=entity_id,
        role=role,
        value=value,
        unit=unit,
        at=NOW - timedelta(seconds=ago_sec),
        available=available,
        last_on_at=(
            NOW - timedelta(seconds=last_on_ago_sec) if last_on_ago_sec is not None else None
        ),
    )


def _snapshot(readings: list[SensorReading]):
    """Собрать снимок локации «Спальня» по показаниям.

    Args:
        readings: Показания датчиков.

    Returns:
        Снимок локации.
    """
    return build_snapshot(
        location_id="spalnia",
        name="Спальня",
        kind="room",
        readings=readings,
        now=NOW,
        stale_after_sec=STALE_AFTER,
        presence_window_sec=PRESENCE_WINDOW,
    )


class TestReadings:
    """Показания попадают в снимок с единицей и временем (FR-002)."""

    def test_reading_carries_value_unit_and_time(self) -> None:
        """Значение, единица и время — всё на месте."""
        snapshot = _snapshot([_reading("sensor.t", "temperature", 22.4, unit="°C", ago_sec=30)])

        reading = snapshot.readings["temperature"][0]
        assert reading.value == 22.4
        assert reading.unit == "°C"
        assert reading.at == (NOW - timedelta(seconds=30)).isoformat()
        assert reading.stale is False

    def test_two_sensors_of_one_role_are_a_list(self) -> None:
        """У роли бывает несколько датчиков: снимок хранит список."""
        snapshot = _snapshot(
            [
                _reading("sensor.t1", "temperature", 21.0),
                _reading("sensor.t2", "temperature", 23.0),
            ]
        )

        values = [r.value for r in snapshot.readings["temperature"]]
        assert values == [21.0, 23.0]
        assert snapshot.derived["sensor_count"] == 2

    def test_location_without_sensors_is_empty_but_exists(self) -> None:
        """Локация без датчиков существует и честно пуста."""
        snapshot = _snapshot([])

        assert snapshot.readings == {}
        assert snapshot.available is False
        assert snapshot.derived["sensor_count"] == 0


class TestStale:
    """Молчание отличается от «значение не изменилось» (FR-011)."""

    def test_fresh_reading_is_not_stale(self) -> None:
        """Свежее показание молчащим не считается."""
        snapshot = _snapshot([_reading("sensor.t", "temperature", 22.0, ago_sec=3599)])

        assert snapshot.readings["temperature"][0].stale is False
        assert snapshot.derived["stale_count"] == 0

    def test_old_reading_is_stale_and_named(self) -> None:
        """Старое показание помечено и названо в списке молчащих."""
        snapshot = _snapshot([_reading("sensor.guest", "temperature", 18.0, ago_sec=7200)])

        assert snapshot.readings["temperature"][0].stale is True
        assert snapshot.derived["stale_count"] == 1
        assert snapshot.derived["stale_sensors"] == ["sensor.guest"]

    def test_stale_value_is_kept(self) -> None:
        """Значение молчащего датчика остаётся последним известным."""
        snapshot = _snapshot([_reading("sensor.guest", "temperature", 18.0, ago_sec=7200)])

        assert snapshot.readings["temperature"][0].value == 18.0


class TestUnavailable:
    """Исчезнувший датчик отличается от пустого показания."""

    def test_unavailable_value_marks_reading_unavailable(self) -> None:
        """``unavailable`` — недоступное показание."""
        snapshot = _snapshot([_reading("sensor.broken", "illuminance", "unavailable", unit="lx")])

        reading = snapshot.readings["illuminance"][0]
        assert reading.available is False
        assert snapshot.derived["available_count"] == 0

    def test_available_count_ignores_unavailable(self) -> None:
        """Счётчик доступных не считает недоступные."""
        snapshot = _snapshot(
            [
                _reading("sensor.t", "temperature", 22.0),
                _reading("sensor.hum", "humidity", "unknown"),
            ]
        )

        assert snapshot.derived["available_count"] == 1
        assert snapshot.derived["sensor_count"] == 2
        assert snapshot.available is True


class TestDerived:
    """Производные: присутствие, движение, проёмы (FR-003)."""

    def test_motion_within_window_is_occupied(self) -> None:
        """Недавнее движение — локация занята."""
        snapshot = _snapshot([_reading("binary_sensor.m", "motion", "off", last_on_ago_sec=171)])

        assert snapshot.derived["occupied"] is True
        assert snapshot.derived["last_motion_ago_sec"] == 171

    def test_old_motion_is_not_occupied(self) -> None:
        """Давнее движение — локация пуста, время движения сохраняется."""
        snapshot = _snapshot([_reading("binary_sensor.m", "motion", "off", last_on_ago_sec=3600)])

        assert snapshot.derived["occupied"] is False
        assert snapshot.derived["last_motion_ago_sec"] == 3600

    def test_never_seen_motion_is_empty(self) -> None:
        """Движение ни разу не срабатывало — времени нет, локация пуста."""
        snapshot = _snapshot([_reading("binary_sensor.m", "motion", "off")])

        assert snapshot.derived["occupied"] is False
        assert snapshot.derived["last_motion_at"] is None
        assert snapshot.derived["last_motion_ago_sec"] is None

    def test_open_contacts_are_listed(self) -> None:
        """Открытые окна и двери перечислены поимённо."""
        snapshot = _snapshot(
            [
                _reading("binary_sensor.okno", "contact", "on"),
                _reading("binary_sensor.dver", "contact", "off"),
            ]
        )

        assert snapshot.derived["contacts_open"] == ["binary_sensor.okno"]

    def test_dead_motion_sensor_does_not_count_as_presence(self) -> None:
        """Мёртвый датчик движения не делает локацию занятой."""
        snapshot = _snapshot(
            [
                _reading(
                    "binary_sensor.m",
                    "motion",
                    "unavailable",
                    available=False,
                    last_on_ago_sec=60,
                )
            ]
        )

        assert snapshot.derived["occupied"] is False, (
            "присутствие посчитано по недоступному датчику: это ложь, а не удобное умолчание"
        )
        assert snapshot.derived["contacts_open"] == []

    def test_denied_contact_of_dead_sensor_is_not_open(self) -> None:
        """Недоступный контакт не считается открытым."""
        snapshot = _snapshot(
            [
                _reading("binary_sensor.okno", "contact", "on", available=False),
                _reading("binary_sensor.dver", "contact", "on", available=True),
            ]
        )

        assert snapshot.derived["contacts_open"] == ["binary_sensor.dver"]


class TestSnapshotShape:
    """Снимок несёт, кто он, и когда снят."""

    def test_snapshot_names_location_and_time(self) -> None:
        """Локация и время снимка заполнены."""
        snapshot = _snapshot([_reading("sensor.t", "temperature", 22.0)])

        assert snapshot.location.id == "spalnia"
        assert snapshot.location.name == "Спальня"
        assert snapshot.location.kind == "room"
        assert snapshot.at == NOW.isoformat()

    def test_snapshot_is_json_serialisable(self) -> None:
        """Снимок отдаётся наружу без доработки (HTTP, MQTT)."""
        snapshot = _snapshot([_reading("sensor.t", "temperature", 22.0, unit="°C")])

        payload = snapshot.model_dump(mode="json")

        assert payload["location"]["id"] == "spalnia"
        assert payload["readings"]["temperature"][0]["unit"] == "°C"
        assert isinstance(payload["derived"]["occupied"], bool)
