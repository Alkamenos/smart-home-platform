"""Обнаружение устройств в Home Assistant и применение их к манифесту.

Манифест пишется только через ``ManifestStore`` — тем же путём, что и
веб-интерфейс. Раньше здесь был сырой YAML: правки из мастера и CLI
расходились с состоянием интерфейса, и «Reload» откатывал результат.
Пересборка машин состояний убрана: ею занимается сервис жизненного
цикла устройств (``DeviceLifecycleService``), а не этот сервис.

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from loguru import logger

from .classifier import DeviceClassifier
from .models import BulkApplyRequest, DiscoveredDevice


if TYPE_CHECKING:
    from src.adapters.ha_adapter import HAAdapter
    from src.core.persistence.manifest_store import ManifestStore


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

    def __init__(self, ha_adapter: HAAdapter, manifest_store: ManifestStore | None = None) -> None:
        """Создаёт сервис обнаружения.

        Args:
            ha_adapter: Адаптер для сканирования сущностей Home Assistant.
            manifest_store: Хранилище манифеста. Если не передано, создаётся
                по пути манифеста при первом применении.
        """
        self._ha_adapter = ha_adapter
        self._manifest_store = manifest_store
        self._classifier = DeviceClassifier()
        logger.info("Сервис обнаружения устройств инициализирован")

    def _store_for(self, manifest_path: str) -> ManifestStore:
        """Возвращает хранилище манифеста, создавая его при необходимости.

        Args:
            manifest_path: Путь к файлу манифеста.

        Returns:
            Хранилище манифеста с уже загруженным состоянием.
        """
        from src.core.persistence.manifest_store import ManifestStore

        if self._manifest_store is None or self._manifest_store.path != manifest_path:
            self._manifest_store = ManifestStore(manifest_path)
        if self._manifest_store.current is None:
            self._manifest_store.load()
        return self._manifest_store

    @staticmethod
    def _room_manifest(manifest: Any, target_room: str) -> Any:
        """Находит комнату манифеста или создаёт её.

        Args:
            manifest: Модель манифеста.
            target_room: Идентификатор комнаты.

        Returns:
            Модель комнаты.
        """
        from src.core.models.manifest import RoomConfig

        room = next((r for r in manifest.rooms if r.id == target_room), None)
        if room is None:
            room = RoomConfig(
                id=target_room,
                name=target_room.replace("_", " ").title(),
                sensors={},
                devices=[],
            )
            manifest.rooms.append(room)
        return room

    @staticmethod
    def _already_present(room: Any, entity_id: str) -> bool:
        """Проверяет, нет ли уже такого устройства в комнате.

        Args:
            room: Модель комнаты.
            entity_id: Идентификатор сущности.

        Returns:
            True, если устройство уже описано в комнате.
        """
        return (
            any(device.id == entity_id for device in room.devices)
            or entity_id in (room.sensors or {}).values()
        )

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
        """Массово применяет найденные устройства к манифесту.

        Args:
            request: Параметры отбора (категории, автоприменение, исключения).
            manifest_path: Путь к файлу манифеста.

        Returns:
            Итог применения: счётчики добавленных устройств и путь к резервной копии.
        """
        scan_result = await self.scan_devices(page=1, page_size=10000)
        all_devices = scan_result["devices"]

        selected = self._select_for_bulk(request, all_devices)
        if request.dry_run:
            return {"dry_run": True, "would_add": len(selected), "dry_run_selected": selected}

        store = self._store_for(manifest_path)
        manifest = store.current
        added_count = 0
        for selection in selected:
            device = next(
                (d for d in all_devices if d["entity_id"] == selection["device_entity_id"]),
                None,
            )
            if device is None:
                continue
            room = self._room_manifest(manifest, selection["target_room"])
            if self._add_to_room(
                room,
                entity_id=selection["device_entity_id"],
                category=device["category"],
                domain=device["domain"],
                behavior_template=selection["behavior_template"],
            ):
                added_count += 1

        store.mark_changed()
        store.save()
        backup_path = f"{manifest_path}.bak"

        logger.info(f"Массовое применение: добавлено устройств — {added_count}")
        return {
            "success": True,
            "devices_added": added_count,
            "backup_path": backup_path,
            "already_present": len(selected) - added_count,
        }

    def _select_for_bulk(
        self, request: BulkApplyRequest, all_devices: list[dict]
    ) -> list[dict[str, Any]]:
        """Отбирает устройства для массового применения.

        Args:
            request: Параметры отбора.
            all_devices: Все найденные устройства.

        Returns:
            Список отобранных устройств в формате применения.
        """
        auto_apply_flags = {
            "lighting": request.auto_apply_lighting,
            "climate_control": request.auto_apply_climate,
            "ventilation": request.auto_apply_ventilation,
        }
        requested_categories = {c.value for c in request.include_categories}

        selected: list[dict[str, Any]] = []
        for device in all_devices:
            if device["entity_id"] in request.exclude_entities:
                continue
            by_category = device["category"] in requested_categories
            by_auto_apply = bool(device.get("auto_apply")) and auto_apply_flags.get(
                device["category"], False
            )
            if not (request.include_all or by_category or by_auto_apply):
                continue
            selected.append(
                {
                    "device_entity_id": device["entity_id"],
                    "include": True,
                    "target_room": device["area_id"] or "unassigned",
                    "behavior_template": device["suggested_behavior"],
                }
            )
        return selected

    @staticmethod
    def _add_to_room(
        room: Any,
        entity_id: str,
        category: str,
        domain: str,
        behavior_template: str | None,
        behavior_params: dict | None = None,
    ) -> bool:
        """Добавляет устройство в комнату манифеста, если его там ещё нет.

        Args:
            room: Модель комнаты.
            entity_id: Идентификатор сущности.
            category: Категория устройства.
            domain: Домен сущности.
            behavior_template: Шаблон поведения.
            behavior_params: Параметры поведения.

        Returns:
            True, если устройство добавлено; False, если уже было или это датчик без
            свободного слота в комнате.
        """
        from src.core.models.manifest import BehaviorConfig, DeviceConfig

        if DeviceDiscoveryService._already_present(room, entity_id):
            return False

        if category in ("temperature_sensor", "humidity_sensor", "motion_sensor"):
            sensor_type = category.replace("_sensor", "")
            if room.sensors is None:
                room.sensors = {}
            if room.sensors.get(sensor_type):
                logger.debug(f"Слот датчика {sensor_type} комнаты {room.id} уже занят")
                return False
            room.sensors[sensor_type] = entity_id
            return True

        device_entry = DeviceConfig(id=entity_id, type=domain)
        if behavior_template:
            device_entry.behaviors = [
                BehaviorConfig(
                    template=behavior_template,
                    priority=10,
                    params=behavior_params or {},
                )
            ]
        room.devices.append(device_entry)
        return True

    async def apply_selective(
        self, selections: list[dict], manifest_path: str, dry_run: bool = False
    ) -> dict:
        """Применяет выбранные пользователем устройства к манифесту.

        Args:
            selections: Выбранные устройства с комнатой и поведением.
            manifest_path: Путь к файлу манифеста.
            dry_run: True — только посчитать, ничего не записывая.

        Returns:
            Итог применения: счётчики, список неудачных устройств с причинами
            и путь к резервной копии.
        """
        store = self._store_for(manifest_path)
        manifest = store.current
        added_devices: list[str] = []
        failed_devices: list[dict[str, Any]] = []
        skipped_devices: list[str] = []

        for selection in selections:
            entity_id: str | None = selection.get("device_entity_id")
            if not entity_id:
                failed_devices.append(
                    {"entity_id": entity_id or "", "error": "Не указан идентификатор устройства"}
                )
                continue

            try:
                target_room: str = selection.get("target_room") or "unassigned"
                domain = entity_id.split(".")[0] if "." in entity_id else "unknown"
                category = selection.get("category") or _category_for_domain(domain)

                if dry_run:
                    room = next((r for r in manifest.rooms if r.id == target_room), None)
                    if room is None or self._already_present(room, entity_id):
                        added_devices.append(entity_id)
                    else:
                        skipped_devices.append(entity_id)
                    continue

                room = self._room_manifest(manifest, target_room)
                created = self._add_to_room(
                    room,
                    entity_id=entity_id,
                    category=category,
                    domain=domain,
                    behavior_template=selection.get("behavior_template"),
                    behavior_params=selection.get("behavior_params"),
                )
                if created:
                    added_devices.append(entity_id)
                else:
                    skipped_devices.append(entity_id)
            except Exception as e:
                logger.warning(f"Не удалось добавить устройство {entity_id}: {e}")
                failed_devices.append({"entity_id": entity_id, "error": str(e)})

        if dry_run:
            return {
                "dry_run": True,
                "would_add": len(added_devices),
                "already_present": len(skipped_devices),
                "devices": added_devices,
                "failed": len(failed_devices),
                "failed_devices": failed_devices,
            }

        store.mark_changed()
        store.save()
        backup_path = f"{manifest_path}.bak"

        logger.info(
            f"Выборочное применение: добавлено — {len(added_devices)}, "
            f"уже было — {len(skipped_devices)}, ошибок — {len(failed_devices)}"
        )
        return {
            "success": not failed_devices,
            "devices_added": len(added_devices),
            "already_present": len(skipped_devices),
            "failed": len(failed_devices),
            "failed_devices": failed_devices,
            "backup_path": backup_path,
        }


def _category_for_domain(domain: str) -> str:
    """Определяет категорию устройства по домену сущности.

    Args:
        domain: Домен сущности Home Assistant.

    Returns:
        Категория устройства.
    """
    if domain in ("sensor", "binary_sensor"):
        return "motion_sensor"
    return "other"
