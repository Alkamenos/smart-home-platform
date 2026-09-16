"""Tests for EventBus module based on specification."""

import uuid
from unittest.mock import AsyncMock, patch

import pytest
from src.core.event_bus import EventBus


class TestEventBusInitialization:
    """Test EventBus initialization according to specification."""

    def test_creates_empty_subscribers_dict(self):
        """EventBus should initialize with empty subscribers dictionary."""
        bus = EventBus()
        assert bus._subscribers == {}

    def test_creates_empty_filtered_subscribers_list(self):
        """EventBus should initialize with empty filtered subscribers list."""
        bus = EventBus()
        assert bus._filtered_subscribers == []


class TestSubscribe:
    """Test subscribe method according to specification."""

    def test_subscribes_handler_to_event_type(self):
        """Should add handler to subscribers list for given event type."""
        bus = EventBus()
        handler = AsyncMock()

        bus.subscribe("motion_detected", handler)

        assert "motion_detected" in bus._subscribers
        assert handler in bus._subscribers["motion_detected"]

    def test_subscribes_multiple_handlers_to_same_event(self):
        """Should allow multiple handlers for the same event type."""
        bus = EventBus()
        handler1 = AsyncMock()
        handler2 = AsyncMock()

        bus.subscribe("motion_detected", handler1)
        bus.subscribe("motion_detected", handler2)

        assert len(bus._subscribers["motion_detected"]) == 2
        assert handler1 in bus._subscribers["motion_detected"]
        assert handler2 in bus._subscribers["motion_detected"]

    def test_subscribes_to_different_event_types(self):
        """Should maintain separate subscriber lists for different event types."""
        bus = EventBus()
        motion_handler = AsyncMock()
        temp_handler = AsyncMock()

        bus.subscribe("motion_detected", motion_handler)
        bus.subscribe("temperature_changed", temp_handler)

        assert "motion_detected" in bus._subscribers
        assert "temperature_changed" in bus._subscribers
        assert len(bus._subscribers["motion_detected"]) == 1
        assert len(bus._subscribers["temperature_changed"]) == 1
        assert motion_handler in bus._subscribers["motion_detected"]
        assert temp_handler in bus._subscribers["temperature_changed"]

    def test_creates_new_list_for_new_event_type(self):
        """Should create a new list when subscribing to a new event type."""
        bus = EventBus()
        handler = AsyncMock()

        bus.subscribe("new_event", handler)

        assert bus._subscribers["new_event"] == [handler]


class TestUnsubscribe:
    """Test unsubscribe method according to specification."""

    def test_removes_handler_from_subscribers(self):
        """Should remove handler from subscribers list for given event type."""
        bus = EventBus()
        handler = AsyncMock()
        bus.subscribe("motion_detected", handler)

        bus.unsubscribe("motion_detected", handler)

        assert handler not in bus._subscribers.get("motion_detected", [])

    def test_removes_only_specified_handler(self):
        """Should remove only the specified handler, leaving others intact."""
        bus = EventBus()
        handler1 = AsyncMock()
        handler2 = AsyncMock()
        bus.subscribe("motion_detected", handler1)
        bus.subscribe("motion_detected", handler2)

        bus.unsubscribe("motion_detected", handler1)

        assert handler1 not in bus._subscribers["motion_detected"]
        assert handler2 in bus._subscribers["motion_detected"]

    def test_unsubscribe_nonexistent_event_type(self):
        """Should not raise error when unsubscribing from nonexistent event type."""
        bus = EventBus()
        handler = AsyncMock()

        # Should not raise any exception
        bus.unsubscribe("nonexistent_event", handler)

    def test_unsubscribe_handler_not_subscribed(self):
        """Should not raise error when unsubscribing handler that wasn't subscribed."""
        bus = EventBus()
        handler1 = AsyncMock()
        handler2 = AsyncMock()
        bus.subscribe("motion_detected", handler1)

        # Should not raise any exception
        bus.unsubscribe("motion_detected", handler2)


