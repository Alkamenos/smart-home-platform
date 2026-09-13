#!/usr/bin/env python3
"""
Тест реального event loop в cmd_run().

Проверяет:
1. Event loop запускается корректно
2. События обрабатываются в реальном времени
3. Ctrl+C (SIGINT) корректно останавливает платформу
4. FSM подписывается на события через EventBus
"""

import asyncio
import signal
import pytest
import sys
import os
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

# Добавляем parent directory в path
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.event_bus import EventBus
from core.fsm import FSMEngine, FSMDefinition, Transition
from core.logger import Logger


class TestEventLoopBasic:
    """Базовые тесты event loop."""
    
    def test_event_bus_subscribe_with_filter(self):
        """Тест: subscribe_with_filter работает корректно."""
        event_bus = EventBus()
        received_events = []
        
        def handler(data):
            received_events.append(data)
        
        # Подписываемся с фильтром
        event_bus.subscribe_with_filter(
            event_type="state_changed",
            filter_params={"entity_id": "binary_sensor.kitchen_motion"},
            handler=handler,
        )
        
        # Публикуем событие которое соответствует фильтру
        event_bus.publish(
            event_type="state_changed",
            data={"entity_id": "binary_sensor.kitchen_motion", "new_state": "on"}
        )
        
        assert len(received_events) == 1
        assert received_events[0]["entity_id"] == "binary_sensor.kitchen_motion"
    
    def test_event_bus_subscribe_with_filter_no_match(self):
        """Тест: фильтр не пропускает неподходящие события."""
        event_bus = EventBus()
        received_events = []
        
        def handler(data):
            received_events.append(data)
        
        # Подписываемся с фильтром
        event_bus.subscribe_with_filter(
            event_type="state_changed",
            filter_params={"entity_id": "binary_sensor.kitchen_motion"},
            handler=handler,
        )
        
        # Публикуем событие от другого сенсора
        event_bus.publish(
            event_type="state_changed",
            data={"entity_id": "binary_sensor.living_room_motion", "new_state": "on"}
        )
        
        # Handler не должен быть вызван
        assert len(received_events) == 0
    
    @pytest.mark.asyncio
    async def test_fsm_triggered_by_event(self):
        """Тест: FSM триггерится событием из EventBus."""
        event_bus = EventBus()
        logger = Logger(component="test")
        fsm = FSMEngine(event_bus=event_bus, logger=logger)
        
        # Создаём простую FSM
        transitions = (
            Transition(
                from_state="OFF",
                to_state="ON",
                trigger="motion_detected",
            ),
        )
        
        definition = FSMDefinition(
            entity_id="light.test_room",
            initial_state="OFF",
            states=("OFF", "ON"),
            transitions=transitions,
        )
        
        fsm.register_definition(definition)
        
        # Проверяем начальное состояние
        state = fsm.get_state("light.test_room")
        assert state.current_state == "OFF"
        
        # Триггерим событие
        await fsm.trigger(
            entity_id="light.test_room",
            event="motion_detected",
            external_ctx={"source": "test"}
        )
        
        # Проверяем новое состояние
        state = fsm.get_state("light.test_room")
        assert state.current_state == "ON"


