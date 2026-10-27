"""Действия разложены по доменам, а фасад сохраняет прежний вход (B80).

До разреза все действия жили в одном ``core/action_handlers.py`` (1400 строк).
Проверка держит две вещи: обработчики действительно живут в доменных модулях
и старый импорт из фасада отдаёт те же самые функции.
"""

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from typing import Any

from core.action_handlers import ACTION_HANDLERS, register_all_actions, turn_on_light
from core.actions.lighting import turn_on_light as lighting_turn_on_light


class _Registry:
    """Реестр-двойник: запоминает регистрации."""

    def __init__(self) -> None:
        self.actions: dict[str, Any] = {}

    def register_action(self, name: str, handler: Any) -> None:
        """Запомнить действие."""
        self.actions[name] = handler


def test_handlers_live_in_domain_modules() -> None:
    """Все 31 действие разложены по доменным модулям."""
    modules = {handler.__module__ for handler in ACTION_HANDLERS.values()}

    assert len(ACTION_HANDLERS) == 32, f"реестр потерял действия: {sorted(ACTION_HANDLERS)}"
    assert modules == {
        "core.actions.common",
        "core.actions.lighting",
        "core.actions.climate",
        "core.actions.ventilation",
        "core.actions.covers",
    }, f"действия остались вне доменных модулей: {sorted(modules)}"


def test_facade_reexports_old_names() -> None:
    """Прежний импорт из `core.action_handlers` — та же функция."""
    assert turn_on_light is lighting_turn_on_light


def test_registration_registers_every_handler() -> None:
    """Регистрация по-прежнему ставит все действия в реестр."""
    registry = _Registry()

    register_all_actions(registry)

    assert set(registry.actions) == set(ACTION_HANDLERS)
