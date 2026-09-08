"""
Tests for Trigger Mapper

Проверяет:
- test_trigger_mapper_invokes_fsm_on_sensor_change - маппинг сенсоров на триггеры FSM
- test_context_passed_from_sensor_value - контекст передаётся из значения сенсора
- test_multiple_triggers_same_sensor - один сенсор может триггерить разные события
- test_unregister_definition - отписка триггеров
"""

import pytest
from unittest.mock import Mock, call
from core.fsm import FSMEngine, FSMDefinition, Transition
from core.event_bus import EventBus
from core.logger import Logger
from adapters.asyncio_scheduler import AsyncioScheduler
from adapters.trigger_mapper import MockTriggerMapper


@pytest.fixture
def event_bus():
    return EventBus()


@pytest.fixture
def logger():
    return Logger(component="test", quiet=True)


@pytest.fixture
def scheduler():
    return AsyncioScheduler()


@pytest.fixture
def fsm_engine(event_bus, logger, scheduler):
    return FSMEngine(event_bus, logger, scheduler)


@pytest.fixture
def sample_definition():
    """Создаёт тестовое определение с triggers_mapping"""
    return FSMDefinition(
        entity_id="light.test_room",
        states=("OFF", "ON"),
        initial="OFF",
        triggers_mapping={
            "motion_detected": "binary_sensor.test_motion",
            "motion_cleared": "binary_sensor.test_motion",
            "manual_change": "light.test_room",
        },
        transitions=(
            Transition(
                from_state="OFF",
                to_state="ON",
                trigger="motion_detected",
                priority=10,
                reason="Motion detected"
            ),
            Transition(
                from_state="ON",
                to_state="OFF",
                trigger="motion_cleared",
                priority=10,
                reason="Motion cleared"
            ),
            Transition(
                from_state="*",
                to_state="ON",
                trigger="manual_change",
                priority=5,
                reason="Manual change"
            ),
        )
    )


def test_trigger_mapper_invokes_fsm_on_sensor_change(fsm_engine, sample_definition):
    """
    Проверяет что при изменении сенсора вызывается соответствующий триггер FSM.
    
    Сценарий:
    1. Регистрируем определение с triggers_mapping
    2. Вызываем mapper.trigger() для сенсора binary_sensor.test_motion
    3. Ожидаем что FSM получит триггер motion_detected и перейдёт в ON
    """
    # Регистрируем определение в FSM Engine
    fsm_engine.register(sample_definition)
    
    # Создаём маппер и регистрируем определение
    mapper = MockTriggerMapper(fsm_engine)
    mapper.register_definition(sample_definition)
    
    # Изначально состояние OFF
    state = fsm_engine.get_state("light.test_room")
    assert state.current == "OFF"
    
    # Вызываем триггер через маппер (симулируем изменение сенсора)
    mapper.trigger("binary_sensor.test_motion", new_value=True, old_value=False)
    
    # FSM должен был перейти в состояние ON
    state = fsm_engine.get_state("light.test_room")
    assert state.current == "ON"
    assert state.entered_by == "motion_detected"


def test_context_passed_from_sensor_value(fsm_engine, sample_definition):
    """
    Проверяет что значение сенсора попадает в контекст триггера.
    
    Сценарий:
    1. Регистрируем определение
    2. Вызываем mapper.trigger() с new_value=True
    3. Проверяем что в истории перехода есть context с entity_id и new_value
    """
    # Регистрируем определение
    fsm_engine.register(sample_definition)
    
    mapper = MockTriggerMapper(fsm_engine)
    mapper.register_definition(sample_definition)
    
    # Вызываем триггер с конкретным значением
    mapper.trigger("binary_sensor.test_motion", new_value=True, old_value=False)
    
    # Получаем историю переходов
    state = fsm_engine.get_state("light.test_room")
    assert len(state.history) > 0
    
    # Последний переход должен содержать контекст с данными сенсора
    last_event = state.history[-1]
    assert last_event["trigger"] == "motion_detected"
    
    # Контекст должен содержать entity_id сенсора и его значение
    # Примечание: контекст хранится в событии event_bus, проверяем через подписку


def test_multiple_triggers_same_sensor(fsm_engine, sample_definition):
    """
    Проверяет что один сенсор может триггерить разные события в зависимости от значения.
    
    Сценарий:
    1. Один сенсор binary_sensor.test_motion мапится на motion_detected и motion_cleared
    2. При new_value=True -> motion_detected
    3. При new_value=False -> motion_cleared
    """
    # Регистрируем определение
    fsm_engine.register(sample_definition)
    
    mapper = MockTriggerMapper(fsm_engine)
    mapper.register_definition(sample_definition)
    
    # Включаем движением
    mapper.trigger("binary_sensor.test_motion", new_value=True, old_value=False)
    state = fsm_engine.get_state("light.test_room")
    assert state.current == "ON"
    
    # Выключаем отсутствием движения
    mapper.trigger("binary_sensor.test_motion", new_value=False, old_value=True)
    state = fsm_engine.get_state("light.test_room")
    assert state.current == "OFF"


