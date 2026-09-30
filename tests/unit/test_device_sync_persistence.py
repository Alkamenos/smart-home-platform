"""Unit-тесты персистентности истории операций DeviceSyncEventPersistence (spec 005, T003)."""

from datetime import datetime
from pathlib import Path
from uuid import uuid4

from src.core.models.device_sync_event import DeviceSyncEvent
from src.core.persistence.devices import DeviceSyncEventPersistence


class TestAppendAndList:
    """Запись и чтение списка."""

    async def test_append_then_list(self, tmp_path: Path) -> None:
        """Записанная операция читается обратно."""
        persistence = DeviceSyncEventPersistence(data_dir=tmp_path)
        event = DeviceSyncEvent(device_id=uuid4(), action="config_changed", user_id="u1")

        await persistence.append_event(event)
        result = await persistence.list_events(event.device_id)

        assert len(result) == 1
        assert result[0].id == event.id
        assert result[0].user_id == "u1"

    async def test_persistence_survives_reload(self, tmp_path: Path) -> None:
        """Записи переживают пересоздание персистентности (SC-003/FR-002)."""
        device_id = uuid4()
        first = DeviceSyncEventPersistence(data_dir=tmp_path)
        await first.append_event(
            DeviceSyncEvent(device_id=device_id, action="config_changed", user_id="u1")
        )

        second = DeviceSyncEventPersistence(data_dir=tmp_path)
        result = await second.list_events(device_id)

        assert len(result) == 1

    async def test_only_requested_device(self, tmp_path: Path) -> None:
        """Читаются только записи запрошенного устройства."""
        persistence = DeviceSyncEventPersistence(data_dir=tmp_path)
        other_device = uuid4()
        await persistence.append_event(
            DeviceSyncEvent(device_id=other_device, action="config_changed")
        )

        result = await persistence.list_events(uuid4())

        assert result == []


class TestSortingFilteringPagination:
    """Сортировка, фильтр, пагинация (FR-007, research R6)."""

    async def test_newest_first(self, tmp_path: Path) -> None:
        """Новые записи первыми (по timestamp убывание)."""
        persistence = DeviceSyncEventPersistence(data_dir=tmp_path)
        device_id = uuid4()
        for minute in (0, 5, 10):
            await persistence.append_event(
                DeviceSyncEvent(
                    device_id=device_id,
                    action="config_changed",
                    timestamp=datetime(2026, 9, 29, 12, minute, 0),
                )
            )

        result = await persistence.list_events(device_id)

        assert [r.timestamp.minute for r in result] == [10, 5, 0]

    async def test_filter_by_action(self, tmp_path: Path) -> None:
        """Фильтр по типу операции; чужие типы не попадают (FR-007)."""
        persistence = DeviceSyncEventPersistence(data_dir=tmp_path)
        device_id = uuid4()
        await persistence.append_event(
            DeviceSyncEvent(device_id=device_id, action="config_changed")
        )
        await persistence.append_event(
            DeviceSyncEvent(device_id=device_id, action="command_executed")
        )

        result = await persistence.list_events(device_id, action="config_changed")

        assert len(result) == 1
        assert result[0].action == "config_changed"

    async def test_unknown_action_returns_empty(self, tmp_path: Path) -> None:
        """Неизвестное значение фильтра → пустой список (контрактный кейс 9)."""
        persistence = DeviceSyncEventPersistence(data_dir=tmp_path)
        device_id = uuid4()
        await persistence.append_event(
            DeviceSyncEvent(device_id=device_id, action="config_changed")
        )

        result = await persistence.list_events(device_id, action="nonexistent")

        assert result == []

    async def test_pagination(self, tmp_path: Path) -> None:
        """limit/offset применяются после фильтра/сортировки (FR-007)."""
        persistence = DeviceSyncEventPersistence(data_dir=tmp_path)
        device_id = uuid4()
        for minute in (0, 1, 2, 3):
            await persistence.append_event(
                DeviceSyncEvent(
                    device_id=device_id,
                    action="config_changed",
                    timestamp=datetime(2026, 9, 29, 12, minute, 0),
                )
            )

        page = await persistence.list_events(device_id, limit=2, offset=2)

        assert len(page) == 2
        assert [r.timestamp.minute for r in page] == [1, 0]


class TestErrorHandling:
    """Отказоустойчивость (FR-009 контекст: чтение не падает)."""

    async def test_missing_file_returns_empty(self, tmp_path: Path) -> None:
        """Файл отсутствует → пустой список, без исключения."""
        persistence = DeviceSyncEventPersistence(data_dir=tmp_path)

        assert await persistence.list_events(uuid4()) == []

    async def test_corrupted_json_returns_empty(self, tmp_path: Path) -> None:
        """Повреждённый JSON → пустой список + не исключение (research R6)."""
        persistence = DeviceSyncEventPersistence(data_dir=tmp_path)
        persistence.events_file.write_text("{not valid json", encoding="utf-8")

        result = await persistence.list_events(uuid4())

        assert result == []
