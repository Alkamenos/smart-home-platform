"""
Device Import Service for Smart Home Platform.

This module provides services for importing devices from Home Assistant
into the platform manifest with idempotency, domain mapping, and import statuses.
"""

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Literal

from loguru import logger


if TYPE_CHECKING:
    from src.adapters.ha_adapter import HAAdapter
    from src.core.models.manifest import Manifest
    from src.webui.app import ManifestStore


@dataclass
class DeviceImportResult:
    """Result of importing a single device."""

    device_id: str
    device_name: str
    status: Literal["new", "updated", "skipped", "error"]
    message: str | None = None
    external_ids: dict[str, str] | None = None
    capabilities: list[str] | None = None


@dataclass
class ImportSummary:
    """Summary of device import operation."""

    total: int = 0
    new: int = 0
    updated: int = 0
    skipped: int = 0
    errors: int = 0
    devices: list[DeviceImportResult] = field(default_factory=list)
    dry_run: bool = False
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))

    def add_result(self, result: DeviceImportResult) -> None:
        """Add import result to summary."""
        self.devices.append(result)
        self.total += 1

        if result.status == "new":
            self.new += 1
        elif result.status == "updated":
            self.updated += 1
        elif result.status == "skipped":
            self.skipped += 1
        elif result.status == "error":
            self.errors += 1


class DomainMapper:
    """Mapper for Home Assistant domains to platform capabilities."""

    # Primary domains - create separate devices in manifest
    PRIMARY_DOMAINS: dict[str, list[str]] = {
        "light": ["light"],
        "switch": ["switch"],
        "cover": ["cover"],
        "climate": ["climate"],
        "fan": ["fan"],
        "lock": ["lock"],
        "siren": ["siren"],
        "scene": ["scene"],
        "button": ["button"],
        "input_boolean": ["switch"],
        "input_button": ["button"],
        "input_select": ["select"],
    }

    # Technical domains - imported only if include_technical=True
    TECHNICAL_DOMAINS: dict[str, list[str]] = {
        "sensor": ["sensor"],
        "binary_sensor": ["binary_sensor"],
        "number": ["number"],
        "select": ["select"],
        "text": ["text"],
        "date": ["date"],
        "datetime": ["datetime"],
        "time": ["time"],
    }

    # Excluded domains - never imported
    EXCLUDED_DOMAINS: set[str] = {
        "automation",
        "script",
        "zone",
        "person",
        "device_tracker",
        "geo_location",
        "sun",
        "weather",
        "map",
        "camera",
        "image",
        "media_player",  # Requires special handling
        "remote",
        "stt",
        "tts",
        "notify",
    }

    def get_capabilities(self, entity_domain: str) -> list[str]:
        """
        Get platform capabilities for an HA entity domain.

        Args:
            entity_domain: HA entity domain (e.g., 'light', 'switch')

        Returns:
            List of platform capabilities
        """
        # Check primary domains
        if entity_domain in self.PRIMARY_DOMAINS:
            return self.PRIMARY_DOMAINS[entity_domain].copy()

        # Check technical domains
        if entity_domain in self.TECHNICAL_DOMAINS:
            return self.TECHNICAL_DOMAINS[entity_domain].copy()

        # Unknown domain - log warning and return empty
        logger.warning(f"Unknown HA domain: {entity_domain}")
        return []

    def should_import_entity(
        self,
        entity_domain: str,
        include_technical: bool = False,
    ) -> bool:
        """
        Check if an entity of given domain should be imported.

        Args:
            entity_domain: HA entity domain
            include_technical: Whether to include technical domains

        Returns:
            True if entity should be imported
        """
        # Check if excluded
        if entity_domain in self.EXCLUDED_DOMAINS:
            return False

        # Check if primary domain
        if entity_domain in self.PRIMARY_DOMAINS:
            return True

        # Check if technical domain
        if entity_domain in self.TECHNICAL_DOMAINS:
            return include_technical

        # Unknown domain - don't import
        return False

    def is_primary_device(self, entity_domain: str) -> bool:
        """
        Check if domain represents a primary device.

        Primary devices are created as separate devices in manifest.
        Technical entities are added as capabilities to existing devices.

        Args:
            entity_domain: HA entity domain

        Returns:
            True if domain is a primary device domain
        """
        return entity_domain in self.PRIMARY_DOMAINS


