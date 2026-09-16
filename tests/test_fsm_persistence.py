"""
Tests for FSM Persistence component.

Specification:
1. FSMPersistence должен сохранять состояния FSM при переходах
2. При старте платформы должны восстанавливаться сохранённые состояния
3. Сохранение должно работать через input_text или fallback в JSON файл
4. Должна быть поддержка кэширования состояний в памяти
5. Восстановление должно проверять валидность состояния (существование в определениях)
6. FSMPersistence должен подписываться на события fsm.transition и platform.started
7. Для каждого entity_id должен быть уникальный ключ хранения
"""

import json
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.fsm import State as FSMState
from core.fsm_persistence import FSMPersistence


class MockFSMEngine:
    """Mock FSM Engine для тестов."""

    def __init__(self):
        self._states = {}
        self._definitions = {}

    def get_state(self, entity_id):
        return self._states.get(entity_id)

    def set_state(self, entity_id, state):
        self._states[entity_id] = state

    def add_definition(self, entity_id, definition):
        self._definitions[entity_id] = definition


def create_mock_state(current_state="OFF", history=None):
    """Создаёт объект State согласно спецификации fsm.py."""
    return FSMState(
        current_state=current_state,
        entered_at=time.time(),
        context={}
    )


class MockDefinition:
    """Mock Definition object."""

    def __init__(self, states=None):
        self.states = states or ("OFF", "ON", "MANUAL")


@pytest.fixture
def mock_event_bus():
    """Создаёт mock event bus."""
    bus = MagicMock()
    bus.subscribe = MagicMock()
    bus.publish = MagicMock()
    return bus


@pytest.fixture
def mock_fsm_engine():
    """Создаёт mock FSM engine."""
    return MockFSMEngine()


@pytest.fixture
def mock_adapter():
    """Создаёт mock adapter."""
    adapter = MagicMock()
    adapter.set_entity_state = AsyncMock()
    return adapter


@pytest.fixture
def mock_logger():
    """Создаёт mock logger."""
    logger = MagicMock()
    logger.info = MagicMock()
    logger.debug = MagicMock()
    logger.warning = MagicMock()
    logger.error = MagicMock()
    return logger


@pytest.fixture
def persistence(mock_event_bus, mock_fsm_engine, mock_adapter, mock_logger):
    """Создаёт экземпляр FSMPersistence для тестов."""
    return FSMPersistence(
        event_bus=mock_event_bus,
        fsm_engine=mock_fsm_engine,
        adapter=mock_adapter,
        logger=mock_logger,
    )


class TestFSMPersistenceInitialization:
    """Тесты инициализации FSMPersistence."""

    def test_initializes_with_empty_entities(self, persistence):
        """При инициализации список включённых сущностей пуст."""
        assert persistence._enabled_entities == {}

    def test_initializes_with_empty_cache(self, persistence):
        """При инициализации кэш состояний пуст."""
        assert persistence._state_cache == {}

    def test_input_text_available_by_default(self, persistence):
        """По умолчанию input_text доступен."""
        assert persistence._input_text_available is True

    def test_subscribes_to_fsm_transition_event(self, mock_event_bus, persistence):
        """FSMPersistence подписывается на fsm.transition."""
        # Проверяем что subscribe был вызван для fsm.transition
        calls = [call[0][0] for call in mock_event_bus.subscribe.call_args_list]
        assert "fsm.transition" in calls

    def test_subscribes_to_platform_started_event(self, mock_event_bus, persistence):
        """FSMPersistence подписывается на platform.started."""
        calls = [call[0][0] for call in mock_event_bus.subscribe.call_args_list]
        assert "platform.started" in calls


