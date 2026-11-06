"""Стартовая сверка света запускается после подключения к HA (T058).

Проверяется проводка контейнера: adapter.start() не блокирует, поэтому сверка
ждёт события подключения, а не выполняется сразу после сборки.

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from app.container import Container


class _Watchdog:
    """Сторож-двойник: запоминает режим стартовой проверки."""

    def __init__(self) -> None:
        self.calls: list[bool] = []

    async def check_once(self, startup: bool = False) -> None:
        """Запомнить вызов."""
        self.calls.append(startup)


class _Dispatcher:
    """Диспетчер-двойник: запоминает намерения."""

    def __init__(self) -> None:
        self.intents: list[Any] = []

    async def submit(self, intent: Any) -> bool:
        """Запомнить намерение и подтвердить доставку."""
        self.intents.append(intent)
        return True


@pytest.mark.asyncio
async def test_startup_cleanup_runs_once_after_ha_connected() -> None:
    """Первое подключение запускает стартовую сверку ровно один раз."""
    container = object.__new__(Container)
    container._startup_light_cleanup_done = False  # noqa: SLF001
    container._adapter = SimpleNamespace(is_connected=True)  # noqa: SLF001
    watchdog = _Watchdog()
    container._watchdog = watchdog  # type: ignore[assignment]  # noqa: SLF001

    await container._on_ha_connected("ha.connected", {})  # noqa: SLF001
    await container._on_ha_connected("ha.connected", {})  # noqa: SLF001

    assert watchdog.calls == [True], "стартовая сверка должна пройти один раз"


@pytest.mark.asyncio
async def test_startup_cleanup_waits_for_connection() -> None:
    """Пока связи нет, сверка не выполняется и не помечается сделанной."""
    container = object.__new__(Container)
    container._startup_light_cleanup_done = False  # noqa: SLF001
    container._adapter = SimpleNamespace(is_connected=False)  # noqa: SLF001
    watchdog = _Watchdog()
    container._watchdog = watchdog  # type: ignore[assignment]  # noqa: SLF001

    await container._reconcile_startup_lights()  # noqa: SLF001

    assert watchdog.calls == []
    assert container._startup_light_cleanup_done is False  # noqa: SLF001


@pytest.mark.asyncio
async def test_startup_light_off_bypasses_lockout() -> None:
    """Стартовое выключение идёт через диспетчер с обходом блокировки."""
    container = object.__new__(Container)
    dispatcher = _Dispatcher()
    container._dispatcher = dispatcher  # type: ignore[assignment]  # noqa: SLF001

    await container._turn_off_startup_light("light.stol")  # noqa: SLF001

    assert len(dispatcher.intents) == 1
    intent = dispatcher.intents[0]
    assert intent.device_id == "light.stol"
    assert intent.domain == "light"
    assert intent.service == "turn_off"
    assert intent.bypass_lockout is True
    assert intent.source == "startup_cleanup"
