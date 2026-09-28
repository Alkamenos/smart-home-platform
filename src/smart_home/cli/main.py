"""
Smart Home CLI - Command-line interface for smart home platform.

Provides commands for managing, validating, and visualizing
smart home automation configurations.
"""

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import argparse
import sys


def main() -> int:
    """
    Main entry point for the smart-home CLI.

    Returns:
        Exit code (0 for success, non-zero for error).
    """
    parser = argparse.ArgumentParser(
        prog="smart-home",
        description="Smart Home FSM Platform CLI",
    )

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # Import and setup commands
    from .commands.bulk_import import setup_bulk_import_parser
    from .commands.export_fsm import setup_export_fsm_parser
    from .commands.shell import setup_shell_parser

    setup_bulk_import_parser(subparsers)
    setup_export_fsm_parser(subparsers)
    setup_shell_parser(subparsers)

    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        return 0

    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