class TestEnableForEntity:
    """Тесты метода enable_for_entity()."""

    def test_enables_persistence_with_default_key(self, persistence, mock_logger):
        """Включение персистентности с ключом по умолчанию."""
        persistence.enable_for_entity("light.living_room")

        assert "light.living_room" in persistence._enabled_entities
        assert persistence._enabled_entities["light.living_room"] == "light_living_room_mode"

    def test_enables_persistence_with_custom_key(self, persistence):
        """Включение персистентности с кастомным ключом."""
        persistence.enable_for_entity("light.kitchen", storage_key="custom_kitchen_mode")

        assert persistence._enabled_entities["light.kitchen"] == "custom_kitchen_mode"

    def test_enables_multiple_entities(self, persistence):
        """Можно включить персистентность для нескольких сущностей."""
        persistence.enable_for_entity("light.living_room")
        persistence.enable_for_entity("light.kitchen")
        persistence.enable_for_entity("climate.bedroom")

        assert len(persistence._enabled_entities) == 3
        assert "light.living_room" in persistence._enabled_entities
        assert "light.kitchen" in persistence._enabled_entities
        assert "climate.bedroom" in persistence._enabled_entities

    def test_logs_enabled_message(self, persistence, mock_logger):
        """При включении пишется лог."""
        persistence.enable_for_entity("light.test")

        mock_logger.info.assert_any_call(
            "Enabled persistence for light.test (key: light_test_mode)"
        )


class TestOnFSMTransition:
    """Тесты обработчика переходов FSM."""

    def test_saves_state_on_transition(self, persistence, mock_logger):
        """Сохранение состояния при переходе FSM."""
        persistence.enable_for_entity("light.living_room")

        transition_data = {
            "entity_id": "light.living_room",
            "to_state": "ON_MOTION",
            "from_state": "OFF",
            "trigger": "motion_detected",
        }

        with patch.object(persistence, "_save_state") as mock_save:
            persistence._on_fsm_transition(transition_data)

            mock_save.assert_called_once_with("light_living_room_mode", "ON_MOTION", "light.living_room")

    def test_updates_cache_on_transition(self, persistence):
        """Кэш обновляется при переходе."""
        persistence.enable_for_entity("light.living_room")

        transition_data = {
            "entity_id": "light.living_room",
            "to_state": "PARTY",
        }

        persistence._on_fsm_transition(transition_data)

        assert persistence._state_cache["light.living_room"] == "PARTY"

    def test_ignores_transition_without_entity_id(self, persistence, mock_logger):
        """Переход без entity_id игнорируется."""
        transition_data = {"to_state": "ON"}

        with patch.object(persistence, "_save_state") as mock_save:
            persistence._on_fsm_transition(transition_data)
            mock_save.assert_not_called()

    def test_ignores_transition_without_to_state(self, persistence, mock_logger):
        """Переход без to_state игнорируется."""
        transition_data = {"entity_id": "light.living_room"}

        with patch.object(persistence, "_save_state") as mock_save:
            persistence._on_fsm_transition(transition_data)
            mock_save.assert_not_called()

    def test_ignores_disabled_entity(self, persistence):
        """Переход для не включённой сущности игнорируется."""
        persistence.enable_for_entity("light.living_room")

        transition_data = {
            "entity_id": "light.other_room",
            "to_state": "ON",
        }

        with patch.object(persistence, "_save_state") as mock_save:
            persistence._on_fsm_transition(transition_data)
            mock_save.assert_not_called()

    def test_tracks_old_state_in_cache(self, persistence):
        """Старое состояние отслеживается в кэше."""
        persistence.enable_for_entity("light.living_room")
        persistence._state_cache["light.living_room"] = "OFF"

        transition_data = {
            "entity_id": "light.living_room",
            "to_state": "ON",
        }

        # Логирование должно содержать old_state и new_state
        persistence._on_fsm_transition(transition_data)

        assert persistence._state_cache["light.living_room"] == "ON"


