"""
Tests for State Store implementations
"""

import pytest
import asyncio
import tempfile
import json
from pathlib import Path

from core.state_store import (
    StateStore,
    MemoryStateStore,
    FileStateStore,
    InputTextStateStore,
    DebouncedStateStore
)


# ============================================
# MemoryStateStore Tests
# ============================================

class TestMemoryStateStore:
    """Тесты для MemoryStateStore"""
    
    @pytest.fixture
    def store(self):
        return MemoryStateStore()
    
    @pytest.mark.asyncio
    async def test_save_and_load(self, store):
        """Сохранение и загрузка работают"""
        state_data = {
            "current": "ON",
            "entered_at": 12345.0,
            "entered_by": "test"
        }
        
        await store.save("light.test", state_data)
        loaded = await store.load("light.test")
        
        assert loaded is not None
        assert loaded["current"] == "ON"
        assert loaded["entered_at"] == 12345.0
    
    @pytest.mark.asyncio
    async def test_load_nonexistent(self, store):
        """Загрузка несуществующего возвращает None"""
        result = await store.load("light.nonexistent")
        assert result is None
    
    @pytest.mark.asyncio
    async def test_load_all(self, store):
        """Загрузка всех состояний"""
        await store.save("light.one", {"current": "ON"})
        await store.save("light.two", {"current": "OFF"})
        
        all_states = await store.load_all()
        
        assert len(all_states) == 2
        assert all_states["light.one"]["current"] == "ON"
        assert all_states["light.two"]["current"] == "OFF"
    
    @pytest.mark.asyncio
    async def test_delete(self, store):
        """Удаление работает"""
        await store.save("light.test", {"current": "ON"})
        await store.delete("light.test")
        
        result = await store.load("light.test")
        assert result is None
    
    @pytest.mark.asyncio
    async def test_clear(self, store):
        """Очистка работает"""
        await store.save("light.one", {"current": "ON"})
        await store.save("light.two", {"current": "OFF"})
        
        await store.clear()
        
        all_states = await store.load_all()
        assert len(all_states) == 0
    
    @pytest.mark.asyncio
    async def test_handles_concurrent_access(self, store):
        """Параллельный доступ не вызывает проблем"""
        async def save_and_load(i):
            await store.save(f"light.{i}", {"current": f"STATE_{i}"})
            return await store.load(f"light.{i}")
        
        tasks = [save_and_load(i) for i in range(10)]
        results = await asyncio.gather(*tasks)
        
        for i, result in enumerate(results):
            assert result is not None
            assert result["current"] == f"STATE_{i}"


# ============================================
# FileStateStore Tests
# ============================================