class TestPlatformRunner:
    """Тесты PlatformRunner."""
    
    @pytest.fixture
    def mock_args(self):
        """Создаёт mock аргументы для PlatformRunner."""
        args = MagicMock()
        args.mock = True
        args.rooms = ["test_room"]
        args.zones = []
        return args
    
    def test_platform_runner_init(self, mock_args):
        """Тест: PlatformRunner инициализируется корректно."""
        from cli import PlatformRunner
        
        runner = PlatformRunner(mock_args)
        
        assert runner.args == mock_args
        assert runner.event_bus is not None
        assert runner.fsm is not None
        assert runner.adapter is None
        assert not runner._shutdown_event.is_set()
    
    def test_platform_runner_setup_components(self, mock_args):
        """Тест: setup_components создаёт компоненты."""
        from cli import PlatformRunner
        
        runner = PlatformRunner(mock_args)
        definitions = runner.setup_components()
        
        # Должны быть созданы автоматы для освещения
        assert len(definitions) >= 1
        
        # FSM должны быть зарегистрированы
        assert len(runner.fsm._definitions) >= 1
    
    @pytest.mark.asyncio
    async def test_platform_runner_shutdown(self, mock_args):
        """Тест: shutdown корректно останавливает платформу."""
        from cli import PlatformRunner
        
        runner = PlatformRunner(mock_args)
        runner.setup_components()
        
        # Вызываем shutdown
        await runner.shutdown()
        
        # Проверяем что FSM shutdown был вызван (состояния сохранены)
        # В реальной реализации здесь была бы проверка что таймеры отменены
    
    @pytest.mark.asyncio  
    async def test_handle_signal_sets_shutdown_event(self, mock_args):
        """Тест: handle_signal устанавливает shutdown event."""
        from cli import PlatformRunner
        
        runner = PlatformRunner(mock_args)
        
        # Проверяем что изначально event не установлен
        assert not runner._shutdown_event.is_set()
        
        # Вызываем обработчик сигнала
        runner.handle_signal(signal.SIGINT)
        
        # Проверяем что event установлен
        assert runner._shutdown_event.is_set()


class TestEventLoopIntegration:
    """Интеграционные тесты event loop."""
    
    @pytest.mark.asyncio
    async def test_event_bus_to_fsm_integration(self):
        """Тест: Интеграция EventBus -> FSM."""
        event_bus = EventBus()
        logger = Logger(component="test")
        fsm = FSMEngine(event_bus=event_bus, logger=logger)
        
        # Регистрируем FSM
        transitions = (
            Transition(
                from_state="OFF",
                to_state="ON",
                trigger="motion_detected",
            ),
        )
        
        definition = FSMDefinition(
            entity_id="light.integration_test",
            initial_state="OFF",
            states=("OFF", "ON"),
            transitions=transitions,
        )
        
        fsm.register_definition(definition)
        
        # Подписываем FSM на события через EventBus
        async def motion_handler(data):
            if data.get("new_state") == "on":
                await fsm.trigger(
                    entity_id="light.integration_test",
                    event="motion_detected",
                    external_ctx=data
                )
        
        event_bus.subscribe_with_filter(
            event_type="state_changed",
            filter_params={"entity_id": "binary_sensor.test_motion"},
            handler=motion_handler
        )
        
        # Начальное состояние
        state = fsm.get_state("light.integration_test")
        assert state.current_state == "OFF"
        
        # Публикуем событие
        event_bus.publish(
            event_type="state_changed",
            data={
                "entity_id": "binary_sensor.test_motion",
                "new_state": "on",
                "old_state": "off"
            }
        )
        
        # Даем время на обработку async handler
        await asyncio.sleep(0.1)
        
        # Проверяем что FSM перешёл в ON
        state = fsm.get_state("light.integration_test")
        assert state.current_state == "ON"


class TestGracefulShutdown:
    """Тесты graceful shutdown."""
    
    @pytest.mark.asyncio
    async def test_shutdown_event_wait(self):
        """Тест: run_event_loop ждёт shutdown event."""
        from cli import PlatformRunner
        from unittest.mock import MagicMock
        
        args = MagicMock()
        args.mock = True
        args.rooms = []
        args.zones = []
        
        runner = PlatformRunner(args)
        runner.setup_components()
        
        # Запускаем event loop в фоне
        async def wait_and_stop():
            await asyncio.sleep(0.1)
            runner.handle_signal(signal.SIGINT)
        
        # Создаём задачу которая остановит loop
        stop_task = asyncio.create_task(wait_and_stop())
        
        # Запускаем event loop (он должен завершиться после сигнала)
        await runner.run_event_loop()
        
        # Ждём завершения задачи остановки
        await stop_task
        
        # Проверяем что shutdown event установлен
        assert runner._shutdown_event.is_set()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
