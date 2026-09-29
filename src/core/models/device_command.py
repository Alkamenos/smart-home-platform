"""
Модель DeviceCommand для представления команд устройств.

T048: Определяет структуру команды и её параметры.
"""

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, validator


class DeviceCommand(BaseModel):
    """Команда устройства - действие, которое можно выполнить на устройстве."""

    id: UUID = Field(default_factory=uuid4, description="Уникальный ID команды")
    device_id: UUID = Field(description="ID устройства")
    name: str = Field(
        min_length=1, max_length=255, description="Имя команды (уникально в пределах устройства)"
    )
    ha_service: str = Field(
        pattern=r"^[a-z_]+\.[a-z_]+$",
        description="Сервис Home Assistant в формате domain.service (e.g., 'light.turn_on')",
    )
    description: str | None = Field(default=None, max_length=1000, description="Описание команды")
    parameters: dict[str, Any] = Field(
        default_factory=dict, description="Параметры команды (ключ -> тип значения)"
    )
    return_type: str | None = Field(
        default=None, description="Тип возвращаемого значения (e.g., 'bool', 'dict', 'str')"
    )
    execution_timeout: int = Field(
        default=30, ge=1, le=300, description="Таймаут выполнения в секундах (макс 300)"
    )
    is_safe: bool = Field(
        default=True, description="Безопасна ли команда (не требует дополнительной проверки)"
    )
    enabled: bool = Field(default=True, description="Включена ли команда")
    created_at: datetime = Field(
        default_factory=datetime.utcnow, description="Время создания команды"
    )
    updated_at: datetime = Field(
        default_factory=datetime.utcnow, description="Время последнего обновления"
    )

    @validator("execution_timeout")
    def validate_timeout(self, v):
        """Валидация таймаута - максимум 300 секунд."""
        if v > 300:
            raise ValueError("execution_timeout must be <= 300 seconds")
        return v

    class Config:
        """Pydantic config."""

        json_schema_extra = {
            "example": {
                "id": "550e8400-e29b-41d4-a716-446655440001",
                "device_id": "550e8400-e29b-41d4-a716-446655440000",
                "name": "turn_on",
                "ha_service": "light.turn_on",
                "description": "Включить свет",
                "parameters": {
                    "brightness": {"type": "integer", "min": 0, "max": 255},
                    "color_temp": {"type": "integer", "min": 150, "max": 500},
                },
                "return_type": "bool",
                "execution_timeout": 30,
                "is_safe": True,
                "enabled": True,
                "created_at": "2026-09-29T10:00:00Z",
            }
        }


class CommandExecutionRequest(BaseModel):
    """Запрос на выполнение команды."""

    name: str = Field(min_length=1, max_length=255, description="Имя команды для выполнения")
    parameters: dict[str, Any] = Field(default_factory=dict, description="Параметры для выполнения")

    class Config:
        """Pydantic config."""

        json_schema_extra = {
            "example": {"name": "turn_on", "parameters": {"brightness": 200, "color_temp": 300}}
        }


class CommandExecutionResponse(BaseModel):
    """Ответ на выполнение команды."""

    id: UUID = Field(description="ID выполненной команды")
    device_id: UUID = Field(description="ID устройства")
    command_name: str = Field(description="Имя выполненной команды")
    status: str = Field(description="Статус выполнения: pending, executing, success, failed")
    created_at: datetime = Field(description="Время создания запроса")
    completed_at: datetime | None = Field(default=None, description="Время завершения")
    result: dict[str, Any] | None = Field(default=None, description="Результат выполнения")
    error: str | None = Field(default=None, description="Ошибка выполнения если есть")

    class Config:
        """Pydantic config."""

        json_schema_extra = {
            "example": {
                "id": "550e8400-e29b-41d4-a716-446655440001",
                "device_id": "550e8400-e29b-41d4-a716-446655440000",
                "command_name": "turn_on",
                "status": "success",
                "created_at": "2026-09-29T10:00:00Z",
                "completed_at": "2026-09-29T10:00:01Z",
                "result": {"state": "on"},
            }
        }
