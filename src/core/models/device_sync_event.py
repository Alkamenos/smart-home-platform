"""Модель истории операций с устройствами (ТР-010, spec 005; spec 006 — жизненный цикл)."""

from datetime import datetime
from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, model_validator


SyncAction = Literal[
    "config_changed",
    "command_executed",
    "access_granted",
    "access_revoked",
    "access_updated",
    # Жизненный цикл устройства (spec 006)
    "device_added",
    "device_updated",
    "device_deleted",
    "device_archived",
    "device_restored",
    "devices_applied",
]

SOURCE_LEVEL_ACTIONS: frozenset[str] = frozenset({"devices_applied"})
"""Действия уровня источника: не привязаны к одному устройству."""


class DeviceSyncEvent(BaseModel):
    """Запись одной операции над устройством в истории операций.

    Фиксирует факт изменения конфигурации, отправки команды, изменения
    прав доступа или операции жизненного цикла устройства с указанием
    инициатора, времени и значений до/после (ТР-010). Поля before/after
    заполняются только там, где есть изменяемое состояние (spec 005, clarify Q1).
    """

    id: UUID = Field(default_factory=uuid4, description="ID записи")
    device_id: UUID | None = Field(
        default=None,
        description=(
            "Устройство, над которым выполнена операция; "
            "None допустим только для действий уровня источника (devices_applied)"
        ),
    )
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

    @model_validator(mode="after")
    def _validate_device_scope(self) -> "DeviceSyncEvent":
        """Проверяет, что устройство указано для всех действий, кроме уровня источника.

        Returns:
            Валидированная модель события.

        Raises:
            ValueError: Для действия, привязанного к устройству, не указан device_id.
        """
        if self.device_id is None and self.action not in SOURCE_LEVEL_ACTIONS:
            msg = f"device_id обязателен для действия '{self.action}'"
            raise ValueError(msg)
        return self

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
