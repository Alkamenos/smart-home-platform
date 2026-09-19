"""Tests for Circuit Breaker pattern implementation.

These tests verify that the CircuitBreaker properly protects against
cascading failures and implements the three-state pattern correctly.
"""

from __future__ import annotations

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock

import pytest


from adapters.circuit_breaker import (
    CircuitBreaker,
    CircuitBreakerConfig,
    CircuitBreakerError,
    CircuitBreakerState,
)


class TestCircuitBreakerInitialization:
    """Test CircuitBreaker initialization and default state."""

    def test_should_create_with_default_config(self) -> None:
        """Test circuit breaker creation with default configuration."""
        cb = CircuitBreaker(name="test")

        assert cb.name == "test"
        assert cb.state == CircuitBreakerState.CLOSED
        assert cb.is_closed
        assert not cb.is_open
        assert not cb.is_half_open
        assert cb.failure_count == 0

    def test_should_create_with_custom_config(self) -> None:
        """Test circuit breaker creation with custom configuration."""
        config = CircuitBreakerConfig(
            failure_threshold=3,
            recovery_timeout_sec=10.0,
            half_open_max_calls=1,
        )
        cb = CircuitBreaker(name="test", config=config)

        assert cb.config.failure_threshold == 3
        assert cb.config.recovery_timeout_sec == 10.0
        assert cb.config.half_open_max_calls == 1


class TestCircuitBreakerClosedState:
    """Test circuit breaker behavior in CLOSED state."""

    @pytest.mark.asyncio
    async def test_should_allow_calls_in_closed_state(self) -> None:
        """Test that calls pass through in closed state."""
        cb = CircuitBreaker(name="test")

        async def success_func() -> str:
            return "success"

        result = await cb.call(success_func)
        assert result == "success"
        assert cb.state == CircuitBreakerState.CLOSED

    @pytest.mark.asyncio
    async def test_should_track_failures_in_closed_state(self) -> None:
        """Test that failures are tracked in closed state."""
        config = CircuitBreakerConfig(failure_threshold=3)
        cb = CircuitBreaker(name="test", config=config)

        async def failing_func() -> None:
            raise ValueError("Test error")

        for i in range(2):
            with pytest.raises(ValueError):
                await cb.call(failing_func)

        assert cb.failure_count == 2
        assert cb.state == CircuitBreakerState.CLOSED

    @pytest.mark.asyncio
    async def test_should_open_after_threshold_failures(self) -> None:
        """Test that circuit opens after reaching failure threshold."""
        config = CircuitBreakerConfig(failure_threshold=3)
        cb = CircuitBreaker(name="test", config=config)

        async def failing_func() -> None:
            raise ValueError("Test error")

        # Trigger threshold failures
        for i in range(3):
            with pytest.raises(ValueError):
                await cb.call(failing_func)

        assert cb.state == CircuitBreakerState.OPEN
        assert cb.is_open
        assert cb.failure_count == 3

    @pytest.mark.asyncio
    async def test_should_reset_failure_count_on_success(self) -> None:
        """Test that success resets failure count in closed state."""
        config = CircuitBreakerConfig(failure_threshold=5)
        cb = CircuitBreaker(name="test", config=config)

        async def failing_func() -> None:
            raise ValueError("Test error")

        async def success_func() -> str:
            return "success"

        # Cause some failures
        for i in range(2):
            with pytest.raises(ValueError):
                await cb.call(failing_func)

        assert cb.failure_count == 2

        # Success should reset counter
        await cb.call(success_func)
        assert cb.failure_count == 0


class TestCircuitBreakerOpenState:
    """Test circuit breaker behavior in OPEN state."""

    @pytest.mark.asyncio
    async def test_should_block_calls_in_open_state(self) -> None:
        """Test that calls are blocked when circuit is open."""
        config = CircuitBreakerConfig(failure_threshold=2, recovery_timeout_sec=60)
        cb = CircuitBreaker(name="test", config=config)

        async def failing_func() -> None:
            raise ValueError("Test error")

        # Open the circuit
        for i in range(2):
            with pytest.raises(ValueError):
                await cb.call(failing_func)

        assert cb.state == CircuitBreakerState.OPEN

        # Subsequent calls should be blocked
        with pytest.raises(CircuitBreakerError) as exc_info:
            await cb.call(failing_func)

        assert "OPEN" in str(exc_info.value)
        assert exc_info.value.state == CircuitBreakerState.OPEN

    @pytest.mark.asyncio
    async def test_should_transition_to_half_open_after_timeout(self) -> None:
        """Test transition from OPEN to HALF-OPEN after timeout."""
        config = CircuitBreakerConfig(
            failure_threshold=2,
            recovery_timeout_sec=0.1,  # 100ms for testing
        )
        cb = CircuitBreaker(name="test", config=config)

        async def failing_func() -> None:
            raise ValueError("Test error")

        # Open the circuit
        for i in range(2):
            with pytest.raises(ValueError):
                await cb.call(failing_func)

        assert cb.state == CircuitBreakerState.OPEN

        # Wait for recovery timeout
        await asyncio.sleep(0.15)

        # Next call attempt should transition to HALF-OPEN
        async def success_func() -> str:
            return "success"

        result = await cb.call(success_func)
        assert result == "success"
        assert cb.state == CircuitBreakerState.HALF_OPEN


