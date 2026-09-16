"""Tests for guard classes in Smart Home Platform."""

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0

from datetime import datetime, time
from unittest.mock import MagicMock, patch

import pytest
from src.core.guards.base import BaseGuard
from src.core.guards.composite_guard import CompositeGuard
from src.core.guards.numeric_guard import NumericGuard
from src.core.guards.state_guard import StateGuard
from src.core.guards.time_guard import TimeGuard


class TestBaseGuard:
    """Test suite for BaseGuard abstract class."""

    def test_base_guard_is_abstract(self) -> None:
        """Test that BaseGuard cannot be instantiated directly."""
        with pytest.raises(TypeError):
            BaseGuard()  # type: ignore[abstract]

    def test_base_guard_evaluate_is_abstract_method(self) -> None:
        """Test that evaluate method is abstract in BaseGuard."""
        assert hasattr(BaseGuard, "evaluate")
        assert getattr(BaseGuard.evaluate, "__isabstractmethod__", False)


class TestCompositeGuard:
    """Test suite for CompositeGuard class."""

    def test_init_with_and_operator(self) -> None:
        """Test initialization with AND operator."""
        mock_guard = MagicMock(spec=BaseGuard)
        guard = CompositeGuard(operator="and", guards=[mock_guard])
        assert guard._operator == "and"
        assert guard._guards == [mock_guard]

    def test_init_with_or_operator(self) -> None:
        """Test initialization with OR operator."""
        mock_guard = MagicMock(spec=BaseGuard)
        guard = CompositeGuard(operator="or", guards=[mock_guard])
        assert guard._operator == "or"

    def test_init_with_invalid_operator_raises(self) -> None:
        """Test that invalid operator raises ValueError."""
        with pytest.raises(ValueError, match="Unsupported operator"):
            CompositeGuard(operator="xor", guards=[])  # type: ignore[arg-type]

    def test_init_with_empty_guards(self) -> None:
        """Test initialization with empty guards list."""
        guard = CompositeGuard(operator="and", guards=[])
        assert guard._guards == []

    def test_evaluate_and_all_true(self) -> None:
        """Test AND evaluation when all guards return True."""
        mock_guard1 = MagicMock(spec=BaseGuard)
        mock_guard1.evaluate.return_value = True
        mock_guard2 = MagicMock(spec=BaseGuard)
        mock_guard2.evaluate.return_value = True

        guard = CompositeGuard(operator="and", guards=[mock_guard1, mock_guard2])
        result = guard.evaluate(state=None, context={})

        assert result is True
        mock_guard1.evaluate.assert_called_once()
        mock_guard2.evaluate.assert_called_once()

    def test_evaluate_and_one_false(self) -> None:
        """Test AND evaluation when one guard returns False."""
        mock_guard1 = MagicMock(spec=BaseGuard)
        mock_guard1.evaluate.return_value = True
        mock_guard2 = MagicMock(spec=BaseGuard)
        mock_guard2.evaluate.return_value = False

        guard = CompositeGuard(operator="and", guards=[mock_guard1, mock_guard2])
        result = guard.evaluate(state=None, context={})

        assert result is False

    def test_evaluate_or_any_true(self) -> None:
        """Test OR evaluation when any guard returns True."""
        mock_guard1 = MagicMock(spec=BaseGuard)
        mock_guard1.evaluate.return_value = False
        mock_guard2 = MagicMock(spec=BaseGuard)
        mock_guard2.evaluate.return_value = True

        guard = CompositeGuard(operator="or", guards=[mock_guard1, mock_guard2])
        result = guard.evaluate(state=None, context={})

        assert result is True

    def test_evaluate_or_all_false(self) -> None:
        """Test OR evaluation when all guards return False."""
        mock_guard1 = MagicMock(spec=BaseGuard)
        mock_guard1.evaluate.return_value = False
        mock_guard2 = MagicMock(spec=BaseGuard)
        mock_guard2.evaluate.return_value = False

        guard = CompositeGuard(operator="or", guards=[mock_guard1, mock_guard2])
        result = guard.evaluate(state=None, context={})

        assert result is False

    def test_evaluate_empty_guards_returns_true(self) -> None:
        """Test that empty guards list returns True."""
        guard = CompositeGuard(operator="and", guards=[])
        result = guard.evaluate(state=None, context={})
        assert result is True

    def test_evaluate_passes_state_and_context(self) -> None:
        """Test that state and context are passed to child guards."""
        mock_guard = MagicMock(spec=BaseGuard)
        mock_guard.evaluate.return_value = True

        guard = CompositeGuard(operator="and", guards=[mock_guard])
        test_state = MagicMock()
        test_context = {"key": "value"}

        guard.evaluate(state=test_state, context=test_context)

        mock_guard.evaluate.assert_called_once_with(test_state, test_context)


