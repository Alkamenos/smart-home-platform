"""
Unit тесты для DeviceCache и IndexManager.

Покрывает следующие аспекты:
- LRU кэширование с вытеснением
- TTL (time-to-live) для кэша
- Thread-safe операции
- Индексирование по различным критериям
- Метрики производительности
"""

import threading
import time
from uuid import uuid4

import pytest
from src.core.models.device import Device
from src.core.persistence.cache import DeviceCache
from src.core.persistence.index_manager import IndexManager


# ============================================================================
# Фиксчеры для создания тестовых данных
# ============================================================================


@pytest.fixture
def sample_device():
    """Фикстура: создать пример Device объекта."""
    source_id = uuid4()
    return Device(
        ha_entity_id="light.kitchen_light",
        source_id=source_id,
        name="Kitchen Light",
        device_type="light",
        model="Philips Hue A19",
        manufacturer="Philips",
        state={"state": "on", "brightness": 200},
        status="available",
    )


@pytest.fixture
def sample_devices():
    """Фикстура: создать несколько Device объектов."""
    source_id = uuid4()
    return [
        Device(
            ha_entity_id=f"light.room_{i}",
            source_id=source_id,
            name=f"Room {i} Light",
            device_type="light",
            state={"state": "on"},
            status="available",
        )
        for i in range(5)
    ]


@pytest.fixture
def device_cache():
    """Фикстура: создать DeviceCache с небольшим TTL для тестов."""
    return DeviceCache(max_size=10, ttl_seconds=2)


@pytest.fixture
def index_manager():
    """Фикстура: создать IndexManager."""
    return IndexManager()


# ============================================================================
# Тесты для DeviceCache
# ============================================================================


class TestDeviceCache:
    """Тесты функциональности кэша DeviceCache."""

    def test_cache_set_and_get(self, device_cache, sample_device):
        """Тест: добавление и получение элемента из кэша."""
        key = f"device:{sample_device.id}"

        device_cache.set(key, sample_device)
        retrieved = device_cache.get(key)

        assert retrieved is not None
        assert retrieved.id == sample_device.id
        assert device_cache.cache_hits == 1

    def test_cache_miss(self, device_cache):
        """Тест: обращение к несуществующему элементу."""
        result = device_cache.get("nonexistent_key")

        assert result is None
        assert device_cache.cache_misses == 1

    def test_cache_invalidate(self, device_cache, sample_device):
        """Тест: инвалидация элемента из кэша."""
        key = f"device:{sample_device.id}"

        device_cache.set(key, sample_device)
        result = device_cache.invalidate(key)

        assert result is True
        assert device_cache.get(key) is None
        assert device_cache.invalidations == 1

    def test_cache_invalidate_nonexistent(self, device_cache):
        """Тест: попытка инвалидации несуществующего элемента."""
        result = device_cache.invalidate("nonexistent_key")

        assert result is False
        assert device_cache.invalidations == 0

    def test_cache_clear(self, device_cache, sample_devices):
        """Тест: полная очистка кэша."""
        for device in sample_devices:
            device_cache.set(f"device:{device.id}", device)

        assert device_cache.get_size() == 5

        device_cache.clear()

        assert device_cache.get_size() == 0
        assert device_cache.get("device:" + str(sample_devices[0].id)) is None

    def test_cache_lru_eviction(self, device_cache):
        """Тест: LRU вытеснение при достижении максимального размера."""
        # Создаем 11 элементов (кэш имеет размер 10)
        keys_and_values = [(f"key_{i}", f"value_{i}") for i in range(11)]

        for key, value in keys_and_values:
            device_cache.set(key, value)

        # Первый элемент должен быть вытеснен
        assert device_cache.get("key_0") is None
        # Последний элемент должен быть в кэше
        assert device_cache.get("key_10") is not None
        assert device_cache.get_size() == 10

    def test_cache_ttl_expiration(self, device_cache, sample_device):
        """Тест: истечение TTL."""
        key = f"device:{sample_device.id}"

        device_cache.set(key, sample_device)
        assert device_cache.get(key) is not None

        # Ждем истечения TTL (2 секунды)
        time.sleep(2.1)

        assert device_cache.get(key) is None
        assert device_cache.cache_misses == 1
        assert device_cache.invalidations >= 1

    def test_cache_extend_ttl(self, device_cache, sample_device):
        """Тест: продление TTL элемента."""
        key = f"device:{sample_device.id}"

        device_cache.set(key, sample_device)
        time.sleep(1)

        # Продлеваем TTL
        result = device_cache.extend_ttl(key, additional_seconds=3)

        assert result is True

        # Ждем еще 1.5 секунды (итого 2.5 с момента создания)
        time.sleep(1.5)

        # Элемент все еще должен быть в кэше
        assert device_cache.get(key) is not None

    def test_cache_invalidate_by_prefix(self, device_cache):
        """Тест: инвалидация по префиксу."""
        # Добавляем элементы с разными префиксами
        for i in range(5):
            device_cache.set(f"device:{i}", f"device_value_{i}")
            device_cache.set(f"source:{i}", f"source_value_{i}")

        # Инвалидируем по префиксу "device:"
        removed_count = device_cache.invalidate_by_prefix("device:")

        assert removed_count == 5

        # Элементы с префиксом "device:" должны быть удалены
        for i in range(5):
            assert device_cache.get(f"device:{i}") is None
            # Но "source:" должны остаться
            assert device_cache.get(f"source:{i}") is not None

    def test_cache_cleanup_expired(self, device_cache):
        """Тест: очистка истекших записей."""
        # Добавляем элементы
        for i in range(5):
            device_cache.set(f"key_{i}", f"value_{i}")

        initial_size = device_cache.get_size()
        assert initial_size == 5

        # Ждем истечения TTL
        time.sleep(2.1)

        # Очищаем истекшие
        removed_count = device_cache.cleanup_expired()

        assert removed_count == 5
        assert device_cache.get_size() == 0

    def test_cache_stats(self, device_cache, sample_device):
        """Тест: получение статистики кэша."""
        key = f"device:{sample_device.id}"

        device_cache.set(key, sample_device)
        device_cache.get(key)  # hit
        device_cache.get("nonexistent")  # miss
        device_cache.get(key)  # hit

        stats = device_cache.get_stats()

        assert stats["cache_hits"] == 2
        assert stats["cache_misses"] == 1
        assert stats["cache_size"] == 1
        assert stats["total_requests"] == 3
        assert stats["hit_rate_percent"] == pytest.approx(66.67, abs=0.1)

    def test_cache_thread_safety(self, device_cache):
        """Тест: thread-safe операции."""

        def worker(thread_id):
            for i in range(100):
                key = f"key_{thread_id}_{i}"
                device_cache.set(key, f"value_{thread_id}_{i}")
                device_cache.get(key)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(5)]

        for thread in threads:
            thread.start()

        for thread in threads:
            thread.join()

        # Проверяем что размер кэша разумный (не больше max_size)
        assert device_cache.get_size() <= device_cache.max_size

    def test_cache_move_to_end_on_access(self, device_cache):
        """Тест: перемещение элемента в конец при доступе (LRU)."""
        # Добавляем элементы до почти полного размера
        for i in range(9):
            device_cache.set(f"key_{i}", f"value_{i}")

        # Обращаемся к первому элементу (переместит его в конец)
        device_cache.get("key_0")

        # Добавляем еще элемент
        device_cache.set("key_new", "new_value")

        # Второй элемент должен быть вытеснен (т.к. первый был недавно использован)
        assert device_cache.get("key_1") is None
        assert device_cache.get("key_0") is not None
        assert device_cache.get("key_new") is not None


