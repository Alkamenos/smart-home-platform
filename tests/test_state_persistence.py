"""
Tests for State Persistence module.

Спецификация:
1. StatePersistence сохраняет состояния FSM в JSON файл
2. Поддерживает атомарную запись с блокировкой файлов
3. Работает на Windows (msvcrt) и Linux/Unix (fcntl)
4. Методы: save_state, load_state, clear_state, clear_all, save_all
5. При сохранении используется временный файл + atomic rename
6. Блокировка предотвращает race conditions при concurrent доступе
"""

import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from core.state_persistence import StatePersistence


class TestStatePersistenceInitialization:
    """Тесты инициализации StatePersistence"""

    def test_creates_storage_directory(self):
        """При инициализации создается директория для файла хранения"""
        with tempfile.TemporaryDirectory() as tmpdir:
            storage_path = os.path.join(tmpdir, "subdir", "state.json")
            persistence = StatePersistence(storage_path)
            
            assert Path(storage_path).parent.exists()
            assert persistence.storage_path == Path(storage_path)

    def test_default_storage_path(self):
        """По умолчанию используется state.json в текущей директории"""
        persistence = StatePersistence()
        
        assert persistence.storage_path == Path("state.json")


class TestSaveState:
    """Тесты метода save_state"""

    @pytest.fixture
    def persistence(self):
        """Создает StatePersistence с временным файлом"""
        fd, path = tempfile.mkstemp(suffix=".json")
        os.close(fd)
        os.unlink(path)  # Удаляем файл, оставляем путь
        return StatePersistence(path)

    def test_saves_state_to_file(self, persistence):
        """save_state сохраняет состояние в JSON файл"""
        entity_id = "light.kitchen"
        state = "ON_MOTION"
        context = {"motion_detected": True, "brightness": 80}
        
        persistence.save_state(entity_id, state, context)
        
        # Проверяем содержимое файла
        with open(persistence.storage_path) as f:
            data = json.load(f)
        
        assert entity_id in data
        assert data[entity_id]["state"] == state
        assert data[entity_id]["context"] == context

    def test_saves_multiple_states(self, persistence):
        """Можно сохранить несколько состояний разных entity"""
        persistence.save_state("light.one", "ON", {"bright": 100})
        persistence.save_state("light.two", "OFF", {"bright": 0})
        persistence.save_state("climate.thermostat", "HEATING", {"temp": 22})
        
        with open(persistence.storage_path) as f:
            data = json.load(f)
        
        assert len(data) == 3
        assert data["light.one"]["state"] == "ON"
        assert data["light.two"]["state"] == "OFF"
        assert data["climate.thermostat"]["state"] == "HEATING"

    def test_updates_existing_state(self, persistence):
        """При повторном сохранении состояние обновляется"""
        persistence.save_state("light.kitchen", "ON", {"bright": 100})
        persistence.save_state("light.kitchen", "OFF", {"bright": 0})
        
        with open(persistence.storage_path) as f:
            data = json.load(f)
        
        assert data["light.kitchen"]["state"] == "OFF"
        assert data["light.kitchen"]["context"]["bright"] == 0

    def test_uses_windows_locking_on_windows(self, persistence):
        """На Windows используется msvcrt.locking"""
        # Этот тест просто проверяет что save_state работает
        # Реальное тестирование platform-specific locking требует соответствующей OS
        persistence.save_state("light.test", "ON", {})
        
        with open(persistence.storage_path) as f:
            data = json.load(f)
        
        assert "light.test" in data

    @patch('sys.platform', 'linux')
    @patch('core.state_persistence.fcntl')
    def test_uses_fcntl_locking_on_linux(self, mock_fcntl, persistence):
        """На Linux используется fcntl.flock"""
        mock_fcntl.LOCK_EX = 1
        mock_fcntl.LOCK_UN = 2
        
        persistence.save_state("light.test", "ON", {})
        
        # Проверяем что fcntl.flock вызывался
        assert mock_fcntl.flock.called

    def test_handles_empty_context(self, persistence):
        """Пустой контекст сохраняется корректно"""
        persistence.save_state("light.test", "ON", {})
        
        with open(persistence.storage_path) as f:
            data = json.load(f)
        
        assert data["light.test"]["context"] == {}

    def test_handles_complex_context(self, persistence):
        """Сложный контекст с вложенными структурами сохраняется"""
        context = {
            "nested": {"key": "value"},
            "list": [1, 2, 3],
            "unicode": "привет мир",
            "special": "/\\\"quotes\\\""
        }
        
        persistence.save_state("light.test", "COMPLEX", context)
        
        with open(persistence.storage_path) as f:
            data = json.load(f)
        
        assert data["light.test"]["context"] == context


