"""Unit-тесты модели DeviceSyncEvent (spec 005, ТР-010, T002)."""

from datetime import datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError
from src.core.models.device_sync_event import DeviceSyncEvent


class TestDeviceSyncEventModel:
    """Тесты модели записи операции устройства."""

    def test_minimal_fields(self) -> None:
        """Минимальная запись: только device_id и action, остальное — defaults."""
        event = DeviceSyncEvent(device_id=uuid4(), action="config_changed")

        assert event.id is not None
        assert event.user_id == "system"  # FR-010
        assert event.timestamp is not None
        assert event.before is None
        assert event.after is None
        assert event.data is None

    def test_full_fields(self) -> None:
        """Полная запись: до/после и данные операции сохраняются."""
        device_id = uuid4()
        event = DeviceSyncEvent(
            device_id=device_id,
            action="config_changed",
            user_id="admin_user",
            timestamp=datetime(2026, 9, 29, 12, 0, 0),
            before={"location": "кухня"},
            after={"location": "гостиная"},
            data={"source": "api"},
        )

        assert event.device_id == device_id
        assert event.user_id == "admin_user"
        assert event.before == {"location": "кухня"}
        assert event.after == {"location": "гостиная"}

    def test_json_serialization(self) -> None:
        """Сериализация mode="json" — datetime → ISO, UUID → str (для JSON-хранилища)."""
        event = DeviceSyncEvent(device_id=uuid4(), action="command_executed")

        data = event.model_dump(mode="json")

        assert isinstance(data["id"], str)
        assert isinstance(data["device_id"], str)
        assert isinstance(data["timestamp"], str)
        assert data["action"] == "command_executed"

    @pytest.mark.parametrize(
        "action",
        [
            "config_changed",
            "command_executed",
            "access_granted",
            "access_revoked",
            "access_updated",
            "device_added",
            "device_updated",
            "device_deleted",
            "device_archived",
            "device_restored",
            "devices_applied",
        ],
    )
    def test_valid_actions(self, action: str) -> None:
        """Все типы операций валидны (data-model.md, spec 005 + spec 006)."""
        device_id = None if action == "devices_applied" else uuid4()
        event = DeviceSyncEvent(device_id=device_id, action=action)

        assert event.action == action

    def test_invalid_action_rejected(self) -> None:
        """Неизвестный тип операции отклоняется (Literal)."""
        with pytest.raises(ValidationError):
            DeviceSyncEvent(device_id=uuid4(), action="device_exploded")

    def test_device_id_required_for_device_level_actions(self) -> None:
        """Для действий уровня устройства device_id обязателен (data-model.md)."""
        with pytest.raises(ValidationError):
            DeviceSyncEvent(device_id=None, action="device_deleted")

    def test_device_id_optional_for_source_level_actions(self) -> None:
        """Для действия уровня источника device_id может быть пустым."""
        event = DeviceSyncEvent(device_id=None, action="devices_applied")

        assert event.device_id is None

    def test_before_after_optional(self) -> None:
        """До/после опциональны — для команд остаются None (clarify Q1)."""
        event = DeviceSyncEvent(device_id=uuid4(), action="command_executed")

        assert event.before is None
        assert event.after is None
