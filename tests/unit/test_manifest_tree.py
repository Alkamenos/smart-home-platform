"""Дерево мест в манифесте: комнаты и локации — одно пространство (B93).

Владелец мыслит деревом: «Теплица — локация в саду», «зона грядок в саду»,
«ворота и калитки на улице». Плоские разделы ``rooms``/``locations`` этого не
выражали, поэтому появился ``parent``.

Проверки держат не только счастливый путь, но и то, что ломает дерево:

* один идентификатор у комнаты и локации (вложенность стала бы неоднозначной);
* родитель, которого нет;
* место, вложенное само в себя, и цикл;
* локация внутри комнаты: комнаты — внутренние помещения, улица в них не входит.
"""

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import pytest
from pydantic import ValidationError

from core.models.manifest import (
    InstanceConfig,
    LocationConfig,
    Manifest,
    RoomConfig,
)


def _instance() -> InstanceConfig:
    """Описание дома для манифеста.

    Returns:
        Модель дома.
    """
    return InstanceConfig(
        id="probe", name="Probe", owner="probe", created_at="2026-01-01T00:00:00Z"
    )


def _manifest(
    rooms: list[RoomConfig] | None = None,
    locations: list[LocationConfig] | None = None,
) -> Manifest:
    """Собрать манифест с заданными местами.

    Args:
        rooms: Комнаты.
        locations: Локации.

    Returns:
        Манифест.
    """
    return Manifest(
        instance=_instance(),
        rooms=rooms or [],
        locations=locations or [],
    )


class TestPlaceTree:
    """Вложенность мест читается: родитель, дети, путь."""

    def test_parent_children_and_path(self) -> None:
        """Улица → сад → теплица: дети и путь собираются по родителям."""
        manifest = _manifest(
            locations=[
                LocationConfig(id="ulitsa", name="Улица", kind="outdoor"),
                LocationConfig(id="sad", name="Сад", kind="garden", parent="ulitsa"),
                LocationConfig(id="teplitsa", name="Теплица", kind="garden", parent="sad"),
            ]
        )

        assert [place.id for place in manifest.children(None)] == ["ulitsa"]
        assert [place.id for place in manifest.children("sad")] == ["teplitsa"]
        assert [place.id for place in manifest.place_path("teplitsa")] == [
            "ulitsa",
            "sad",
            "teplitsa",
        ]

    def test_room_keeps_its_kind(self) -> None:
        """Комната — место вида ``room``, даже если вид не указан."""
        room = RoomConfig(id="gostinaia", name="Гостиная")

        assert room.kind == "room"
        assert room.parent is None


class TestDashboardFollowsTree:
    """Панель дома идёт по дереву: ребёнок сразу после родителя."""

    def test_child_view_follows_parent(self) -> None:
        """«Теплица в саду» стоит после сада, а не в общем списке.

        Returns:
            Ничего.
        """
        from dashboard.lovelace_generator import LovelaceGenerator

        manifest = _manifest(
            locations=[
                LocationConfig(id="ulitsa", name="Улица", kind="outdoor"),
                LocationConfig(id="sad", name="Сад", kind="garden", parent="ulitsa"),
                LocationConfig(id="teplitsa", name="Теплица", kind="garden", parent="sad"),
            ]
        )

        views = LovelaceGenerator().generate(manifest)["views"]
        titles = [view["title"] for view in views if view["title"] != "Платформа"]

        assert titles == ["Улица", "Сад", "Теплица"]


class TestTreeInvariants:
    """Дерево не принимает то, что делает вложенность неоднозначной."""

    def test_duplicate_id_between_room_and_location(self) -> None:
        """Один id у комнаты и локации — ошибка манифеста."""
        with pytest.raises(ValidationError):
            _manifest(
                rooms=[RoomConfig(id="sad", name="Сад")],
                locations=[LocationConfig(id="sad", name="Сад", kind="garden")],
            )

    def test_unknown_parent(self) -> None:
        """Родителя нет — ссылка битая."""
        with pytest.raises(ValidationError):
            _manifest(
                locations=[
                    LocationConfig(id="teplitsa", name="Теплица", kind="garden", parent="sad")
                ]
            )

    def test_place_cannot_be_its_own_parent(self) -> None:
        """Место не может быть родителем само себе."""
        with pytest.raises(ValidationError):
            _manifest(locations=[LocationConfig(id="sad", name="Сад", kind="garden", parent="sad")])

    def test_cycle_is_rejected(self) -> None:
        """Сад в теплице и теплица в саду — цикл."""
        with pytest.raises(ValidationError):
            _manifest(
                locations=[
                    LocationConfig(id="sad", name="Сад", kind="garden", parent="teplitsa"),
                    LocationConfig(id="teplitsa", name="Теплица", kind="garden", parent="sad"),
                ]
            )

    def test_location_cannot_be_nested_in_room(self) -> None:
        """Локация внутри комнаты — неверная модель дома."""
        with pytest.raises(ValidationError):
            _manifest(
                rooms=[RoomConfig(id="gostinaia", name="Гостиная")],
                locations=[
                    LocationConfig(id="ulitsa", name="Улица", kind="outdoor", parent="gostinaia")
                ],
            )