class TestSubscribeWithFilter:
    """Test subscribe_with_filter method according to specification."""

    def test_adds_filtered_subscriber(self):
        """Should add tuple of (event_type, filter_params, handler) to filtered_subscribers."""
        bus = EventBus()
        handler = AsyncMock()
        filter_params = {"device_id": "sensor.motion_1"}

        bus.subscribe_with_filter("state_changed", filter_params, handler)

        assert len(bus._filtered_subscribers) == 1
        assert bus._filtered_subscribers[0] == ("state_changed", filter_params, handler)

    def test_adds_multiple_filtered_subscribers(self):
        """Should allow multiple filtered subscribers."""
        bus = EventBus()
        handler1 = AsyncMock()
        handler2 = AsyncMock()
        filter1 = {"device_id": "sensor.motion_1"}
        filter2 = {"device_id": "sensor.motion_2"}

        bus.subscribe_with_filter("state_changed", filter1, handler1)
        bus.subscribe_with_filter("state_changed", filter2, handler2)

        assert len(bus._filtered_subscribers) == 2

    def test_filtered_subscriber_with_complex_filter(self):
        """Should support complex filter parameters with multiple keys."""
        bus = EventBus()
        handler = AsyncMock()
        filter_params = {"device_id": "sensor.motion_1", "room": "hallway", "zone": "ground_floor"}

        bus.subscribe_with_filter("state_changed", filter_params, handler)

        assert bus._filtered_subscribers[0][1] == filter_params


class TestMatchesFilter:
    """Test _matches_filter method according to specification."""

    def test_matches_when_all_keys_match(self):
        """Should return True when all filter keys exist in payload with matching values."""
        bus = EventBus()
        filter_params = {"device_id": "sensor.motion_1", "room": "hallway"}
        payload = {"device_id": "sensor.motion_1", "room": "hallway", "state": "on"}

        result = bus._matches_filter(filter_params, payload)

        assert result is True

    def test_does_not_match_when_key_missing(self):
        """Should return False when filter key is missing from payload."""
        bus = EventBus()
        filter_params = {"device_id": "sensor.motion_1", "room": "hallway"}
        payload = {"device_id": "sensor.motion_1", "state": "on"}

        result = bus._matches_filter(filter_params, payload)

        assert result is False

    def test_does_not_match_when_value_differs(self):
        """Should return False when filter key exists but value differs."""
        bus = EventBus()
        filter_params = {"device_id": "sensor.motion_1", "room": "hallway"}
        payload = {"device_id": "sensor.motion_1", "room": "kitchen"}

        result = bus._matches_filter(filter_params, payload)

        assert result is False

    def test_matches_with_extra_payload_keys(self):
        """Should return True when payload has extra keys beyond filter."""
        bus = EventBus()
        filter_params = {"device_id": "sensor.motion_1"}
        payload = {
            "device_id": "sensor.motion_1",
            "room": "hallway",
            "state": "on",
            "timestamp": "2024-01-01T00:00:00",
        }

        result = bus._matches_filter(filter_params, payload)

        assert result is True

    def test_non_dict_payload_returns_false(self):
        """Should return False when payload is not a dictionary."""
        bus = EventBus()
        filter_params = {"device_id": "sensor.motion_1"}

        assert bus._matches_filter(filter_params, None) is False
        assert bus._matches_filter(filter_params, "string") is False
        assert bus._matches_filter(filter_params, 123) is False
        assert bus._matches_filter(filter_params, []) is False

    def test_empty_filter_matches_any_dict(self):
        """Should return True for empty filter params with any dict payload."""
        bus = EventBus()
        filter_params = {}
        payload = {"any": "data"}

        result = bus._matches_filter(filter_params, payload)

        assert result is True


