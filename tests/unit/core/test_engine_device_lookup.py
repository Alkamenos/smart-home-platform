"""Поиск автоматов по устройству не должен цеплять чужое (боевой дефект 2026-10-12).

``fan.base_smart`` — префикс ``fan.base_smart_2``. Прежний поиск по
``startswith(f"{device_id}_")`` возвращал автоматы **обоих** рекуператоров, и в
бою датчик спальни маршрутизировался на рекуператор кабинета. Устройство берётся
из ``target_device_id``; префикс оставлен запасным путём для определений без него.
"""

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from core.fsm.engine import FSMDefinition, FSMEngine, Transition


def _definition(entity_id: str, device_id: str | None) -> FSMDefinition:
    """Автомат устройства с явно заданным ``target_device_id``.

    Args:
        entity_id: Идентификатор автомата.
        device_id: Устройство-владелец.

    Returns:
        Определение автомата.
    """
    return FSMDefinition(
        entity_id=entity_id,
        initial_state="IDLE",
        states=["IDLE"],
        transitions=[
            Transition(from_state="IDLE", to_state="IDLE", trigger="ping", action=lambda *a: None)
        ],
        target_device_id=device_id,
    )


class TestDeviceLookupIsExact:
    """Устройство не смешивается с устройством-омонимом по префиксу."""

    def test_prefix_sibling_is_not_returned(self) -> None:
        """``fan.base_smart`` не приносит автомат ``fan.base_smart_2``.

        Returns:
            Ничего.
        """
        engine = FSMEngine()
        engine.register_definition(
            _definition("fan.base_smart_ventilation_modes_10", "fan.base_smart")
        )
        engine.register_definition(
            _definition("fan.base_smart_2_ventilation_modes_10", "fan.base_smart_2")
        )

        found = engine.get_entities_by_device("fan.base_smart")

        assert found == ["fan.base_smart_ventilation_modes_10"], (
            f"по устройству fan.base_smart найдено {found}: в бою туда попал "
            "автомат соседнего рекуператора, и датчик одной комнаты управлял "
            "прибором другой"
        )

    def test_exact_device_returns_its_own_fsm(self) -> None:
        """У устройства с подчёркиванием в имени возвращается только своё.

        Returns:
            Ничего.
        """
        engine = FSMEngine()
        engine.register_definition(
            _definition("fan.base_smart_ventilation_modes_10", "fan.base_smart")
        )
        engine.register_definition(
            _definition("fan.base_smart_2_ventilation_modes_10", "fan.base_smart_2")
        )

        assert engine.get_entities_by_device("fan.base_smart_2") == [
            "fan.base_smart_2_ventilation_modes_10"
        ]

    def test_prefix_fallback_works_without_target_device(self) -> None:
        """Определение без ``target_device_id`` находится по префиксу.

        Returns:
            Ничего.
        """
        engine = FSMEngine()
        engine.register_definition(_definition("light.kitchen_lighting_10", None))

        assert engine.get_entities_by_device("light.kitchen") == ["light.kitchen_lighting_10"]
