"""
Tests for Base Adapter - abstract base class tests
"""

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import pytest

from src.adapters.base import BaseAdapter


class ConcreteTestAdapter(BaseAdapter):
    """Concrete implementation of BaseAdapter for testing purposes."""

    def __init__(self) -> None:
        self._states: dict[str, str] = {}
        self._callbacks: dict[str, list] = {}
        self._available: bool = True

    def get_state(self, entity_id: str) -> str | None:
        """Get state of a device."""
        return self._states.get(entity_id)

    def send_command(
        self, entity_id: str, command: str, attributes: dict = None
    ) -> bool:
        """Send command to a device."""
        self._states[entity_id] = command
        return True

    def subscribe_to_changes(
        self, entity_id: str, callback: callable
    ) -> None:
        """Subscribe to device state changes."""
        if entity_id not in self._callbacks:
            self._callbacks[entity_id] = []
        self._callbacks[entity_id].append(callback)

    def is_available(self) -> bool:
        """Check if adapter is available."""
        return self._available


class TestBaseAdapterInterface:
    """Tests for BaseAdapter interface and contract."""

    def test_base_adapter_is_abstract(self) -> None:
        """Test that BaseAdapter cannot be instantiated directly."""
        with pytest.raises(TypeError):
            BaseAdapter()  # type: ignore

    def test_concrete_adapter_implements_all_methods(self) -> None:
        """Test that concrete implementation satisfies the interface."""
        adapter = ConcreteTestAdapter()
        assert adapter is not None

    def test_get_state_abstract_method_exists(self) -> None:
        """Test that get_state method is defined in base class."""
        assert hasattr(BaseAdapter, "get_state")
        assert getattr(BaseAdapter, "get_state").__isabstractmethod__

    def test_send_command_abstract_method_exists(self) -> None:
        """Test that send_command method is defined in base class."""
        assert hasattr(BaseAdapter, "send_command")
        assert getattr(BaseAdapter, "send_command").__isabstractmethod__

    def test_subscribe_to_changes_abstract_method_exists(self) -> None:
        """Test that subscribe_to_changes method is defined in base class."""
        assert hasattr(BaseAdapter, "subscribe_to_changes")
        assert getattr(BaseAdapter, "subscribe_to_changes").__isabstractmethod__

    def test_is_available_abstract_method_exists(self) -> None:
        """Test that is_available method is defined in base class."""
        assert hasattr(BaseAdapter, "is_available")
        assert getattr(BaseAdapter, "is_available").__isabstractmethod__


class TestConcreteAdapterImplementation:
    """Tests for concrete adapter implementation."""

    def test_get_state_returns_none_for_unknown_entity(self) -> None:
        """Test get_state returns None for unknown entity."""
        adapter = ConcreteTestAdapter()
        assert adapter.get_state("light.unknown") is None

    def test_get_state_returns_stored_state(self) -> None:
        """Test get_state returns stored state."""
        adapter = ConcreteTestAdapter()
        adapter._states["light.living_room"] = "on"
        assert adapter.get_state("light.living_room") == "on"

    def test_send_command_stores_state(self) -> None:
        """Test send_command stores the command as state."""
        adapter = ConcreteTestAdapter()
        result = adapter.send_command("light.living_room", "turn_on")
        assert result is True
        assert adapter.get_state("light.living_room") == "turn_on"

    def test_send_command_with_attributes(self) -> None:
        """Test send_command accepts optional attributes."""
        adapter = ConcreteTestAdapter()
        result = adapter.send_command(
            "light.bedroom", "set_brightness", {"brightness": 50}
        )
        assert result is True
        assert adapter.get_state("light.bedroom") == "set_brightness"

    def test_subscribe_to_changes_adds_callback(self) -> None:
        """Test subscribe_to_changes adds callback to list."""
        adapter = ConcreteTestAdapter()
        callback = lambda x, y: None
        adapter.subscribe_to_changes("light.living_room", callback)
        assert "light.living_room" in adapter._callbacks
        assert callback in adapter._callbacks["light.living_room"]

    def test_subscribe_to_changes_multiple_callbacks(self) -> None:
        """Test subscribe_to_changes handles multiple callbacks."""
        adapter = ConcreteTestAdapter()
        callback1 = lambda x, y: None
        callback2 = lambda x, y: None
        adapter.subscribe_to_changes("light.living_room", callback1)
        adapter.subscribe_to_changes("light.living_room", callback2)
        assert len(adapter._callbacks["light.living_room"]) == 2

    def test_is_available_returns_true_by_default(self) -> None:
        """Test is_available returns True by default."""
        adapter = ConcreteTestAdapter()
        assert adapter.is_available() is True

    def test_is_available_can_be_set_to_false(self) -> None:
        """Test is_available can be set to False."""
        adapter = ConcreteTestAdapter()
        adapter._available = False
        assert adapter.is_available() is False