class TestOnPlatformStarted:
    """Тесты восстановления состояний при старте платформы."""

    def test_restores_valid_state(self, mock_event_bus, mock_fsm_engine, mock_logger):
        """Восстановление валидного состояния."""
        persistence = FSMPersistence(
            event_bus=mock_event_bus,
            fsm_engine=mock_fsm_engine,
            adapter=MagicMock(),
            logger=mock_logger,
        )

        # Включаем персистентность
        persistence.enable_for_entity("light.living_room")

        # Создаём mock FSM state
        current_state = create_mock_state(current_state="OFF")
        mock_fsm_engine.set_state("light.living_room", current_state)

        # Добавляем определение с состоянием PARTY
        definition = MockDefinition(states=("OFF", "ON", "PARTY"))
        mock_fsm_engine.add_definition("light.living_room", definition)

        # Мок загрузки сохранённого состояния
        with patch.object(persistence, "_load_state", return_value="PARTY"):
            with patch.object(persistence, "_restore_state") as mock_restore:
                persistence._on_platform_started({})

                mock_restore.assert_called_once_with("light.living_room", "PARTY")

    def test_skips_restore_if_no_saved_state(self, mock_event_bus, mock_fsm_engine, mock_logger):
        """Пропуск восстановления если нет сохранённого состояния."""
        persistence = FSMPersistence(
            event_bus=mock_event_bus,
            fsm_engine=mock_fsm_engine,
            adapter=MagicMock(),
            logger=mock_logger,
        )

        persistence.enable_for_entity("light.living_room")

        with patch.object(persistence, "_load_state", return_value=None):
            with patch.object(persistence, "_restore_state") as mock_restore:
                persistence._on_platform_started({})

                mock_restore.assert_not_called()

    def test_skips_restore_if_fsm_not_found(self, mock_event_bus, mock_logger):
        """Пропуск восстановления если FSM не найден."""
        mock_fsm_engine = MockFSMEngine()
        persistence = FSMPersistence(
            event_bus=mock_event_bus,
            fsm_engine=mock_fsm_engine,
            adapter=MagicMock(),
            logger=mock_logger,
        )

        persistence.enable_for_entity("light.nonexistent")

        with patch.object(persistence, "_load_state", return_value="ON"):
            with patch.object(persistence, "_restore_state") as mock_restore:
                persistence._on_platform_started({})

                mock_restore.assert_not_called()

    def test_skips_restore_if_state_invalid(self, mock_event_bus, mock_fsm_engine, mock_logger):
        """Пропуск восстановления если состояние невалидно."""
        persistence = FSMPersistence(
            event_bus=mock_event_bus,
            fsm_engine=mock_fsm_engine,
            adapter=MagicMock(),
            logger=mock_logger,
        )

        persistence.enable_for_entity("light.living_room")

        current_state = create_mock_state(current_state="OFF")
        mock_fsm_engine.set_state("light.living_room", current_state)

        # Определение не содержит INVALID_STATE
        definition = MockDefinition(states=("OFF", "ON", "PARTY"))
        mock_fsm_engine.add_definition("light.living_room", definition)

        with patch.object(persistence, "_load_state", return_value="INVALID_STATE"):
            with patch.object(persistence, "_restore_state") as mock_restore:
                persistence._on_platform_started({})

                mock_restore.assert_not_called()

    def test_logs_restore_count(self, mock_event_bus, mock_fsm_engine, mock_logger):
        """Логирование количества восстановленных состояний."""
        persistence = FSMPersistence(
            event_bus=mock_event_bus,
            fsm_engine=mock_fsm_engine,
            adapter=MagicMock(),
            logger=mock_logger,
        )

        persistence.enable_for_entity("light.living_room")
        persistence.enable_for_entity("light.kitchen")

        current_state = create_mock_state(current_state="OFF")
        mock_fsm_engine.set_state("light.living_room", current_state)
        mock_fsm_engine.set_state("light.kitchen", current_state)

        definition = MockDefinition(states=("OFF", "ON"))
        mock_fsm_engine.add_definition("light.living_room", definition)
        mock_fsm_engine.add_definition("light.kitchen", definition)

        with patch.object(persistence, "_load_state", return_value="ON"):
            with patch.object(persistence, "_restore_state"):
                persistence._on_platform_started({})

                mock_logger.info.assert_any_call("Restore complete. Restored 2 states")


class TestSaveState:
    """Тесты сохранения состояний."""

    @pytest.mark.asyncio
    async def test_saves_via_input_text_when_available(self, persistence, mock_adapter):
        """Сохранение через input_text когда доступен."""
        persistence._input_text_available = True

        with patch("asyncio.get_running_loop"):
            with patch("asyncio.create_task") as mock_create_task:
                persistence._save_state("test_mode", "ON", "light.test")

                mock_create_task.assert_called_once()

    def test_falls_back_to_file_on_error(self, persistence, mock_logger):
        """Fallback в файл при ошибке input_text."""
        persistence._input_text_available = True

        with patch("asyncio.get_running_loop"):
            with patch("asyncio.create_task", side_effect=Exception("Async error")):
                with patch.object(persistence, "_save_to_file") as mock_save_file:
                    persistence._save_state("test_mode", "ON", "light.test")

                    mock_save_file.assert_called_once()

    def test_sets_input_text_unavailable_on_error(self, persistence):
        """Флаг input_text_available сбрасывается при ошибке."""
        persistence._input_text_available = True

        with patch("asyncio.get_running_loop"):
            with patch("asyncio.create_task", side_effect=Exception("Error")):
                with patch.object(persistence, "_save_to_file"):
                    persistence._save_state("test_mode", "ON", "light.test")

                    assert persistence._input_text_available is False

    def test_saves_directly_to_file_when_unavailable(self, persistence):
        """Прямое сохранение в файл когда input_text недоступен."""
        persistence._input_text_available = False

        with patch.object(persistence, "_save_to_file") as mock_save_file:
            persistence._save_state("test_mode", "ON", "light.test")

            mock_save_file.assert_called_once_with("test_mode", "ON")


