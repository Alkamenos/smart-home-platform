"""Circuit Breaker implementation for protecting Home Assistant from overload.

This module implements the Circuit Breaker pattern to prevent cascading failures
when Home Assistant becomes unresponsive or starts failing requests.

States:
- CLOSED: Normal operation, requests pass through
- OPEN: Too many failures, requests are blocked for a timeout period
- HALF-OPEN: Testing recovery with limited probe requests
"""

from __future__ import annotations

import asyncio
import time
from enum import Enum
from typing import TYPE_CHECKING, Any, Callable


if TYPE_CHECKING:
    from collections.abc import Awaitable

__all__ = [
    "CircuitBreaker",
    "CircuitBreakerState",
    "CircuitBreakerError",
    "CircuitBreakerConfig",
]


class CircuitBreakerState(Enum):
    """Circuit breaker states."""

    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitBreakerError(Exception):
    """Exception raised when circuit breaker is open."""

    def __init__(self, message: str = "Circuit breaker is open", state: CircuitBreakerState | None = None) -> None:
        """Initialize the exception.

        Args:
            message: Exception message.
            state: Current circuit breaker state.
        """
        super().__init__(message)
        self.state = state


class CircuitBreakerConfig:
    """Configuration for Circuit Breaker behavior."""

    def __init__(
        self,
        failure_threshold: int = 5,
        recovery_timeout_sec: float = 30.0,
        half_open_max_calls: int = 2,
    ) -> None:
        """Initialize circuit breaker configuration.

        Args:
            failure_threshold: Number of failures before opening circuit.
            recovery_timeout_sec: Time in seconds to wait before attempting recovery.
            half_open_max_calls: Maximum number of test calls in half-open state.
        """
        self.failure_threshold = failure_threshold
        self.recovery_timeout_sec = recovery_timeout_sec
        self.half_open_max_calls = half_open_max_calls