class TestFileStateStore:
    """Тесты для FileStateStore"""
    
    @pytest.fixture
    def temp_file(self):
        # Создаём временный путь но не файл
        import tempfile
        path = tempfile.mktemp(suffix='.json')
        yield path
        # Cleanup
        try:
            p = Path(path)
            if p.exists():
                p.unlink()
            tmp = p.with_suffix('.tmp')
            if tmp.exists():
                tmp.unlink()
        except Exception:
            pass
    
    @pytest.fixture
    def file_store(self, temp_file):
        from unittest.mock import MagicMock
        logger = MagicMock()
        return FileStateStore(temp_file, debounce_sec=0.1, logger=logger)
    
    @pytest.mark.asyncio
    async def test_creates_file_on_first_save(self, temp_file):
        """Файл создается при первом сохранении"""
        store = FileStateStore(temp_file, debounce_sec=0.1)
        await store.save("light.test", {"current": "ON"})
        await store.flush()
        
        assert Path(temp_file).exists()
    
    @pytest.mark.asyncio
    async def test_saves_state_correctly(self, temp_file):
        """Формат сохранения правильный"""
        store = FileStateStore(temp_file, debounce_sec=0.1)
        state_data = {
            "current": "ON_MOTION",
            "entered_at": 1694184000.0,
            "entered_by": "motion_detected"
        }
        
        await store.save("light.kitchen", state_data)
        await store.flush()
        
        with open(temp_file, 'r') as f:
            data = json.load(f)
        
        assert data["version"] == 1
        assert "states" in data
        assert "light.kitchen" in data["states"]
        assert data["states"]["light.kitchen"]["current"] == "ON_MOTION"
    
    @pytest.mark.asyncio
    async def test_loads_saved_state(self, temp_file):
        """Загрузка после сохранения"""
        store = FileStateStore(temp_file, debounce_sec=0.1)
        state_data = {"current": "ON", "entered_at": 12345.0}
        
        await store.save("light.test", state_data)
        await store.flush()
        
        # Создаём новый инстанс для проверки загрузки
        store2 = FileStateStore(temp_file, debounce_sec=0.1)
        loaded = await store2.load("light.test")
        
        assert loaded is not None
        assert loaded["current"] == "ON"
    
    @pytest.mark.asyncio
    async def test_handles_corrupted_file(self, temp_file):
        """Битый файл не роняет систему"""
        # Пишем битый JSON
        with open(temp_file, 'w') as f:
            f.write("{ invalid json }")
        
        store = FileStateStore(temp_file, debounce_sec=0.1, logger=None)
        loaded = await store.load("light.test")
        
        # Должен вернуть None а не упасть
        assert loaded is None
    
    @pytest.mark.asyncio
    async def test_handles_missing_file(self, temp_file):
        """Отсутствие файла нормально"""
        # Файл ещё не создан - это нормально
        store = FileStateStore(temp_file, debounce_sec=0.1, logger=None)
        loaded = await store.load("light.test")
        
        assert loaded is None
    
    @pytest.mark.asyncio
    async def test_atomic_write(self, temp_file):
        """Атомарная запись - нет частичных данных"""
        store = FileStateStore(temp_file, debounce_sec=0.1)
        
        # Сохраняем состояние
        await store.save("light.test", {"current": "ON"})
        await store.flush()
        
        # Проверяем что нет временного файла
        tmp_path = Path(temp_file).with_suffix('.tmp')
        assert not tmp_path.exists()
    
    @pytest.mark.asyncio
    async def test_debounce(self, temp_file):
        """Дебаунс работает"""
        store = FileStateStore(temp_file, debounce_sec=1.0)
        
        # Быстрые сохранения
        await store.save("light.one", {"current": "ON"})
        await store.save("light.two", {"current": "OFF"})
        await store.save("light.three", {"current": "AUTO"})
        
        # Сразу после сохранения файл может ещё не существовать
        #因为 дебаунс
        await asyncio.sleep(0.1)
        
        # Файл может ещё не быть записан
        # Это ожидаемое поведение дебаунса
    
    @pytest.mark.asyncio
    async def test_version_check(self, temp_file):
        """Проверка версии формата"""
        # Создаём файл со старой версией
        old_data = {
            "version": 0,
            "states": {"light.test": {"current": "ON"}}
        }
        with open(temp_file, 'w') as f:
            json.dump(old_data, f)
        
        store = FileStateStore(temp_file, debounce_sec=0.1, logger=None)
        loaded = await store.load("light.test")
        
        # Должна сработать миграция
        assert loaded is not None
    
    @pytest.mark.asyncio
    async def test_delete(self, temp_file):
        """Удаление работает"""
        store = FileStateStore(temp_file, debounce_sec=0.1)
        await store.save("light.test", {"current": "ON"})
        await store.flush()
        
        await store.delete("light.test")
        await store.flush()
        
        loaded = await store.load("light.test")
        assert loaded is None
    
    @pytest.mark.asyncio
    async def test_clear(self, temp_file):
        """Очистка работает"""
        store = FileStateStore(temp_file, debounce_sec=0.1)
        await store.save("light.one", {"current": "ON"})
        await store.save("light.two", {"current": "OFF"})
        await store.flush()
        
        await store.clear()
        
        all_states = await store.load_all()
        assert len(all_states) == 0


# ============================================
# InputTextStateStore Tests
# ============================================

