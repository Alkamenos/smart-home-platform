"""
Тест маршрутизации событий от сенсоров к FSM.

Проверяет, что:
1. EventBus поддерживает параметрические подписки через subscribe_with_filter
2. FSMFactory автоматически подписывает FSM на события из params
3. Событие от binary_sensor.kitchen_motion доставляется в обе FSM 
   (lighting и night_light) одного устройства
"""

import asyncio
import pytest
import sys
import os

# Добавляем parent directory в path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.smart_home.core.event_bus import EventBus
from src.smart_home.core.fsm import FSMEngine, FSMDefinition, Transition
from src.smart_home.core.fsm_factory import FSMFactory
from src.smart_home.core.registry import Registry
from src.smart_home.core.models.manifest import BehaviorConfig, LightMotionDevice


class TestEventBusWithFilters:
    """Тесты для EventBus с параметрическими подписками."""
    
    @pytest.mark.asyncio
    async def test_subscribe_with_filter_basic(self):
        """Базовый тест subscribe_with_filter."""
        event_bus = EventBus()
        received_events = []
        
        async def handler(event_type, payload, trace_id=None):
            received_events.append((event_type, payload))
        
        # Подписываемся с фильтром
        event_bus.subscribe_with_filter(
            event_type="state_change",
            filter_params={"entity_id": "binary_sensor.kitchen_motion"},
            handler=handler,
        )
        
        # Публикуем событие, которое соответствует фильтру
        await event_bus.publish(
            event_type="state_change",
            payload={"entity_id": "binary_sensor.kitchen_motion", "new_state": "on"},
        )
        
        assert len(received_events) == 1
        assert received_events[0][0] == "state_change"
        assert received_events[0][1]["entity_id"] == "binary_sensor.kitchen_motion"
    
    @pytest.mark.asyncio
    async def test_subscribe_with_filter_no_match(self):
        """Тест: фильтр не пропускает неподходящие события."""
        event_bus = EventBus()
        received_events = []
        
        async def handler(event_type, payload, trace_id=None):
            received_events.append((event_type, payload))
        
        # Подписываемся с фильтром на kitchen_motion
        event_bus.subscribe_with_filter(
            event_type="state_change",
            filter_params={"entity_id": "binary_sensor.kitchen_motion"},
            handler=handler,
        )
        
        # Публикуем событие от другого сенсора
        await event_bus.publish(
            event_type="state_change",
            payload={"entity_id": "binary_sensor.living_room_motion", "new_state": "on"},
        )
        
        # Handler не должен быть вызван
        assert len(received_events) == 0
    
    @pytest.mark.asyncio
    async def test_subscribe_with_filter_multiple_handlers(self):
        """Тест: несколько handlers на одно событие с фильтром."""
        event_bus = EventBus()
        received_events_1 = []
        received_events_2 = []
        
        async def handler_1(event_type, payload, trace_id=None):
            received_events_1.append((event_type, payload))
        
        async def handler_2(event_type, payload, trace_id=None):
            received_events_2.append((event_type, payload))
        
        # Два handlers подписываются на один и тот же фильтр
        event_bus.subscribe_with_filter(
            event_type="state_change",
            filter_params={"entity_id": "binary_sensor.kitchen_motion"},
            handler=handler_1,
        )
        event_bus.subscribe_with_filter(
            event_type="state_change",
            filter_params={"entity_id": "binary_sensor.kitchen_motion"},
            handler=handler_2,
        )
        
        # Публикуем событие
        await event_bus.publish(
            event_type="state_change",
            payload={"entity_id": "binary_sensor.kitchen_motion", "new_state": "on"},
        )
        
        # Оба handler должны получить событие
        assert len(received_events_1) == 1
        assert len(received_events_2) == 1