class CircuitBreaker:
    """Circuit Breaker implementation for fault tolerance.

    This class wraps async function calls and tracks failures. When the failure
    threshold is exceeded, the circuit opens and blocks further calls for a
    configured timeout period. After the timeout, it enters a half-open state
    where a limited number of test calls are allowed to check if the service
    has recovered.

    Attributes:
        name: Unique identifier for this circuit breaker.
        config: Configuration parameters.
        state: Current circuit breaker state.
        failure_count: Number of consecutive failures.
        success_count: Number of consecutive successes in half-open state.
        last_failure_time: Timestamp of the last failure.
        open_until: Timestamp when the circuit will transition to half-open.
    """

    def __init__(self, name: str, config: CircuitBreakerConfig | None = None) -> None:
        """Initialize the circuit breaker.

        Args:
            name: Unique identifier for this circuit breaker.
            config: Optional configuration. Uses defaults if not provided.
        """
        self.name: str = name
        self.config: CircuitBreakerConfig = config or CircuitBreakerConfig()
        self._state: CircuitBreakerState = CircuitBreakerState.CLOSED
        self._failure_count: int = 0
        self._success_count: int = 0
        self._half_open_calls: int = 0
        self._last_failure_time: float = 0.0
        self._open_until: float = 0.0
        self._lock: asyncio.Lock = asyncio.Lock()

        # Callbacks for state changes
        self._on_state_change_callbacks: list[Callable[[CircuitBreakerState], Awaitable[None]]] = []

    @property
    def state(self) -> CircuitBreakerState:
        """Get current circuit breaker state.

        Returns:
            Current state of the circuit breaker.
        """
        return self._state

    @property
    def failure_count(self) -> int:
        """Get current failure count.

        Returns:
            Number of consecutive failures.
        """
        return self._failure_count

    @property
    def is_closed(self) -> bool:
        """Check if circuit breaker is closed (normal operation).

        Returns:
            True if circuit is closed.
        """
        return self._state == CircuitBreakerState.CLOSED

    @property
    def is_open(self) -> bool:
        """Check if circuit breaker is open (blocking calls).

        Returns:
            True if circuit is open.
        """
        return self._state == CircuitBreakerState.OPEN

    @property
    def is_half_open(self) -> bool:
        """Check if circuit breaker is in half-open state (testing recovery).

        Returns:
            True if circuit is half-open.
        """
        return self._state == CircuitBreakerState.HALF_OPEN

    def on_state_change(self, callback: Callable[[CircuitBreakerState], Awaitable[None]]) -> None:
        """Register a callback for state change events.

        Args:
            callback: Async function to call when state changes.
        """
        self._on_state_change_callbacks.append(callback)

    async def _notify_state_change(self, new_state: CircuitBreakerState) -> None:
        """Notify all registered callbacks of a state change.

        Args:
            new_state: The new circuit breaker state.
        """
        for callback in self._on_state_change_callbacks:
            try:
                await callback(new_state)
            except Exception:
                pass  # Don't let callback errors affect circuit breaker

    async def _transition_to(self, new_state: CircuitBreakerState) -> None:
        """Transition to a new state.

        Args:
            new_state: The target state.
        """
        if self._state != new_state:
            old_state = self._state
            self._state = new_state
            await self._notify_state_change(new_state)

    def _should_attempt_reset(self) -> bool:
        """Check if enough time has passed to attempt reset.

        Returns:
            True if recovery timeout has elapsed.
        """
        if self._state != CircuitBreakerState.OPEN:
            return False
        return time.time() >= self._open_until

    async def call(self, func: Callable[..., Awaitable[Any]], *args: Any, **kwargs: Any) -> Any:
        """Execute a function through the circuit breaker.

        Args:
            func: Async function to execute.
            *args: Positional arguments for the function.
            **kwargs: Keyword arguments for the function.

        Returns:
            Result of the function call.

        Raises:
            CircuitBreakerError: If circuit is open and blocking calls.
            Exception: Any exception raised by the wrapped function.
        """
        async with self._lock:
            # Check if we should transition from OPEN to HALF-OPEN
            if self._state == CircuitBreakerState.OPEN:
                if self._should_attempt_reset():
                    await self._transition_to(CircuitBreakerState.HALF_OPEN)
                    self._half_open_calls = 0
                else:
                    raise CircuitBreakerError(
                        f"Circuit breaker '{self.name}' is OPEN",
                        state=self._state,
                    )

            # Check if we're in HALF-OPEN and have exceeded max calls
            if self._state == CircuitBreakerState.HALF_OPEN:
                if self._half_open_calls >= self.config.half_open_max_calls:
                    raise CircuitBreakerError(
                        f"Circuit breaker '{self.name}' HALF-OPEN call limit exceeded",
                        state=self._state,
                    )
                self._half_open_calls += 1

        # Execute the function
        try:
            result = await func(*args, **kwargs)
            await self._on_success()
            return result
        except Exception as e:
            await self._on_failure()
            raise

    async def _on_success(self) -> None:
        """Handle successful function call.

        Resets failure count and potentially transitions to CLOSED state.
        """
        async with self._lock:
            if self._state == CircuitBreakerState.HALF_OPEN:
                self._success_count += 1
                # If we've had enough successes, close the circuit
                if self._success_count >= self.config.half_open_max_calls:
                    await self._transition_to(CircuitBreakerState.CLOSED)
                    self._failure_count = 0
                    self._success_count = 0
            elif self._state == CircuitBreakerState.CLOSED:
                # Reset failure count on success in closed state
                self._failure_count = 0

    async def _on_failure(self) -> None:
        """Handle failed function call.

        Increments failure count and potentially transitions to OPEN state.
        """
        async with self._lock:
            self._failure_count += 1
            self._last_failure_time = time.time()

            if self._state == CircuitBreakerState.HALF_OPEN:
                # Any failure in half-open state opens the circuit again
                await self._transition_to(CircuitBreakerState.OPEN)
                self._open_until = time.time() + self.config.recovery_timeout_sec
                self._success_count = 0
            elif self._state == CircuitBreakerState.CLOSED:
                if self._failure_count >= self.config.failure_threshold:
                    await self._transition_to(CircuitBreakerState.OPEN)
                    self._open_until = time.time() + self.config.recovery_timeout_sec

    def record_success(self) -> None:
        """Manually record a success (for non-wrapped calls).

        This method is synchronous and doesn't use locks for simplicity.
        Use with caution in concurrent scenarios.
        """
        if self._state == CircuitBreakerState.HALF_OPEN:
            self._success_count += 1
            if self._success_count >= self.config.half_open_max_calls:
                self._state = CircuitBreakerState.CLOSED
                self._failure_count = 0
                self._success_count = 0
        elif self._state == CircuitBreakerState.CLOSED:
            self._failure_count = 0

    def record_failure(self) -> None:
        """Manually record a failure (for non-wrapped calls).

        This method is synchronous and doesn't use locks for simplicity.
        Use with caution in concurrent scenarios.
        """
        self._failure_count += 1
        self._last_failure_time = time.time()

        if self._state == CircuitBreakerState.HALF_OPEN:
            self._state = CircuitBreakerState.OPEN
            self._open_until = time.time() + self.config.recovery_timeout_sec
            self._success_count = 0
        elif self._state == CircuitBreakerState.CLOSED:
            if self._failure_count >= self.config.failure_threshold:
                self._state = CircuitBreakerState.OPEN
                self._open_until = time.time() + self.config.recovery_timeout_sec

    def get_stats(self) -> dict[str, Any]:
        """Get circuit breaker statistics.

        Returns:
            Dictionary with current statistics.
        """
        return {
            "name": self.name,
            "state": self._state.value,
            "failure_count": self._failure_count,
            "success_count": self._success_count,
            "half_open_calls": self._half_open_calls,
            "last_failure_time": self._last_failure_time,
            "open_until": self._open_until if self._state == CircuitBreakerState.OPEN else None,
        }

    def reset(self) -> None:
        """Reset the circuit breaker to initial state.

        This clears all counters and transitions to CLOSED state.
        """
        self._state = CircuitBreakerState.CLOSED
        self._failure_count = 0
        self._success_count = 0
        self._half_open_calls = 0
        self._last_failure_time = 0.0
        self._open_until = 0.0