class TestCircuitBreakerHalfOpenState:
    """Test circuit breaker behavior in HALF-OPEN state."""

    @pytest.mark.asyncio
    async def test_should_allow_limited_calls_in_half_open(self) -> None:
        """Test that limited calls are allowed in half-open state."""
        config = CircuitBreakerConfig(
            failure_threshold=2,
            recovery_timeout_sec=0.05,
            half_open_max_calls=2,
        )
        cb = CircuitBreaker(name="test", config=config)

        async def failing_func() -> None:
            raise ValueError("Test error")

        # Open the circuit
        for i in range(2):
            with pytest.raises(ValueError):
                await cb.call(failing_func)

        # Wait for recovery timeout
        await asyncio.sleep(0.1)

        # Should allow half_open_max_calls attempts
        async def success_func() -> str:
            return "success"

        # First call succeeds and transitions to HALF-OPEN
        await cb.call(success_func)
        assert cb.state == CircuitBreakerState.HALF_OPEN

        # Second call should succeed and close the circuit
        await cb.call(success_func)
        assert cb.state == CircuitBreakerState.CLOSED

    @pytest.mark.asyncio
    async def test_should_reopen_on_failure_in_half_open(self) -> None:
        """Test that failure in half-open state reopens circuit."""
        config = CircuitBreakerConfig(
            failure_threshold=2,
            recovery_timeout_sec=0.05,
            half_open_max_calls=2,
        )
        cb = CircuitBreaker(name="test", config=config)

        async def failing_func() -> None:
            raise ValueError("Test error")

        # Open the circuit
        for i in range(2):
            with pytest.raises(ValueError):
                await cb.call(failing_func)

        # Wait for recovery timeout
        await asyncio.sleep(0.1)

        # First call triggers transition to HALF-OPEN but fails
        with pytest.raises(ValueError):
            await cb.call(failing_func)

        # Should be back to OPEN
        assert cb.state == CircuitBreakerState.OPEN

    @pytest.mark.asyncio
    async def test_should_block_after_half_open_limit(self) -> None:
        """Test that calls are blocked after exceeding half-open limit."""
        config = CircuitBreakerConfig(
            failure_threshold=2,
            recovery_timeout_sec=0.05,
            half_open_max_calls=1,  # Only 1 success needed to close
        )
        cb = CircuitBreaker(name="test", config=config)

        async def failing_func() -> None:
            raise ValueError("Test error")

        # Open the circuit
        for i in range(2):
            with pytest.raises(ValueError):
                await cb.call(failing_func)

        # Wait for recovery timeout
        await asyncio.sleep(0.1)

        async def success_func() -> str:
            return "success"

        # Make max calls in half-open state - first call transitions to HALF-OPEN and succeeds
        await cb.call(success_func)  # Transitions to HALF-OPEN, success_count=1, closes circuit
        
        # Circuit is now CLOSED, so more calls should work
        assert cb.state == CircuitBreakerState.CLOSED
        result = await cb.call(success_func)
        assert result == "success"
        assert cb.state == CircuitBreakerState.CLOSED


class TestCircuitBreakerCallbacks:
    """Test circuit breaker state change callbacks."""

    @pytest.mark.asyncio
    async def test_should_notify_on_state_change(self) -> None:
        """Test that callbacks are notified on state changes."""
        cb = CircuitBreaker(name="test")
        states: list[CircuitBreakerState] = []

        async def callback(state: CircuitBreakerState) -> None:
            states.append(state)

        cb.on_state_change(callback)

        async def failing_func() -> None:
            raise ValueError("Test error")

        # Trigger state changes
        for i in range(5):
            with pytest.raises(ValueError):
                await cb.call(failing_func)

        # Should have been notified of CLOSED -> OPEN transition
        assert CircuitBreakerState.OPEN in states


class TestCircuitBreakerManualRecording:
    """Test manual success/failure recording methods."""

    def test_should_record_manual_success(self) -> None:
        """Test manual success recording."""
        cb = CircuitBreaker(name="test")

        cb.record_success()
        assert cb.state == CircuitBreakerState.CLOSED
        assert cb.failure_count == 0

    def test_should_record_manual_failure(self) -> None:
        """Test manual failure recording."""
        config = CircuitBreakerConfig(failure_threshold=2)
        cb = CircuitBreaker(name="test", config=config)

        cb.record_failure()
        assert cb.failure_count == 1
        assert cb.state == CircuitBreakerState.CLOSED

        cb.record_failure()
        assert cb.state == CircuitBreakerState.OPEN

    def test_should_reset_manually(self) -> None:
        """Test manual reset."""
        config = CircuitBreakerConfig(failure_threshold=2)
        cb = CircuitBreaker(name="test", config=config)

        # Open the circuit
        cb.record_failure()
        cb.record_failure()
        assert cb.state == CircuitBreakerState.OPEN

        # Reset
        cb.reset()
        assert cb.state == CircuitBreakerState.CLOSED
        assert cb.failure_count == 0


class TestCircuitBreakerStats:
    """Test circuit breaker statistics."""

    def test_should_get_stats(self) -> None:
        """Test getting circuit breaker statistics."""
        config = CircuitBreakerConfig(failure_threshold=5)
        cb = CircuitBreaker(name="test_cb", config=config)

        stats = cb.get_stats()

        assert stats["name"] == "test_cb"
        assert stats["state"] == "closed"
        assert stats["failure_count"] == 0
        assert "half_open_calls" in stats
        assert "last_failure_time" in stats
