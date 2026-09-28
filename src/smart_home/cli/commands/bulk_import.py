"""
Bulk Import CLI Command - Import 200+ devices from Home Assistant.

Provides interactive CLI workflow for discovering, classifying, and importing
devices from Home Assistant into the smart home platform manifest.
"""

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path
from typing import Any

import yaml
from loguru import logger


__all__ = ["setup_bulk_import_parser", "handle_bulk_import_command"]


async def handle_bulk_import_command(args: argparse.Namespace) -> int:
    """Execute bulk import command."""
    try:
        manifest_path = args.manifest
        subcommand = args.subcommand

        if subcommand == "discover":
            return await _handle_discover(args, manifest_path)
        elif subcommand == "interactive":
            return await _handle_interactive(args, manifest_path)
        elif subcommand == "apply":
            return await _handle_apply(args, manifest_path)
        elif subcommand == "config":
            return await _handle_config(args, manifest_path)
        else:
            print(f"Unknown subcommand: {subcommand}")
            return 1

    except Exception as e:
        logger.error(f"Bulk import error: {e}")
        print(f"Error: {e}", file=sys.stderr)
        return 1


async def _handle_discover(args: argparse.Namespace, manifest_path: str) -> int:
    """Discover devices from Home Assistant."""
    from src.adapters.ha_adapter import HAAdapter
    from src.core.discovery.discovery_service import DeviceDiscoveryService

    # Initialize HA adapter
    ws_url = args.ws_url or "ws://localhost:8123/api/websocket"
    token = args.token or ""

    adapter = HAAdapter(
        mode="websocket",
        ws_url=ws_url,
        token=token,
    )

    await adapter.start()

    try:
        discovery = DeviceDiscoveryService(adapter)
        page = args.page or 1
        page_size = args.page_size or 25

        # Apply filters
        filter_domain = args.filter_domain
        filter_category = args.filter_category
        filter_area = args.filter_area

        result = await discovery.scan_devices(
            page=page,
            page_size=page_size,
            filter_domain=filter_domain,
            filter_category=filter_category,
            filter_area=filter_area,
        )

        # Display results
        _print_discover_results(result, args)
        return 0

    finally:
        await adapter.stop()


async def _handle_apply(args: argparse.Namespace, manifest_path: str) -> int:
    """Apply selected devices to manifest."""
    from src.adapters.ha_adapter import HAAdapter
    from src.core.discovery.discovery_service import DeviceDiscoveryService
    from src.core.discovery.models import BulkApplyRequest

    # Verify manifest exists
    if not Path(manifest_path).exists():
        print(f"Error: Manifest not found: {manifest_path}", file=sys.stderr)
        return 1

    # Initialize HA adapter
    ws_url = args.ws_url or "ws://localhost:8123/api/websocket"
    token = args.token or ""

    adapter = HAAdapter(
        mode="websocket",
        ws_url=ws_url,
        token=token,
    )

    await adapter.start()

    try:
        discovery = DeviceDiscoveryService(adapter)

        # Build request
        request = BulkApplyRequest(
            include_all=args.include_all or False,
            auto_apply_lighting=args.auto_apply_lighting or False,
            auto_apply_climate=args.auto_apply_climate or False,
            auto_apply_ventilation=args.auto_apply_ventilation or False,
            dry_run=args.dry_run or False,
        )

        result = await discovery.bulk_apply(request, manifest_path)

        # Display results
        _print_apply_results(result, args)
        return 0

    finally:
        await adapter.stop()


async def _handle_config(args: argparse.Namespace, manifest_path: str) -> int:
    """Show or update configuration."""
    config_file = Path.home() / ".config" / "smart_home" / "bulk_import.yaml"

    if args.show:
        if config_file.exists():
            with open(config_file) as f:
                print(f.read())
        else:
            print("No configuration found. Use --set to create one.")
        return 0

    # TODO: Implement --set for config management
    return 0