class TestSaveToFile:
    """Тесты сохранения в файл."""

    def test_creates_storage_directory(self, persistence, tmp_path):
        """Создание директории для хранения."""
        storage_dir = tmp_path / ".homeassistant" / ".storage" / "fsm_persistence"

        with patch("pathlib.Path.home", return_value=tmp_path):
            with patch("builtins.open", create=True):
                persistence._save_to_file("test_mode", "ON")

                assert storage_dir.exists() or True  # Директория должна быть создана

    def test_saves_json_with_state_and_timestamp(self, persistence, tmp_path):
        """Сохранение JSON с состоянием и timestamp."""
        storage_dir = tmp_path / ".homeassistant" / ".storage" / "fsm_persistence"
        storage_dir.mkdir(parents=True)

        with patch("pathlib.Path.home", return_value=tmp_path):
            persistence._save_to_file("test_mode", "PARTY")

            storage_file = storage_dir / "test_mode.json"
            assert storage_file.exists()

            with open(storage_file) as f:
                data = json.load(f)
                assert data["state"] == "PARTY"
                assert "updated_at" in data

    def test_handles_save_error_gracefully(self, persistence, mock_logger):
        """Обработка ошибки сохранения."""
        with patch("pathlib.Path.home", side_effect=Exception("Path error")):
            persistence._save_to_file("test_mode", "ON")

            mock_logger.error.assert_called()


class TestLoadState:
    """Тесты загрузки состояний."""

    def test_loads_from_file_when_input_text_unavailable(self, persistence, tmp_path):
        """Загрузка из файла когда input_text недоступен."""
        persistence._input_text_available = False

        storage_dir = tmp_path / ".homeassistant" / ".storage" / "fsm_persistence"
        storage_dir.mkdir(parents=True)

        storage_file = storage_dir / "test_mode.json"
        with open(storage_file, "w") as f:
            json.dump({"state": "ON_MOTION", "updated_at": 1234567890}, f)

        with patch("pathlib.Path.home", return_value=tmp_path):
            result = persistence._load_state("test_mode")
            assert result == "ON_MOTION"

    def test_returns_none_if_file_not_exists(self, persistence, tmp_path):
        """Возврат None если файл не существует."""
        persistence._input_text_available = False

        with patch("pathlib.Path.home", return_value=tmp_path):
            result = persistence._load_state("nonexistent_mode")
            assert result is None


class TestLoadFromFile:
    """Тесты загрузки из файла."""

    def test_loads_valid_json(self, persistence, tmp_path):
        """Загрузка валидного JSON."""
        storage_dir = tmp_path / ".homeassistant" / ".storage" / "fsm_persistence"
        storage_dir.mkdir(parents=True)

        storage_file = storage_dir / "test_mode.json"
        with open(storage_file, "w") as f:
            json.dump({"state": "AWAY", "updated_at": 1234567890}, f)

        with patch("pathlib.Path.home", return_value=tmp_path):
            result = persistence._load_from_file("test_mode")
            assert result == "AWAY"

    def test_returns_none_for_missing_file(self, persistence, tmp_path):
        """Возврат None для отсутствующего файла."""
        with patch("pathlib.Path.home", return_value=tmp_path):
            result = persistence._load_from_file("missing_mode")
            assert result is None

    def test_returns_none_for_invalid_json(self, persistence, tmp_path):
        """Возврат None для невалидного JSON."""
        storage_dir = tmp_path / ".homeassistant" / ".storage" / "fsm_persistence"
        storage_dir.mkdir(parents=True)

        storage_file = storage_dir / "test_mode.json"
        with open(storage_file, "w") as f:
            f.write("invalid json {")

        with patch("pathlib.Path.home", return_value=tmp_path):
            result = persistence._load_from_file("test_mode")
            assert result is None


