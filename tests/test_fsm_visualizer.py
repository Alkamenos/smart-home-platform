"""
Tests for FSM Visualizer module.

Tests cover Mermaid and Graphviz generation, file export,
and batch visualization functionality.
"""

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import os
import tempfile
from typing import Any

import pytest

from core.fsm.engine import FSMDefinition, Transition
from core.fsm.visualizer import FSMVisualizer


@pytest.fixture
def sample_transition() -> Transition:
    """Create a sample transition for testing."""
    return Transition(
        from_state="OFF",
        to_state="ON",
        trigger="motion_detected",
        timeout_sec=180,
    )


@pytest.fixture
def sample_fsm() -> FSMDefinition:
    """Create a sample FSM definition for testing."""

    def dummy_guard(ctx: dict[str, Any]) -> bool:
        return True

    def dummy_action(ctx: dict[str, Any]) -> None:
        pass

    return FSMDefinition(
        entity_id="light.kitchen_lighting_10",
        initial_state="OFF",
        states=("OFF", "ON", "TIMEOUT", "MANUAL"),
        transitions=(
            Transition(
                from_state="OFF",
                to_state="ON",
                trigger="motion_detected",
                timeout_sec=180,
            ),
            Transition(
                from_state="ON",
                to_state="TIMEOUT",
                trigger="timeout",
            ),
            Transition(
                from_state="TIMEOUT",
                to_state="OFF",
                trigger="timeout",
            ),
            Transition(
                from_state="*",
                to_state="MANUAL",
                trigger="manual_change",
                guard=dummy_guard,
                action=dummy_action,
            ),
            Transition(
                from_state="MANUAL",
                to_state="OFF",
                trigger="auto_release",
            ),
        ),
        debounce_sec=0.5,
        params={"brightness": 255},
    )


@pytest.fixture
def visualizer() -> FSMVisualizer:
    """Create a visualizer instance for testing."""
    return FSMVisualizer()


class TestFSMVisualizerMermaid:
    """Tests for Mermaid diagram generation."""

    def test_to_mermaid_should_generate_valid_header(
        self, visualizer: FSMVisualizer, sample_fsm: FSMDefinition
    ) -> None:
        """Test that Mermaid output starts with correct header."""
        result = visualizer.to_mermaid(sample_fsm)

        assert result.startswith("stateDiagram-v2")

    def test_to_mermaid_should_include_initial_state(
        self, visualizer: FSMVisualizer, sample_fsm: FSMDefinition
    ) -> None:
        """Test that initial state transition is included."""
        result = visualizer.to_mermaid(sample_fsm)

        assert "[*] --> OFF" in result

    def test_to_mermaid_should_format_transitions(
        self, visualizer: FSMVisualizer, sample_fsm: FSMDefinition
    ) -> None:
        """Test that transitions are formatted correctly."""
        result = visualizer.to_mermaid(sample_fsm)

        assert "OFF --> ON: motion_detected, timeout 180s" in result
        assert "ON --> TIMEOUT: timeout" in result
        assert "TIMEOUT --> OFF: timeout" in result

    def test_to_mermaid_should_handle_wildcard_state(
        self, visualizer: FSMVisualizer, sample_fsm: FSMDefinition
    ) -> None:
        """Test that wildcard state (*) is handled correctly."""
        result = visualizer.to_mermaid(sample_fsm)

        assert "any_state --> MANUAL: manual_change" in result

    def test_to_mermaid_with_device_id_should_add_title(
        self, visualizer: FSMVisualizer, sample_fsm: FSMDefinition
    ) -> None:
        """Test that device_id adds title to diagram."""
        result = visualizer.to_mermaid(sample_fsm, device_id="light.kitchen")

        assert "title light.kitchen" in result


class TestFSMVisualizerGraphviz:
    """Tests for Graphviz DOT generation."""

    def test_to_graphviz_should_generate_valid_header(
        self, visualizer: FSMVisualizer, sample_fsm: FSMDefinition
    ) -> None:
        """Test that Graphviz output starts with correct header."""
        result = visualizer.to_graphviz(sample_fsm)

        assert result.startswith("digraph FSM {")
        assert "rankdir=LR;" in result
        assert "node [shape=circle];" in result

    def test_to_graphviz_should_include_initial_node(
        self, visualizer: FSMVisualizer, sample_fsm: FSMDefinition
    ) -> None:
        """Test that initial invisible node is created."""
        result = visualizer.to_graphviz(sample_fsm)

        assert '""" [shape=point, width=0.5];' in result or '"" [shape=point' in result

    def test_to_graphviz_should_highlight_initial_state(
        self, visualizer: FSMVisualizer, sample_fsm: FSMDefinition
    ) -> None:
        """Test that initial state has double peripheries."""
        result = visualizer.to_graphviz(sample_fsm)

        assert "OFF [peripheries=2];" in result

    def test_to_graphviz_should_format_transitions(
        self, visualizer: FSMVisualizer, sample_fsm: FSMDefinition
    ) -> None:
        """Test that transitions are formatted correctly."""
        result = visualizer.to_graphviz(sample_fsm)

        assert 'OFF -> ON [label="motion_detected\\ntimeout 180s"]' in result

    def test_to_graphviz_should_include_guard_and_action(
        self, visualizer: FSMVisualizer, sample_fsm: FSMDefinition
    ) -> None:
        """Test that guard and action are noted in label."""
        result = visualizer.to_graphviz(sample_fsm)

        # Check that manual_change transition includes guard and action
        assert "guard" in result
        assert "action" in result

    def test_to_graphviz_with_device_id_should_add_label(
        self, visualizer: FSMVisualizer, sample_fsm: FSMDefinition
    ) -> None:
        """Test that device_id adds label to graph."""
        result = visualizer.to_graphviz(sample_fsm, device_id="light.kitchen")

        assert 'label="light.kitchen";' in result


