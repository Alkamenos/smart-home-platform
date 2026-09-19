"""Tests for Circuit Breaker pattern implementation.

Tests cover all circuit breaker states, transitions, and edge cases.
"""

from __future__ import annotations

import time
from unittest.mock import Mock

import pytest

from src.core.circuit_breaker import (
    CircuitBreaker,
    CircuitBreakerConfig,
    CircuitBreakerError,
    CircuitBreakerStats,
    CircuitState,
)


class TestCircuitState:
    """Test CircuitState enum."""

    def test_states_exist(self) -> None:
        """Test that all expected states exist."""
        assert CircuitState.CLOSED.value == "closed"
        assert CircuitState.OPEN.value == "open"
        assert CircuitState.HALF_OPEN.value == "half_open"


class TestCircuitBreakerConfig:
    """Test CircuitBreakerConfig dataclass."""

    def test_default_values(self) -> None:
        """Test default configuration values."""
        config = CircuitBreakerConfig()
        assert config.failure_threshold == 5
        assert config.recovery_timeout_sec == 30.0
        assert config.half_open_max_calls == 2
        assert config.success_threshold == 2

    def test_custom_values(self) -> None:
        """Test custom configuration values."""
        config = CircuitBreakerConfig(
            failure_threshold=3,
            recovery_timeout_sec=10.0,
            half_open_max_calls=1,
            success_threshold=1,
        )
        assert config.failure_threshold == 3
        assert config.recovery_timeout_sec == 10.0
        assert config.half_open_max_calls == 1
        assert config.success_threshold == 1


class TestCircuitBreakerStats:
    """Test CircuitBreakerStats dataclass."""

    def test_default_values(self) -> None:
        """Test default statistics values."""
        stats = CircuitBreakerStats()
        assert stats.total_calls == 0
        assert stats.successful_calls == 0
        assert stats.failed_calls == 0
        assert stats.rejected_calls == 0
        assert stats.state_changes == 0
        assert stats.last_failure_time is None
        assert stats.last_success_time is None


class TestCircuitBreakerInitialization:
    """Test CircuitBreaker initialization."""

    def test_init_with_defaults(self) -> None:
        """Test initialization with default config."""
        breaker = CircuitBreaker(name="test")
        assert breaker.name == "test"
        assert breaker.is_closed
        assert not breaker.is_open
        assert not breaker.is_half_open

    def test_init_with_custom_config(self) -> None:
        """Test initialization with custom config."""
        config = CircuitBreakerConfig(failure_threshold=3)
        breaker = CircuitBreaker(name="test", config=config)
        assert breaker.name == "test"
        assert breaker.is_closed


class TestCircuitBreakerSuccess:
    """Test successful calls through circuit breaker."""

    def test_successful_call_in_closed_state(self) -> None:
        """Test successful call keeps circuit closed."""
        breaker = CircuitBreaker(name="test")
        
        def success_func() -> str:
            return "success"
        
        result = breaker.execute(success_func)
        assert result == "success"
        assert breaker.is_closed
        assert breaker.stats.successful_calls == 1
        assert breaker.stats.total_calls == 1

    def test_successful_call_resets_failure_count(self) -> None:
        """Test that success resets failure count in CLOSED state."""
        config = CircuitBreakerConfig(failure_threshold=3)
        breaker = CircuitBreaker(name="test", config=config)
        
        def fail_func() -> None:
            raise Exception("fail")
        
        def success_func() -> str:
            return "success"
        
        # Two failures
        for _ in range(2):
            with pytest.raises(Exception):
                breaker.execute(fail_func)
        
        # One success should reset failure count
        breaker.execute(success_func)
        
        # Two more failures should not open circuit
        for _ in range(2):
            with pytest.raises(Exception):
                breaker.execute(fail_func)
        
        assert breaker.is_closed


class TestCircuitBreakerFailure:
    """Test failure handling in circuit breaker."""

    def test_open_after_threshold_failures(self) -> None:
        """Test circuit opens after reaching failure threshold."""
        config = CircuitBreakerConfig(failure_threshold=3)
        breaker = CircuitBreaker(name="test", config=config)
        
        def fail_func() -> None:
            raise Exception("fail")
        
        # Three failures should open circuit
        for _ in range(3):
            with pytest.raises(Exception):
                breaker.execute(fail_func)
        
        assert breaker.is_open
        assert breaker.stats.failed_calls == 3
        assert breaker.stats.state_changes == 1  # CLOSED -> OPEN

    def test_reject_calls_when_open(self) -> None:
        """Test that calls are rejected when circuit is open."""
        config = CircuitBreakerConfig(failure_threshold=2)
        breaker = CircuitBreaker(name="test", config=config)
        
        def fail_func() -> None:
            raise Exception("fail")
        
        def success_func() -> str:
            return "success"
        
        # Open the circuit
        for _ in range(2):
            with pytest.raises(Exception):
                breaker.execute(fail_func)
        
        assert breaker.is_open
        
        # Calls should be rejected
        with pytest.raises(CircuitBreakerError):
            breaker.execute(success_func)
        
        assert breaker.stats.rejected_calls == 1


