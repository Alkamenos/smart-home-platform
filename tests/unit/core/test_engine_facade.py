"""Публичные фасады после разделения модулей (спека 018, US4, T053).

Внутреннее устройство может меняться, но точки входа, которыми пользуются
приложение и тесты, должны оставаться на месте.

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0
"""

from __future__ import annotations

from adapters.ha_adapter import HAAdapter
from app.container import Container
from app.context import PlatformContext
from core.fsm.engine import FSMEngine


def test_engine_facade_is_intact() -> None:
    """Движок сохраняет публичные методы управления."""
    for name in (
        "trigger",
        "get_state",
        "get_all_states",
        "explain",
        "register_definition",
        "shutdown",
    ):
        assert callable(getattr(FSMEngine, name, None)), f"FSMEngine.{name} пропал"


def test_container_facade_is_intact() -> None:
    """Composition root собирает платформу и возвращает контекст."""
    assert callable(getattr(Container, "build", None))
    assert callable(getattr(Container, "announce_started", None))


def test_platform_context_has_shutdown() -> None:
    """Контекст платформы умеет корректно останавливаться."""
    assert callable(getattr(PlatformContext, "shutdown", None))


def test_adapter_dashboard_facade_is_intact() -> None:
    """У адаптера остаются методы панелей, вынесенные в отдельный модуль."""
    for name in (
        "find_dashboard",
        "create_dashboard",
        "save_dashboard_config",
        "get_dashboard_entities",
    ):
        assert callable(getattr(HAAdapter, name, None)), f"HAAdapter.{name} пропал"