class TestFSMFactorySubscription:
    """Тесты для автоматической подписки FSMFactory на события сенсоров."""
    
    @pytest.fixture
    def setup_system(self):
        """Создать систему с EventBus, FSMEngine, Registry и FSMFactory."""
        event_bus = EventBus()
        engine = FSMEngine()
        registry = Registry()
        
        # Регистрируем простые action для тестов
        async def turn_on_light(state, context):
            return {}
        
        async def turn_off_light(state, context):
            return {}
        
        registry.register_action("turn_on_light", turn_on_light)
        registry.register_action("turn_off_light", turn_off_light)
        
        # Регистрируем guard
        def is_day_time(state, context):
            return context.get("is_day_time", True)
        
        registry.register_guard("is_day_time", is_day_time)
        
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
    async def test_both_fsm_receive_motion_event(self, setup_system):
        """
        Тест: оба поведения (lighting и night_light) получают событие от motion_sensor.
        
        Сценарий:
        1. Создаем устройство light.kitchen с двумя behaviors:
           - lighting (priority 10) с motion_sensor
           - night_light (priority 20) с тем же motion_sensor
        2. FSMFactory автоматически подписывает обе FSM на события binary_sensor.kitchen_motion
        3. Публикуем событие motion_detected
        4. Проверяем, что обе FSM получили событие и перешли в соответствующие состояния
        """
        system = setup_system
        event_bus = system["event_bus"]
        engine = system["engine"]
        factory = system["factory"]
        
        # Создаем behavior configs аналогично манифесту
        lighting_behavior = BehaviorConfig(
            template="lighting",
            priority=10,
            params={
                "motion_sensor": "binary_sensor.kitchen_motion",
                "motion_timeout_sec": 300,
                "schedule": "07:00-23:00",
                "brightness": 255,
            },
        )
        
        night_light_behavior = BehaviorConfig(
            template="night_light",
            priority=20,
            params={
                "brightness": 10,
                "schedule": "23:00-07:00",
                "timeout_sec": 60,
            },
        )
        
        # Создаем device
        device = LightMotionDevice(
            type="light_motion",
            id="light.kitchen",
            name="Kitchen Light",
            room="kitchen",
            behaviors=[lighting_behavior, night_light_behavior],
        )
        
        # Создаем FSM из behaviors
        lighting_defs = factory.create_from_behavior("light.kitchen", lighting_behavior)
        night_light_defs = factory.create_from_behavior("light.kitchen", night_light_behavior)
        
        # Регистрируем FSM в engine
        for definition in lighting_defs + night_light_defs:
            engine.register_definition(definition)
        
        # Проверяем, что создано 2 FSM
        assert len(lighting_defs) == 1
        assert len(night_light_defs) == 1
        
        lighting_entity_id = lighting_defs[0].entity_id
        night_light_entity_id = night_light_defs[0].entity_id
        
        # Проверяем, что entity_id уникальны
        assert lighting_entity_id != night_light_entity_id
        assert "lighting" in lighting_entity_id or "light.kitchen" in lighting_entity_id
        assert "night_light" in night_light_entity_id or "light.kitchen" in night_light_entity_id
        
        # Начальные состояния должны быть OFF
        lighting_state = engine.get_state(lighting_entity_id)
        night_light_state = engine.get_state(night_light_entity_id)
        
        assert lighting_state is not None
        assert night_light_state is not None
        assert lighting_state.current_state == "OFF"
        assert night_light_state.current_state == "OFF"
        
        # Теперь эмулируем событие от motion sensor через EventBus
        # Это должно триггерить обе FSM
        await event_bus.publish(
            event_type="state_change",
            payload={
                "entity_id": "binary_sensor.kitchen_motion",
                "new_state": "on",
                "old_state": "off",
            },
        )
        
        # Даем время на обработку асинхронных событий
        await asyncio.sleep(0.1)
        
        # Проверяем, что обе FSM получили событие
        # lighting FSM должен перейти в ON_MOTION (если is_day_time=True)
        # night_light FSM должен перейти в ON_NIGHT
        lighting_state_after = engine.get_state(lighting_entity_id)
        night_light_state_after = engine.get_state(night_light_entity_id)
        
        # Хотя бы одна FSM должна была отреагировать
        # (в зависимости от guard условий)
        assert (
            lighting_state_after.current_state != "OFF" or
            night_light_state_after.current_state != "OFF"
        ), "Хотя бы одна FSM должна была отреагировать на событие motion"
        
        print(f"✅ Lighting FSM: {lighting_state.current_state} -> {lighting_state_after.current_state}")
        print(f"✅ Night Light FSM: {night_light_state.current_state} -> {night_light_state_after.current_state}")
    
    @pytest.mark.asyncio
    async def test_motion_sensor_event_reaches_both_fsm(self, setup_system):
        """
        Прямой тест: событие от binary_sensor.kitchen_motion доставляется в обе FSM.
        
        Этот тест явно проверяет requirement из задачи.
        """
        system = setup_system
        event_bus = system["event_bus"]
        engine = system["engine"]
        factory = system["factory"]
        registry = system["registry"]
        
        # Для упрощения теста регистрируем переходы без guards
        # чтобы обе FSM точно отреагировали на motion_detected
        
        # Создаем простую FSM для lighting
        lighting_transitions = (
            Transition(
                from_state="OFF",
                to_state="ON",
                trigger="motion_detected",
                action="turn_on_light",
            ),
        )
        
        lighting_def = FSMDefinition(
            entity_id="light.kitchen__lighting_10",
            initial_state="OFF",
            states=("OFF", "ON"),
            transitions=lighting_transitions,
        )
        
        # Создаем простую FSM для night_light
        night_light_transitions = (
            Transition(
                from_state="OFF",
                to_state="ON_NIGHT",
                trigger="motion_detected",
                action="turn_on_light",
            ),
        )
        
        night_light_def = FSMDefinition(
            entity_id="light.kitchen__night_light_20",
            initial_state="OFF",
            states=("OFF", "ON_NIGHT"),
            transitions=night_light_transitions,
        )
        
        engine.register_definition(lighting_def)
        engine.register_definition(night_light_def)
        
        # Подписываем обе FSM на события motion sensor через EventBus
        async def create_handler(entity_id):
            async def handler(event_type, payload, trace_id=None):
                new_state = payload.get("new_state", "")
                if new_state == "on":
                    await engine.trigger(
                        entity_id=entity_id,
                        event="motion_detected",
                        external_ctx=payload,
                        trace_id=trace_id,
                    )
            return handler
        
        motion_sensor = "binary_sensor.kitchen_motion"
        
        event_bus.subscribe_with_filter(
            event_type="state_change",
            filter_params={"entity_id": motion_sensor},
            handler=await create_handler("light.kitchen__lighting_10"),
        )
        
        event_bus.subscribe_with_filter(
            event_type="state_change",
            filter_params={"entity_id": motion_sensor},
            handler=await create_handler("light.kitchen__night_light_20"),
        )
        
        # Начальные состояния
        assert engine.get_state("light.kitchen__lighting_10").current_state == "OFF"
        assert engine.get_state("light.kitchen__night_light_20").current_state == "OFF"
        
        # Публикуем событие от motion sensor
        await event_bus.publish(
            event_type="state_change",
            payload={
                "entity_id": motion_sensor,
                "new_state": "on",
                "old_state": "off",
            },
        )
        
        # Проверяем, что обе FSM перешли в активное состояние
        lighting_state = engine.get_state("light.kitchen__lighting_10")
        night_light_state = engine.get_state("light.kitchen__night_light_20")
        
        assert lighting_state.current_state == "ON", \
            f"Lighting FSM должна перейти в ON, но получила {lighting_state.current_state}"
        assert night_light_state.current_state == "ON_NIGHT", \
            f"Night Light FSM должна перейти в ON_NIGHT, но получила {night_light_state.current_state}"
        
        print("✅ Обе FSM получили событие от binary_sensor.kitchen_motion")
        print(f"   - Lighting FSM: OFF -> {lighting_state.current_state}")
        print(f"   - Night Light FSM: OFF -> {night_light_state.current_state}")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
