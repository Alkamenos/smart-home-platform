"""
События для системы управления устройствами.

Представляют события синхронизации, изменения конфигурации, состояния и доступа к устройствам.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional, Literal
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
    metadata: Optional[dict[str, Any]] = None


@dataclass
class DeviceConfigChangedEvent:
    """Событие изменения конфигурации устройства."""

    device_id: UUID
    changed_fields: dict[str, Any]
    changed_by: Optional[str] = None  # Пользователь или система
    timestamp: datetime = None
    metadata: Optional[dict[str, Any]] = None

    def __post_init__(self) -> None:
        """Инициализация с временем события."""
        if self.timestamp is None:
            self.timestamp = datetime.utcnow()


@dataclass
class DeviceStateChangedEvent:
    """Событие изменения состояния устройства."""

    device_id: UUID
    old_state: Optional[dict[str, Any]]
    new_state: dict[str, Any]
    timestamp: datetime
    source: str = "ha"  # 'ha' для Home Assistant или 'local' для локальных изменений
    metadata: Optional[dict[str, Any]] = None


@dataclass
class DeviceAccessChangedEvent:
    """T070: Событие изменения доступа пользователя к устройству."""

    device_id: UUID
    user_id: str
    action: Literal["granted", "revoked", "updated"]  # Действие: предоставлено, отозвано, обновлено
    role: Optional[Literal["viewer", "controller", "admin"]] = None  # Новая роль (при granted/updated)
    previous_role: Optional[Literal["viewer", "controller", "admin"]] = None  # Предыдущая роль
    granted_by: Optional[str] = None  # Администратор который совершил действие
    timestamp: datetime = None
    metadata: Optional[dict[str, Any]] = None

    def __post_init__(self) -> None:
        """Инициализация с временем события."""
        if self.timestamp is None:
            self.timestamp = datetime.utcnow()
