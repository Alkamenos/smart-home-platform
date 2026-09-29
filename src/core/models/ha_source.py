"""Home Assistant Source configuration model."""

from datetime import datetime
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, HttpUrl


class HASource(BaseModel):
    """Источник Home Assistant - конфигурация подключения к HA."""

    id: UUID = Field(default_factory=uuid4, description="Уникальный идентификатор источника")
    name: str = Field(
        min_length=1,
        max_length=255,
        description="Отображаемое название источника (e.g., 'Home Assistant Pro')",
    )
    url: HttpUrl = Field(description="URL для подключения к HA (e.g., 'http://192.168.1.100:8123')")
    token: str = Field(
        min_length=10, description="Long-lived access token (шифруется при сохранении)"
    )
    status: str = Field(
        default="disconnected", description="Статус соединения: connected, disconnected, error"
    )
    last_sync: datetime | None = Field(
        default=None, description="Время последней успешной синхронизации"
    )
    last_error: str | None = Field(
        default=None, description="Сообщение об ошибке последней попытки подключения"
    )
    device_count: int | None = Field(
        default=0, description="Количество загруженных устройств из этого источника"
    )
    created_at: datetime = Field(
        default_factory=datetime.utcnow, description="Время создания записи"
    )
    updated_at: datetime = Field(
        default_factory=datetime.utcnow, description="Время последнего обновления"
    )

    class Config:
        """Pydantic config."""

        json_schema_extra = {
            "example": {
                "id": "550e8400-e29b-41d4-a716-446655440000",
                "name": "Home Assistant Pro",
                "url": "http://192.168.1.100:8123",
                "token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
                "status": "connected",
                "device_count": 47,
                "created_at": "2026-09-29T10:00:00Z",
                "updated_at": "2026-09-29T10:05:00Z",
            }
        }
