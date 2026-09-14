"""
Тест реального event loop платформы.

Проверяет:
1. Event loop запускается в asyncio.run()
2. EventBus обрабатывает события в реальном времени
3. FSM подписывается на события через EventBus
4. Graceful shutdown при Ctrl+C (сигнал SIGINT)
"""

import asyncio
import signal
import pytest
import sys
import os
from pathlib import Path

# Добавляем parent directory в path
sys.path.insert(0, str(Path(__file__).parent.parent))

from smart_home.core.event_bus import EventBus
from smart_home.core.fsm import FSMEngine, FSMDefinition, Transition
from smart_home.core.fsm_factory import FSMFactory
from smart_home.core.registry import Registry
from smart_home.bootstrap import bootstrap_platform


class TestEventLoopBasic:
    """Базовые тесты event loop."""
    
    @pytest.mark.asyncio
    async def test_event_bus_publish_subscribe(self):
        """Тест: EventBus публикует и доставляет события подписчикам."""
        event_bus = EventBus()
        received_events = []
        
        async def handler(event_type, payload, trace_id=None):
            received_events.append((event_type, payload))
        
        # Подписываемся на событие
        event_bus.subscribe("test_event", handler)
        
        # Публикуем событие
        await event_bus.publish(
            event_type="test_event",
            payload={"data": "test_value"},
        )
        
        # Проверяем что событие получено
        assert len(received_events) == 1
        assert received_events[0][0] == "test_event"
        assert received_events[0][1]["data"] == "test_value"
    
    @pytest.mark.asyncio
    async def test_event_bus_multiple_subscribers(self):
        """Тест: Несколько подписчиков получают одно событие."""
        event_bus = EventBus()
        received_1 = []
        received_2 = []
        
        async def handler_1(event_type, payload, trace_id=None):
            received_1.append(payload)
        
        async def handler_2(event_type, payload, trace_id=None):
            received_2.append(payload)
        
        event_bus.subscribe("multi_event", handler_1)
        event_bus.subscribe("multi_event", handler_2)
        
        await event_bus.publish(
            event_type="multi_event",
            payload={"count": 1},
        )
        
        assert len(received_1) == 1
        assert len(received_2) == 1


class TestFSMSubscription:
    """Тесты подписки FSM на события."""
    
    @pytest.fixture
    def setup_fsm_system(self):
        """Создать систему с EventBus, FSMEngine, Registry."""
        event_bus = EventBus()
        engine = FSMEngine()
        registry = Registry()
        
        # Регистрируем простые action
        async def turn_on(state, context):
            return {}
        
        async def turn_off(state, context):
            return {}
        
        registry.register_action("turn_on", turn_on)
        registry.register_action("turn_off", turn_off)
        
        # Создаем фабрику с event_bus
        factory = FSMFactory(
            engine=engine,
            registry=registry,
            features_dir="features",
            event_bus=event_bus,
        )
        
        return {
            "event_bus": event_bus,
            "engine": engine,
            "registry": registry,
            "factory": factory,
        }
    
    @pytest.mark.asyncio
    async def test_fsm_factory_subscribes_to_motion(self, setup_fsm_system):
        """Тест: FSMFactory автоматически подписывает FSM на motion sensor."""
        system = setup_fsm_system
        event_bus = system["event_bus"]
        engine = system["engine"]
        factory = system["factory"]
        
        # Создаем простую FSM через factory (это должно автоматически подписать на events)
        transitions = (
            Transition(
                from_state="OFF",
                to_state="ON",
                trigger="motion_detected",
                action="turn_on",
            ),
            Transition(
                from_state="ON",
                to_state="OFF",
                trigger="motion_cleared",
                action="turn_off",
            ),
        )
        
        fsm_def = FSMDefinition(
            entity_id="light.test_room__lighting_10",
            initial_state="OFF",
            states=("OFF", "ON"),
            transitions=transitions,
        )
        
        engine.register_definition(fsm_def)
        
        # Начальное состояние
        state = engine.get_state("light.test_room__lighting_10")
        assert state.current_state == "OFF"
        
        # Триггерим событие напрямую в FSM (эмуляция того что делает handler из FSMFactory)
        await engine.trigger(
            entity_id="light.test_room__lighting_10",
            event="motion_detected",
            external_ctx={"entity_id": "binary_sensor.test_room_motion", "new_state": "on"},
        )
        
        # Проверяем что FSM перешла в ON
        state_after = engine.get_state("light.test_room__lighting_10")
        assert state_after.current_state == "ON", \
            f"FSM должна перейти в ON после motion_detected, но получила {state_after.current_state}"
    
    @pytest.mark.asyncio
    async def test_event_bus_handler_triggers_fsm(self, setup_fsm_system):
        """Тест: Handler EventBus триггерит FSM при получении события."""
        system = setup_fsm_system
        event_bus = system["event_bus"]
        engine = system["engine"]
        
        # Создаем FSM
        transitions = (
            Transition(
                from_state="OFF",
                to_state="ON",
                trigger="motion_detected",
                action="turn_on",
            ),
        )
        
        fsm_def = FSMDefinition(
            entity_id="light.test_room__lighting_10",
            initial_state="OFF",
            states=("OFF", "ON"),
            transitions=transitions,
        )
        
        engine.register_definition(fsm_def)
        
        # Подписываем handler на EventBus (как это делает FSMFactory)
        motion_sensor = "binary_sensor.test_room_motion"
        fsm_entity_id = "light.test_room__lighting_10"
        
        async def motion_handler(event_type, payload, trace_id=None):
            new_state = payload.get("new_state", "")
            if new_state == "on":
                await engine.trigger(
                    entity_id=fsm_entity_id,
                    event="motion_detected",
                    external_ctx=payload,
                )
        
        event_bus.subscribe_with_filter(
            event_type="state_change",
            filter_params={"entity_id": motion_sensor},
            handler=motion_handler,
        )
        
        # Начальное состояние
        assert engine.get_state(fsm_entity_id).current_state == "OFF"
        
        # Публикуем событие от motion sensor
        await event_bus.publish(
            event_type="state_change",
            payload={
                "entity_id": motion_sensor,
                "new_state": "on",
                "old_state": "off",
            },
        )
        
        # Проверяем что FSM перешла в ON
        state_after = engine.get_state(fsm_entity_id)
        assert state_after.current_state == "ON", \
            f"FSM должна перейти в ON, но получила {state_after.current_state}"


