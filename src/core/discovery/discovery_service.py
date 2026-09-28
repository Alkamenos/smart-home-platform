"""Service for discovering 200+ devices from Home Assistant."""

from __future__ import annotations

from typing import TYPE_CHECKING

from loguru import logger

from .classifier import DeviceClassifier
from .models import BulkApplyRequest, DiscoveredDevice


if TYPE_CHECKING:
    from src.adapters.ha_adapter import HAAdapter
    from src.core.container import Container


SYSTEM_DOMAINS = {
    "automation",
    "script",
    "scene",
    "zone",
    "person",
    "sun",
    "weather",
    "device_tracker",
    "group",
    "input_boolean",
    "input_text",
    "input_number",
    "input_select",
    "input_datetime",
    "timer",
    "counter",
    "update",
    "persistent_notification",
    "hacs",
}

PAGE_SIZE = 25


class DeviceDiscoveryService:
    """Сканирует 200+ устройств с пагинацией и автоприменением шаблонов."""

    def __init__(self, ha_adapter: HAAdapter, container: Container | None = None) -> None:
        """Initialize the discovery service.

        Args:
            ha_adapter: Adapter used to scan Home Assistant entities.
            container: Optional platform container, required for FSM hot-reload.
        """
        self._ha_adapter = ha_adapter
        self._container = container
        self._classifier = DeviceClassifier()
        logger.info("DeviceDiscoveryService initialized")

    async def scan_devices(
        self,
        page: int = 1,
        page_size: int = PAGE_SIZE,
        filter_domain: str | None = None,
        filter_category: str | None = None,
        filter_area: str | None = None,
    ) -> dict:
        """Сканировать устройства с пагинацией."""
        # Проверяем подключение через публичный property is_connected
        if not self._ha_adapter.is_connected:
            raise RuntimeError("HA WebSocket client not connected")

        ws_client = getattr(self._ha_adapter, "_ws_client", None)
        if ws_client is None:
            raise RuntimeError("HA WebSocket client not available")

        all_states = await ws_client.get_states()

        # Фильтруем системные
        filtered = []
        for state_obj in all_states:
            entity_id = state_obj.get("entity_id", "")
            domain = entity_id.split(".")[0] if "." in entity_id else "unknown"
            if domain not in SYSTEM_DOMAINS:
                filtered.append(state_obj)

        # Классифицируем
        devices = []
        for state_obj in filtered:
            entity_id = state_obj.get("entity_id", "")
            domain = entity_id.split(".")[0]
            attributes = state_obj.get("attributes", {})

            category, suggested, auto_apply = self._classifier.classify(
                entity_id, domain, attributes
            )
            area_id = attributes.get("area_id") or self._classifier.extract_room_name(entity_id)

            device = DiscoveredDevice(
                entity_id=entity_id,
                domain=domain,
                name=attributes.get("friendly_name", entity_id),
                friendly_name=attributes.get("friendly_name"),
                area_id=area_id,
                state=state_obj.get("state", "unknown"),
                attributes=attributes,
                category=category,
                suggested_behavior=suggested,
                auto_apply=auto_apply,
            )
            devices.append(device)

        # Применяем фильтры
        if filter_domain:
            devices = [d for d in devices if d.domain == filter_domain]
        if filter_category:
            devices = [d for d in devices if d.category.value == filter_category]
        if filter_area:
            devices = [d for d in devices if d.area_id == filter_area]

        # Статистика
        by_domain = {}
        by_category = {}
        for d in devices:
            by_domain[d.domain] = by_domain.get(d.domain, 0) + 1
            by_category[d.category.value] = by_category.get(d.category.value, 0) + 1

        # Пагинация
        total = len(devices)
        total_pages = (total + page_size - 1) // page_size
        start = (page - 1) * page_size
        end = start + page_size
        page_devices = devices[start:end]

        # Автоприменение
        auto_stats = self._classifier.get_auto_apply_count(devices)

        return {
            "total": total,
            "page": page,
            "page_size": page_size,
            "total_pages": total_pages,
            "devices": [d.model_dump(mode="json") for d in page_devices],
            "by_domain": by_domain,
            "by_category": by_category,
            "auto_apply_stats": auto_stats,
        }

    async def bulk_apply(self, request: BulkApplyRequest, manifest_path: str) -> dict:
        """Массовое применение для 200+ устройств."""
        # Получаем все устройства
        scan_result = await self.scan_devices(page=1, page_size=10000)
        all_devices = scan_result["devices"]

        selections = []
        for device in all_devices:
            if device["entity_id"] in request.exclude_entities:
                continue

            include = False
            if (
                request.include_all
                or device["category"] in [c.value for c in request.include_categories]
                or (
                    device["auto_apply"]
                    and (
                        (device["category"] == "lighting" and request.auto_apply_lighting)
                        or (device["category"] == "climate_control" and request.auto_apply_climate)
                        or (device["category"] == "ventilation" and request.auto_apply_ventilation)
                    )
                )
            ):
                include = True

            if include:
                selections.append(
                    {
                        "device_entity_id": device["entity_id"],
                        "include": True,
                        "target_room": device["area_id"] or "unassigned",
                        "behavior_template": device["suggested_behavior"],
                    }
                )

        if request.dry_run:
            return {"dry_run": True, "would_add": len(selections)}

        # Применяем к манифесту
        from datetime import datetime

        import yaml

        with open(manifest_path) as f:
            manifest = yaml.safe_load(f) or {}

        rooms = manifest.setdefault("rooms", [])
        added_count = 0

        for sel in selections:
            entity_id = sel["device_entity_id"]
            target_room = sel["target_room"]
            behavior_template = sel["behavior_template"]

            # Найти или создать комнату
            room = next((r for r in rooms if r["id"] == target_room), None)
            if room is None:
                room = {
                    "id": target_room,
                    "name": target_room.replace("_", " ").title(),
                    "sensors": {},
                    "devices": [],
                }
                rooms.append(room)

            # Найти оригинальное устройство для категории
            device_obj = next((d for d in all_devices if d["entity_id"] == entity_id), None)
            if not device_obj:
                continue

            if device_obj["category"] in ("temperature_sensor", "humidity_sensor", "motion_sensor"):
                sensor_type = device_obj["category"].replace("_sensor", "")
                room.setdefault("sensors", {})[sensor_type] = entity_id
            else:
                device_entry = {"id": entity_id, "type": device_obj["domain"]}
                if behavior_template:
                    device_entry["behaviors"] = [
                        {
                            "template": behavior_template,
                            "priority": 10,
                            "params": {},
                        }
                    ]
                room.setdefault("devices", []).append(device_entry)

            added_count += 1

        # Backup
        backup_path = f"{manifest_path}.bak.{datetime.now():%Y%m%d_%H%M%S}"
        with open(backup_path, "w") as f:
            yaml.dump(manifest, f, default_flow_style=False, sort_keys=False)

        # Сохраняем
        with open(manifest_path, "w") as f:
            yaml.dump(manifest, f, default_flow_style=False, sort_keys=False)

        # Hot reload
        await self._hot_reload_fsm(manifest)

        logger.info(f"Bulk apply: {added_count} devices added. Backup: {backup_path}")
        return {"success": True, "devices_added": added_count, "backup_path": backup_path}

    async def apply_selective(
        self, selections: list[dict], manifest_path: str, dry_run: bool = False
    ) -> dict:
        """Apply selectively chosen devices to manifest.

        Args:
            selections: List of device selections with entity_id, room, behavior, etc.
            manifest_path: Path to manifest file
            dry_run: If True, don't write to file, just return what would be added

        Returns:
            Result with success status and number of devices added/would be added
        """
        from datetime import datetime

        import yaml

        # Load current manifest
        with open(manifest_path) as f:
            manifest = yaml.safe_load(f) or {}

        rooms = manifest.setdefault("rooms", [])
        added_devices = []
        failed_devices = []

        for selection in selections:
            try:
                entity_id: str | None = selection.get("device_entity_id")
                if not entity_id:
                    continue

                target_room: str = selection.get("target_room", "unassigned") or "unassigned"
                behavior_template: str | None = selection.get("behavior_template")
                domain = entity_id.split(".")[0] if "." in entity_id else "unknown"

                # Find or create room
                room = next((r for r in rooms if r["id"] == target_room), None)
                if room is None and not dry_run:
                    room = {
                        "id": target_room,
                        "name": target_room.replace("_", " ").title(),
                        "sensors": {},
                        "devices": [],
                    }
                    rooms.append(room)
                elif room is None:
                    room = {
                        "id": target_room,
                        "name": target_room.replace("_", " ").title(),
                        "sensors": {},
                        "devices": [],
                    }

                # Determine device type based on domain
                if domain in ("sensor", "binary_sensor"):
                    # For sensors, extract type from entity_id or use as-is
                    sensor_type = entity_id.split("_")[1] if "_" in entity_id else "custom"
                    room.setdefault("sensors", {})[sensor_type] = entity_id
                else:
                    # For regular devices
                    device_entry = {"id": entity_id, "type": domain}
                    if behavior_template:
                        device_entry["behaviors"] = [
                            {
                                "template": behavior_template,
                                "priority": 10,
                                "params": selection.get("behavior_params", {}),
                            }
                        ]
                    room.setdefault("devices", []).append(device_entry)

                added_devices.append(entity_id)
            except Exception as e:
                logger.warning(f"Failed to add device {entity_id}: {e}")
                failed_devices.append({"entity_id": entity_id, "error": str(e)})

        if dry_run:
            return {
                "dry_run": True,
                "would_add": len(added_devices),
                "devices": added_devices,
            }

        # Create backup
        backup_path = f"{manifest_path}.bak.{datetime.now():%Y%m%d_%H%M%S}"
        with open(backup_path, "w") as f:
            yaml.dump(manifest, f, default_flow_style=False, sort_keys=False)

        # Save manifest
        with open(manifest_path, "w") as f:
            yaml.dump(manifest, f, default_flow_style=False, sort_keys=False)

        # Hot reload
        await self._hot_reload_fsm(manifest)

        logger.info(
            f"Selective apply: {len(added_devices)} devices added, "
            f"{len(failed_devices)} failed. Backup: {backup_path}"
        )
        return {
            "success": True,
            "devices_added": len(added_devices),
            "failed": len(failed_devices),
            "failed_devices": failed_devices,
            "backup_path": backup_path,
        }

    async def _hot_reload_fsm(self, manifest: dict) -> None:
        """Пересоздать FSM definitions после обновления манифеста.

        Args:
            manifest: Updated manifest data.
        """
        if self._container is None:
            logger.warning("Hot reload skipped: no container available")
            return

        try:
            from src.core.manifest_generator import ManifestAutomationGenerator

            generator = ManifestAutomationGenerator(manifest)
            result = generator.generate_all()

            fsm_engine = self._container.fsm
            event_router = self._container.event_router

            all_definitions = (
                result.lighting_definitions
                + result.climate_definitions
                + result.ventilation_definitions
            )
            all_mappings = (
                result.lighting_mappings + result.climate_mappings + result.ventilation_mappings
            )

            for definition in all_definitions:
                fsm_engine.register_definition(definition)

            for mapping in all_mappings:
                event_router.add_mapping(mapping)

            logger.info(f"Hot reload: registered {len(all_definitions)} FSM definitions")
        except Exception as e:
            logger.error(f"Hot reload failed: {e}")
