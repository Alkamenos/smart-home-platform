"""Дашборд собирается из дома, а не из фантазии (BACKLOG B79).

Проверки держат то, на чём обожглись 2026-10-16: владелец опубликовал дашборд и
увидел «ошибка конфигурации» почти в каждой второй карточке. Причины были три, и
каждой здесь поставлен заслон:

* карточки автоматов ссылались на придуманные сущности вида
  ``binary_sensor.<русское имя>_active`` — их нет в доме;
* использовался тип ``entity-button``, которого в современном Home Assistant нет;
* обогреватель-выключатель попадал в карточку ``thermostat``, а ей нужен ``climate.*``.

Правило генератора: **сначала дом, потом карточка**.
"""

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from typing import Any

from core.models.manifest import load_manifest
from dashboard.lovelace_generator import LovelaceGenerator


#: Типы карточек, которые Home Assistant знает и рисует.
VALID_CARD_TYPES = {"entities", "entity", "markdown", "button", "grid", "vertical-stack"}


def _house() -> Any:
    """Загрузить дом для проверок.

    Returns:
        Манифест боевого дома из репозитория.
    """
    return load_manifest("instances/leonids_house_prod/manifest.yaml")


def _views(config: dict[str, Any]) -> list[dict[str, Any]]:
    """Все представления дашборда.

    Args:
        config: Конфигурация дашборда.

    Returns:
        Список представлений.
    """
    return list(config.get("views") or [])


def _cards(config: dict[str, Any]) -> list[dict[str, Any]]:
    """Все карточки всех представлений.

    Args:
        config: Конфигурация дашборда.

    Returns:
        Плоский список карточек.
    """
    return [card for view in _views(config) for card in (view.get("cards") or [])]


class TestOnlyRealEntities:
    """В карточках только то, что есть в доме."""

    def test_no_fabricated_automation_cards(self) -> None:
        """Придуманных сущностей автоматов нет.

        Прежде генератор строил ``binary_sensor.<имя>_active`` из русского имени
        прибора — таких сущностей в доме не бывает.

        Returns:
            Ничего.
        """
        config = LovelaceGenerator().generate(_house())

        mentioned = [entity for card in _cards(config) for entity in _entities_of(card)]

        assert mentioned, "дашборд не ссылается ни на одну сущность"
        assert not [e for e in mentioned if e.endswith("_active")], (
            f"в дашборде придуманные сущности автоматов: {[e for e in mentioned if e.endswith('_active')][:3]}"
        )
        assert not [e for e in mentioned if any(ord(ch) > 127 for ch in e)], (
            "в идентификаторах сущностей кириллица: таких сущностей в доме нет"
        )

    def test_entities_come_from_the_house(self) -> None:
        """Каждая упомянутая сущность описана в доме.

        Returns:
            Ничего.
        """
        manifest = _house()
        known = {device.id for room in manifest.rooms for device in room.devices}
        for room in manifest.rooms:
            known.update(entity for _, entity in _roles(room.sensors))
        for location in manifest.locations:
            known.update(entity for _, entity in _roles(location.sensors))
            known.update(device.id for device in (getattr(location, "devices", None) or []))

        config = LovelaceGenerator().generate(manifest)

        unknown = [
            entity
            for card in _cards(config)
            for entity in _entities_of(card)
            if entity not in known
        ]
        assert not unknown, f"дашборд ссылается на чужие сущности: {unknown[:3]}"


class TestOnlyKnownCardTypes:
    """В дашборде только те типы карточек, которые Home Assistant знает."""

    def test_card_types_are_valid(self) -> None:
        """Удалённых и незнакомых типов карточек нет.

        Returns:
            Ничего.
        """
        config = LovelaceGenerator().generate(_house())

        kinds = {str(card.get("type")) for card in _cards(config)}

        assert kinds <= VALID_CARD_TYPES, f"незнакомые типы карточек: {kinds - VALID_CARD_TYPES}"

    def test_no_thermostat_card_for_a_switch(self) -> None:
        """Обогреватель-выключатель не попадает в карточку термостата.

        Карточка ``thermostat`` требует ``climate.*``: у выключателя она даёт
        «ошибка конфигурации».

        Returns:
            Ничего.
        """
        config = LovelaceGenerator().generate(_house())

        for card in _cards(config):
            if card.get("type") == "thermostat":
                assert str(card.get("entity", "")).startswith("climate."), (
                    f"термостат-карточка на не-климате: {card.get('entity')}"
                )


class TestDashboardShape:
    """Дашборд состоит из мест дома."""

    def test_rooms_and_locations_are_separate_views(self) -> None:
        """Комнаты и локации — разные представления.

        Returns:
            Ничего.
        """
        manifest = _house()

        config = LovelaceGenerator().generate(manifest)

        titles = [view["title"] for view in _views(config)]
        assert [room.name for room in manifest.rooms] == titles[: len(manifest.rooms)]
        assert [location.name for location in manifest.locations] == titles[len(manifest.rooms) :]

    def test_paths_are_usable_by_home_assistant(self) -> None:
        """Пути представлений — латиница, цифры и дефис.

        Returns:
            Ничего.
        """
        config = LovelaceGenerator().generate(_house())

        for view in _views(config):
            path = str(view.get("path") or "")
            assert path, "представление без пути"
            assert all(char.isalnum() and char.isascii() or char == "-" for char in path), (
                f"путь представления недопустим для Home Assistant: {path!r}"
            )

    def test_sensor_labels_are_human(self) -> None:
        """Роли датчиков названы по-русски, а не кодом.

        Returns:
            Ничего.
        """
        config = LovelaceGenerator().generate(_house())

        names = [
            str(entry.get("name"))
            for card in _cards(config)
            for entry in (card.get("entities") or [])
            if isinstance(entry, dict)
        ]

        assert "Температура" in names, f"датчики названы кодом: {sorted(set(names))[:8]}"
        assert not [name for name in names if name.islower() and "_" in name], (
            "роль показана владельцу как есть"
        )


def _entities_of(card: dict[str, Any]) -> list[str]:
    """Сущности, на которые ссылается карточка.

    Args:
        card: Карточка Lovelace.

    Returns:
        Список идентификаторов сущностей.
    """
    found: list[str] = []
    if isinstance(card.get("entity"), str):
        found.append(card["entity"])
    for entry in card.get("entities") or []:
        if isinstance(entry, str):
            found.append(entry)
        elif isinstance(entry, dict) and isinstance(entry.get("entity"), str):
            found.append(entry["entity"])
    return found


def _roles(sensors: Any) -> list[tuple[str, str]]:
    """Пара «роль — сущность» из карты датчиков места.

    Args:
        sensors: Карта датчиков комнаты или локации.

    Returns:
        Список пар.
    """
    from core.models.manifest import iter_role_entities

    return list(iter_role_entities(sensors))
