"""
Модель доступа к устройствам на основе ролей пользователей.

Отслеживает какие пользователи имеют доступ к каким устройствам и с какими правами.
"""

from datetime import datetime
from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class DeviceAccess(BaseModel):
    """Запись доступа пользователя к устройству."""

    id: UUID = Field(default_factory=uuid4, description="ID записи доступа")
    device_id: UUID = Field(description="ID устройства")
    user_id: str = Field(description="ID пользователя (строка)")
    role: Literal["viewer", "controller", "admin"] = Field(
        description="Роль пользователя. viewer: только просмотр, controller: управление, admin: полный доступ"
    )
    granted_by: str = Field(
        description="ID пользователя (администратора) который предоставил доступ"
    )
    created_at: datetime = Field(
        default_factory=datetime.utcnow,
        description="Время создания записи доступа"
    )

    class Config:
        """Pydantic config."""
        json_schema_extra = {
            "example": {
                "id": "550e8400-e29b-41d4-a716-446655440001",
                "device_id": "550e8400-e29b-41d4-a716-446655440002",
                "user_id": "user_123",
                "role": "controller",
                "granted_by": "admin_user",
                "created_at": "2026-09-29T10:00:00Z"
            }
        }

    def can_view(self) -> bool:
        """Проверяет может ли пользователь просматривать устройство."""
        return self.role in ["viewer", "controller", "admin"]

    def can_control(self) -> bool:
        """Проверяет может ли пользователь управлять устройством."""
        return self.role in ["controller", "admin"]

    def can_manage_access(self) -> bool:
        """Проверяет может ли пользователь управлять доступом к устройству."""
        return self.role == "admin"
