"""CLI command for importing devices from Home Assistant."""

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from loguru import logger


if TYPE_CHECKING:
    pass


def setup_import_devices_parser(subparsers: argparse._SubParsersAction) -> None:
    """Set up the import-devices command parser."""
    parser = subparsers.add_parser(
        "import-devices",
        help="Import devices from Home Assistant into the manifest",
        description=(
            "Import devices from a Home Assistant instance into the smart home manifest. "
            "Supports dry-run mode, area filtering, and technical entity inclusion."
        ),
    )

    parser.add_argument(
        "instance_id",
        help="Home Assistant instance ID in the manifest",
    )

    parser.add_argument(
        "--area",
        "-a",
        dest="area_id",
        default=None,
        help="Import only from specific area (by area ID)",
    )

    parser.add_argument(
        "--dry-run",
        "-n",
        action="store_true",
        help="Show what would be imported without saving changes",
    )

    parser.add_argument(
        "--include-technical",
        "-t",
        action="store_true",
        help="Include technical entities (sensors, binary_sensors, etc.)",
    )

    parser.add_argument(
        "--output",
        "-o",
        dest="output_file",
        default=None,
        type=Path,
        help="Save import results to JSON file",
    )

    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Enable verbose output",
    )

    parser.add_argument(
        "--manifest",
        "-m",
        dest="manifest_path",
        default="manifest.yaml",
        help="Path to manifest YAML file (default: manifest.yaml)",
    )

    parser.set_defaults(func=import_devices_command)


async def import_devices_command(args: argparse.Namespace) -> int:
    """Execute the import-devices command."""
    from src.adapters.ha_adapter import HAAdapter
    from src.services.device_import import DeviceImportService
    from src.webui.app import ManifestStore

    # Configure logging
    if args.verbose:
        logger.remove()
        logger.add(sys.stderr, level="DEBUG")

    try:
        # Initialize manifest store
        manifest_path = Path(args.manifest_path)
        if not manifest_path.exists():
            logger.error(f"Manifest file not found: {manifest_path}")
            return 1

        manifest_store = ManifestStore(str(manifest_path))

        # Initialize HA adapter
        # For CLI, we need to get HA connection details from config or environment
        # This is a simplified version - in production, you'd load from secrets/config
        ha_url = None
        ha_token = None

        # Try to load from environment or config file
        import os

        ha_url = os.environ.get("HA_WS_URL", "ws://localhost:8123/api/websocket")
        ha_token = os.environ.get("HA_TOKEN")

        if not ha_token:
            # Try to load from secrets file
            secrets_path = manifest_path.parent / "secrets.yaml"
            if secrets_path.exists():
                import yaml

                with open(secrets_path) as f:
                    secrets = yaml.safe_load(f) or {}
                    ha_token = secrets.get("ha_token")

        if not ha_token:
            logger.error(
                "Home Assistant token not found. "
                "Set HA_TOKEN environment variable or add ha_token to secrets.yaml"
            )
            return 1

        # Create HA adapter in websocket mode
        ha_adapter = HAAdapter(
            mode="websocket",
            ws_url=ha_url,
            token=ha_token,
        )

        # Start adapter connection
        await ha_adapter.start()

        # Wait for connection
        import asyncio

        max_wait = 10
        waited = 0.0
        while not ha_adapter.is_connected and waited < max_wait:
            await asyncio.sleep(0.5)
            waited += 0.5

        if not ha_adapter.is_connected:
            logger.error("Failed to connect to Home Assistant")
            return 1

        logger.info("Connected to Home Assistant")

        # Create import service
        import_service = DeviceImportService(
            ha_adapter=ha_adapter,
            manifest_store=manifest_store,
        )

        # Run import
        summary = await import_service.import_devices(
            instance_id=args.instance_id,
            area_id=args.area_id,
            dry_run=args.dry_run,
            include_technical=args.include_technical,
        )

        # Print results
        print("\n=== Import Summary ===")
        print(f"Total devices processed: {summary.total}")
        print(f"  New:       {summary.new}")
        print(f"  Updated:   {summary.updated}")
        print(f"  Skipped:   {summary.skipped}")
        print(f"  Errors:    {summary.errors}")
        print(f"Dry run:     {summary.dry_run}")
        print(f"Timestamp:   {summary.timestamp.isoformat()}")

        if summary.devices:
            print("\n=== Device Details ===")
            for device in summary.devices:
                status_icon = {
                    "new": "✨",
                    "updated": "🔄",
                    "skipped": "⏭️",
                    "error": "❌",
                }.get(device.status, "•")

                print(f"{status_icon} {device.device_name} ({device.device_id})")
                print(f"   Status: {device.status}")
                if device.message:
                    print(f"   Message: {device.message}")
                if device.capabilities:
                    print(f"   Capabilities: {', '.join(device.capabilities)}")
                print()

        # Save to file if requested
        if args.output_file:
            output_data = {
                "summary": {
                    "total": summary.total,
                    "new": summary.new,
                    "updated": summary.updated,
                    "skipped": summary.skipped,
                    "errors": summary.errors,
                    "dry_run": summary.dry_run,
                    "timestamp": summary.timestamp.isoformat(),
                },
                "devices": [
                    {
                        "device_id": d.device_id,
                        "device_name": d.device_name,
                        "status": d.status,
                        "message": d.message,
                        "external_ids": d.external_ids,
                        "capabilities": d.capabilities,
                    }
                    for d in summary.devices
                ],
            }

            with open(args.output_file, "w") as f:
                json.dump(output_data, f, indent=2)

            logger.info(f"Results saved to {args.output_file}")

        # Cleanup
        await ha_adapter.stop()

        return 0 if summary.errors == 0 else 1

    except Exception as e:
        logger.error(f"Import failed: {e}")
        if args.verbose:
            import traceback

            traceback.print_exc()
        return 1