def _print_discover_results(result: dict[str, Any], args: argparse.Namespace) -> None:
    """Pretty-print discovery results."""
    total = result.get("total", 0)
    page = result.get("page", 1)
    total_pages = result.get("total_pages", 1)
    devices = result.get("devices", [])

    print("\n📱 Device Discovery Results")
    print(f"{'=' * 70}")
    print(f"Total devices: {total}")
    print(f"Page: {page}/{total_pages}")
    print()

    # Summary by domain
    by_domain = result.get("by_domain", {})
    if by_domain:
        print("By Domain:")
        for domain, count in sorted(by_domain.items()):
            print(f"  {domain:20} {count:3} devices")
        print()

    # Summary by category
    by_category = result.get("by_category", {})
    if by_category:
        print("By Category:")
        for category, count in sorted(by_category.items()):
            print(f"  {category:25} {count:3} devices")
        print()

    # Auto-apply statistics
    auto_stats = result.get("auto_apply_stats", {})
    if auto_stats:
        auto_count = auto_stats.get("auto_apply", 0)
        manual_count = auto_stats.get("manual", 0)
        print(f"Auto-apply Ready: {auto_count} devices")
        print(f"Manual Review: {manual_count} devices")
        print()

    # Device list
    if devices:
        print(f"{'Entity ID':<35} {'Category':<20} {'Behavior':<20}")
        print("-" * 75)
        for device in devices[:10]:  # Show first 10
            entity_id = device.get("entity_id", "")
            category = device.get("category", "")
            behavior = device.get("suggested_behavior", "-")
            print(f"{entity_id:<35} {category:<20} {behavior:<20}")

        if len(devices) > 10:
            print(f"... and {len(devices) - 10} more")

    # Navigation
    print()
    if page < total_pages:
        print(f"💡 Tip: Use --page {page + 1} to see next page")


def _print_apply_results(result: dict[str, Any], args: argparse.Namespace) -> None:
    """Pretty-print apply results."""
    is_dry_run = result.get("dry_run", False)
    success = result.get("success", False)
    devices_added = result.get("devices_added", 0)
    backup_path = result.get("backup_path", "")

    if is_dry_run:
        would_add = result.get("would_add", 0)
        print("\n🔍 Dry Run Results")
        print(f"{'=' * 70}")
        print(f"Would add {would_add} devices to manifest")
        print()
        print("💡 Run without --dry-run to apply changes")
    else:
        print("\n✅ Apply Results")
        print(f"{'=' * 70}")
        if success:
            print(f"✓ Successfully added {devices_added} devices")
            if backup_path:
                print(f"✓ Backup created: {backup_path}")
            print()
            print("💡 Next steps:")
            print("  1. Review the updated manifest")
            print("  2. Adjust parameters as needed")
            print("  3. Run 'smart-home export-fsm' to visualize FSMs")
        else:
            print("✗ Failed to apply changes")
            failed = result.get("failed", 0)
            if failed > 0:
                print(f"  {failed} devices failed")


def _load_existing_rooms(manifest_path: str) -> list[dict]:
    """Load existing rooms from manifest."""
    if not Path(manifest_path).exists():
        return []

    with open(manifest_path) as f:
        manifest = yaml.safe_load(f) or {}

    return manifest.get("rooms", [])