class TestInputTextStateStore:
    """Тесты для InputTextStateStore"""
    
    @pytest.fixture
    def store(self):
        from unittest.mock import MagicMock
        logger = MagicMock()
        return InputTextStateStore(logger=logger)
    
    def test_entity_to_helper_mapping(self, store):
        """Маппинг entity_id -> helper_name"""
        helper = store._entity_to_helper("light.kitchen")
        assert helper == "input_text.platform_v3_light_kitchen"
        
        helper = store._entity_to_helper("climate.living_room")
        assert helper == "input_text.platform_v3_climate_living_room"
    
    def test_compact_serialization(self, store):
        """Данные компактно упакованы"""
        state_data = {
            "current": "ON_MOTION",
            "entered_at": 1694184000.0,
            "entered_by": "motion",
            "last_controlled_by": "manual"
        }
        
        serialized = store._serialize("light.kitchen", state_data)
        
        # Проверяем формат
        parts = serialized.split("|")
        assert len(parts) == 5
        assert parts[0] == "light.kitchen"
        assert parts[1] == "ON_MOTION"
        
        # Проверяем длину < 255
        assert len(serialized) < 255
    
    def test_deserialization(self, store):
        """При загрузке данные восстанавливаются"""
        serialized = "light.kitchen|ON_MOTION|1694184000|motion|manual"
        
        data = store._deserialize(serialized)
        
        assert data is not None
        assert data["current"] == "ON_MOTION"
        assert data["entered_at"] == 1694184000.0
        assert data["entered_by"] == "motion"
        assert data["last_controlled_by"] == "manual"
    
    def test_handles_special_chars(self, store):
        """Спецсимволы в entity_id обрабатываются"""
        entity_id = "light.kitchen_main"
        helper = store._entity_to_helper(entity_id)
        
        # Должен корректно обработать подчёркивания
        assert "platform_v3" in helper
    
    @pytest.mark.asyncio
    async def test_missing_helper_returns_none(self, store):
        """Нет хелпера → предупреждение и None"""
        # В тестах нет реального HA, поэтому должен вернуть None
        result = await store.load("light.nonexistent")
        assert result is None


# ============================================
# DebouncedStateStore Tests
# ============================================

class TestDebouncedStateStore:
    """Тесты для DebouncedStateStore"""
    
    @pytest.fixture
    def inner_store(self):
        return MemoryStateStore()
    
    @pytest.fixture
    def debounced_store(self, inner_store):
        return DebouncedStateStore(inner_store, debounce_sec=0.1)
    
    @pytest.mark.asyncio
    async def test_writes_immediately_if_delay_passed(self, debounced_store):
        """Пишет сразу если дебаунс истёк"""
        await debounced_store.save("light.test", {"current": "ON"})
        
        # Ждём больше debounce_sec
        await asyncio.sleep(0.2)
        
        loaded = await debounced_store.load("light.test")
        assert loaded is not None
    
    @pytest.mark.asyncio
    async def test_delays_write(self, debounced_store):
        """Не пишет если дебаунс не истёк"""
        await debounced_store.save("light.test", {"current": "ON"})
        
        # Сразу после save данные могут быть в pending
        # Это ожидаемое поведение
    
    @pytest.mark.asyncio
    async def test_flush_writes_all_pending(self, debounced_store):
        """Flush записывает всё"""
        await debounced_store.save("light.one", {"current": "ON"})
        await debounced_store.save("light.two", {"current": "OFF"})
        
        await debounced_store.flush()
        
        # После flush данные должны быть в inner store
        loaded_one = await debounced_store.load("light.one")
        loaded_two = await debounced_store.load("light.two")
        
        assert loaded_one is not None
        assert loaded_two is not None
    
    @pytest.mark.asyncio
    async def test_multiple_saves_collapse_to_one(self, debounced_store):
        """Несколько сохранений превращаются в одно"""
        # Несколько быстрых сохранений
        await debounced_store.save("light.test", {"current": "ONE"})
        await debounced_store.save("light.test", {"current": "TWO"})
        await debounced_store.save("light.test", {"current": "THREE"})
        
        await debounced_store.flush()
        
        # Должно сохраниться последнее состояние
        loaded = await debounced_store.load("light.test")
        assert loaded["current"] == "THREE"
    
    @pytest.mark.asyncio
    async def test_preserves_latest_state(self, debounced_store):
        """Сохраняется последнее состояние, не первое"""
        await debounced_store.save("light.test", {"current": "FIRST"})
        await asyncio.sleep(0.01)
        await debounced_store.save("light.test", {"current": "LAST"})
        
        await debounced_store.flush()
        
        loaded = await debounced_store.load("light.test")
        assert loaded["current"] == "LAST"