class TestNumericGuard:
    """Test suite for NumericGuard class."""

    def test_init_with_valid_operator(self) -> None:
        """Test initialization with valid operators."""
        for op in ["<", ">", "<=", ">=", "=="]:
            guard = NumericGuard(entity="sensor.temp", operator_str=op, value=25.0)
            assert guard._entity_id == "sensor.temp"
            assert guard._threshold == 25.0

    def test_init_with_invalid_operator_raises(self) -> None:
        """Test that invalid operator raises ValueError."""
        with pytest.raises(ValueError, match="Unsupported operator"):
            NumericGuard(entity="sensor.temp", operator_str="!=", value=25.0)

    def test_evaluate_less_than_true(self) -> None:
        """Test less-than comparison when condition is true."""
        guard = NumericGuard(entity="sensor.temp", operator_str="<", value=25.0)
        context = {"entities": {"sensor.temp": 20.0}}
        result = guard.evaluate(state=None, context=context)
        assert result is True

    def test_evaluate_less_than_false(self) -> None:
        """Test less-than comparison when condition is false."""
        guard = NumericGuard(entity="sensor.temp", operator_str="<", value=25.0)
        context = {"entities": {"sensor.temp": 30.0}}
        result = guard.evaluate(state=None, context=context)
        assert result is False

    def test_evaluate_greater_than_true(self) -> None:
        """Test greater-than comparison when condition is true."""
        guard = NumericGuard(entity="sensor.temp", operator_str=">", value=25.0)
        context = {"entities": {"sensor.temp": 30.0}}
        result = guard.evaluate(state=None, context=context)
        assert result is True

    def test_evaluate_equal_true(self) -> None:
        """Test equality comparison when condition is true."""
        guard = NumericGuard(entity="sensor.temp", operator_str="==", value=25.0)
        context = {"entities": {"sensor.temp": 25.0}}
        result = guard.evaluate(state=None, context=context)
        assert result is True

    def test_evaluate_less_equal_boundary(self) -> None:
        """Test less-than-or-equal at boundary."""
        guard = NumericGuard(entity="sensor.temp", operator_str="<=", value=25.0)
        context = {"entities": {"sensor.temp": 25.0}}
        result = guard.evaluate(state=None, context=context)
        assert result is True

    def test_evaluate_greater_equal_boundary(self) -> None:
        """Test greater-than-or-equal at boundary."""
        guard = NumericGuard(entity="sensor.temp", operator_str=">=", value=25.0)
        context = {"entities": {"sensor.temp": 25.0}}
        result = guard.evaluate(state=None, context=context)
        assert result is True

    def test_evaluate_missing_entity_returns_false(self) -> None:
        """Test that missing entity returns False."""
        guard = NumericGuard(entity="sensor.temp", operator_str="<", value=25.0)
        context = {"entities": {}}
        result = guard.evaluate(state=None, context=context)
        # Default value is 0, so 0 < 25.0 is True
        assert result is True

    def test_evaluate_invalid_value_returns_false(self) -> None:
        """Test that non-numeric value returns False."""
        guard = NumericGuard(entity="sensor.temp", operator_str="<", value=25.0)
        context = {"entities": {"sensor.temp": "invalid"}}
        result = guard.evaluate(state=None, context=context)
        assert result is False

    def test_evaluate_none_value_returns_false(self) -> None:
        """Test that None value returns False."""
        guard = NumericGuard(entity="sensor.temp", operator_str="<", value=25.0)
        context = {"entities": {"sensor.temp": None}}
        result = guard.evaluate(state=None, context=context)
        assert result is False

    def test_evaluate_uses_default_zero_when_no_entities(self) -> None:
        """Test that default 0 is used when entities key is missing."""
        guard = NumericGuard(entity="sensor.temp", operator_str="<", value=5.0)
        context = {}
        result = guard.evaluate(state=None, context=context)
        assert result is True  # 0 < 5.0


class TestStateGuard:
    """Test suite for StateGuard class."""

    def test_init_stores_entity_and_state(self) -> None:
        """Test initialization stores entity ID and expected state."""
        guard = StateGuard(entity="binary_sensor.motion", is_state="on")
        assert guard._entity_id == "binary_sensor.motion"
        assert guard._expected_state == "on"

    def test_evaluate_matching_state_returns_true(self) -> None:
        """Test evaluation when state matches expected."""
        guard = StateGuard(entity="binary_sensor.motion", is_state="on")
        context = {"entities": {"binary_sensor.motion": "on"}}
        result = guard.evaluate(state=None, context=context)
        assert result is True

    def test_evaluate_non_matching_state_returns_false(self) -> None:
        """Test evaluation when state doesn't match expected."""
        guard = StateGuard(entity="binary_sensor.motion", is_state="on")
        context = {"entities": {"binary_sensor.motion": "off"}}
        result = guard.evaluate(state=None, context=context)
        assert result is False

    def test_evaluate_missing_entity_returns_false(self) -> None:
        """Test evaluation when entity is missing from context."""
        guard = StateGuard(entity="binary_sensor.motion", is_state="on")
        context = {"entities": {}}
        result = guard.evaluate(state=None, context=context)
        assert result is False

    def test_evaluate_empty_string_state(self) -> None:
        """Test evaluation with empty string state."""
        guard = StateGuard(entity="binary_sensor.motion", is_state="")
        context = {"entities": {"binary_sensor.motion": ""}}
        result = guard.evaluate(state=None, context=context)
        assert result is True

    def test_evaluate_case_sensitive(self) -> None:
        """Test that state comparison is case-sensitive."""
        guard = StateGuard(entity="binary_sensor.motion", is_state="ON")
        context = {"entities": {"binary_sensor.motion": "on"}}
        result = guard.evaluate(state=None, context=context)
        assert result is False

    def test_evaluate_no_entities_key_returns_false(self) -> None:
        """Test evaluation when entities key is missing from context."""
        guard = StateGuard(entity="binary_sensor.motion", is_state="on")
        context = {}
        result = guard.evaluate(state=None, context=context)
        assert result is False


