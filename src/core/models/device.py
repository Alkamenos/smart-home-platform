"""Device model for managing HA devices in the platform."""

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


# Forward reference to avoid circular imports
TYPE_CHECKING = False
if TYPE_CHECKING:
    pass


class Device(BaseModel):
    """Устройство - физическое или виртуальное устройство в Home Assistant."""

    id: UUID = Field(default_factory=uuid4, description="ID устройства в платформе")
    ha_entity_id: str = Field(
        pattern=r"^[a-z_]+\.[a-z0-9_]+$",
        description="Идентификатор сущности в HA (e.g., 'light.kitchen_light')",
    )
    source_id: UUID = Field(description="Ссылка на HASource")
    name: str = Field(
        min_length=1, max_length=255, description="Исходное название устройства из HA"
    )
    device_type: str = Field(
        description="Тип устройства (light, switch, binary_sensor, climate, etc.)"
    )
    model: str | None = Field(
        default=None, description="Модель устройства (e.g., 'Philips Hue A19')"
    )
    manufacturer: str | None = Field(default=None, description="Производитель (e.g., 'Philips')")
    ha_area_id: str | None = Field(
        default=None,
        description="ID области (комнаты) в Home Assistant, если известна (e.g., 'kitchen')",
    )
    state: dict[str, Any] = Field(default_factory=dict, description="Текущее состояние")
    attributes: dict[str, Any] = Field(default_factory=dict, description="Дополнительные атрибуты")
    config: dict[str, Any] | None = Field(
        default=None,
        description="Конфигурация устройства (display_name, description, location, tags, etc.)",
    )
    status: str = Field(
        default="available",
        description="Статус доступности: available, unavailable, removed_from_ha",
    )
    last_state_update: datetime = Field(
        default_factory=datetime.utcnow, description="Время последнего обновления состояния"
    )
    created_at: datetime = Field(
        default_factory=datetime.utcnow, description="Время добавления в платформу"
    )
    updated_at: datetime = Field(
        default_factory=datetime.utcnow, description="Время последнего обновления записи"
    )

    class Config:
        """Pydantic config."""

        json_schema_extra = {
            "example": {
                "id": "550e8400-e29b-41d4-a716-446655440001",
                "ha_entity_id": "light.kitchen_light",
                "source_id": "550e8400-e29b-41d4-a716-446655440000",
                "name": "Kitchen Light",
                "device_type": "light",
                "model": "Philips Hue A19",
                "manufacturer": "Philips",
                "state": {"state": "on", "brightness": 200},
                "config": {
                    "display_name": "Кухонный свет",
                    "description": "Основное освещение кухни",
                    "location": "Кухня",
                    "tags": ["lighting", "kitchen"],
                },
                "status": "available",
                "created_at": "2026-09-29T10:00:00Z",
            }
        }