class DeviceImportService:
    """Service for importing devices from Home Assistant."""

    def __init__(
        self,
        ha_adapter: HAAdapter,
        manifest_store: ManifestStore,
        domain_mapper: DomainMapper | None = None,
    ):
        self.ha_adapter = ha_adapter
        self.manifest_store = manifest_store
        self.domain_mapper = domain_mapper or DomainMapper()

    async def import_devices(
        self,
        instance_id: str,
        area_id: str | None = None,
        dry_run: bool = False,
        include_technical: bool = False,
    ) -> ImportSummary:
        """
        Import devices from Home Assistant into the manifest.

        Args:
            instance_id: HA instance ID in the manifest
            area_id: Optional, import only from specific area
            dry_run: If True, don't save changes
            include_technical: Include technical entities (sensors, binary_sensor)

        Returns:
            ImportSummary with import results
        """
        logger.info(f"Starting device import for instance {instance_id}")

        summary = ImportSummary(dry_run=dry_run)

        try:
            # Get data from HA
            areas = await self.ha_adapter.get_areas()
            devices = await self.ha_adapter.get_devices(area_id=area_id)
            entities = await self.ha_adapter.get_entities()

            logger.debug(f"Found {len(devices)} devices in HA")

            # Group entities by device_id
            from collections import defaultdict

            device_entities = defaultdict(list)
            for entity in entities:
                if entity.device_id:
                    device_entities[entity.device_id].append(entity)

            # Get manifest
            if self.manifest_store.current is None:
                await self.manifest_store.load()

            manifest = self.manifest_store.current

            # Find or create room mapping
            area_to_room = {}
            for area in areas:
                # Try to find existing room with same name
                room = next(
                    (r for r in manifest.rooms if r.name.lower() == area.name.lower()), None
                )
                if room:
                    area_to_room[area.id] = room.id
                else:
                    # Create new room
                    from src.core.models.manifest import RoomConfig

                    room_id = area.id.replace("_", "-").lower()
                    room = RoomConfig(id=room_id, name=area.name)
                    if not dry_run:
                        manifest.rooms.append(room)
                    area_to_room[area.id] = room_id

            # Process each device
            for ha_device in devices:
                try:
                    result = await self._process_device(
                        ha_device=ha_device,
                        device_entities=device_entities.get(ha_device.id, []),
                        manifest=manifest,
                        area_to_room=area_to_room,
                        instance_id=instance_id,
                        include_technical=include_technical,
                        dry_run=dry_run,
                    )
                    summary.add_result(result)
                except Exception as e:
                    logger.error(f"Failed to import device {ha_device.id}: {e}")
                    summary.add_result(
                        DeviceImportResult(
                            device_id=ha_device.id,
                            device_name=ha_device.name or "Unknown",
                            status="error",
                            message=str(e),
                        )
                    )

            # Save manifest if not dry run
            if not dry_run:
                self.manifest_store.save()
                logger.info(
                    f"Import complete: {summary.new} new, {summary.updated} updated, "
                    f"{summary.skipped} skipped, {summary.errors} errors"
                )
            else:
                logger.info(
                    f"Dry run complete: {summary.new} would be new, "
                    f"{summary.updated} would be updated"
                )

        except Exception as e:
            logger.error(f"Import failed: {e}")
            raise

        return summary

    async def _process_device(
        self,
        ha_device: Any,
        device_entities: list,
        manifest: Manifest,
        area_to_room: dict[str, str],
        instance_id: str,
        include_technical: bool,
        dry_run: bool,
    ) -> DeviceImportResult:
        """Process a single HA device for import."""
        from datetime import datetime

        from src.core.models.manifest import DeviceCapabilities, DeviceConfig, DeviceOrigin

        # Get room for this device
        room_id = area_to_room.get(ha_device.area_id)
        if not room_id:
            raise ValueError(f"No room found for area {ha_device.area_id}")

        # Filter and map entities to capabilities
        capabilities = []
        for entity in device_entities:
            if self.domain_mapper.should_import_entity(entity.domain, include_technical):
                caps = self.domain_mapper.get_capabilities(entity.domain)
                capabilities.extend(caps)

        if not capabilities:
            # No importable entities, skip
            return DeviceImportResult(
                device_id=ha_device.id,
                device_name=ha_device.name or "Unknown",
                status="skipped",
                message="No importable entities",
            )

        # Determine device name
        device_name = ha_device.name
        if not device_name and device_entities:
            device_name = device_entities[0].name
        if not device_name:
            device_name = f"Device {ha_device.id}"

        # Generate device ID (slugified name + HA ID suffix for uniqueness)
        import re

        slug_name = re.sub(r"[^a-z0-9]+", "-", device_name.lower()).strip("-")
        device_id = f"{slug_name}-{ha_device.id[-6:]}" if len(ha_device.id) > 6 else slug_name

        # Check for existing device by external_id
        existing = manifest.find_device_by_external_id("home_assistant", ha_device.id)

        if existing:
            _, existing_device = existing
            # Check if anything changed
            has_changes = (
                existing_device.name != device_name
                or existing_device.capabilities is None
                or len(existing_device.capabilities.supported_features) != len(capabilities)
            )

            if has_changes:
                if not dry_run:
                    # Update existing device
                    existing_device.name = device_name
                    existing_device.capabilities = DeviceCapabilities(
                        domain=device_entities[0].domain if device_entities else "unknown",
                        supported_features=capabilities,
                    )
                    existing_device.origin.last_synced_at = datetime.now(UTC).isoformat()

                return DeviceImportResult(
                    device_id=existing_device.id,
                    device_name=device_name,
                    status="updated",
                    external_ids={"home_assistant": ha_device.id},
                    capabilities=capabilities,
                    message="Device updated",
                )
            else:
                return DeviceImportResult(
                    device_id=existing_device.id,
                    device_name=device_name,
                    status="skipped",
                    external_ids={"home_assistant": ha_device.id},
                    capabilities=capabilities,
                    message="No changes detected",
                )

        # Create new device
        device_config = DeviceConfig(
            id=device_id,
            type=capabilities[0] if capabilities else "unknown",
            name=device_name,
            origin=DeviceOrigin(
                source="home_assistant",
                instance_id=instance_id,
                imported_at=datetime.now(UTC).isoformat(),
            ),
            external_ids={"home_assistant": ha_device.id},
            capabilities=DeviceCapabilities(
                domain=device_entities[0].domain if device_entities else "unknown",
                supported_features=capabilities,
            ),
        )

        if not dry_run:
            manifest.add_or_update_device(room_id, device_config)

        return DeviceImportResult(
            device_id=device_id,
            device_name=device_name,
            status="new",
            external_ids={"home_assistant": ha_device.id},
            capabilities=capabilities,
            message="Device imported successfully",
        )