def _get_room_choice(device: dict, existing_rooms: list[dict]) -> str:
    """Interactively ask user to choose or create a room."""
    entity_id = device.get("entity_id", "")
    suggested_room = device.get("area_id") or "unassigned"

    # Get list of existing rooms
    room_ids = [r["id"] for r in existing_rooms] if existing_rooms else []

    print(f"\n📦 {entity_id}")
    print(f"   Category: {device.get('category')}")
    print(f"   Suggested room: {suggested_room}")

    if room_ids:
        print("\n   Available rooms:")
        for i, room_id in enumerate(room_ids, 1):
            print(f"     {i}. {room_id}")
        print(f"     {len(room_ids) + 1}. {suggested_room} (suggested)")
        print(f"     {len(room_ids) + 2}. <enter new room name>")

        while True:
            try:
                choice = input(f"\n   Choose room [1-{len(room_ids) + 2}]: ").strip()
                choice_num = int(choice)

                if 1 <= choice_num <= len(room_ids):
                    return room_ids[choice_num - 1]
                elif choice_num == len(room_ids) + 1:
                    return suggested_room
                elif choice_num == len(room_ids) + 2:
                    new_room = input("   Enter new room name: ").strip().lower().replace(" ", "_")
                    return new_room or "unassigned"
                else:
                    print(f"   Invalid choice. Please enter 1-{len(room_ids) + 2}")
            except ValueError:
                print("   Invalid input. Please enter a number.")
    else:
        # No existing rooms
        print(f"\n   1. {suggested_room} (suggested)")
        print("   2. <enter new room name>")

        while True:
            try:
                choice = input("\n   Choose room [1-2]: ").strip()
                choice_num = int(choice)

                if choice_num == 1:
                    return suggested_room
                elif choice_num == 2:
                    new_room = input("   Enter new room name: ").strip().lower().replace(" ", "_")
                    return new_room or suggested_room
                else:
                    print("   Invalid choice. Please enter 1 or 2")
            except ValueError:
                print("   Invalid input. Please enter a number.")


async def _handle_interactive(args: argparse.Namespace, manifest_path: str) -> int:
    """Interactive mode for selecting devices and rooms."""
    from src.adapters.ha_adapter import HAAdapter
    from src.core.discovery.discovery_service import DeviceDiscoveryService

    # Verify manifest exists
    if not Path(manifest_path).exists():
        print(f"Error: Manifest not found: {manifest_path}", file=sys.stderr)
        return 1

    # Load existing rooms
    existing_rooms = _load_existing_rooms(manifest_path)

    # Initialize HA adapter
    ws_url = args.ws_url or "ws://localhost:8123/api/websocket"
    token = args.token or ""

    adapter = HAAdapter(
        mode="websocket",
        ws_url=ws_url,
        token=token,
    )

    await adapter.start()

    try:
        discovery = DeviceDiscoveryService(adapter)

        # Scan all devices
        print("\n🔍 Scanning Home Assistant devices...")
        result = await discovery.scan_devices(page=1, page_size=10000)
        all_devices = result.get("devices", [])

        print(f"\n📱 Found {len(all_devices)} devices")
        print(f"{'=' * 70}")

        # Interactive selection
        selections = []

        for i, device in enumerate(all_devices, 1):
            print(f"\n[{i}/{len(all_devices)}]")

            # Ask if user wants to include this device
            entity_id = device.get("entity_id", "")
            category = device.get("category", "unknown")

            include = input(f"Add {entity_id} ({category})? [y/n]: ").strip().lower()
            if include != "y":
                continue

            # Ask for room
            target_room = _get_room_choice(device, existing_rooms)

            # Ask for behavior template
            suggested_behavior = device.get("suggested_behavior")
            if suggested_behavior:
                use_suggested = (
                    input(f"   Use suggested behavior '{suggested_behavior}'? [y/n]: ")
                    .strip()
                    .lower()
                )
                behavior = suggested_behavior if use_suggested == "y" else None
            else:
                behavior = None

            selection = {
                "device_entity_id": entity_id,
                "include": True,
                "target_room": target_room,
                "behavior_template": behavior,
            }
            selections.append(selection)

            # Add room to existing_rooms if new
            if not any(r["id"] == target_room for r in existing_rooms):
                existing_rooms.append(
                    {
                        "id": target_room,
                        "name": target_room.replace("_", " ").title(),
                    }
                )

        if not selections:
            print("\n⚠️  No devices selected")
            return 0

        separator = "=" * 70
        print(f"\n{separator}")
        print(f"✓ Selected {len(selections)} devices")

        # Dry-run first
        print("\n🔍 Preview (dry-run)...")
        dry_result = await discovery.apply_selective(selections, manifest_path, dry_run=True)
        print(f"Would add {dry_result.get('would_add', 0)} devices")

        # Ask for confirmation
        apply_now = input("\nApply changes? [y/n]: ").strip().lower()
        if apply_now != "y":
            print("Cancelled.")
            return 0

        # Apply for real
        print("\n💾 Applying changes...")
        result = await discovery.apply_selective(selections, manifest_path, dry_run=False)

        if result.get("success"):
            print(f"✓ Successfully added {result.get('devices_added', 0)} devices")
            if result.get("backup_path"):
                print(f"✓ Backup: {result.get('backup_path')}")
        else:
            print("✗ Failed to apply changes")
            return 1

        return 0

    finally:
        await adapter.stop()


