"""Ручное действие из Home Assistant доходит до автомата (спека 017, B57).

Регресс: изменение состояния, сделанное человеком, фиксировалось трекером (и
давало блокировку оверрайда), но **событие автомату не отправлялось** — ручное
состояние умел только UI-путь. Поэтому включённая руками гирлянда не возвращалась
к автоматике. Тест держит доставку `manual_switch_on`/`manual_switch_off`.

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from adapters.ha_adapter import HAAdapter
from core.events.event_bus import EventBus
from core.events.fsm_events import EVENT_HA_CONNECTED


class _Engine:
    """Движок-двойник: один автомат у устройства, запоминает триггеры."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict[str, Any]]] = []

    def get_entities_by_device(self, device_id: str) -> list[str]:
        """Автоматы устройства."""
        return ["light.girlianda_terassa_deco_light_10"]

    async def trigger(
        self, entity_id: str, event: str, context: dict[str, Any] | None = None, **kwargs: Any
    ) -> bool:
        """Запомнить вызов."""
        self.calls.append((entity_id, event, dict(context or {})))
        return True


class _Middleware:
    """Трекер-двойник: помнит ручные записи."""

    def __init__(self) -> None:
        self.recorded: list[str] = []

    def record_manual_control(self, entity_id: str) -> None:
        """Запомнить ручное управление."""
        self.recorded.append(entity_id)


def _adapter(engine: _Engine, middleware: _Middleware) -> HAAdapter:
    """Адаптер в режиме websocket с подменёнными движком и трекером.

    Args:
        engine: Движок-двойник.
        middleware: Трекер-двойник.

    Returns:
        Адаптер.
    """
    return HAAdapter(
        mode="websocket",
        ws_url="ws://ha.invalid/api/websocket",
        token="test-token-длинный",
        engine=engine,  # type: ignore[arg-type]
        manual_lockout_middleware=middleware,  # type: ignore[arg-type]
    )


@pytest.mark.asyncio
async def test_connection_event_is_published_after_connect() -> None:
    """Подключение (в том числе после обрыва) объявляется шине (B62)."""
    bus = EventBus()
    seen: list[dict[str, Any]] = []

    async def collector(event_type: str, payload: dict[str, Any], trace_id: str = "") -> None:
        """Запомнить событие."""
        seen.append(dict(payload))

    bus.subscribe(EVENT_HA_CONNECTED, collector)
    adapter = _adapter(_Engine(), _Middleware())
    adapter._engine = SimpleNamespace(event_bus=bus)  # noqa: SLF001

    await adapter._publish_connection_established()  # noqa: SLF001

    assert seen, "подключение не объявлено шине"


@pytest.mark.asyncio
async def test_manual_change_from_ha_reaches_fsm() -> None:
    """Изменение, сделанное человеком, уходит автомату как `manual_switch_on`."""
    engine = _Engine()
    middleware = _Middleware()

    await _adapter(engine, middleware).on_state_change(
        "light.girlianda_terassa", "on", "off", {"user_id": "leonid"}
    )

    assert middleware.recorded == ["light.girlianda_terassa"]
    assert [call[1] for call in engine.calls] == ["manual_switch_on"]


@pytest.mark.asyncio
async def test_manual_off_from_ha_reaches_fsm() -> None:
    """Выключение человеком уходит автомату как `manual_switch_off`."""
    engine = _Engine()

    await _adapter(engine, _Middleware()).on_state_change(
        "light.girlianda_terassa", "off", "on", {"user_id": "leonid"}
    )

    assert [call[1] for call in engine.calls] == ["manual_switch_off"]


@pytest.mark.asyncio
async def test_change_without_user_is_not_manual() -> None:
    """Изменение без пользователя (автоматика/платформа) автомат не будит."""
    engine = _Engine()

    await _adapter(engine, _Middleware()).on_state_change(
        "light.girlianda_terassa", "on", "off", {}
    )

    assert engine.calls == []


@pytest.mark.asyncio
async def test_unknown_state_does_not_wake_fsm() -> None:
    """Значение вне «включено/выключено» ручным событием не считается."""
    engine = _Engine()

    await _adapter(engine, _Middleware()).on_state_change(
        "sensor.some_temperature", "22.4", "22.0", {"user_id": "leonid"}
    )

    assert engine.calls == []
