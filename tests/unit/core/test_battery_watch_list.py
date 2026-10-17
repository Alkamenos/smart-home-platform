"""Список наблюдения за батарейками берётся из манифеста, а не придумывается (B88).

Прежде список собирался выводом имени из имени датчика: у каждой сущности комнаты
отрезался последний сегмент после `_` и приписывалось `_battery`. Домен при этом
оставался от датчика, поэтому выходили имена, которых в доме нет
(`binary_sensor.…_battery`, тогда как батарейка — `sensor.…`), а сам список
повторялся: 26 записей на 13 имён, из них 6 придуманных. Дом отвечал на них
`404`, и наблюдение за зарядом было наполовину мнимым — видно это стало только
после правки К-5, которая назвала отсутствие сущности отказом, а не молчанием.

Здесь проверяется само правило: список — это роли `battery` комнат и локаций плюс
перечень из правил дома, без повторов и без выдуманных имён.

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0
"""

from __future__ import annotations

from core.container import Container
from core.models.manifest import (
    AutomationDomainRules,
    AutomationRules,
    InstanceConfig,
    LocationConfig,
    Manifest,
    RoomConfig,
)


def _manifest(
    room_sensors: dict[str, object] | None = None,
    location_sensors: dict[str, object] | None = None,
    watch_entities: list[str] | None = None,
) -> Manifest:
    """Манифест для проверки списка батареек.

    Args:
        room_sensors: Датчики комнаты.
        location_sensors: Датчики локации.
        watch_entities: Батарейки из правил дома.

    Returns:
        Модель манифеста.
    """
    rules = AutomationRules()
    if watch_entities is not None:
        rules = AutomationRules(
            lighting=AutomationDomainRules(battery_watch_entities=list(watch_entities))
        )
    return Manifest(
        version=1,
        instance=InstanceConfig(
            id="probe", name="Probe", owner="probe", created_at="2026-01-01T00:00:00Z"
        ),
        rooms=[
            RoomConfig(
                id="gostinaia",
                name="Гостиная",
                sensors=room_sensors or {"motion": "binary_sensor.dvizhenie"},
            )
        ],
        locations=(
            [LocationConfig(id="ulitsa", name="Улица", kind="outdoor", sensors=location_sensors)]
            if location_sensors is not None
            else []
        ),
        automation_rules=rules,
    )


def _batteries(**kwargs: object) -> list[str]:
    """Список наблюдения, собранный контейнером.

    Args:
        **kwargs: Аргументы ``_manifest``.

    Returns:
        Список сущностей заряда.
    """
    return Container(manifest=_manifest(**kwargs))._battery_watch_entities()  # noqa: SLF001


class TestBatteryWatchList:
    """Список заряда — из манифеста, без выдумок и повторов."""

    def test_battery_roles_of_room_and_location_are_watched(self) -> None:
        """Роли `battery` комнаты и локации попадают в наблюдение как есть."""
        batteries = _batteries(
            room_sensors={
                "motion": "binary_sensor.dvizhenie",
                "temperature": "sensor.temperatura",
                "battery": "sensor.datchik_battery",
            },
            location_sensors={"battery": "sensor.ulichnyi_datchik_battery"},
        )

        assert batteries == ["sensor.datchik_battery", "sensor.ulichnyi_datchik_battery"]

    def test_no_names_are_invented_from_sensor_names(self) -> None:
        """Комната без роли `battery` — пустой список, а не придуманные имена.

        Здесь и был дефект: из `binary_sensor.dvizhenie` выводилось
        `binary_sensor.dvizhenie_battery`, которого в доме нет.
        """
        batteries = _batteries(
            room_sensors={
                "motion": "binary_sensor.dvizhenie",
                "temperature": "sensor.temperatura",
            }
        )

        assert batteries == [], (
            "платформа придумала сущности заряда из имён датчиков: дом ответит на "
            "них 404, и наблюдение будет только выглядеть работающим"
        )

    def test_extra_batteries_from_house_rules_are_added(self) -> None:
        """Батарейки датчиков вне манифеста добавляются правилами дома."""
        batteries = _batteries(
            room_sensors={"battery": "sensor.datchik_battery"},
            watch_entities=["sensor.ulichnyi_datchik_battery"],
        )

        assert batteries == ["sensor.datchik_battery", "sensor.ulichnyi_datchik_battery"]

    def test_the_same_battery_is_not_watched_twice(self) -> None:
        """Одна батарейка — одна запись, даже если названа в двух местах."""
        batteries = _batteries(
            room_sensors={"battery": "sensor.datchik_battery"},
            location_sensors={"battery": "sensor.datchik_battery"},
            watch_entities=["sensor.datchik_battery"],
        )

        assert batteries == ["sensor.datchik_battery"], f"повторы в списке: {batteries}"

    def test_several_batteries_of_one_role_are_all_watched(self) -> None:
        """У роли бывает несколько сущностей: наблюдение берёт обе."""
        batteries = _batteries(
            room_sensors={"battery": ["sensor.odna_battery", "sensor.drugaia_battery"]}
        )

        assert batteries == ["sensor.odna_battery", "sensor.drugaia_battery"]

    def test_no_batteries_anywhere_gives_empty_list(self) -> None:
        """Батареек в манифесте нет — наблюдать нечего."""
        assert _batteries() == []
