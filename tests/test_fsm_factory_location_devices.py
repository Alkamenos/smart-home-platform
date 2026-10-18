"""Автоматика прибора строится одинаково для комнаты и локации (B79).

Требование владельца 2026-10-19: «автоматы должны работать независимо от того,
комната или локация». Прежде сборка автоматов шла по ``Manifest.all_devices``, а
тот перебирал **только комнаты**: перенос места из комнат в локации молча
выключал его автоматику — свет в контейнере, гирлянда террасы, ночное освещение
сада перестали бы работать без единой ошибки в журнале.

Проверка держит обе стороны: прибор локации получает свой автомат с именем места
(оно нужно правилам «комнат без окон»), и прибор комнаты не перестаёт собираться.
"""

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import pytest

from core.fsm.engine import FSMEngine
from core.fsm.factory import FSMFactory
from core.models.manifest import (
    AutomationRules,
    BehaviorConfig,
    DeviceConfig,
    InstanceConfig,
    LocationConfig,
    Manifest,
    RoomConfig,
)
from core.registry import Registry


#: Простейший шаблон поведения: проверке нужен сам факт сборки, а не правила.
TEMPLATE = """
initial_state: "OFF"
states:
  - "OFF"
  - "ON_MOTION"
transitions:
  - from_state: "OFF"
    to_state: "ON_MOTION"
    trigger: "motion_detected"
    action: "turn_on_light"
"""


def _instance() -> InstanceConfig:
    """Описание дома для манифеста.

    Returns:
        Модель дома.
    """
    return InstanceConfig(
        id="probe", name="Probe", owner="probe", created_at="2026-01-01T00:00:00Z"
    )


def _device(device_id: str) -> DeviceConfig:
    """Прибор с поведением освещения.

    Args:
        device_id: Идентификатор прибора.

    Returns:
        Прибор манифеста.
    """
    return DeviceConfig(
        id=device_id,
        type="light",
        name="Свет",
        behaviors=[BehaviorConfig(template="lighting", priority=10, params={})],
    )


def _factory(tmp_path: pytest.TempPathFactory) -> FSMFactory:
    """Фабрика с одним шаблоном поведения и зарегистрированным действием.

    Args:
        tmp_path: Временный каталог.

    Returns:
        Фабрика автоматов.
    """
    (tmp_path / "lighting.yaml").write_text(TEMPLATE, encoding="utf-8")
    registry = Registry()

    async def turn_on_light(state: object, context: dict[str, object]) -> bool:
        """Действие-заглушка: проверке нужен факт сборки, а не управление.

        Args:
            state: Состояние автомата.
            context: Контекст перехода.

        Returns:
            True.
        """
        del state, context
        return True

    registry.register_action("turn_on_light", turn_on_light)
    return FSMFactory(FSMEngine(), registry, features_dir=str(tmp_path))


class TestAutomationDoesNotDependOnPlaceKind:
    """Комната и локация — разные места, но правило сборки одно."""

    def test_device_in_location_gets_its_automation(self, tmp_path) -> None:
        """Прибор локации собирается, и место уходит в автомат."""
        factory = _factory(tmp_path)
        manifest = Manifest(
            instance=_instance(),
            locations=[
                LocationConfig(
                    id="konteiner",
                    name="Контейнер",
                    kind="other",
                    devices=[_device("light.svet_v_konteinere")],
                )
            ],
            automation_rules=AutomationRules(),
        )

        definitions = factory.create_from_manifest(manifest)

        assert [item.entity_id for item in definitions] == [
            "light.svet_v_konteinere_lighting_10"
        ], "автоматика прибора локации не собрана"
        assert definitions[0].room == "konteiner", "место не доехало до правил"

    def test_device_in_room_still_gets_its_automation(self, tmp_path) -> None:
        """Комната собирается как прежде — правка ничего не сломала."""
        factory = _factory(tmp_path)
        manifest = Manifest(
            instance=_instance(),
            rooms=[
                RoomConfig(
                    id="sanuzel",
                    name="Санузел",
                    devices=[_device("light.vykliuchatel_sanuzel_switch1")],
                )
            ],
            automation_rules=AutomationRules(),
        )

        definitions = factory.create_from_manifest(manifest)

        assert [item.entity_id for item in definitions] == [
            "light.vykliuchatel_sanuzel_switch1_lighting_10"
        ]
        assert definitions[0].room == "sanuzel"
