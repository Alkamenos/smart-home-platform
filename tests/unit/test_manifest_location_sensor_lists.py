"""Локация принимает несколько сущностей на одну роль (B79, теплица).

Схема манифеста и раньше разрешала «роль → список сущностей» (две камеры на
террасе дают движение и детекции), но проверка датчиков локации ждала строку и
падала на списке: `AttributeError: 'list' object has no attribute 'strip'`.
Теплица — первая локация, которой понадобились три температуры сразу (огурцы,
томаты, обогреватель), поэтому дефект и всплыл.

Проверки держат обе стороны: список читается, а пустая сущность внутри списка
по-прежнему отвергается — иначе датчик молчал бы, хотя описан в манифесте.
"""

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import pytest
from pydantic import ValidationError

from core.models.manifest import LocationConfig, role_entities


class TestLocationDevices:
    """У локации могут быть приборы — только показ, без поведений."""

    def test_devices_are_kept(self) -> None:
        """Фонарь улицы остаётся в локации, а не теряется при разборе."""
        location = LocationConfig(
            id="ulitsa",
            name="Улица",
            kind="outdoor",
            devices=[{"id": "light.fonar", "type": "light", "name": "Фонарь", "behaviors": []}],
        )

        assert [device.id for device in location.devices] == ["light.fonar"]
        assert location.devices[0].behaviors == []


class TestLocationSensorLists:
    """Локация с несколькими сущностями одной роли."""

    def test_list_of_entities_is_accepted(self) -> None:
        """Три температуры теплицы читаются как три сущности одной роли."""
        location = LocationConfig(
            id="teplitsa",
            name="Теплица",
            kind="garden",
            sensors={
                "temperature": [
                    "sensor.temperatura_v_teplitse_ogurtsy_temperature",
                    "sensor.temperatura_v_teplitse_tomaty_temperature",
                    "sensor.d1215es_new_current_temperature",
                ]
            },
        )

        assert role_entities(location.sensors, "temperature") == [
            "sensor.temperatura_v_teplitse_ogurtsy_temperature",
            "sensor.temperatura_v_teplitse_tomaty_temperature",
            "sensor.d1215es_new_current_temperature",
        ]

    def test_empty_entity_inside_list_is_rejected(self) -> None:
        """Пустая сущность в списке — ошибка манифеста, а не молчание."""
        with pytest.raises(ValidationError):
            LocationConfig(
                id="teplitsa",
                name="Теплица",
                kind="garden",
                sensors={"temperature": ["sensor.a", "  "]},
            )

    def test_empty_string_is_still_rejected(self) -> None:
        """Одиночная пустая строка отвергается как раньше."""
        with pytest.raises(ValidationError):
            LocationConfig(
                id="teplitsa",
                name="Теплица",
                kind="garden",
                sensors={"temperature": " "},
            )