class TestPublish:
    """Test publish method according to specification."""

    @pytest.mark.asyncio
    async def test_calls_handler_with_event_type_and_payload(self):
        """Should call subscribed handler with event_type and payload."""
        bus = EventBus()
        handler = AsyncMock()
        bus.subscribe("motion_detected", handler)

        await bus.publish("motion_detected", {"device_id": "sensor.motion_1"})

        handler.assert_called_once()
        call_args = handler.call_args
        assert call_args.args[0] == "motion_detected"
        assert call_args.args[1] == {"device_id": "sensor.motion_1"}
        assert "trace_id" in call_args.kwargs

    @pytest.mark.asyncio
    async def test_generates_trace_id_if_not_provided(self):
        """Should generate a UUID trace_id if not provided."""
        bus = EventBus()
        handler = AsyncMock()
        bus.subscribe("test_event", handler)

        with patch("uuid.uuid4", return_value=uuid.UUID("12345678-1234-5678-1234-567812345678")):
            await bus.publish("test_event", {"data": "value"})

            handler.assert_called_once()
            call_kwargs = handler.call_args.kwargs
            assert call_kwargs["trace_id"] == "12345678"

    @pytest.mark.asyncio
    async def test_uses_provided_trace_id(self):
        """Should use provided trace_id instead of generating one."""
        bus = EventBus()
        handler = AsyncMock()
        bus.subscribe("test_event", handler)

        await bus.publish("test_event", {"data": "value"}, trace_id="custom-trace")

        handler.assert_called_once_with("test_event", {"data": "value"}, trace_id="custom-trace")

    @pytest.mark.asyncio
    async def test_calls_all_handlers_for_event(self):
        """Should call all handlers subscribed to the event type."""
        bus = EventBus()
        handler1 = AsyncMock()
        handler2 = AsyncMock()
        handler3 = AsyncMock()
        bus.subscribe("motion_detected", handler1)
        bus.subscribe("motion_detected", handler2)
        bus.subscribe("motion_detected", handler3)

        await bus.publish("motion_detected", {"device_id": "sensor.motion_1"})

        handler1.assert_called_once()
        handler2.assert_called_once()
        handler3.assert_called_once()

    @pytest.mark.asyncio
    async def test_does_not_call_handlers_for_other_events(self):
        """Should not call handlers subscribed to different event types."""
        bus = EventBus()
        motion_handler = AsyncMock()
        temp_handler = AsyncMock()
        bus.subscribe("motion_detected", motion_handler)
        bus.subscribe("temperature_changed", temp_handler)

        await bus.publish("motion_detected", {"device_id": "sensor.motion_1"})

        motion_handler.assert_called_once()
        temp_handler.assert_not_called()

    @pytest.mark.asyncio
    async def test_handles_handler_exception_gracefully(self):
        """Should continue calling other handlers even if one raises exception."""
        bus = EventBus()
        failing_handler = AsyncMock(side_effect=Exception("Handler failed"))
        success_handler = AsyncMock()
        bus.subscribe("test_event", failing_handler)
        bus.subscribe("test_event", success_handler)

        # Should not raise exception
        await bus.publish("test_event", {"data": "value"})

        failing_handler.assert_called_once()
        success_handler.assert_called_once()

    @pytest.mark.asyncio
    async def test_calls_filtered_subscriber_when_filter_matches(self):
        """Should call filtered subscriber when payload matches filter."""
        bus = EventBus()
        handler = AsyncMock()
        filter_params = {"device_id": "sensor.motion_1"}
        bus.subscribe_with_filter("state_changed", filter_params, handler)

        await bus.publish("state_changed", {"device_id": "sensor.motion_1", "state": "on"})

        handler.assert_called_once()

    @pytest.mark.asyncio
    async def test_does_not_call_filtered_subscriber_when_filter_does_not_match(self):
        """Should not call filtered subscriber when payload doesn't match filter."""
        bus = EventBus()
        handler = AsyncMock()
        filter_params = {"device_id": "sensor.motion_1"}
        bus.subscribe_with_filter("state_changed", filter_params, handler)

        await bus.publish("state_changed", {"device_id": "sensor.motion_2", "state": "on"})

        handler.assert_not_called()

    @pytest.mark.asyncio
    async def test_calls_both_regular_and_filtered_subscribers(self):
        """Should call both regular and filtered subscribers appropriately."""
        bus = EventBus()
        regular_handler = AsyncMock()
        filtered_handler = AsyncMock()
        bus.subscribe("state_changed", regular_handler)
        bus.subscribe_with_filter(
            "state_changed", {"device_id": "sensor.motion_1"}, filtered_handler
        )

        await bus.publish("state_changed", {"device_id": "sensor.motion_1", "state": "on"})

        regular_handler.assert_called_once()
        filtered_handler.assert_called_once()

    @pytest.mark.asyncio
    async def test_does_not_call_filtered_subscriber_for_non_dict_payload(self):
        """Should not attempt to call filtered subscribers with non-dict payload."""
        bus = EventBus()
        handler = AsyncMock()
        filter_params = {"device_id": "sensor.motion_1"}
        bus.subscribe_with_filter("state_changed", filter_params, handler)

        # Should not raise exception and should not call handler
        await bus.publish("state_changed", "non_dict_payload")

        handler.assert_not_called()

    @pytest.mark.asyncio
    async def test_handles_filtered_handler_exception_gracefully(self):
        """Should continue processing even if filtered handler raises exception."""
        bus = EventBus()
        failing_handler = AsyncMock(side_effect=Exception("Filtered handler failed"))
        filter_params = {"device_id": "sensor.motion_1"}
        bus.subscribe_with_filter("state_changed", filter_params, failing_handler)

        # Should not raise exception
        await bus.publish("state_changed", {"device_id": "sensor.motion_1", "state": "on"})

        failing_handler.assert_called_once()

    @pytest.mark.asyncio
    async def test_publishes_to_no_subscribers(self):
        """Should handle publishing when there are no subscribers."""
        bus = EventBus()

        # Should not raise any exception
        await bus.publish("nonexistent_event", {"data": "value"})

    @pytest.mark.asyncio
    async def test_handler_without_trace_id_support(self):
        """Should handle handlers that don't accept trace_id parameter.

        Note: The current implementation tries with trace_id first, then falls back
        to calling without trace_id on TypeError. This means legacy handlers that
        don't accept trace_id will be called twice - once with trace_id (which may
        fail silently in real handlers) and once without.
        """
        bus = EventBus()
        # Create a handler that only accepts 2 positional arguments
        call_count = {"value": 0}
        call_args_list = []

        async def legacy_handler(event_type, payload):
            call_count["value"] += 1
            call_args_list.append((event_type, payload))

        bus.subscribe("test_event", legacy_handler)

        # Should not raise exception
        await bus.publish("test_event", {"data": "value"})

        # Handler is called once (the second attempt after TypeError)
        assert call_count["value"] == 1
        assert call_args_list[0] == ("test_event", {"data": "value"})


