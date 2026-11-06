"""Стартовая сверка света запускается после подключения к HA (T058).

Проверяется проводка контейнера: adapter.start() не блокирует, поэтому сверка
ждёт события подключения, а не выполняется сразу после сборки.

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.container import Container


class _Watchdog:
    """Сторож-двойник: запоминает режим стартовой проверки."""

    def __init__(self) -> None:
        self.calls: list[bool] = []

    async def check_once(self, startup: bool = False) -> None:
        """Запомнить вызов."""
        self.calls.append(startup)


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
