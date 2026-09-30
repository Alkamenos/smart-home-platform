"""Модель истории операций с устройствами (ТР-010, spec 005)."""

from datetime import datetime
from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


SyncAction = Literal[
    "config_changed",
    "command_executed",
    "access_granted",
    "access_revoked",
    "access_updated",
]


class DeviceSyncEvent(BaseModel):
    """Запись одной операции над устройством в истории операций.

    Фиксирует факт изменения конфигурации, отправки команды или изменения
    прав доступа с указанием инициатора, времени и значений до/после
    (ТР-010). Поля before/after заполняются только там, где есть
    изменяемое состояние (spec 005, clarify Q1).
    """

    id: UUID = Field(default_factory=uuid4, description="ID записи")
    device_id: UUID = Field(description="Устройство, над которым выполнена операция")
    action: SyncAction = Field(description="Тип операции")
    user_id: str = Field(
        default="system",
        min_length=1,
        description="Инициатор операции; для системных операций — 'system'",
    )
    timestamp: datetime = Field(
        default_factory=datetime.utcnow,
        description="Время операции (UTC)",
    )
    before: dict[str, Any] | None = Field(
        default=None,
        description="Состояние до (config-поля, роль); для команд — None",
    )
    after: dict[str, Any] | None = Field(
        default=None,
        description="Состояние после (config-поля, роль); для команд — None",
    )
    data: dict[str, Any] | None = Field(
        default=None,
        description="Релевантные данные: содержимое команды, роль, идентификаторы участников",
    )

    class Config:
        """Pydantic config."""

        json_schema_extra = {
            "example": {
                "id": "0f9d1b2a-9c8e-4f1d-a3b2-111122223333",
                "device_id": "550e8400-e29b-41d4-a716-446655440002",
                "action": "config_changed",
                "user_id": "admin_user",
                "timestamp": "2026-09-29T12:00:00Z",
                "before": {"location": "кухня"},
                "after": {"location": "гостиная"},
                "data": None,
            }
        }