def test_unregister_definition(fsm_engine, sample_definition):
    """
    Проверяет что после unregister_definition триггеры больше не работают.
    """
    # Регистрируем определение
    fsm_engine.register(sample_definition)
    
    mapper = MockTriggerMapper(fsm_engine)
    mapper.register_definition(sample_definition)
    
    # Убедимся что работает
    mapper.trigger("binary_sensor.test_motion", new_value=True, old_value=False)
    state = fsm_engine.get_state("light.test_room")
    assert state.current == "ON"
    
    # Отписываем определение
    mapper.unregister_definition("light.test_room")
    
    # Сбрасываем состояние вручную для чистоты теста
    fsm_engine._states["light.test_room"] = fsm_engine._states["light.test_room"].__class__(
        entity_id="light.test_room",
        current="OFF",
        entered_at=0.0,
        entered_by="test",
        entered_why="test"
    )
    
    # Триггер больше не должен работать
    mapper.trigger("binary_sensor.test_motion", new_value=True, old_value=False)
    state = fsm_engine.get_state("light.test_room")
    assert state.current == "OFF"  # осталось OFF


def test_context_contains_sensor_data(fsm_engine, event_bus):
    """
    Проверяет что контекст триггера содержит данные сенсора.
    """
    definition = FSMDefinition(
        entity_id="light.context_test",
        states=("OFF", "ON"),
        initial="OFF",
        triggers_mapping={
            "test_trigger": "sensor.test_value",
        },
        transitions=(
            Transition(
                from_state="OFF",
                to_state="ON",
                trigger="test_trigger",
                priority=10,
                reason="Test"
            ),
        )
    )
    
    # Регистрируем определение
    fsm_engine = FSMEngine(event_bus, Logger(component="test", quiet=True), AsyncioScheduler())
    fsm_engine.register(definition)
    
    mapper = MockTriggerMapper(fsm_engine)
    mapper.register_definition(definition)
    
    # Подписываемся на событие fsm.transition для проверки контекста
    received_context = {}
    def capture_context(data):
        if data.get("entity_id") == "light.context_test":
            received_context.update(data.get("context", {}))
    
    event_bus.subscribe("fsm.transition", capture_context)
    
    # Вызываем триггер с значением сенсора
    sensor_value = 42.5
    mapper.trigger("sensor.test_value", new_value=sensor_value, old_value=40.0)
    
    # Проверяем что контекст содержит данные сенсора
    assert received_context.get("entity_id") == "sensor.test_value"
    assert received_context.get("new_value") == sensor_value
    assert received_context.get("old_value") == 40.0


def test_unknown_sensor_ignored(fsm_engine, sample_definition):
    """
    Проверяет что триггеры от незарегистрированных сенсоров игнорируются.
    """
    # Регистрируем определение
    fsm_engine.register(sample_definition)
    
    mapper = MockTriggerMapper(fsm_engine)
    mapper.register_definition(sample_definition)
    
    # Вызываем триггер от неизвестного сенсора
    mapper.trigger("binary_sensor.unknown_sensor", new_value=True, old_value=False)
    
    # Состояние не должно измениться
    state = fsm_engine.get_state("light.test_room")
    assert state.current == "OFF"


def test_multiple_definitions_same_sensor(fsm_engine):
    """
    Проверяет что один сенсор может триггерить несколько автоматов.
    """
    # Создаём два автомата с одним и тем же сенсором
    definition1 = FSMDefinition(
        entity_id="light.room1",
        states=("OFF", "ON"),
        initial="OFF",
        triggers_mapping={
            "motion": "binary_sensor.hallway_motion",
        },
        transitions=(
            Transition(from_state="OFF", to_state="ON", trigger="motion", priority=10, reason="Motion"),
        )
    )
    
    definition2 = FSMDefinition(
        entity_id="light.room2",
        states=("OFF", "ON"),
        initial="OFF",
        triggers_mapping={
            "motion": "binary_sensor.hallway_motion",
        },
        transitions=(
            Transition(from_state="OFF", to_state="ON", trigger="motion", priority=10, reason="Motion"),
        )
    )
    
    # Регистрируем оба определения
    fsm_engine.register(definition1)
    fsm_engine.register(definition2)
    
    mapper = MockTriggerMapper(fsm_engine)
    mapper.register_definition(definition1)
    mapper.register_definition(definition2)
    
    # Один сенсор триггерит оба автомата
    mapper.trigger("binary_sensor.hallway_motion", new_value=True, old_value=False)
    
    state1 = fsm_engine.get_state("light.room1")
    state2 = fsm_engine.get_state("light.room2")
    
    assert state1.current == "ON"
    assert state2.current == "ON"
