"""
События для системы управления устройствами.

Представляют события синхронизации, изменения конфигурации, состояния и доступа к устройствам.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal
from uuid import UUID


@dataclass
class DeviceLoadedEvent:
    """Событие загрузки устройства из Home Assistant."""

    device_id: UUID
    source_id: UUID
    ha_entity_id: str
    name: str
    device_type: str
    timestamp: datetime
    metadata: dict[str, Any] | None = None


@dataclass
class DeviceConfigChangedEvent:
    """Событие изменения конфигурации устройства."""

    device_id: UUID
    changed_fields: dict[str, Any]
    changed_by: str | None = None  # Пользователь или система
    timestamp: datetime = None
    metadata: dict[str, Any] | None = None

    def __post_init__(self) -> None:
        """Инициализация с временем события."""
        if self.timestamp is None:
            self.timestamp = datetime.utcnow()


@dataclass
class DeviceStateChangedEvent:
    """Событие изменения состояния устройства."""

    device_id: UUID
    old_state: dict[str, Any] | None
    new_state: dict[str, Any]
    timestamp: datetime
    source: str = "ha"  # 'ha' для Home Assistant или 'local' для локальных изменений
    metadata: dict[str, Any] | None = None


@dataclass
class DeviceAccessChangedEvent:
    """T070: Событие изменения доступа пользователя к устройству."""

    device_id: UUID
    user_id: str
    action: Literal["granted", "revoked", "updated"]  # Действие: предоставлено, отозвано, обновлено
    role: Literal["viewer", "controller", "admin"] | None = None  # Новая роль (при granted/updated)
    previous_role: Literal["viewer", "controller", "admin"] | None = None  # Предыдущая роль
    granted_by: str | None = None  # Администратор который совершил действие
    timestamp: datetime = None
    metadata: dict[str, Any] | None = None

    def __post_init__(self) -> None:
        """Инициализация с временем события."""
        if self.timestamp is None:
            self.timestamp = datetime.utcnow()