class TestCircuitBreakerRecovery:
    """Test circuit breaker recovery mechanism."""

    def test_transition_to_half_open_after_timeout(self) -> None:
        """Test transition from OPEN to HALF-OPEN after timeout."""
        config = CircuitBreakerConfig(
            failure_threshold=2,
            recovery_timeout_sec=0.1,
        )
        breaker = CircuitBreaker(name="test", config=config)
        
        def fail_func() -> None:
            raise Exception("fail")
        
        # Open the circuit
        for _ in range(2):
            with pytest.raises(Exception):
                breaker.execute(fail_func)
        
        assert breaker.is_open
        
        # Wait for timeout
        time.sleep(0.15)
        
        # Accessing state should trigger transition
        assert breaker.is_half_open

    def test_close_after_successful_half_open_calls(self) -> None:
        """Test circuit closes after successful calls in HALF-OPEN."""
        config = CircuitBreakerConfig(
            failure_threshold=2,
            recovery_timeout_sec=0.1,
            success_threshold=2,
            half_open_max_calls=3,
        )
        breaker = CircuitBreaker(name="test", config=config)
        
        def fail_func() -> None:
            raise Exception("fail")
        
        def success_func() -> str:
            return "success"
        
        # Open the circuit
        for _ in range(2):
            with pytest.raises(Exception):
                breaker.execute(fail_func)
        
        # Wait for timeout
        time.sleep(0.15)
        
        # Trigger transition to HALF-OPEN
        assert breaker.state == CircuitState.HALF_OPEN
        
        # Two successful calls should close circuit
        breaker.execute(success_func)
        breaker.execute(success_func)
        
        assert breaker.is_closed

    def test_reopen_on_failure_in_half_open(self) -> None:
        """Test circuit reopens on failure in HALF-OPEN state."""
        config = CircuitBreakerConfig(
            failure_threshold=2,
            recovery_timeout_sec=0.1,
        )
        breaker = CircuitBreaker(name="test", config=config)
        
        def fail_func() -> None:
            raise Exception("fail")
        
        # Open the circuit
        for _ in range(2):
            with pytest.raises(Exception):
                breaker.execute(fail_func)
        
        # Wait for timeout
        time.sleep(0.15)
        
        # Trigger transition to HALF-OPEN
        assert breaker.state == CircuitState.HALF_OPEN
        
        # Failure in HALF-OPEN should reopen circuit
        with pytest.raises(Exception):
            breaker.execute(fail_func)
        
        assert breaker.is_open


class TestCircuitBreakerHalfOpenLimits:
    """Test HALF-OPEN state call limits."""

    def test_reject_after_max_half_open_calls(self) -> None:
        """Test rejection after reaching max HALF-OPEN calls."""
        config = CircuitBreakerConfig(
            failure_threshold=2,
            recovery_timeout_sec=0.1,
            half_open_max_calls=2,
        )
        breaker = CircuitBreaker(name="test", config=config)
        
        def fail_func() -> None:
            raise Exception("fail")
        
        def success_func() -> str:
            return "success"
        
        # Open the circuit
        for _ in range(2):
            with pytest.raises(Exception):
                breaker.execute(fail_func)
        
        # Wait for timeout
        time.sleep(0.15)
        
        # Trigger transition to HALF-OPEN
        assert breaker.state == CircuitState.HALF_OPEN
        
        # Make max calls without completing them (simulate in-progress)
        breaker._half_open_calls = 2
        
        # Next call should be rejected
        with pytest.raises(CircuitBreakerError):
            breaker.execute(success_func)


class TestCircuitBreakerDecorator:
    """Test circuit breaker decorator."""

    def test_decorator_wraps_function(self) -> None:
        """Test that decorator properly wraps function."""
        breaker = CircuitBreaker(name="test")
        
        @breaker.call
        def my_func(x: int) -> int:
            return x * 2
        
        result = my_func(5)
        assert result == 10
        assert breaker.stats.successful_calls == 1


class TestCircuitBreakerReset:
    """Test circuit breaker reset functionality."""

    def test_reset_clears_state(self) -> None:
        """Test that reset clears all state."""
        config = CircuitBreakerConfig(failure_threshold=2)
        breaker = CircuitBreaker(name="test", config=config)
        
        def fail_func() -> None:
            raise Exception("fail")
        
        # Open the circuit
        for _ in range(2):
            with pytest.raises(Exception):
                breaker.execute(fail_func)
        
        assert breaker.is_open
        
        # Reset
        breaker.reset()
        
        assert breaker.is_closed
        assert breaker.stats.total_calls == 0
        assert breaker.stats.state_changes == 0


class TestCircuitBreakerStateInfo:
    """Test get_state_info method."""

    def test_get_state_info_returns_dict(self) -> None:
        """Test that get_state_info returns proper dictionary."""
        breaker = CircuitBreaker(name="test")
        
        info = breaker.get_state_info()
        
        assert "name" in info
        assert "state" in info
        assert "is_closed" in info
        assert "is_open" in info
        assert "is_half_open" in info
        assert "failure_count" in info
        assert "half_open_calls" in info
        assert "stats" in info
        
        assert info["name"] == "test"
        assert info["state"] == "closed"
        assert info["is_closed"] is True


class TestCircuitBreakerEdgeCases:
    """Test edge cases and error handling."""

    def test_circuit_breaker_error_not_counted_as_failure(self) -> None:
        """Test that CircuitBreakerError doesn't count as failure."""
        config = CircuitBreakerConfig(failure_threshold=2)
        breaker = CircuitBreaker(name="test", config=config)
        
        def fail_func() -> None:
            raise Exception("fail")
        
        # Open the circuit
        for _ in range(2):
            with pytest.raises(Exception):
                breaker.execute(fail_func)
        
        initial_failed = breaker.stats.failed_calls
        
        # Try to call when open - should raise CircuitBreakerError
        with pytest.raises(CircuitBreakerError):
            breaker.execute(lambda: "test")
        
        # Failed calls count should not increase
        assert breaker.stats.failed_calls == initial_failed

    def test_exception_propagates_correctly(self) -> None:
        """Test that original exceptions are propagated."""
        breaker = CircuitBreaker(name="test")
        
        def custom_error_func() -> None:
            raise ValueError("custom error")
        
        with pytest.raises(ValueError, match="custom error"):
            breaker.execute(custom_error_func)
