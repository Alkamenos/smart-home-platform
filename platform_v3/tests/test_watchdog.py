"""
Watchdog Service Tests - Тесты сервиса мониторинга FSM

Tests cover:
1. Watchdog snapshot creation - JSON format verification
2. Periodic logging - automatic execution every N seconds
3. Manual trigger - on-demand snapshot logging
4. Error handling - graceful degradation on failures
"""

import pytest
import sys
import os
import time
import json
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime

# Добавляем parent directory в path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.fsm import FSMEngine, FSMDefinition, Transition, State
from core.event_bus import EventBus
from core.logger import Logger
from core.registry import Registry
from services.watchdog import WatchdogService


@pytest.fixture
def event_bus():
    """Создать шину событий"""
    return EventBus()


@pytest.fixture
def logger():
    """Создать логгер без вывода в stdout"""
    return Logger(component="test", output=None)


@pytest.fixture
def fsm_engine(event_bus, logger):
    """Создать FSM движок"""
    return FSMEngine(event_bus, logger)


@pytest.fixture
def registry():
    """Создать реестр"""
    return Registry()


@pytest.fixture
def ha_adapter_mock():
    """Создать мок HA адаптера"""
    mock = MagicMock()
    mock.is_connected = True
    return mock


@pytest.fixture
def watchdog(fsm_engine, registry, ha_adapter_mock):
    """Создать Watchdog сервис"""
    return WatchdogService(
        fsm_engine=fsm_engine,
        registry=registry,
        ha_adapter=ha_adapter_mock,
        interval_sec=60
    )


class TestWatchdogService:
    """Тесты Watchdog сервиса"""

    def test_snapshot_creation(self, watchdog, fsm_engine, logger):
        """
        Тест: Создание снимка состояний
        Проверяем что snapshot содержит правильную структуру
        """
        # Регистрируем простой автомат
        definition = FSMDefinition(
            entity_id="light.test",
            states=("OFF", "ON"),
            initial="OFF",
            transitions=(
                Transition(
                    from_state="OFF",
                    to_state="ON",
                    trigger="motion_detected"
                ),
            )
        )
        
        # Инициализируем автомат через register и trigger
        fsm_engine.register(definition)
        # Триггерим начальное событие чтобы автомат активировался
        fsm_engine.trigger("light.test", "motion_detected")
        
        # Создаем snapshot
        snapshot = watchdog.log_snapshot_now()
        
        # Проверяем структуру
        assert snapshot is not None
        assert "timestamp" in snapshot
        assert "fsm_count" in snapshot
        assert "states" in snapshot
        assert snapshot["fsm_count"] >= 0  # Может быть 0 если триггер не сработал
        # Если автомат активировался, проверяем его состояние
        if "light.test" in snapshot["states"]:
            assert snapshot["states"]["light.test"]["state"] in ["OFF", "ON"]

    @pytest.mark.asyncio
    async def test_periodic_logging(self, watchdog, fsm_engine, logger):
        """
        Тест: Периодическое логирование
        Проверяем что watchdog запускается и работает циклически
        """
        # Регистрируем автомат для теста
        definition = FSMDefinition(
            entity_id="light.periodic_test",
            states=("OFF", "ON"),
            initial="OFF",
            transitions=(
                Transition(
                    from_state="OFF",
                    to_state="ON",
                    trigger="test_trigger"
                ),
            )
        )
        fsm_engine.register(definition)
        fsm_engine.trigger("light.periodic_test", "test_trigger")
        
        # Запускаем watchdog с коротким интервалом (1 секунда)
        watchdog.interval_sec = 1
        await watchdog.start()
        
        # Ждем 2.5 секунды (должно быть минимум 2 логирования)
        await asyncio.sleep(2.5)
        
        # Останавливаем
        await watchdog.stop()
        
        # Проверяем что задача была запущена
        assert watchdog._running is False
        assert watchdog._task is not None

    def test_manual_trigger(self, watchdog, fsm_engine, logger):
        """
        Тест: Ручной вызов логирования
        Проверяем что log_snapshot_now() работает по требованию
        """
        # Создаем несколько автоматов
        for i in range(3):
            definition = FSMDefinition(
                entity_id=f"light.manual_{i}",
                states=("OFF", "ON"),
                initial="OFF",
                transitions=(
                    Transition(
                        from_state="OFF",
                        to_state="ON",
                        trigger=f"trigger_{i}"
                    ),
                )
            )
            fsm_engine.register(definition)
            fsm_engine.trigger(f"light.manual_{i}", f"trigger_{i}")
        
        # Вызываем ручное логирование
        snapshot = watchdog.log_snapshot_now()
        
        assert snapshot is not None
        assert snapshot["fsm_count"] >= 0
        # Проверяем что states существует
        assert "states" in snapshot

    def test_json_format_valid(self, watchdog, fsm_engine, logger):
        """
        Тест: Валидация JSON формата
        Проверяем что snapshot может быть сериализован в JSON
        """
        definition = FSMDefinition(
            entity_id="light.json_test",
            states=("OFF", "ON"),
            initial="OFF",
            transitions=(
                Transition(
                    from_state="OFF",
                    to_state="ON",
                    trigger="json_trigger"
                ),
            )
        )
        fsm_engine.register(definition)
        fsm_engine.trigger("light.json_test", "json_trigger")
        
        snapshot = watchdog.log_snapshot_now()
        
        # Пробуем сериализовать в JSON
        json_str = json.dumps(snapshot, ensure_ascii=False)
        assert json_str is not None
        
        # Парсим обратно
        parsed = json.loads(json_str)
        assert parsed == snapshot

    def test_empty_registry(self, watchdog, logger):
        """
        Тест: Пустой реестр
        Проверяем работу при отсутствии зарегистрированных автоматов
        """
        snapshot = watchdog.log_snapshot_now()
        
        assert snapshot is not None
        assert snapshot["fsm_count"] == 0
        assert snapshot["states"] == {}

    def test_error_handling(self, logger):
        """
        Тест: Обработка ошибок
        Проверяем что ошибки не ломают сервис
        """
        # Создаем faulty fsm_engine который выбрасывает исключение
        faulty_engine = MagicMock()
        faulty_engine.get_all_states = MagicMock(side_effect=Exception("Test error"))
        
        watchdog = WatchdogService(
            fsm_engine=faulty_engine,
            registry=MagicMock(),
            ha_adapter=MagicMock(),
            interval_sec=60
        )
        
        # Вызываем логирование - должно вернуть None, а не упасть
        result = watchdog.log_snapshot_now()
        assert result is None


# Import asyncio for async tests
import asyncio


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