def setup_bulk_import_parser(subparsers: argparse._SubParsersAction) -> None:
    """Setup bulk-import subcommand parser."""
    parser = subparsers.add_parser(
        "bulk-import",
        help="Bulk import devices from Home Assistant",
        description="Discover, classify, and import 200+ devices from HA into manifest",
    )

    parser.add_argument(
        "-m",
        "--manifest",
        required=True,
        help="Path to manifest YAML file",
    )

    subparsers_import = parser.add_subparsers(
        dest="subcommand",
        help="Subcommand",
        required=True,
    )

    # interactive subcommand (recommended)
    interactive = subparsers_import.add_parser(
        "interactive",
        help="Interactive mode: select devices and assign to rooms",
    )
    interactive.add_argument(
        "--ws-url",
        default="ws://localhost:8123/api/websocket",
        help="WebSocket URL for HA",
    )
    interactive.add_argument(
        "--token",
        help="Long-lived access token for HA",
    )
    interactive.set_defaults(func=lambda args: asyncio.run(handle_bulk_import_command(args)))

    # discover subcommand
    discover = subparsers_import.add_parser(
        "discover",
        help="Scan and display devices from Home Assistant",
    )
    discover.add_argument("--page", type=int, default=1, help="Page number (default: 1)")
    discover.add_argument(
        "--page-size",
        type=int,
        default=25,
        help="Devices per page (default: 25)",
    )
    discover.add_argument(
        "--filter-domain",
        help="Filter by domain (e.g., light, switch)",
    )
    discover.add_argument(
        "--filter-category",
        help="Filter by category (lighting, climate_control, ventilation)",
    )
    discover.add_argument(
        "--filter-area",
        help="Filter by HA area",
    )
    discover.add_argument(
        "--ws-url",
        default="ws://localhost:8123/api/websocket",
        help="WebSocket URL for HA",
    )
    discover.add_argument(
        "--token",
        help="Long-lived access token for HA",
    )
    discover.set_defaults(func=lambda args: asyncio.run(handle_bulk_import_command(args)))

    # apply subcommand
    apply = subparsers_import.add_parser(
        "apply",
        help="Apply devices to manifest",
    )
    apply.add_argument(
        "--include-all",
        action="store_true",
        help="Include all discovered devices",
    )
    apply.add_argument(
        "--auto-apply-lighting",
        action="store_true",
        help="Auto-apply lighting behavior template",
    )
    apply.add_argument(
        "--auto-apply-climate",
        action="store_true",
        help="Auto-apply climate control behavior template",
    )
    apply.add_argument(
        "--auto-apply-ventilation",
        action="store_true",
        help="Auto-apply ventilation behavior template",
    )
    apply.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be added without modifying",
    )
    apply.add_argument(
        "--ws-url",
        default="ws://localhost:8123/api/websocket",
        help="WebSocket URL for HA",
    )
    apply.add_argument(
        "--token",
        help="Long-lived access token for HA",
    )
    apply.set_defaults(func=lambda args: asyncio.run(handle_bulk_import_command(args)))

    # config subcommand
    config = subparsers_import.add_parser(
        "config",
        help="Manage bulk import configuration",
    )
    config.add_argument(
        "--show",
        action="store_true",
        help="Show current configuration",
    )
    config.set_defaults(func=lambda args: asyncio.run(handle_bulk_import_command(args)))

    parser.set_defaults(func=lambda args: asyncio.run(handle_bulk_import_command(args)))
