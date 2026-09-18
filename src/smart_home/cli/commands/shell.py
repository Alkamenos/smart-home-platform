"""
Interactive REPL Shell for Smart Home Platform.

Provides an interactive Python shell with pre-loaded platform components
for development and debugging purposes.
"""

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import argparse
import asyncio
import code
import sys
from typing import Any


def create_repl_context(manifest_path: str) -> dict[str, Any]:
    """
    Create a context dictionary with all platform components for the REPL.

    Args:
        manifest_path: Path to the manifest YAML file.

    Returns:
        Dictionary with platform components available in the REPL namespace.
    """
    import sys
    from pathlib import Path

    # Add src directory to path for imports
    src_dir = str(Path(__file__).parent.parent.parent)
    if src_dir not in sys.path:
        sys.path.insert(0, src_dir)

    from bootstrap import bootstrap_platform

    # Bootstrap the platform
    ctx = bootstrap_platform(manifest_path)

    # Create the REPL context with all important components
    repl_context: dict[str, Any] = {
        # Core components
        "engine": ctx.fsm,
        "event_bus": ctx.event_bus,
        "adapter": ctx.adapter,
        "dispatcher": ctx.dispatcher,
        "event_router": ctx.event_router,
        "control_tracker": ctx.control_tracker,
        # Manifest data
        "manifest": ctx.manifest,
        "rooms": ctx.manifest.rooms,
        "devices": ctx.manifest.devices,
        "zones": ctx.manifest.zones,
        # Helper functions
        "help": _create_repl_help(),
    }

    return repl_context


def _create_repl_help() -> callable:
    """
    Create a help function for the REPL.

    Returns:
        A function that prints available commands and components.
    """

    def repl_help() -> None:
        """Print available commands and components in the REPL."""
        help_text = """
Smart Home Platform REPL - Available Components:

Core Components:
  - engine:           FSMEngine instance for state machine management
  - event_bus:        EventBus for publishing/subscribing to events
  - adapter:          HAAdapter or MockAdapter for calling services
  - dispatcher:       CommandDispatcher with middleware chain
  - event_router:     EventRouter for routing sensor events to FSMs
  - control_tracker:  ControlTracker for tracking manual interventions

Manifest Data:
  - manifest:         Full manifest object
  - rooms:            List of rooms from manifest
  - devices:          List of devices from manifest
  - zones:            List of zones from manifest

Usage Examples:
  >>> await engine.trigger("binary_sensor.kitchen_motion", "motion_detected")
  >>> engine.get_state("light.kitchen_lighting_10")
  >>> await adapter.call_service("light", "turn_on", "light.kitchen")
  >>> event_router.get_mapping_for_sensor("binary_sensor.kitchen_motion")
  >>> dispatcher.active_sources

Type 'help(component)' for more information about a specific component.
"""
        print(help_text)

    return repl_help


async def run_async_repl(local_vars: dict[str, Any]) -> None:
    """
    Run an async-aware REPL loop.

    This function provides top-level await support in the REPL.

    Args:
        local_vars: Dictionary of variables to expose in the REPL namespace.
    """
    import readline  # noqa: F401  # pylint: disable=unused-import

    banner = """
╔═══════════════════════════════════════════════════════════╗
║         Smart Home Platform Interactive REPL              ║
╠═══════════════════════════════════════════════════════════╣
║ Type 'help()' for available components and usage examples ║
║ Type 'exit()' or Ctrl+D to exit                           ║
╚═══════════════════════════════════════════════════════════╝
"""

    # Create the interactive console with async support
    console = code.InteractiveConsole(locals=local_vars)

    # Print the banner
    print(banner)

    # Start the REPL loop
    try:
        console.interact(banner="")
    except (KeyboardInterrupt, SystemExit):
        print("\nExiting REPL...")


def cmd_shell(args: argparse.Namespace) -> int:
    """
    Execute the shell command.

    Args:
        args: Parsed command-line arguments.

    Returns:
        Exit code (0 for success, non-zero for error).
    """
    manifest_path = args.manifest

    try:
        # Create the REPL context
        repl_context = create_repl_context(manifest_path)

        # Add metadata to the context
        repl_context["__doc__"] = "Smart Home Platform REPL"

        # Run the REPL
        asyncio.run(run_async_repl(repl_context))

        return 0

    except FileNotFoundError as e:
        print(f"Error: Manifest file not found: {e}", file=sys.stderr)
        return 1
    except Exception as e:  # pylint: disable=broad-except
        print(f"Error initializing REPL: {e}", file=sys.stderr)
        return 1


def setup_shell_parser(subparsers: Any) -> None:
    """
    Set up the shell subcommand parser.

    Args:
        subparsers: ArgumentParser subparsers object.
    """
    parser = subparsers.add_parser(
        "shell",
        help="Start interactive REPL for development and debugging",
        description="Launch an interactive Python shell with pre-loaded platform components",
    )

    parser.add_argument(
        "--manifest",
        "-m",
        type=str,
        default="instances/leonids_house/manifest.yaml",
        help="Path to the manifest YAML file (default: instances/leonids_house/manifest.yaml)",
    )

    parser.set_defaults(func=cmd_shell)
