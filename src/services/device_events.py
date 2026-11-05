"""Device event publication for the device service (spec 018, T058).

Extracted from DeviceService: the event names and payload shapes are a contract
with the rest of the platform, so they live together and away from storage.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from core.events.device_events import (
    DeviceAccessChangedEvent,
    DeviceConfigChangedEvent,
    DeviceStateChangedEvent,
)
from core.events.event_bus import EventBus
from core.models.device import Device


logger = logging.getLogger("services.device_service")

EVENT_DEVICE_LOADED = "device.loaded"
EVENT_DEVICE_CONFIG_CHANGED = "device.config_changed"
EVENT_DEVICE_STATE_CHANGED = "device.state_changed"
EVENT_DEVICE_ACCESS_CHANGED = "device.access_changed"
EVENT_DEVICE_REMOVED = "device.removed"


class DeviceEventsMixin:
    """Publish device lifecycle and state events."""

    event_bus: EventBus

    async def _publish_config_changed_event(
        self,
        device_id: UUID,
        changed_fields: dict[str, Any],
        changed_by: str | None = None,
    ) -> None:
        """T040: Публикует событие изменения конфигурации через EventBus.

        Args:
            device_id: ID устройства
            changed_fields: Измененные поля
            changed_by: Кто сделал изменение
        """
        try:
            event = DeviceConfigChangedEvent(
                device_id=device_id,
                changed_fields=changed_fields,
                changed_by=changed_by or "unknown",
                timestamp=datetime.utcnow(),
            )

            await self.event_bus.publish(
                EVENT_DEVICE_CONFIG_CHANGED,
                {
                    "device_id": str(event.device_id),
                    "changes": event.changed_fields,
                    "changed_by": event.changed_by,
                    "timestamp": event.timestamp.isoformat() if event.timestamp else None,
                },
            )
            logger.debug(f"Опубликовано событие изменения конфигурации для устройства {device_id}")

        except Exception as e:
            logger.error(f"Ошибка публикации события изменения конфигурации: {e}")

    async def _publish_access_changed_event(
        self,
        device_id: UUID,
        user_id: str,
        action: Literal["granted", "revoked", "updated"],
        role: Literal["viewer", "controller", "admin"] | None = None,
        previous_role: Literal["viewer", "controller", "admin"] | None = None,
        granted_by: str | None = None,
    ) -> None:
        """T070: Публикует событие изменения доступа через EventBus.

        Args:
            device_id: ID устройства
            user_id: ID пользователя
            action: Действие (granted, revoked, updated)
            role: Новая роль (при granted/updated)
            previous_role: Предыдущая роль
            granted_by: Администратор который совершил действие
        """
        try:
            event = DeviceAccessChangedEvent(
                device_id=device_id,
                user_id=user_id,
                action=action,
                role=role,
                previous_role=previous_role,
                granted_by=granted_by,
                timestamp=datetime.utcnow(),
            )

            await self.event_bus.publish(
                EVENT_DEVICE_ACCESS_CHANGED,
                {
                    "device_id": str(event.device_id),
                    "user_id": event.user_id,
                    "action": event.action,
                    "role": event.role,
                    "previous_role": event.previous_role,
                    "granted_by": event.granted_by,
                    "timestamp": event.timestamp.isoformat() if event.timestamp else None,
                },
            )
            logger.debug(
                f"Опубликовано событие изменения доступа: {action} для user {user_id} на device {device_id}"
            )

        except Exception as e:
            logger.error(f"Ошибка публикации события изменения доступа: {e}")

    # T066: Методы проверки и управления доступом
    async def _publish_device_loaded_event(self, device: Device) -> None:
        """Публикует событие загрузки устройства через EventBus.

        Args:
            device: Загруженное устройство
        """
        try:
            from core.events.device_events import DeviceLoadedEvent

            event = DeviceLoadedEvent(
                device_id=device.id,
                source_id=device.source_id,
                ha_entity_id=device.ha_entity_id,
                name=device.name,
                device_type=device.device_type,
                timestamp=datetime.utcnow(),
            )

            await self.event_bus.publish(
                EVENT_DEVICE_LOADED,
                {
                    "device_id": str(event.device_id),
                    "source_id": str(event.source_id),
                    "ha_entity_id": event.ha_entity_id,
                    "name": event.name,
                    "device_type": event.device_type,
                    "state": device.state,
                    "timestamp": event.timestamp.isoformat(),
                },
            )
            logger.debug(f"Опубликовано событие загрузки устройства: {device.id}")

        except Exception as e:
            logger.error(f"Ошибка публикации события загрузки устройства: {e}")

    async def _publish_device_removed_event(self, device: Device) -> None:
        """Публикует событие исчезновения устройства из Home Assistant.

        Args:
            device: Устройство, помеченное как removed_from_ha.
        """
        try:
            await self.event_bus.publish(
                EVENT_DEVICE_REMOVED,
                {
                    "device_id": str(device.id),
                    "source_id": str(device.source_id),
                    "ha_entity_id": device.ha_entity_id,
                    "name": device.name,
                    "status": device.status,
                    "timestamp": datetime.utcnow().isoformat(),
                },
            )
            logger.debug(f"Опубликовано событие исчезновения устройства: {device.ha_entity_id}")
        except Exception as e:
            logger.error(f"Ошибка публикации события исчезновения устройства: {e}")

    async def _publish_state_changed_event(
        self,
        device_id: UUID,
        old_state: dict[str, Any] | None,
        new_state: dict[str, Any],
    ) -> None:
        """T058: Публикует событие изменения состояния через EventBus.

        Args:
            device_id: ID устройства
            old_state: Старое состояние
            new_state: Новое состояние
        """
        try:
            event = DeviceStateChangedEvent(
                device_id=device_id,
                old_state=old_state,
                new_state=new_state,
                timestamp=datetime.utcnow(),
                source="ha",
            )

            await self.event_bus.publish(
                EVENT_DEVICE_STATE_CHANGED,
                {
                    "device_id": str(event.device_id),
                    "old_state": event.old_state,
                    "new_state": event.new_state,
                    "source": event.source,
                    "timestamp": event.timestamp.isoformat(),
                },
            )
            logger.debug(f"Published state changed event for device {device_id}")

        except Exception as e:
            logger.error(f"Error publishing state changed event: {e}")

    # ============ Методы управления кэшем и индексом ============
