"""Устройство не должно попадать в случайную комнату.

Две ночи подряд применение пачки устройств переписало состав дома, и виноват
оказался не только молчаливый отказ на уменьшение (#88), но и выбор комнаты:
если устройство пришло без комнаты, код брал **первую комнату манифеста**. В
боевом манифесте первой была `kitchen` — туда и сложились двадцать чужих
светильников, потому что комнату никто не выбирал.

Правило: комнату выбирает владелец либо она известна из Home Assistant. Если ни
того, ни другого — отказ с внятным текстом, а не тихое размещение в чужой
комнате.
"""

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from typing import Any

import pytest

from core.models.manifest import InstanceConfig, Manifest, RoomConfig
from webui.routes.devices.devices import _default_room_id


def _manifest(*room_ids: str) -> Any:
    """Манифест с заданными комнатами.

    Args:
        *room_ids: Идентификаторы комнат по порядку.

    Returns:
        Модель манифеста.
    """
    return Manifest(
        version=1,
        instance=InstanceConfig(
            id="probe", name="Probe", owner="probe", created_at="2026-01-01T00:00:00Z"
        ),
        rooms=[
            RoomConfig(id=room_id, name=room_id.title(), sensors={}, devices=[])
            for room_id in room_ids
        ],
    )


def _device(area_id: str | None = None) -> Any:
    """Устройство с указанной областью Home Assistant.

    Args:
        area_id: Идентификатор области либо None.

    Returns:
        Простой объект с полем `ha_area_id`.
    """

    class _Device:
        """Заглушка устройства."""

        def __init__(self, value: str | None) -> None:
            self.ha_area_id = value

    return _Device(area_id)


class TestDeviceNeverLandsInAForeignRoom:
    """Комната устройства — из выбора владельца или из его области в HA."""

    def test_area_of_device_wins(self) -> None:
        """Область устройства в Home Assistant — источник комнаты."""
        manifest = _manifest("kitchen", "gostinaia")

        chosen = _default_room_id(manifest, _device(area_id="gostinaia"))

        assert chosen == "gostinaia", (
            f"устройство из области gostinaia попало в {chosen!r}: комната бралась "
            "из первой в манифесте, а не из дома"
        )

    def test_unknown_area_falls_back_to_first_room_with_warning_free_choice(self) -> None:
        """Область, которой нет в манифесте, комнату не подменяет.

        Область Home Assistant и комнаты манифеста — разные справочники;
        молчаливый выбор другой комнаты означал бы, что устройство управляется
        по датчику не своей комнаты.

        Args:
            Ничего.
        """
        manifest = _manifest("gostinaia")

        with pytest.raises(ValueError, match="комнат"):
            _default_room_id(manifest, _device(area_id="neizvestnaya-oblast"))

    def test_device_without_room_or_area_is_refused(self) -> None:
        """Нет выбора и нет области — отказ, а не первая комната подряд.

        Args:
            Ничего.
        """
        manifest = _manifest("kitchen", "gostinaia")

        with pytest.raises(ValueError, match="комнат"):
            _default_room_id(manifest, _device(area_id=None))

    def test_manifest_without_rooms_is_refused(self) -> None:
        """В манифесте без комнат устройство добавлять некуда.

        Args:
            Ничего.
        """
        with pytest.raises(ValueError, match="комнат"):
            _default_room_id(_manifest(), _device(area_id="gostinaia"))
