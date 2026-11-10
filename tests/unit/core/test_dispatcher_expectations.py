"""Диспетчер запоминает ожидание после реально отправленной команды."""

from __future__ import annotations

from typing import Any

import pytest

from core.commands.dispatcher import CommandDispatcher, CommandIntent
from core.commands.expectations import CommandExpectationTracker


class _Adapter:
    """Адаптер-двойник: команда доставлена."""

    async def call_service(self, **_kwargs: Any) -> bool:
        """Подтвердить вызов.

        Args:
            _kwargs: Параметры сервиса.

        Returns:
            True.
        """
        return True


@pytest.mark.asyncio
async def test_dispatcher_records_state_command() -> None:
    """Успешный turn_on оставляет ожидание on."""
    tracker = CommandExpectationTracker()
    dispatcher = CommandDispatcher(
        ha_adapter=_Adapter(),  # type: ignore[arg-type]
        expectations=tracker,
    )

    sent = await dispatcher.submit(
        CommandIntent(
            device_id="light.probe",
            domain="light",
            service="turn_on",
            data={},
            priority=10,
            source="test",
        )
    )

    assert sent is True
    pending = tracker.pending()
    assert len(pending) == 1
    assert pending[0].expected_state == "on"


@pytest.mark.asyncio
async def test_dispatcher_does_not_record_timer_command() -> None:
    """number.set_value не создаёт ожидания состояния."""
    tracker = CommandExpectationTracker()
    dispatcher = CommandDispatcher(
        ha_adapter=_Adapter(),  # type: ignore[arg-type]
        expectations=tracker,
    )

    await dispatcher.submit(
        CommandIntent(
            device_id="number.timer",
            domain="number",
            service="set_value",
            data={"value": 0},
            priority=10,
            source="test",
        )
    )

    assert tracker.pending() == ()
