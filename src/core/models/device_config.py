"""Модель конфигурации устройства."""

from datetime import datetime
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, field_validator


class DeviceConfig(BaseModel):
    """Конфигурация устройства - параметры, которые настраивает администратор.

    Валидирует и хранит конфигурационные параметры для устройств:
    - display_name: Пользовательское название (1-255 символов, уникально)
    - description: Описание устройства (0-1000 символов)
    - location: Расположение (0-255 символов)
    - tags: Теги для категоризации (макс 10 тегов по 50 символов каждый)
    """

    id: UUID = Field(default_factory=uuid4, description="ID конфигурации в платформе")
    device_id: UUID = Field(description="Ссылка на Device")
    display_name: str | None = Field(
        default=None,
        min_length=1,
        max_length=255,
        description="Пользовательское название устройства",
    )
    description: str | None = Field(
        default=None, max_length=1000, description="Описание устройства"
    )
    location: str | None = Field(
        default=None,
        max_length=255,
        description="Расположение устройства (e.g., 'Кухня', 'Спальня')",
    )
    tags: list[str] | None = Field(
        default=None, description="Теги для категоризации устройства (макс 10 тегов)"
    )
    enabled: bool = Field(default=True, description="Включено ли устройство")
    custom_settings: dict = Field(default_factory=dict, description="Кастомные настройки (JSON)")
    created_by: str | None = Field(default=None, description="Кто создал эту конфигурацию")
    updated_by: str | None = Field(default=None, description="Кто последний обновил конфигурацию")
    created_at: datetime = Field(
        default_factory=datetime.utcnow, description="Время создания конфигурации"
    )
    updated_at: datetime = Field(
        default_factory=datetime.utcnow, description="Время последнего обновления конфигурации"
    )

    @field_validator("display_name")
    @classmethod
    def validate_display_name(cls, v: str | None) -> str | None:
        """Валидирует display_name - не пустой если указан."""
        if v is not None and v.strip() == "":
            raise ValueError("display_name не может быть пустым")
        return v

    @field_validator("tags")
    @classmethod
    def validate_tags(cls, v: list[str] | None) -> list[str] | None:
        """Валидирует теги - не более 10 тегов, каждый не более 50 символов."""
        if v is None:
            return v

        if len(v) > 10:
            raise ValueError("Не может быть более 10 тегов")

        for tag in v:
            if len(tag) > 50:
                raise ValueError(f"Тег '{tag}' слишком длинный (макс 50 символов)")
            if not tag.strip():
                raise ValueError("Теги не могут быть пустыми")

        return v

    class Config:
        """Pydantic config."""

        json_schema_extra = {
            "example": {
                "id": "550e8400-e29b-41d4-a716-446655440002",
                "device_id": "550e8400-e29b-41d4-a716-446655440001",
                "display_name": "Кухонный свет",
                "description": "Основное освещение кухни",
                "location": "Кухня",
                "tags": ["lighting", "kitchen"],
                "enabled": True,
                "created_at": "2026-09-29T10:00:00Z",
                "updated_at": "2026-09-29T10:00:00Z",
            }
        }