class TestEventBusIntegration:
    """Integration tests for EventBus based on real-world scenarios."""

    @pytest.mark.asyncio
    async def test_motion_sensor_scenario(self):
        """Test complete motion sensor event flow."""
        bus = EventBus()

        # Simulate room context manager
        room_context = {"motion_active": False}

        async def update_context(event_type, payload, trace_id=None):
            room_context["motion_active"] = payload.get("state") == "on"

        # Simulate logger
        logged_events = []

        async def log_event(event_type, payload, trace_id=None):
            logged_events.append({"type": event_type, "payload": payload, "trace_id": trace_id})

        bus.subscribe("motion_detected", update_context)
        bus.subscribe("motion_detected", log_event)

        # Publish motion detected event
        await bus.publish(
            "motion_detected",
            {"device_id": "sensor.motion_hallway", "state": "on"},
            trace_id="test-trace-1",
        )

        assert room_context["motion_active"] is True
        assert len(logged_events) == 1
        assert logged_events[0]["type"] == "motion_detected"
        assert logged_events[0]["trace_id"] == "test-trace-1"

    @pytest.mark.asyncio
    async def test_filtered_subscription_by_room(self):
        """Test filtered subscriptions for room-specific events."""
        bus = EventBus()

        hallway_actions = []
        kitchen_actions = []

        async def hallway_handler(event_type, payload, trace_id=None):
            hallway_actions.append(payload)

        async def kitchen_handler(event_type, payload, trace_id=None):
            kitchen_actions.append(payload)

        bus.subscribe_with_filter("state_changed", {"room": "hallway"}, hallway_handler)
        bus.subscribe_with_filter("state_changed", {"room": "kitchen"}, kitchen_handler)

        # Publish events for different rooms
        await bus.publish("state_changed", {"room": "hallway", "device": "light_1", "state": "on"})
        await bus.publish("state_changed", {"room": "kitchen", "device": "light_2", "state": "on"})
        await bus.publish("state_changed", {"room": "bedroom", "device": "light_3", "state": "on"})

        assert len(hallway_actions) == 1
        assert len(kitchen_actions) == 1
        assert hallway_actions[0]["device"] == "light_1"
        assert kitchen_actions[0]["device"] == "light_2"

    @pytest.mark.asyncio
    async def test_multiple_filtered_subscribers_same_event(self):
        """Test multiple filtered subscribers for the same event type."""
        bus = EventBus()

        results = {"motion_1": 0, "motion_2": 0, "motion_3": 0}

        async def handler_1(event_type, payload, trace_id=None):
            results["motion_1"] += 1

        async def handler_2(event_type, payload, trace_id=None):
            results["motion_2"] += 1

        async def handler_3(event_type, payload, trace_id=None):
            results["motion_3"] += 1

        bus.subscribe_with_filter("motion", {"device_id": "motion_1"}, handler_1)
        bus.subscribe_with_filter("motion", {"device_id": "motion_2"}, handler_2)
        bus.subscribe_with_filter("motion", {"device_id": "motion_3"}, handler_3)

        # Publish events from different devices
        await bus.publish("motion", {"device_id": "motion_1"})
        await bus.publish("motion", {"device_id": "motion_2"})
        await bus.publish("motion", {"device_id": "motion_1"})
        await bus.publish("motion", {"device_id": "motion_3"})

        assert results["motion_1"] == 2
        assert results["motion_2"] == 1
        assert results["motion_3"] == 1
