"""
Unit-тесты для FSM Engine

Проверяют:
- Регистрацию автоматов
- Простые переходы
- Guard условия
- Приоритеты переходов
- Иммутабельность состояний
"""

import pytest
import sys
import os

# Добавляем parent directory в path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.fsm import FSMEngine, FSMDefinition, Transition, State
from core.event_bus import EventBus
from core.logger import Logger


@pytest.fixture
def event_bus():
    """Создать шину событий"""
    return EventBus()


@pytest.fixture
def logger():
    """Создать логгер без вывода в stdout"""
    return Logger(component="test", output=None)


@pytest.fixture
def fsm(event_bus, logger):
    """Создать FSM движок"""
    return FSMEngine(event_bus, logger)


class TestFSMRegistration:
    """Тесты регистрации автоматов"""
    
    def test_register_simple_fsm(self, fsm):
        """Тест простой регистрации"""
        definition = FSMDefinition(
            entity_id="test.entity",
            states=("OFF", "ON"),
            initial="OFF",
            transitions=(
                Transition(from_state="OFF", to_state="ON", trigger="turn_on"),
            )
        )
        
        fsm.register(definition)
        state = fsm.get_state("test.entity")
        
        assert state is not None
        assert state.current == "OFF"
        assert state.entered_by == "init"
    
    def test_register_multiple_fsms(self, fsm):
        """Тест регистрации нескольких автоматов"""
        for i in range(3):
            definition = FSMDefinition(
                entity_id=f"test.entity_{i}",
                states=("OFF", "ON"),
                initial="OFF",
                transitions=(
                    Transition(from_state="OFF", to_state="ON", trigger="turn_on"),
                )
            )
            fsm.register(definition)
        
        assert len(fsm.get_all_states()) == 3


class TestFSMTransitions:
    """Тесты переходов"""
    
    def test_simple_transition(self, fsm):
        """Тест простого перехода"""
        definition = FSMDefinition(
            entity_id="test.entity",
            states=("OFF", "ON"),
            initial="OFF",
            transitions=(
                Transition(from_state="OFF", to_state="ON", trigger="turn_on"),
            )
        )
        
        fsm.register(definition)
        result = fsm.trigger("test.entity", "turn_on", {})
        
        assert result is True
        assert fsm.get_state("test.entity").current == "ON"
    
    def test_transition_from_any_state(self, fsm):
        """Тест перехода из любого состояния"""
        definition = FSMDefinition(
            entity_id="test.entity",
            states=("OFF", "ON", "EMERGENCY"),
            initial="OFF",
            transitions=(
                Transition(from_state="OFF", to_state="ON", trigger="activate"),
                Transition(from_state="*", to_state="EMERGENCY", trigger="emergency"),
            )
        )
        
        fsm.register(definition)
        
        # Переход из OFF -> ON
        fsm.trigger("test.entity", "activate", {})
        assert fsm.get_state("test.entity").current == "ON"
        
        # Переход из ON -> EMERGENCY (из любого состояния)
        fsm.trigger("test.entity", "emergency", {})
        assert fsm.get_state("test.entity").current == "EMERGENCY"
    
    def test_transition_from_tuple(self, fsm):
        """Тест перехода из нескольких состояний"""
        definition = FSMDefinition(
            entity_id="test.entity",
            states=("OFF", "SCHEDULE", "MOTION", "MANUAL"),
            initial="OFF",
            transitions=(
                Transition(
                    from_state=("OFF", "SCHEDULE"),
                    to_state="MOTION",
                    trigger="motion"
                ),
            )
        )
        
        fsm.register(definition)
        
        # Из OFF должен работать
        result = fsm.trigger("test.entity", "motion", {})
        assert result is True
        assert fsm.get_state("test.entity").current == "MOTION"


class TestFSMGuards:
    """Тесты guard условий"""
    
    def test_guard_true(self, fsm):
        """Тест когда guard возвращает True"""
        definition = FSMDefinition(
            entity_id="test.entity",
            states=("OFF", "ON"),
            initial="OFF",
            transitions=(
                Transition(
                    from_state="OFF",
                    to_state="ON",
                    trigger="turn_on",
                    guard=lambda ctx: ctx.get("allowed", False)
                ),
            )
        )
        
        fsm.register(definition)
        
        # Guard возвращает True
        result = fsm.trigger("test.entity", "turn_on", {"allowed": True})
        assert result is True
        assert fsm.get_state("test.entity").current == "ON"
    
    def test_guard_false(self, fsm):
        """Тест когда guard возвращает False"""
        definition = FSMDefinition(
            entity_id="test.entity",
            states=("OFF", "ON"),
            initial="OFF",
            transitions=(
                Transition(
                    from_state="OFF",
                    to_state="ON",
                    trigger="turn_on",
                    guard=lambda ctx: ctx.get("allowed", False)
                ),
            )
        )
        
        fsm.register(definition)
        
        # Guard возвращает False - переход не происходит
        result = fsm.trigger("test.entity", "turn_on", {"allowed": False})
        assert result is False
        assert fsm.get_state("test.entity").current == "OFF"
    
    def test_guard_exception(self, fsm, logger):
        """Тест когда guard вызывает исключение"""
        definition = FSMDefinition(
            entity_id="test.entity",
            states=("OFF", "ON"),
            initial="OFF",
            transitions=(
                Transition(
                    from_state="OFF",
                    to_state="ON",
                    trigger="turn_on",
                    guard=lambda ctx: 1 / 0  # Вызовет ZeroDivisionError
                ),
            )
        )
        
        fsm.register(definition)
        
        # Исключение в guard не должно ломать систему
        result = fsm.trigger("test.entity", "turn_on", {})
        assert result is False
        assert fsm.get_state("test.entity").current == "OFF"
        
        # Ошибка должна быть залогирована
        error_logs = [log for log in logger.get_logs() if log["level"] == "ERROR"]
        assert len(error_logs) > 0


