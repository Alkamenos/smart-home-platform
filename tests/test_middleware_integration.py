"""
Integration tests for Middleware in CommandDispatcher.

Tests cover:
1. Middleware chain is executed before priority checks.
2. If middleware returns None, command is blocked.
3. If middleware returns modified intent, the modified intent is used.
4. add_middleware method allows adding middleware after creation.
"""

import pytest

from smart_home.adapters.mock_adapter import MockAdapter
from smart_home.core.command_dispatcher import CommandDispatcher, CommandIntent


class BlockingMiddleware:
    """Middleware that blocks all commands."""

    async def process(self, intent: CommandIntent):
        return None


class PassThroughMiddleware:
    """Middleware that passes commands through unchanged."""

    async def process(self, intent: CommandIntent):
        return intent


class ModifyPriorityMiddleware:
    """Middleware that modifies the priority of intents."""

    def __init__(self, new_priority: int):
        self._new_priority = new_priority

    async def process(self, intent: CommandIntent):
        # Create a modified intent with new priority
        return CommandIntent(
            device_id=intent.device_id,
            domain=intent.domain,
            service=intent.service,
            data=intent.data,
            priority=self._new_priority,
            source=intent.source,
        )


@pytest.mark.asyncio
async def test_middleware_blocks_command():
    """
    Test that if middleware returns None, the command is blocked.

    Scenario:
    1. Create dispatcher with BlockingMiddleware
    2. Submit a command
    3. Assert: Command is blocked (submit returns False)
    4. Assert: No active intents
    5. Assert: HA adapter was not called
    """
    mock_adapter = MockAdapter()
    blocking_middleware = BlockingMiddleware()

    dispatcher = CommandDispatcher(ha_adapter=mock_adapter, middlewares=[blocking_middleware])

    intent = CommandIntent(
        device_id="light.kitchen",
        domain="light",
        service="turn_on",
        data={"brightness": 255},
        priority=10,
        source="test_middleware",
    )

    result = await dispatcher.submit(intent)

    # Command should be blocked
    assert result is False, "Command should be blocked by middleware"

    # No active intents
    assert (
        "light.kitchen" not in dispatcher.active_intents
    ), "No active intent should exist after blocking"

    # HA adapter should not be called
    assert (
        len(mock_adapter.get_service_calls("light", "turn_on")) == 0
    ), "HA adapter should not be called when middleware blocks command"


@pytest.mark.asyncio
async def test_middleware_chain_allows_command():
    """
    Test that if all middleware pass through, command is accepted.

    Scenario:
    1. Create dispatcher with PassThroughMiddleware
    2. Submit a command
    3. Assert: Command is accepted (submit returns True)
    4. Assert: Active intent exists
    5. Assert: HA adapter was called
    """
    mock_adapter = MockAdapter()
    pass_through = PassThroughMiddleware()

    dispatcher = CommandDispatcher(ha_adapter=mock_adapter, middlewares=[pass_through])

    intent = CommandIntent(
        device_id="light.kitchen",
        domain="light",
        service="turn_on",
        data={"brightness": 255},
        priority=10,
        source="test_middleware",
    )

    result = await dispatcher.submit(intent)

    # Command should be accepted
    assert result is True, "Command should be accepted"

    # Active intent exists
    assert "light.kitchen" in dispatcher.active_intents, "Active intent should exist"

    # HA adapter was called
    calls = mock_adapter.get_service_calls("light", "turn_on")
    assert len(calls) == 1, "HA adapter should be called once"


@pytest.mark.asyncio
async def test_middleware_modifies_intent():
    """
    Test that if middleware returns modified intent, the modified version is used.

    Scenario:
    1. Create dispatcher with ModifyPriorityMiddleware(new_priority=50)
    2. Submit a command with priority=10
    3. Assert: Command is accepted with priority=50
    4. Assert: Active intent has priority=50
    """
    mock_adapter = MockAdapter()
    modify_middleware = ModifyPriorityMiddleware(new_priority=50)

    dispatcher = CommandDispatcher(ha_adapter=mock_adapter, middlewares=[modify_middleware])

    intent = CommandIntent(
        device_id="light.kitchen",
        domain="light",
        service="turn_on",
        data={"brightness": 255},
        priority=10,
        source="test_middleware",
    )

    result = await dispatcher.submit(intent)

    # Command should be accepted
    assert result is True, "Command should be accepted"

    # Active intent should have modified priority
    assert "light.kitchen" in dispatcher.active_intents
    active_intent = dispatcher.active_intents["light.kitchen"]
    assert (
        active_intent.priority == 50
    ), f"Expected priority=50 after middleware modification, got {active_intent.priority}"