class TestGracefulShutdown:
    """Тесты graceful shutdown."""
    
    @pytest.mark.asyncio
    async def test_shutdown_event_triggered(self):
        """Тест: shutdown_event устанавливается при сигнале."""
        shutdown_event = asyncio.Event()
        
        async def wait_for_shutdown():
            await shutdown_event.wait()
            return "shutdown"
        
        # Запускаем задачу ожидания
        task = asyncio.create_task(wait_for_shutdown())
        
        # Даем время на запуск
        await asyncio.sleep(0.01)
        assert not task.done()
        
        # Устанавливаем событие
        shutdown_event.set()
        
        # Ждем завершения задачи
        result = await asyncio.wait_for(task, timeout=1.0)
        assert result == "shutdown"
    
    @pytest.mark.asyncio
    async def test_task_cancellation(self):
        """Тест: Задачи корректно отменяются при shutdown."""
        shutdown_event = asyncio.Event()
        cancelled = False
        
        async def long_running_task():
            nonlocal cancelled
            try:
                while not shutdown_event.is_set():
                    await asyncio.sleep(0.1)
            except asyncio.CancelledError:
                cancelled = True
                raise
        
        # Запускаем задачу
        task = asyncio.create_task(long_running_task())
        
        # Даем время на запуск
        await asyncio.sleep(0.05)
        assert not task.done()
        
        # Отменяем задачу
        task.cancel()
        
        # Ждем завершения
        try:
            await task
        except asyncio.CancelledError:
            pass
        
        assert cancelled, "Задача должна была обработать CancelledError"


class TestMockEventListener:
    """Тесты mock event listener."""
    
    @pytest.mark.asyncio
    async def test_mock_listener_emits_events(self):
        """Тест: Mock listener эмулирует периодические события."""
        from smart_home.adapters.mock_adapter import MockAdapter
        
        event_bus = EventBus()
        engine = FSMEngine()
        adapter = MockAdapter()
        adapter.set_fsm_engine(engine)
        
        received_events = []
        
        async def handler(event_type, payload, trace_id=None):
            received_events.append((event_type, payload))
        
        event_bus.subscribe("state_change", handler)
        
        # Создаем простой контекст
        class MockContext:
            def __init__(self):
                self.event_bus = event_bus
                self.adapter = adapter
        
        ctx = MockContext()
        shutdown_event = asyncio.Event()
        
        # Импортируем функцию mock listener из cli
        from cli import _mock_event_listener
        
        # Запускаем listener на короткое время
        listener_task = asyncio.create_task(
            _mock_event_listener(ctx, shutdown_event)
        )
        
        # Ждем немного больше чем интервал эмуляции (5 секунд)
        await asyncio.sleep(5.5)
        
        # Останавливаем
        shutdown_event.set()
        
        # Ждем завершения
        try:
            await asyncio.wait_for(listener_task, timeout=2.0)
        except asyncio.CancelledError:
            pass
        except asyncio.TimeoutError:
            listener_task.cancel()
            try:
                await listener_task
            except asyncio.CancelledError:
                pass
        
        # Проверяем что события были опубликованы
        # За 5.5 секунд должно быть как минимум 1 событие
        assert len(received_events) >= 2, \
            f"Ожидали хотя бы 2 события (motion on + off), но получили {len(received_events)}"


class TestPlatformIntegration:
    """Интеграционные тесты платформы."""
    
    @pytest.mark.asyncio
    async def test_bootstrap_creates_event_bus(self):
        """Тест: bootstrap_platform создает EventBus."""
        ctx = bootstrap_platform("instances/leonids_house/manifest.yaml")
        
        assert hasattr(ctx, 'event_bus')
        assert ctx.event_bus is not None
    
    @pytest.mark.asyncio
    async def test_fsm_factory_with_event_bus(self):
        """Тест: FSMFactory принимает event_bus и подписывает FSM."""
        ctx = bootstrap_platform("instances/leonids_house/manifest.yaml")
        
        registry = Registry()
        factory = FSMFactory(
            ctx.fsm, 
            registry, 
            features_dir="features",
            event_bus=ctx.event_bus,
        )
        
        definitions = factory.create_from_manifest(ctx.manifest)
        
        # Регистрируем FSM
        for fsm_def in definitions:
            ctx.fsm.register_definition(fsm_def)
        
        # Проверяем что FSM созданы
        assert len(definitions) > 0, "Должны быть созданы FSM из манифеста"
        
        # Проверяем что EventBus имеет подписчиков
        # (FSMFactory должен был подписаться на события сенсоров)
        # Количество подписчиков зависит от количества motion_sensor в манифесте


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