class TestFSMVisualizerBatch:
    """Tests for batch visualization."""

    def test_to_mermaid_batch_should_generate_multiple_fsms(
        self, visualizer: FSMVisualizer, sample_fsm: FSMDefinition
    ) -> None:
        """Test batch generation with multiple FSMs."""
        fsm2 = FSMDefinition(
            entity_id="light.bedroom_lighting_10",
            initial_state="OFF",
            states=("OFF", "ON"),
            transitions=(
                Transition(
                    from_state="OFF",
                    to_state="ON",
                    trigger="motion_detected",
                ),
            ),
        )

        result = visualizer.to_mermaid_batch([sample_fsm, fsm2])

        assert "stateDiagram-v2" in result
        assert "title Smart Home FSM Overview" in result
        assert "%% light.kitchen_lighting_10" in result
        assert "%% light.bedroom_lighting_10" in result
        assert "light_kitchen_lighting_10_OFF" in result
        assert "light_bedroom_lighting_10_OFF" in result


class TestFSMVisualizerExport:
    """Tests for file export functionality."""

    def test_export_to_file_mermaid_should_create_file(
        self, visualizer: FSMVisualizer, sample_fsm: FSMDefinition
    ) -> None:
        """Test Mermaid file export."""
        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = os.path.join(tmpdir, "test_fsm")

            visualizer.export_to_file(sample_fsm, output_path, output_format="mermaid")

            expected_path = output_path + ".mmd"
            assert os.path.exists(expected_path)

            with open(expected_path, encoding="utf-8") as f:
                content = f.read()

            assert "stateDiagram-v2" in content

    def test_export_to_file_graphviz_should_create_file(
        self, visualizer: FSMVisualizer, sample_fsm: FSMDefinition
    ) -> None:
        """Test Graphviz file export."""
        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = os.path.join(tmpdir, "test_fsm")

            visualizer.export_to_file(sample_fsm, output_path, output_format="graphviz")

            expected_path = output_path + ".dot"
            assert os.path.exists(expected_path)

            with open(expected_path, encoding="utf-8") as f:
                content = f.read()

            assert "digraph FSM {" in content

    def test_export_to_file_invalid_format_should_raise(
        self, visualizer: FSMVisualizer, sample_fsm: FSMDefinition
    ) -> None:
        """Test that invalid format raises ValueError."""
        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = os.path.join(tmpdir, "test_fsm")

            with pytest.raises(ValueError, match="Unsupported format"):
                visualizer.export_to_file(sample_fsm, output_path, output_format="invalid")

    def test_export_to_file_preserves_extension(
        self, visualizer: FSMVisualizer, sample_fsm: FSMDefinition
    ) -> None:
        """Test that correct extension is preserved if already present."""
        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = os.path.join(tmpdir, "test_fsm.mmd")

            visualizer.export_to_file(sample_fsm, output_path, output_format="mermaid")

            assert os.path.exists(output_path)


class TestFormatMermaidTransition:
    """Tests for _format_mermaid_transition method."""

    def test_format_simple_transition(self, visualizer: FSMVisualizer) -> None:
        """Test formatting a simple transition."""
        transition = Transition(
            from_state="OFF",
            to_state="ON",
            trigger="button_pressed",
        )

        result = visualizer._format_mermaid_transition(transition)

        assert result == "OFF --> ON: button_pressed"

    def test_format_transition_with_timeout(self, visualizer: FSMVisualizer) -> None:
        """Test formatting transition with timeout."""
        transition = Transition(
            from_state="ON",
            to_state="OFF",
            trigger="timeout",
            timeout_sec=300,
        )

        result = visualizer._format_mermaid_transition(transition)

        assert result == "ON --> OFF: timeout, timeout 300s"


class TestFormatGraphvizTransition:
    """Tests for _format_graphviz_transition method."""

    def test_format_simple_transition(self, visualizer: FSMVisualizer) -> None:
        """Test formatting a simple transition."""
        transition = Transition(
            from_state="OFF",
            to_state="ON",
            trigger="button_pressed",
        )

        result = visualizer._format_graphviz_transition(transition)

        assert result == 'OFF -> ON [label="button_pressed"]'

    def test_format_transition_with_timeout(self, visualizer: FSMVisualizer) -> None:
        """Test formatting transition with timeout."""
        transition = Transition(
            from_state="ON",
            to_state="OFF",
            trigger="timeout",
            timeout_sec=300,
        )

        result = visualizer._format_graphviz_transition(transition)

        assert result == 'ON -> OFF [label="timeout\\ntimeout 300s"]'
