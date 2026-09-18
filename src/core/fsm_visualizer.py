"""
FSM Visualizer - Generate visual representations of FSM state machines.

Supports Mermaid and Graphviz formats for easy visualization of
state machines defined in the manifest.
"""

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from core.fsm import FSMDefinition, Transition


class FSMVisualizer:
    """
    Generate visual representations of FSM state machines.

    Supports multiple output formats:
    - Mermaid: Text-based diagram syntax for web rendering
    - Graphviz DOT: Graph description language for graphviz tools

    Example:
        >>> visualizer = FSMVisualizer()
        >>> mermaid_output = visualizer.to_mermaid(fsm_definition)
        >>> dot_output = visualizer.to_graphviz(fsm_definition)
    """

    def to_mermaid(self, fsm: FSMDefinition, device_id: str | None = None) -> str:
        """
        Generate Mermaid state diagram from FSM definition.

        Args:
            fsm: The FSM definition to visualize.
            device_id: Optional device ID to include in diagram title.

        Returns:
            Mermaid state diagram syntax as a string.

        Example:
            >>> mermaid = visualizer.to_mermaid(fsm)
            >>> print(mermaid)
            stateDiagram-v2
                [*] --> OFF
                OFF --> ON: motion_detected
        """
        lines: list[str] = []
        lines.append("stateDiagram-v2")

        # Add title if device_id provided
        if device_id:
            lines.append(f"    title {device_id}")

        # Add initial state transition
        lines.append(f"    [*] --> {fsm.initial_state}")

        # Add all transitions
        for transition in fsm.transitions:
            transition_line = self._format_mermaid_transition(transition)
            lines.append(f"    {transition_line}")

        return "\n".join(lines)

    def _format_mermaid_transition(self, transition: Transition) -> str:
        """
        Format a single transition as Mermaid syntax.

        Args:
            transition: The transition to format.

        Returns:
            Formatted transition string.
        """
        from_state = transition.from_state
        to_state = transition.to_state
        trigger = transition.trigger

        # Handle wildcard states
        from_state_str = "any_state" if from_state == "*" else str(from_state)

        # Build label with trigger and optional timeout
        label_parts = [trigger]
        if transition.timeout_sec:
            label_parts.append(f"timeout {transition.timeout_sec}s")

        label = ", ".join(label_parts)

        return f"{from_state_str} --> {to_state}: {label}"

    def to_graphviz(self, fsm: FSMDefinition, device_id: str | None = None) -> str:
        """
        Generate Graphviz DOT representation from FSM definition.

        Args:
            fsm: The FSM definition to visualize.
            device_id: Optional device ID to include in graph label.

        Returns:
            Graphviz DOT syntax as a string.

        Example:
            >>> dot = visualizer.to_graphviz(fsm)
            >>> print(dot)
            digraph FSM {
                rankdir=LR;
                node [shape=circle];
                "" [shape=point];
                "" -> OFF;
                OFF -> ON [label="motion_detected"];
            }
        """
        lines: list[str] = []
        lines.append("digraph FSM {")
        lines.append("    rankdir=LR;")
        lines.append("    node [shape=circle];")

        # Add title/label if device_id provided
        if device_id:
            lines.append(f'    label="{device_id}";')
            lines.append("    labelloc=t;")

        # Add initial state node (invisible point)
        lines.append('    "" [shape=point, width=0.5];')

        # Add initial state transition
        lines.append(f'    "" -> {fsm.initial_state};')

        # Add all states as nodes
        for state in fsm.states:
            # Highlight initial state
            if state == fsm.initial_state:
                lines.append(f'    {state} [peripheries=2];')

        # Add all transitions
        for transition in fsm.transitions:
            transition_line = self._format_graphviz_transition(transition)
            lines.append(f"    {transition_line};")

        lines.append("}")
        return "\n".join(lines)

    def _format_graphviz_transition(self, transition: Transition) -> str:
        """
        Format a single transition as Graphviz DOT syntax.

        Args:
            transition: The transition to format.

        Returns:
            Formatted transition string.
        """
        from_state = transition.from_state
        to_state = transition.to_state
        trigger = transition.trigger

        # Handle wildcard states
        from_state_str = "any_state" if from_state == "*" else str(from_state)

        # Build label with trigger and optional info
        label_parts = [trigger]
        if transition.timeout_sec:
            label_parts.append(f"timeout {transition.timeout_sec}s")
        if transition.guard:
            label_parts.append("guard")
        if transition.action:
            label_parts.append("action")

        label = "\\n".join(label_parts)

        return f'{from_state_str} -> {to_state} [label="{label}"]'

    def to_mermaid_batch(
        self, fsms: list[FSMDefinition], device_ids: list[str] | None = None
    ) -> str:
        """
        Generate Mermaid diagram for multiple FSMs.

        Args:
            fsms: List of FSM definitions to visualize.
            device_ids: Optional list of device IDs corresponding to each FSM.

        Returns:
            Combined Mermaid state diagram syntax.
        """
        lines: list[str] = []
        lines.append("stateDiagram-v2")
        lines.append("    title Smart Home FSM Overview")

        for idx, fsm in enumerate(fsms):
            device_id = device_ids[idx] if device_ids and idx < len(device_ids) else fsm.entity_id

            # Add subgraph for each FSM
            safe_name = fsm.entity_id.replace(".", "_").replace("-", "_")
            lines.append(f"\n    subgraph {safe_name}")
            lines.append("        direction TB")
            lines.append(f"        note right of {fsm.initial_state}: {device_id}")

            # Add initial state
            lines.append(f"        [*] --> {fsm.initial_state}")

            # Add transitions
            for transition in fsm.transitions:
                transition_line = self._format_mermaid_transition(transition)
                lines.append(f"        {transition_line}")

            lines.append("    end")

        return "\n".join(lines)

    def export_to_file(
        self,
        fsm: FSMDefinition,
        output_path: str,
        output_format: str = "mermaid",
        device_id: str | None = None,
    ) -> None:
        """
        Export FSM visualization to a file.

        Args:
            fsm: The FSM definition to visualize.
            output_path: Path to the output file.
            output_format: Output format ('mermaid' or 'graphviz').
            device_id: Optional device ID for the diagram title.

        Raises:
            ValueError: If format is not supported.
        """
        if output_format == "mermaid":
            content = self.to_mermaid(fsm, device_id)
            suffix = ".mmd"
        elif output_format == "graphviz":
            content = self.to_graphviz(fsm, device_id)
            suffix = ".dot"
        else:
            raise ValueError(f"Unsupported format: {output_format}. Use 'mermaid' or 'graphviz'.")

        # Ensure correct extension
        if not output_path.endswith(suffix):
            output_path = output_path + suffix

        with open(output_path, "w", encoding="utf-8") as f:
            f.write(content)