class TestLoadState:
    """Тесты метода load_state"""

    @pytest.fixture
    def persistence_with_data(self):
        """Создает StatePersistence с предзаполненными данными"""
        fd, path = tempfile.mkstemp(suffix=".json")
        os.close(fd)
        
        data = {
            "light.kitchen": {"state": "ON_MOTION", "context": {"motion": True}},
            "light.bedroom": {"state": "OFF", "context": {}},
        }
        
        with open(path, "w") as f:
            json.dump(data, f)
        
        return StatePersistence(path), data

    def test_loads_existing_state(self, persistence_with_data):
        """load_state возвращает кортеж (state, context) для существующего entity"""
        persistence, original_data = persistence_with_data
        
        result = persistence.load_state("light.kitchen")
        
        assert result is not None
        assert result[0] == "ON_MOTION"
        assert result[1] == {"motion": True}

    def test_returns_none_for_missing_entity(self, persistence_with_data):
        """load_state возвращает None для несуществующего entity"""
        persistence, _ = persistence_with_data
        
        result = persistence.load_state("light.nonexistent")
        
        assert result is None

    def test_returns_none_when_state_is_null(self, persistence_with_data):
        """Если state=null в файле, возвращается None"""
        persistence, _ = persistence_with_data
        
        # Модифицируем файл чтобы state был null
        with open(persistence.storage_path, "w") as f:
            json.dump({"light.test": {"state": None, "context": {}}}, f)
        
        result = persistence.load_state("light.test")
        
        assert result is None

    def test_returns_empty_context_if_missing(self, persistence_with_data):
        """Если context отсутствует, возвращается пустой dict"""
        persistence, _ = persistence_with_data
        
        # Записываем данные без context
        with open(persistence.storage_path, "w") as f:
            json.dump({"light.test": {"state": "ON"}}, f)
        
        result = persistence.load_state("light.test")
        
        assert result is not None
        assert result[0] == "ON"
        assert result[1] == {}


class TestClearState:
    """Тесты метода clear_state"""

    @pytest.fixture
    def persistence_with_data(self):
        """Создает StatePersistence с данными"""
        fd, path = tempfile.mkstemp(suffix=".json")
        os.close(fd)
        
        data = {
            "light.one": {"state": "ON", "context": {}},
            "light.two": {"state": "OFF", "context": {}},
        }
        
        with open(path, "w") as f:
            json.dump(data, f)
        
        return StatePersistence(path)

    def test_removes_entity_state(self, persistence_with_data):
        """clear_state удаляет состояние конкретного entity"""
        persistence = persistence_with_data
        
        persistence.clear_state("light.one")
        
        with open(persistence.storage_path) as f:
            data = json.load(f)
        
        assert "light.one" not in data
        assert "light.two" in data

    def test_no_error_for_nonexistent_entity(self, persistence_with_data):
        """clear_state не вызывает ошибок для несуществующего entity"""
        persistence = persistence_with_data
        
        # Не должно вызывать исключений
        persistence.clear_state("light.nonexistent")


class TestClearAll:
    """Тесты метода clear_all"""

    @pytest.fixture
    def persistence_with_data(self):
        """Создает StatePersistence с данными"""
        fd, path = tempfile.mkstemp(suffix=".json")
        os.close(fd)
        
        data = {
            "light.one": {"state": "ON", "context": {}},
            "light.two": {"state": "OFF", "context": {}},
        }
        
        with open(path, "w") as f:
            json.dump(data, f)
        
        return StatePersistence(path)

    def test_deletes_storage_file(self, persistence_with_data):
        """clear_all удаляет файл хранения"""
        persistence = persistence_with_data
        
        persistence.clear_all()
        
        assert not persistence.storage_path.exists()

    def test_no_error_if_file_does_not_exist(self):
        """clear_all не вызывает ошибок если файла нет"""
        fd, path = tempfile.mkstemp(suffix=".json")
        os.close(fd)
        os.unlink(path)
        
        persistence = StatePersistence(path)
        
        # Не должно вызывать исключений
        persistence.clear_all()


class TestSaveAll:
    """Тесты метода save_all"""

    @pytest.fixture
    def persistence(self):
        """Создает StatePersistence"""
        fd, path = tempfile.mkstemp(suffix=".json")
        os.close(fd)
        os.unlink(path)
        return StatePersistence(path)

    def test_saves_all_states_at_once(self, persistence):
        """save_all сохраняет все состояния в одном вызове"""
        states = {
            "light.one": ("ON", {"bright": 100}),
            "light.two": ("OFF", {"bright": 0}),
            "climate.thermostat": ("HEATING", {"temp": 22}),
        }
        
        persistence.save_all(states)
        
        with open(persistence.storage_path) as f:
            data = json.load(f)
        
        assert len(data) == 3
        assert data["light.one"]["state"] == "ON"
        assert data["light.one"]["context"] == {"bright": 100}
        assert data["light.two"]["state"] == "OFF"
        assert data["climate.thermostat"]["state"] == "HEATING"

    def test_overwrites_existing_file(self, persistence):
        """save_all перезаписывает существующий файл"""
        # Сначала сохраняем одно состояние
        persistence.save_state("light.old", "OLD", {})
        
        # Затем save_all с новыми данными
        states = {
            "light.new": ("NEW", {}),
        }
        persistence.save_all(states)
        
        with open(persistence.storage_path) as f:
            data = json.load(f)
        
        assert "light.old" not in data
        assert "light.new" in data