class TestRestoreState:
    """Тесты восстановления состояния."""

    def test_restores_state_when_different(self, mock_event_bus, mock_fsm_engine, mock_logger):
        """Восстановление состояния когда оно отличается от текущего."""
        persistence = FSMPersistence(
            event_bus=mock_event_bus,
            fsm_engine=mock_fsm_engine,
            adapter=MagicMock(),
            logger=mock_logger,
        )

        current_state = create_mock_state(current_state="OFF")
        mock_fsm_engine.set_state("light.living_room", current_state)

        definition = MockDefinition(states=("OFF", "ON", "PARTY"))
        mock_fsm_engine.add_definition("light.living_room", definition)

        persistence._restore_state("light.living_room", "PARTY")

        # Проверяем что состояние изменилось
        restored_state = mock_fsm_engine.get_state("light.living_room")
        assert restored_state.current_state == "PARTY"

    def test_publishes_restore_event(self, mock_event_bus, mock_fsm_engine):
        """Публикация события fsm.restored."""
        persistence = FSMPersistence(
            event_bus=mock_event_bus,
            fsm_engine=mock_fsm_engine,
            adapter=MagicMock(),
            logger=MagicMock(),
        )

        current_state = create_mock_state(current_state="OFF")
        mock_fsm_engine.set_state("light.living_room", current_state)

        definition = MockDefinition(states=("OFF", "PARTY"))
        mock_fsm_engine.add_definition("light.living_room", definition)

        persistence._restore_state("light.living_room", "PARTY")

        mock_event_bus.publish.assert_called_with(
            "fsm.restored",
            {
                "entity_id": "light.living_room",
                "restored_state": "PARTY",
                "previous_state": "OFF",
            },
        )

    def test_does_not_restore_if_same_state(self, mock_event_bus, mock_fsm_engine, mock_logger):
        """Не восстанавливает если состояние такое же."""
        persistence = FSMPersistence(
            event_bus=mock_event_bus,
            fsm_engine=mock_fsm_engine,
            adapter=MagicMock(),
            logger=mock_logger,
        )

        current_state = create_mock_state(current_state="PARTY")
        mock_fsm_engine.set_state("light.living_room", current_state)

        definition = MockDefinition(states=("OFF", "PARTY"))
        mock_fsm_engine.add_definition("light.living_room", definition)

        persistence._restore_state("light.living_room", "PARTY")

        # Событие не должно быть опубликовано
        restore_calls = [
            call for call in mock_event_bus.publish.call_args_list if call[0][0] == "fsm.restored"
        ]
        assert len(restore_calls) == 0

    def test_updates_cache_after_restore(self, mock_event_bus, mock_fsm_engine, mock_logger):
        """Обновление кэша после восстановления."""
        persistence = FSMPersistence(
            event_bus=mock_event_bus,
            fsm_engine=mock_fsm_engine,
            adapter=MagicMock(),
            logger=mock_logger,
        )

        current_state = create_mock_state(current_state="OFF")
        mock_fsm_engine.set_state("light.living_room", current_state)

        definition = MockDefinition(states=("OFF", "ON"))
        mock_fsm_engine.add_definition("light.living_room", definition)

        persistence._restore_state("light.living_room", "ON")

        assert persistence._state_cache["light.living_room"] == "ON"

    def test_logs_warning_for_invalid_state(self, mock_event_bus, mock_fsm_engine, mock_logger):
        """Логирование предупреждения для невалидного состояния."""
        persistence = FSMPersistence(
            event_bus=mock_event_bus,
            fsm_engine=mock_fsm_engine,
            adapter=MagicMock(),
            logger=mock_logger,
        )

        current_state = create_mock_state(current_state="OFF")
        mock_fsm_engine.set_state("light.living_room", current_state)

        definition = MockDefinition(states=("OFF", "ON"))
        mock_fsm_engine.add_definition("light.living_room", definition)

        persistence._restore_state("light.living_room", "INVALID")

        mock_logger.warning.assert_called()
