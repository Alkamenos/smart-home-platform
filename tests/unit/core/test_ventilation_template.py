"""Шаблон вентиляции: грузится, переходы существуют, таймер взводится.

Урок D8 из research.md спеки 014: опечатка в имени действия даёт
«работающую» автоматику, которая молчит — переходы проходят, ничего не
выполняя. Поэтому здесь шаблон проверяется целиком: он загружается фабрикой,
все имена условий и действий есть в реестрах, а таймер проветривания
взводится из параметра ``airing_seconds`` (FR-025).

Живые замеры 2026-10-12 (research.md D15): семь скоростей прибора
(проценты 14/29/43/57/71/86/100), MAX-режимы форсируют 100 сами, поэтому
проветривание скорость отдельной командой не задаёт.
"""

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from typing import Any

import pytest
import yaml

from core.action_handlers import ACTION_HANDLERS, register_all_actions
from core.definitions import YAMLFSMDefinition
from core.fsm.engine import FSMEngine
from core.fsm.factory import FSMFactory
from core.guards.builtin import build_guards, register_all_guards
from core.models.manifest import Manifest
from core.registry import Registry


def _template() -> dict[str, Any]:
    """Прочитать шаблон вентиляции.

    Returns:
        Словарь шаблона.
    """
    import pathlib

    return yaml.safe_load(
        pathlib.Path("src/features/ventilation_modes.yaml").read_text(encoding="utf-8")
    )


def _guards() -> dict[str, Any]:
    """Реестр условий.

    Returns:
        Словарь «имя → функция».
    """
    return build_guards(control_tracker=None)


def _factory() -> FSMFactory:
    """Фабрика с зарегистрированными условиями и действиями.

    Returns:
        Готовая фабрика.
    """
    registry = Registry()
    register_all_guards(registry, None)
    register_all_actions(registry)
    return FSMFactory(engine=FSMEngine(), registry=registry, event_bus=None)


class TestTemplateLoads:
    """Шаблон существует и грузится целиком."""

    def test_all_guards_are_registered(self) -> None:
        """Каждое имя условия шаблона есть в реестре условий.

        Returns:
            Ничего.
        """
        guards = _guards()
        for transition in _template()["transitions"]:
            name = transition.get("guard")
            assert not name or name in guards, (
                f"условие {name!r} отсутствует в реестре: переход будет "
                "отказывать, а автоматика — молчать (урок D8)"
            )

    def test_all_actions_are_registered(self) -> None:
        """Каждое имя действия шаблона есть в реестре действий.

        Returns:
            Ничего.
        """
        for transition in _template()["transitions"]:
            name = transition.get("action")
            assert not name or name in ACTION_HANDLERS, (
                f"действие {name!r} отсутствует в реестре: переход проходит "
                "как успешный, ничего не выполняя (урок D8)"
            )

    def test_definition_parses(self) -> None:
        """Шаблон разбирается моделью определения (entity_id добавит фабрика).

        Returns:
            Ничего.
        """
        YAMLFSMDefinition.model_validate({**_template(), "entity_id": "fan.base_smart_10"})


class TestAiringTimeout:
    """Таймер проветривания берётся из параметра поведения (FR-025)."""

    @pytest.mark.asyncio
    async def test_airing_seconds_overrides_default(self) -> None:
        """``airing_seconds`` из манифеста переопределяет ``timeout_sec``.

        Returns:
            Ничего.
        """
        factory = _factory()
        definitions = factory.create_from_manifest(
            Manifest.model_validate(
                {
                    "instance": {"id": "test", "name": "Тестовый дом"},
                    "rooms": [
                        {
                            "id": "kabinet",
                            "name": "Кабинет",
                            "devices": [
                                {
                                    "id": "fan.base_smart",
                                    "type": "fan",
                                    "behaviors": [
                                        {
                                            "template": "ventilation_modes",
                                            "priority": 10,
                                            "params": {"airing_seconds": 1800},
                                        }
                                    ],
                                }
                            ],
                        }
                    ],
                }
            )
        )

        transitions = [t for d in definitions for t in d.transitions]
        airing = [t for t in transitions if t.trigger == "timeout" and t.from_state == "AIRING"]
        assert airing, "перехода AIRING → выход по таймеру нет: проветривание не гаснет"
        assert airing[0].timeout_sec == 1800.0, (
            f"таймер проветривания {airing[0].timeout_sec!r} вместо 1800 из "
            "airing_seconds: проветривание будет длиться час вместо получаса"
        )

    @pytest.mark.asyncio
    async def test_default_timeout_when_no_param(self) -> None:
        """Без параметра — значение шаблона (3600 с).

        Returns:
            Ничего.
        """
        factory = _factory()
        definitions = factory.create_from_manifest(
            Manifest.model_validate(
                {
                    "instance": {"id": "test", "name": "Тестовый дом"},
                    "rooms": [
                        {
                            "id": "kabinet",
                            "name": "Кабинет",
                            "devices": [
                                {
                                    "id": "fan.base_smart",
                                    "type": "fan",
                                    "behaviors": [
                                        {"template": "ventilation_modes", "priority": 10}
                                    ],
                                }
                            ],
                        }
                    ],
                }
            )
        )

        transitions = [t for d in definitions for t in d.transitions]
        airing = [t for t in transitions if t.trigger == "timeout"]
        assert airing
        assert airing[0].timeout_sec == 3600.0
