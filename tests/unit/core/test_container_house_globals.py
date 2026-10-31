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
    """Старое поле climate.thermostat_entity больше не участвует.

    Args:
        Нет.

    Returns:
        Ничего.
    """
    rules = AutomationRules.model_validate(
        {"climate": {"thermostat_entity": "climate.old_thermostat"}}
    )
    adapter = _bind(_container([], rules))

    assert "thermostat" not in adapter.climate_entities
