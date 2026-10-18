"""Имена автоматов и их помощников в Home Assistant (B79).

Идентификатор автомата — общий язык фабрики, журнала, дашборда и зеркала.
Правило живёт в одном месте, и эти проверки держат его от расползания:
идентификатор помощника обязан быть латиницей (кириллица сделала бы его
непредсказуемым) и совпадать с тем, что Home Assistant собирает из имени
помощника.
"""

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from core.fsm.naming import fsm_entity_id, helper_entity_id, helper_id, helper_name


class TestFsmNames:
    """Идентификатор автомата собирается по правилу фабрики."""

    def test_fsm_id_is_device_template_priority(self) -> None:
        """`{прибор}_{шаблон}_{приоритет}` — ровно как у фабрики."""
        assert (
            fsm_entity_id("light.svet_nad_stolom", "lighting", 10)
            == "light.svet_nad_stolom_lighting_10"
        )

    def test_empty_template_falls_back(self) -> None:
        """Без шаблона имя не ломается."""
        assert fsm_entity_id("light.x", "", 10) == "light.x_fsm_10"


class TestHelperNames:
    """Помощник получает предсказуемое латинское имя и идентификатор."""

    def test_helper_id_is_ascii_slug(self) -> None:
        """Точки становятся подчёркиваниями, регистр — нижний."""
        assert (
            helper_id("light.svet_nad_stolom_lighting_10")
            == "fsm_light_svet_nad_stolom_lighting_10"
        )

    def test_helper_id_has_no_cyrillic_or_dots(self) -> None:
        """В идентификаторе только латиница, цифры и подчёркивание."""
        fsm_id = "switch.maslianyi_radiator_climate_control_10"
        entity = helper_entity_id(fsm_id)

        assert entity == "input_text.fsm_switch_maslianyi_radiator_climate_control_10"
        tail = entity.split(".", 1)[1]
        assert all(char.isascii() and (char.isalnum() or char == "_") for char in tail)

    def test_helper_name_is_the_same_fsm_id(self) -> None:
        """Имя — `fsm <идентификатор>`: по нему зеркало находит помощника."""
        fsm_id = "fan.base_smart_ventilation_modes_10"

        assert helper_name(fsm_id) == "fsm fan.base_smart_ventilation_modes_10"
        # Home Assistant собирает идентификатор из имени так же, как helper_id.
        assert helper_id(fsm_id) == "fsm_fan_base_smart_ventilation_modes_10"