class TestFSMPriority:
    """Тесты приоритетов переходов"""
    
    def test_higher_priority_wins(self, fsm):
        """Тест что переход с высшим приоритетом выбирается"""
        definition = FSMDefinition(
            entity_id="test.entity",
            states=("OFF", "ON", "EMERGENCY"),
            initial="OFF",
            transitions=(
                Transition(
                    from_state="OFF",
                    to_state="ON",
                    trigger="activate",
                    priority=10
                ),
                Transition(
                    from_state="OFF",
                    to_state="EMERGENCY",
                    trigger="activate",
                    priority=100
                ),
            )
        )
        
        fsm.register(definition)
        
        # Должен выбрать переход с приоритетом 100
        fsm.trigger("test.entity", "activate", {})
        assert fsm.get_state("test.entity").current == "EMERGENCY"


class TestFSMImmutability:
    """Тесты иммутабельности состояний"""
    
    def test_state_is_immutable(self, fsm):
        """Тест что состояние не мутируется"""
        definition = FSMDefinition(
            entity_id="test.entity",
            states=("OFF", "ON"),
            initial="OFF",
            transitions=(
                Transition(from_state="OFF", to_state="ON", trigger="turn_on"),
            )
        )
        
        fsm.register(definition)
        old_state = fsm.get_state("test.entity")
        
        fsm.trigger("test.entity", "turn_on", {})
        new_state = fsm.get_state("test.entity")
        
        # Старое состояние не должно измениться
        assert old_state.current == "OFF"
        assert new_state.current == "ON"
        assert old_state is not new_state
    
    def test_history_is_preserved(self, fsm):
        """Тест что история переходов сохраняется"""
        definition = FSMDefinition(
            entity_id="test.entity",
            states=("OFF", "ON", "AUTO"),
            initial="OFF",
            transitions=(
                Transition(from_state="OFF", to_state="ON", trigger="turn_on"),
                Transition(from_state="ON", to_state="AUTO", trigger="auto"),
            )
        )
        
        fsm.register(definition)
        fsm.trigger("test.entity", "turn_on", {})
        fsm.trigger("test.entity", "auto", {})
        
        state = fsm.get_state("test.entity")
        assert len(state.history) == 2
        assert state.history[0]["to"] == "AUTO"
        assert state.history[1]["to"] == "ON"


class TestFSMReset:
    """Тесты сброса автомата"""
    
    def test_reset_to_initial(self, fsm):
        """Тест сброса в начальное состояние"""
        definition = FSMDefinition(
            entity_id="test.entity",
            states=("OFF", "ON"),
            initial="OFF",
            transitions=(
                Transition(from_state="OFF", to_state="ON", trigger="turn_on"),
            )
        )
        
        fsm.register(definition)
        fsm.trigger("test.entity", "turn_on", {})
        assert fsm.get_state("test.entity").current == "ON"
        
        # Сброс
        result = fsm.reset("test.entity")
        assert result is True
        assert fsm.get_state("test.entity").current == "OFF"
    
    def test_reset_nonexistent(self, fsm):
        """Тест сброса несуществующего автомата"""
        result = fsm.reset("nonexistent.entity")
        assert result is False


class TestEventBus:
    """Тесты шины событий"""
    
    def test_subscribe_and_publish(self):
        """Тест подписки и публикации"""
        bus = EventBus()
        received_events = []
        
        def handler(data):
            received_events.append(data)
        
        bus.subscribe("test.event", handler)
        bus.publish("test.event", {"key": "value"})
        
        assert len(received_events) == 1
        assert received_events[0] == {"key": "value"}
    
    def test_unsubscribe(self):
        """Тест отписки"""
        bus = EventBus()
        call_count = [0]
        
        def handler(data):
            call_count[0] += 1
        
        bus.subscribe("test.event", handler)
        bus.publish("test.event", {})
        bus.unsubscribe("test.event", handler)
        bus.publish("test.event", {})
        
        assert call_count[0] == 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
