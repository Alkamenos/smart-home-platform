"""
Export FSM CLI Command - Export FSM visualizations from manifest.

Provides CLI commands for generating Mermaid and Graphviz diagrams
from smart home manifest configurations.
"""

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml


if TYPE_CHECKING:
    from core.fsm import FSMDefinition


def load_manifest(manifest_path: str) -> dict[str, Any]:
    """
    Load and parse a YAML manifest file.

    Args:
        manifest_path: Path to the manifest YAML file.

    Returns:
        Parsed manifest as a dictionary.

    Raises:
        FileNotFoundError: If manifest file doesn't exist.
        yaml.YAMLError: If manifest is not valid YAML.
    """
    path = Path(manifest_path)
    if not path.exists():
        raise FileNotFoundError(f"Manifest file not found: {manifest_path}")

    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def generate_fsms_from_manifest(manifest: dict[str, Any]) -> list[tuple[str, FSMDefinition]]:
    """
    Generate FSM definitions from manifest.

    Args:
        manifest: Parsed manifest dictionary.

    Returns:
        List of tuples (device_id, fsm_definition).
    """
    from core.events.event_bus import EventBus
    from core.fsm import FSMEngine
    from core.fsm.factory import FSMFactory
    from core.models.manifest import BehaviorConfig
    from core.registry import Registry

    engine = FSMEngine()
    registry = Registry()
    event_bus = EventBus()
    factory = FSMFactory(
        engine=engine, registry=registry, features_dir="src/features", event_bus=event_bus
    )

    fsms: list[tuple[str, FSMDefinition]] = []

    # Process rooms and devices
    for room in manifest.get("rooms", []):
        for device in room.get("devices", []):
            device_id = device.get("id", "")
            for behavior_data in device.get("behaviors", []):
                behavior = BehaviorConfig(**behavior_data)
                fsm_defs = factory.create_from_behavior(
                    device_id=device_id,
                    behavior=behavior,
                )
                for fsm_def in fsm_defs:
                    fsms.append((device_id, fsm_def))

    return fsms


def cmd_export_fsm(args: argparse.Namespace) -> int:
    """
    Execute the export-fsm command.

    Args:
        args: Parsed command-line arguments.

    Returns:
        Exit code (0 for success, non-zero for error).
    """
    from core.fsm.visualizer import FSMVisualizer

    try:
        manifest = load_manifest(args.manifest)
    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    except yaml.YAMLError as e:
        print(f"Error parsing manifest: {e}", file=sys.stderr)
        return 1

    fsms = generate_fsms_from_manifest(manifest)

    if not fsms:
        print("No FSMs found in manifest.", file=sys.stderr)
        return 1

    visualizer = FSMVisualizer()

    # Filter by device if specified
    if args.device:
        fsms = [(dev_id, fsm) for dev_id, fsm in fsms if dev_id == args.device]
        if not fsms:
            print(f"No FSMs found for device: {args.device}", file=sys.stderr)
            return 1

    # Generate output
    if args.format == "mermaid":
        if len(fsms) == 1:
            device_id, fsm = fsms[0]
            output = visualizer.to_mermaid(fsm, device_id=device_id)
        else:
            device_ids = [dev_id for dev_id, _ in fsms]
            fsm_defs = [fsm for _, fsm in fsms]
            output = visualizer.to_mermaid_batch(fsm_defs, device_ids)
    elif args.format == "graphviz":
        if len(fsms) == 1:
            device_id, fsm = fsms[0]
            output = visualizer.to_graphviz(fsm, device_id=device_id)
        else:
            # For graphviz, output each FSM separately
            outputs = []
            for device_id, fsm in fsms:
                outputs.append(visualizer.to_graphviz(fsm, device_id=device_id))
            output = "\n\n".join(outputs)
    else:
        print(f"Unsupported format: {args.format}", file=sys.stderr)
        return 1

    # Output to file or stdout
    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(output)
        print(f"Exported to: {output_path}")
    else:
        print(output)

    return 0


def setup_export_fsm_parser(subparsers: Any) -> None:
    """
    Set up the export-fsm subcommand parser.

    Args:
        subparsers: ArgumentParser subparsers object.
    """
    parser = subparsers.add_parser(
        "export-fsm",
        help="Export FSM visualization from manifest",
        description="Generate Mermaid or Graphviz diagrams from smart home manifest",
    )

    parser.add_argument(
        "manifest",
        type=str,
        help="Path to the manifest YAML file",
    )

    parser.add_argument(
        "--format",
        "-f",
        type=str,
        choices=["mermaid", "graphviz"],
        default="mermaid",
        help="Output format (default: mermaid)",
    )

    parser.add_argument(
        "--device",
        "-d",
        type=str,
        help="Export only FSMs for specific device (e.g., light.kitchen)",
    )

    parser.add_argument(
        "--output",
        "-o",
        type=str,
        help="Output file path (default: stdout)",
    )

    parser.set_defaults(func=cmd_export_fsm)