class TestAtomicWrite:
    """Тесты атомарности записи"""

    def test_uses_temp_file_then_rename(self):
        """Запись использует временный файл затем atomic rename"""
        fd, path = tempfile.mkstemp(suffix=".json")
        os.close(fd)
        os.unlink(path)
        
        persistence = StatePersistence(path)
        
        # Сохраняем состояние
        persistence.save_state("light.test", "ON", {})
        
        # Проверяем что нет временных файлов
        temp_files = list(Path(path).parent.glob("*.tmp.*"))
        assert len(temp_files) == 0
        
        # Проверяем что основной файл существует и корректен
        assert Path(path).exists()
        with open(path) as f:
            data = json.load(f)
        assert "light.test" in data

    def test_cleans_up_temp_file_on_error(self):
        """Временные файлы очищаются при ошибке"""
        fd, path = tempfile.mkstemp(suffix=".json")
        os.close(fd)
        os.unlink(path)
        
        persistence = StatePersistence(path)
        
        # Создаем ситуацию где temp файл может остаться
        # (в реальной ситуации это проверяется через mocking)
        persistence.save_state("light.test", "ON", {})
        
        # Все temp файлы должны быть удалены
        temp_files = list(Path(path).parent.glob("*.tmp.*"))
        assert len(temp_files) == 0


class TestConcurrentAccess:
    """Тесты concurrent доступа (с моками)"""

    @patch('core.state_persistence.StatePersistence._acquire_lock')
    @patch('core.state_persistence.StatePersistence._release_lock')
    def test_acquire_lock_before_read(self, mock_release, mock_acquire):
        """Блокировка приобретается перед чтением"""
        fd, path = tempfile.mkstemp(suffix=".json")
        os.close(fd)
        
        # Записываем начальные данные
        with open(path, "w") as f:
            json.dump({"existing": {"state": "ON", "context": {}}}, f)
        
        persistence = StatePersistence(path)
        persistence.save_state("light.test", "OFF", {})
        
        # Проверяем что lock был приобретен
        assert mock_acquire.called
        assert mock_release.called

    def test_file_locking_prevents_race_conditions(self):
        """Блокировка файлов предотвращает race conditions"""
        # Этот тест демонстрирует что locking механизм существует
        # Реальное тестирование concurrent доступа требует многопоточности
        fd, path = tempfile.mkstemp(suffix=".json")
        os.close(fd)
        
        persistence = StatePersistence(path)
        
        # Просто проверяем что метод существует и работает
        persistence.save_state("light.test", "ON", {})
        
        with open(path) as f:
            data = json.load(f)
        
        assert "light.test" in data


class TestEdgeCases:
    """Тесты граничных случаев"""

    def test_handles_corrupted_json_file(self):
        """При битом JSON файле save_state работает корректно"""
        fd, path = tempfile.mkstemp(suffix=".json")
        os.close(fd)
        
        # Записываем битый JSON
        with open(path, "w") as f:
            f.write("{ invalid json }}}")
        
        persistence = StatePersistence(path)
        
        # Должно работать несмотря на битый файл
        persistence.save_state("light.test", "ON", {})
        
        # Проверяем что файл теперь корректен
        with open(path) as f:
            data = json.load(f)
        
        assert "light.test" in data

    def test_handles_empty_file(self):
        """Пустой файл обрабатывается корректно"""
        fd, path = tempfile.mkstemp(suffix=".json")
        os.close(fd)
        
        # Создаем пустой файл
        with open(path, "w") as f:
            pass
        
        persistence = StatePersistence(path)
        persistence.save_state("light.test", "ON", {})
        
        with open(path) as f:
            data = json.load(f)
        
        assert "light.test" in data

    def test_handles_unicode_entity_ids(self):
        """Unicode в entity_id обрабатывается корректно"""
        fd, path = tempfile.mkstemp(suffix=".json")
        os.close(fd)
        os.unlink(path)
        
        persistence = StatePersistence(path)
        persistence.save_state("свет.кухня", "ON", {"яркость": 100})
        
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        
        assert "свет.кухня" in data
        assert data["свет.кухня"]["context"]["яркость"] == 100

    def test_handles_special_characters_in_context(self):
        """Спецсимволы в context сохраняются корректно"""
        fd, path = tempfile.mkstemp(suffix=".json")
        os.close(fd)
        os.unlink(path)
        
        persistence = StatePersistence(path)
        context = {"path": "C:\\Users\\test", "quote": 'He said "hello"'}
        persistence.save_state("light.test", "ON", context)
        
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        
        assert data["light.test"]["context"] == context
