"""Circuit Breaker pattern implementation for service call protection.

This module provides a Circuit Breaker implementation to protect Home Assistant
from overload during failures. The circuit breaker has three states:
- CLOSED: Normal operation, requests pass through
- OPEN: Too many errors, requests are blocked for a timeout period
- HALF-OPEN: Testing if service has recovered with limited requests
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, TypeVar

from loguru import logger

T = TypeVar("T")


class CircuitState(Enum):
    """Circuit breaker states."""

    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


@dataclass
class CircuitBreakerConfig:
    """Configuration for Circuit Breaker.

    Attributes:
        failure_threshold: Number of failures before opening circuit.
        recovery_timeout_sec: Seconds to wait before trying again (OPEN -> HALF-OPEN).
        half_open_max_calls: Max calls allowed in HALF-OPEN state before deciding.
        success_threshold: Number of successes in HALF-OPEN to close circuit.
    """

    failure_threshold: int = 5
    recovery_timeout_sec: float = 30.0
    half_open_max_calls: int = 2
    success_threshold: int = 2


@dataclass
class CircuitBreakerStats:
    """Statistics for Circuit Breaker.

    Attributes:
        total_calls: Total number of calls attempted.
        successful_calls: Number of successful calls.
        failed_calls: Number of failed calls.
        rejected_calls: Number of calls rejected due to open circuit.
        state_changes: Number of state transitions.
        last_failure_time: Timestamp of last failure.
        last_success_time: Timestamp of last success.
        last_state_change_time: Timestamp of last state change.
    """

    total_calls: int = 0
    successful_calls: int = 0
    failed_calls: int = 0
    rejected_calls: int = 0
    state_changes: int = 0
    last_failure_time: float | None = None
    last_success_time: float | None = None
    last_state_change_time: float = field(default_factory=time.time)


class CircuitBreakerError(Exception):
    """Exception raised when circuit breaker is open."""

    pass


class CircuitBreaker:
    """Circuit Breaker implementation for protecting service calls.

    The circuit breaker monitors calls to a service and prevents further calls
    when the failure rate exceeds a threshold. This protects the system from
    cascading failures and gives the service time to recover.

    Example:
        >>> config = CircuitBreakerConfig(failure_threshold=3, recovery_timeout_sec=10)
        >>> breaker = CircuitBreaker(name="ha_service", config=config)
        >>> @breaker.call
        ... def make_request():
        ...     return some_service.call()
    """

    def __init__(
        self,
        name: str,
        config: CircuitBreakerConfig | None = None,
    ) -> None:
        """Initialize Circuit Breaker.

        Args:
            name: Name identifier for this circuit breaker (for logging/metrics).
            config: Configuration parameters. Uses defaults if not provided.
        """
        self._name = name
        self._config = config or CircuitBreakerConfig()
        self._state = CircuitState.CLOSED
        self._stats = CircuitBreakerStats()
        self._failure_count = 0
        self._success_count = 0
        self._half_open_calls = 0
        self._opened_at: float | None = None

        logger.info(
            f"CircuitBreaker '{name}' initialized with config: "
            f"failure_threshold={self._config.failure_threshold}, "
            f"recovery_timeout={self._config.recovery_timeout_sec}s"
        )

    @property
    def name(self) -> str:
        """Get circuit breaker name."""
        return self._name

    @property
    def state(self) -> CircuitState:
        """Get current circuit state, checking for timeout transition."""
        if self._state == CircuitState.OPEN and self._opened_at is not None:
            elapsed = time.time() - self._opened_at
            if elapsed >= self._config.recovery_timeout_sec:
                self._transition_to(CircuitState.HALF_OPEN)
        return self._state

    @property
    def stats(self) -> CircuitBreakerStats:
        """Get circuit breaker statistics."""
        return self._stats

    @property
    def is_closed(self) -> bool:
        """Check if circuit is closed (normal operation)."""
        return self.state == CircuitState.CLOSED

    @property
    def is_open(self) -> bool:
        """Check if circuit is open (blocking calls)."""
        return self.state == CircuitState.OPEN

    @property
    def is_half_open(self) -> bool:
        """Check if circuit is half-open (testing recovery)."""
        return self.state == CircuitState.HALF_OPEN

    def _transition_to(self, new_state: CircuitState) -> None:
        """Transition to a new state.

        Args:
            new_state: The state to transition to.
        """
        if self._state != new_state:
            old_state = self._state
            self._state = new_state
            self._stats.state_changes += 1
            self._stats.last_state_change_time = time.time()

            logger.info(
                f"CircuitBreaker '{self._name}' state changed: "
                f"{old_state.value} -> {new_state.value}"
            )

            if new_state == CircuitState.OPEN:
                self._opened_at = time.time()
            elif new_state == CircuitState.HALF_OPEN:
                self._half_open_calls = 0
                self._success_count = 0
            elif new_state == CircuitState.CLOSED:
                self._failure_count = 0
                self._success_count = 0
                self._half_open_calls = 0
                self._opened_at = None

    def _record_success(self) -> None:
        """Record a successful call."""
        self._stats.successful_calls += 1
        self._stats.total_calls += 1
        self._stats.last_success_time = time.time()

        if self._state == CircuitState.HALF_OPEN:
            self._success_count += 1
            if self._success_count >= self._config.success_threshold:
                self._transition_to(CircuitState.CLOSED)
        elif self._state == CircuitState.CLOSED:
            # Reset failure count on success in CLOSED state
            self._failure_count = 0

    def _record_failure(self) -> None:
        """Record a failed call."""
        self._stats.failed_calls += 1
        self._stats.total_calls += 1
        self._stats.last_failure_time = time.time()

        if self._state == CircuitState.HALF_OPEN:
            # Any failure in HALF-OPEN immediately opens circuit
            self._transition_to(CircuitState.OPEN)
        elif self._state == CircuitState.CLOSED:
            self._failure_count += 1
            if self._failure_count >= self._config.failure_threshold:
                self._transition_to(CircuitState.OPEN)

    def _record_rejection(self) -> None:
        """Record a rejected call (circuit was open)."""
        self._stats.rejected_calls += 1
        self._stats.total_calls += 1

    def call(self, func: Callable[..., T]) -> Callable[..., T]:
        """Decorator to wrap a function with circuit breaker protection.

        Args:
            func: Function to wrap.

        Returns:
            Wrapped function with circuit breaker logic.
        """

        def wrapper(*args: Any, **kwargs: Any) -> T:
            return self.execute(func, *args, **kwargs)

        return wrapper

    def execute(self, func: Callable[..., T], *args: Any, **kwargs: Any) -> T:
        """Execute a function with circuit breaker protection.

        Args:
            func: Function to execute.
            *args: Positional arguments to pass to function.
            **kwargs: Keyword arguments to pass to function.

        Returns:
            Result of the function call.

        Raises:
            CircuitBreakerError: If circuit is open and blocking calls.
        """
        current_state = self.state

        if current_state == CircuitState.OPEN:
            self._record_rejection()
            raise CircuitBreakerError(
                f"Circuit breaker '{self._name}' is OPEN. "
                f"Service calls are blocked until recovery."
            )

        if current_state == CircuitState.HALF_OPEN:
            if self._half_open_calls >= self._config.half_open_max_calls:
                self._record_rejection()
                raise CircuitBreakerError(
                    f"Circuit breaker '{self._name}' is HALF-OPEN. "
                    f"Max test calls ({self._config.half_open_max_calls}) reached."
                )
            self._half_open_calls += 1

        try:
            result = func(*args, **kwargs)
            self._record_success()
            return result
        except CircuitBreakerError:
            # Don't count circuit breaker errors as failures
            raise
        except Exception as e:
            self._record_failure()
            logger.warning(
                f"CircuitBreaker '{self._name}' recorded failure: {type(e).__name__}: {e}"
            )
            raise

    def reset(self) -> None:
        """Reset circuit breaker to initial CLOSED state."""
        logger.info(f"CircuitBreaker '{self._name}' manually reset")
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._success_count = 0
        self._half_open_calls = 0
        self._opened_at = None
        self._stats = CircuitBreakerStats()

    def get_state_info(self) -> dict[str, Any]:
        """Get detailed state information for monitoring.

        Returns:
            Dictionary with current state and statistics.
        """
        return {
            "name": self._name,
            "state": self.state.value,
            "is_closed": self.is_closed,
            "is_open": self.is_open,
            "is_half_open": self.is_half_open,
            "failure_count": self._failure_count,
            "half_open_calls": self._half_open_calls,
            "stats": {
                "total_calls": self._stats.total_calls,
                "successful_calls": self._stats.successful_calls,
                "failed_calls": self._stats.failed_calls,
                "rejected_calls": self._stats.rejected_calls,
                "state_changes": self._stats.state_changes,
                "last_failure_time": self._stats.last_failure_time,
                "last_success_time": self._stats.last_success_time,
            },
        }