@pytest.mark.asyncio
async def test_multiple_middleware_chain():
    """
    Test that multiple middleware are executed in order.

    Scenario:
    1. Create dispatcher with [PassThrough, ModifyPriority(50)]
    2. Submit a command with priority=10
    3. Assert: Command is accepted with priority=50
    """
    mock_adapter = MockAdapter()
    pass_through = PassThroughMiddleware()
    modify_middleware = ModifyPriorityMiddleware(new_priority=50)

    dispatcher = CommandDispatcher(
        ha_adapter=mock_adapter, middlewares=[pass_through, modify_middleware]
    )

    intent = CommandIntent(
        device_id="light.kitchen",
        domain="light",
        service="turn_on",
        data={"brightness": 255},
        priority=10,
        source="test_middleware",
    )

    result = await dispatcher.submit(intent)

    # Command should be accepted
    assert result is True

    # Active intent should have modified priority
    active_intent = dispatcher.active_intents["light.kitchen"]
    assert active_intent.priority == 50


@pytest.mark.asyncio
async def test_add_middleware_after_creation():
    """
    Test that add_middleware method allows adding middleware after creation.

    Scenario:
    1. Create dispatcher with empty middleware list
    2. Submit a command - should succeed
    3. Add BlockingMiddleware via add_middleware
    4. Submit another command - should be blocked
    """
    mock_adapter = MockAdapter()

    # Create dispatcher with no middleware
    dispatcher = CommandDispatcher(ha_adapter=mock_adapter, middlewares=[])

    intent = CommandIntent(
        device_id="light.kitchen",
        domain="light",
        service="turn_on",
        data={"brightness": 255},
        priority=10,
        source="test_middleware",
    )

    # First command should succeed
    result1 = await dispatcher.submit(intent)
    assert result1 is True, "First command should succeed without middleware"

    # Add blocking middleware
    blocking_middleware = BlockingMiddleware()
    dispatcher.add_middleware(blocking_middleware)

    # Second command should be blocked
    intent2 = CommandIntent(
        device_id="light.bedroom",
        domain="light",
        service="turn_on",
        data={"brightness": 255},
        priority=10,
        source="test_middleware",
    )

    result2 = await dispatcher.submit(intent2)
    assert result2 is False, "Second command should be blocked by added middleware"


@pytest.mark.asyncio
async def test_middleware_before_priority_check():
    """
    Test that middleware is executed BEFORE priority check.

    Scenario:
    1. Create dispatcher with BlockingMiddleware
    2. Submit high-priority command first
    3. Submit low-priority command - should be blocked by middleware, not priority
    4. Assert: Low-priority command blocked even though it would fail priority anyway
    """
    mock_adapter = MockAdapter()
    blocking_middleware = BlockingMiddleware()

    dispatcher = CommandDispatcher(ha_adapter=mock_adapter, middlewares=[blocking_middleware])

    # High priority command
    high_priority = CommandIntent(
        device_id="light.kitchen",
        domain="light",
        service="turn_on",
        data={"brightness": 255},
        priority=50,
        source="high_priority_source",
    )

    # Low priority command
    low_priority = CommandIntent(
        device_id="light.kitchen",
        domain="light",
        service="turn_off",
        data={},
        priority=10,
        source="low_priority_source",
    )

    # Both should be blocked by middleware (before priority check)
    result1 = await dispatcher.submit(high_priority)
    result2 = await dispatcher.submit(low_priority)

    assert result1 is False, "High priority command should be blocked by middleware"
    assert result2 is False, "Low priority command should be blocked by middleware"
    assert len(dispatcher.active_intents) == 0, "No intents should be active"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