# ============================================================================
# Тесты для IndexManager
# ============================================================================


class TestIndexManager:
    """Тесты функциональности индексирования IndexManager."""

    def test_index_add_and_get_device(self, index_manager, sample_device):
        """Тест: добавление и получение устройства."""
        index_manager.add_device(sample_device)

        retrieved = index_manager.get_device(sample_device.id)

        assert retrieved is not None
        assert retrieved.id == sample_device.id

    def test_index_remove_device(self, index_manager, sample_device):
        """Тест: удаление устройства из индекса."""
        index_manager.add_device(sample_device)
        assert index_manager.get_device(sample_device.id) is not None

        result = index_manager.remove_device(sample_device.id)

        assert result is True
        assert index_manager.get_device(sample_device.id) is None

    def test_index_find_by_source(self, index_manager, sample_devices):
        """Тест: поиск устройств по источнику."""
        for device in sample_devices:
            index_manager.add_device(device)

        source_id = sample_devices[0].source_id
        found_devices = index_manager.find_by_source(source_id)

        assert len(found_devices) == len(sample_devices)
        assert all(d.source_id == source_id for d in found_devices)

    def test_index_find_by_type(self, index_manager):
        """Тест: поиск устройств по типу."""
        source_id = uuid4()
        light_devices = [
            Device(
                ha_entity_id=f"light.room_{i}",
                source_id=source_id,
                name=f"Light {i}",
                device_type="light",
                state={"state": "on"},
                status="available",
            )
            for i in range(3)
        ]
        switch_devices = [
            Device(
                ha_entity_id=f"switch.room_{i}",
                source_id=source_id,
                name=f"Switch {i}",
                device_type="switch",
                state={"state": "on"},
                status="available",
            )
            for i in range(2)
        ]

        for device in light_devices + switch_devices:
            index_manager.add_device(device)

        found_lights = index_manager.find_by_type("light")
        found_switches = index_manager.find_by_type("switch")

        assert len(found_lights) == 3
        assert len(found_switches) == 2
        assert all(d.device_type == "light" for d in found_lights)
        assert all(d.device_type == "switch" for d in found_switches)

    def test_index_find_by_ha_entity_id(self, index_manager, sample_device):
        """Тест: поиск устройства по HA entity ID."""
        index_manager.add_device(sample_device)

        found = index_manager.find_by_ha_entity_id(sample_device.ha_entity_id)

        assert found is not None
        assert found.id == sample_device.id
        assert found.ha_entity_id == sample_device.ha_entity_id

    def test_index_find_by_ha_entity_id_not_found(self, index_manager):
        """Тест: поиск по несуществующему ha_entity_id."""
        found = index_manager.find_by_ha_entity_id("light.nonexistent")

        assert found is None

    def test_index_find_by_status(self, index_manager):
        """Тест: поиск устройств по статусу."""
        source_id = uuid4()
        devices = [
            Device(
                ha_entity_id=f"device_{i}",
                source_id=source_id,
                name=f"Device {i}",
                device_type="light",
                state={},
                status="available" if i < 3 else "unavailable",
            )
            for i in range(5)
        ]

        for device in devices:
            index_manager.add_device(device)

        available = index_manager.find_by_status("available")
        unavailable = index_manager.find_by_status("unavailable")

        assert len(available) == 3
        assert len(unavailable) == 2

    def test_index_find_by_source_and_type(self, index_manager):
        """Тест: поиск по источнику и типу одновременно."""
        source1 = uuid4()
        source2 = uuid4()

        devices = [
            Device(
                ha_entity_id=f"light_s1_{i}",
                source_id=source1,
                name=f"Light S1 {i}",
                device_type="light",
                state={},
                status="available",
            )
            for i in range(3)
        ]
        devices.extend(
            [
                Device(
                    ha_entity_id=f"switch_s1_{i}",
                    source_id=source1,
                    name=f"Switch S1 {i}",
                    device_type="switch",
                    state={},
                    status="available",
                )
                for i in range(2)
            ]
        )
        devices.extend(
            [
                Device(
                    ha_entity_id=f"light_s2_{i}",
                    source_id=source2,
                    name=f"Light S2 {i}",
                    device_type="light",
                    state={},
                    status="available",
                )
                for i in range(2)
            ]
        )

        for device in devices:
            index_manager.add_device(device)

        found = index_manager.find_by_source_and_type(source1, "light")

        assert len(found) == 3
        assert all(d.source_id == source1 and d.device_type == "light" for d in found)

    def test_index_update_device(self, index_manager, sample_device):
        """Тест: обновление существующего устройства."""
        index_manager.add_device(sample_device)

        # Изменяем устройство
        sample_device.device_type = "switch"
        index_manager.update_device(sample_device)

        # Проверяем что устройство обновлено в индексах
        lights = index_manager.find_by_type("light")
        switches = index_manager.find_by_type("switch")

        assert len(lights) == 0
        assert len(switches) == 1
        assert switches[0].id == sample_device.id

    def test_index_clear(self, index_manager, sample_devices):
        """Тест: очистка всех индексов."""
        for device in sample_devices:
            index_manager.add_device(device)

        assert index_manager.get_device_count() == len(sample_devices)

        index_manager.clear()

        assert index_manager.get_device_count() == 0
        assert index_manager.get_device(sample_devices[0].id) is None

    def test_index_rebuild_from_devices(self, index_manager, sample_devices):
        """Тест: пересоздание индекса из списка устройств."""
        index_manager.rebuild_from_devices(sample_devices)

        assert index_manager.get_device_count() == len(sample_devices)

        # Проверяем что все устройства в индексе
        for device in sample_devices:
            assert index_manager.get_device(device.id) is not None

    def test_index_get_all_devices(self, index_manager, sample_devices):
        """Тест: получение всех устройств из индекса."""
        index_manager.rebuild_from_devices(sample_devices)

        all_devices = index_manager.get_all_devices()

        assert len(all_devices) == len(sample_devices)
        assert {d.id for d in all_devices} == {d.id for d in sample_devices}

    def test_index_stats(self, index_manager, sample_devices):
        """Тест: получение статистики индекса."""
        index_manager.rebuild_from_devices(sample_devices)

        stats = index_manager.get_stats()

        assert stats["total_devices"] == len(sample_devices)
        assert stats["unique_sources"] == 1
        assert stats["unique_types"] == 1  # все light
        assert "device_types" in stats
        assert "statuses" in stats

    def test_index_thread_safety(self, index_manager):
        """Тест: thread-safe операции индекса."""
        source_id = uuid4()

        def worker(thread_id):
            for i in range(50):
                device = Device(
                    ha_entity_id=f"device_t{thread_id}_{i}",
                    source_id=source_id,
                    name=f"Device T{thread_id} {i}",
                    device_type="light",
                    state={},
                    status="available",
                )
                index_manager.add_device(device)
                index_manager.get_device(device.id)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(5)]

        for thread in threads:
            thread.start()

        for thread in threads:
            thread.join()

        # Должны быть все 250 устройств (5 потоков * 50 устройств)
        assert index_manager.get_device_count() == 250

    def test_index_remove_nonexistent(self, index_manager):
        """Тест: попытка удалить несуществующее устройство."""
        result = index_manager.remove_device(uuid4())

        assert result is False
        assert index_manager.index_errors == 0
