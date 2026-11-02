"""Контейнер раздаёт адаптеру «домашние» климатические сущности (B76 A5–A6).

Сезон — свойство дома, термостат — свойство комнаты. Проверка держит эти
адреса: если сезон снова начнут искать в правилах климата, а термостат — в
правилах дома, тест покраснеет.

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from core.container import Container
from core.models.manifest import (
    AutomationRules,
    BehaviorConfig,
    DeviceConfig,
    InstanceConfig,
    Manifest,
    RoomConfig,
)


class _Adapter:
    """Адаптер-двойник: только словари ролей, которые заполняет контейнер."""

    def __init__(self) -> None:
        self.climate_entities: dict[str, str] = {}
        self.ventilation_entities: dict[str, str] = {}
        self.lighting_entities: dict[str, str] = {}
        self.cover_entities: dict[str, str] = {}


def _container(rooms: list[RoomConfig], rules: AutomationRules) -> Container:
    """Собрать контейнер с заданными местами и правилами.

    Args:
        rooms: Комнаты манифеста.
        rules: Правила дома.

    Returns:
        Контейнер без собранного адаптера.
    """
    return Container(
        manifest=Manifest(
            version=1,
            instance=InstanceConfig(
                id="probe", name="Probe", owner="probe", created_at="2026-01-01T00:00:00Z"
            ),
            rooms=rooms,
            automation_rules=rules,
        )
    )


def _bind(container: Container) -> _Adapter:
    """Подставить двойник адаптера и выполнить привязку ролей.

    Args:
        container: Контейнер с манифестом.

    Returns:
        Адаптер после привязки.
    """
    adapter = _Adapter()
    container._adapter = adapter  # type: ignore[assignment]  # noqa: SLF001
    container._bind_global_entities()  # noqa: SLF001
    return adapter


def test_season_is_bound_from_house_rules() -> None:
    """Сезон берётся из automation_rules.season_entity."""
    adapter = _bind(_container([], AutomationRules(season_entity="input_boolean.zima")))

    assert adapter.climate_entities["season"] == "input_boolean.zima"


def test_scheduled_light_feature_is_bound_from_house_rules() -> None:
    """Разрешение на плановый свет берётся с уровня дома."""
    rules = AutomationRules(
        scheduled_light_feature_entity="input_boolean.vkliuchat_osnovnoe_osveshchenie"
    )
    adapter = _bind(_container([], rules))

    assert (
        adapter.lighting_entities["scheduled_feature"]
        == "input_boolean.vkliuchat_osnovnoe_osveshchenie"
    )


def test_scheduled_light_fsm_is_known_to_watcher() -> None:
    """Сверка получает имя автомата планового света, чтобы не повторять закат."""
    room = RoomConfig(
        id="sad",
        name="Сад",
        devices=[
            DeviceConfig(
                id="light.vse_fonari",
                type="light",
                name="Основное освещение",
                behaviors=[
                    BehaviorConfig(
                        template="scheduled_light",
                        priority=10,
                        params={"off_by": "sleep"},
                    )
                ],
            )
        ],
    )
    container = _container([room], AutomationRules())

    assert container._scheduled_light_entities() == {  # noqa: SLF001
        "light.vse_fonari_scheduled_light_10"
    }


def test_thermostat_is_bound_from_room() -> None:
    """Термостат берётся из комнаты, а не из общих правил климата."""
    room = RoomConfig(
        id="gostinaia",
        name="Гостиная",
        thermostat_entity="climate.termostat_gostinaia",
    )
    adapter = _bind(_container([room], AutomationRules()))

    assert adapter.climate_entities["thermostat"] == "climate.termostat_gostinaia"


def test_no_room_thermostat_leaves_role_unset() -> None:
    """Без термостата в комнатах роль остаётся пустой."""
    adapter = _bind(_container([RoomConfig(id="spalnia", name="Спальня")], AutomationRules()))

    assert "thermostat" not in adapter.climate_entities


def test_empty_room_thermostat_is_rejected() -> None:
    """Пустое имя термостата — ошибка загрузки, а не «ни с чем»."""
    with pytest.raises(ValidationError):
        RoomConfig(id="gostinaia", name="Гостиная", thermostat_entity="")


def test_thermostat_is_not_taken_from_climate_rules() -> None:
    """Старое поле climate.thermostat_entity отвергается, а не игнорируется.

    Args:
        Нет.

    Returns:
        Ничего.
    """
    with pytest.raises(ValidationError):
        AutomationRules.model_validate({"climate": {"thermostat_entity": "climate.old_thermostat"}})