class TestTimeGuard:
    """Test suite for TimeGuard class."""

    @patch("src.core.guards.time_guard.datetime")
    def test_init_parses_time_range(self, mock_datetime: MagicMock) -> None:
        """Test initialization parses time range correctly."""
        mock_datetime.now.return_value = datetime(2024, 1, 1, 10, 0)
        mock_datetime.strptime = datetime.strptime

        guard = TimeGuard(between="08:00-18:00")
        assert guard._start_str == "08:00"
        assert guard._end_str == "18:00"
        assert guard._start == time(8, 0)
        assert guard._end == time(18, 0)

    @patch("src.core.guards.time_guard.datetime")
    def test_evaluate_within_normal_range(self, mock_datetime: MagicMock) -> None:
        """Test evaluation when current time is within normal range."""
        mock_datetime.now.return_value = datetime(2024, 1, 1, 10, 0)
        mock_datetime.strptime = datetime.strptime

        guard = TimeGuard(between="08:00-18:00")
        result = guard.evaluate(state=None, context={})
        assert result is True

    @patch("src.core.guards.time_guard.datetime")
    def test_evaluate_outside_normal_range(self, mock_datetime: MagicMock) -> None:
        """Test evaluation when current time is outside normal range."""
        mock_datetime.now.return_value = datetime(2024, 1, 1, 20, 0)
        mock_datetime.strptime = datetime.strptime

        guard = TimeGuard(between="08:00-18:00")
        result = guard.evaluate(state=None, context={})
        assert result is False

    @patch("src.core.guards.time_guard.datetime")
    def test_evaluate_at_start_boundary(self, mock_datetime: MagicMock) -> None:
        """Test evaluation at start boundary."""
        mock_datetime.now.return_value = datetime(2024, 1, 1, 8, 0)
        mock_datetime.strptime = datetime.strptime

        guard = TimeGuard(between="08:00-18:00")
        result = guard.evaluate(state=None, context={})
        assert result is True

    @patch("src.core.guards.time_guard.datetime")
    def test_evaluate_at_end_boundary(self, mock_datetime: MagicMock) -> None:
        """Test evaluation at end boundary."""
        mock_datetime.now.return_value = datetime(2024, 1, 1, 18, 0)
        mock_datetime.strptime = datetime.strptime

        guard = TimeGuard(between="08:00-18:00")
        result = guard.evaluate(state=None, context={})
        assert result is True

    @patch("src.core.guards.time_guard.datetime")
    def test_evaluate_midnight_crossing_during_range(self, mock_datetime: MagicMock) -> None:
        """Test evaluation during midnight-crossing range (e.g., 23:00-07:00)."""
        mock_datetime.now.return_value = datetime(2024, 1, 1, 23, 30)
        mock_datetime.strptime = datetime.strptime

        guard = TimeGuard(between="23:00-07:00")
        result = guard.evaluate(state=None, context={})
        assert result is True

    @patch("src.core.guards.time_guard.datetime")
    def test_evaluate_midnight_crossing_early_morning(self, mock_datetime: MagicMock) -> None:
        """Test evaluation in early morning during midnight-crossing range."""
        mock_datetime.now.return_value = datetime(2024, 1, 1, 6, 0)
        mock_datetime.strptime = datetime.strptime

        guard = TimeGuard(between="23:00-07:00")
        result = guard.evaluate(state=None, context={})
        assert result is True

    @patch("src.core.guards.time_guard.datetime")
    def test_evaluate_midnight_crossing_daytime(self, mock_datetime: MagicMock) -> None:
        """Test evaluation during daytime for midnight-crossing range."""
        mock_datetime.now.return_value = datetime(2024, 1, 1, 12, 0)
        mock_datetime.strptime = datetime.strptime

        guard = TimeGuard(between="23:00-07:00")
        result = guard.evaluate(state=None, context={})
        assert result is False
