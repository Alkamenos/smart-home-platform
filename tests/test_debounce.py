"""
Debounce Tests - Тесты защиты от дребезга и спама событий

Tests cover:
1. Motion sensor spam (100 events in 1 second) - FSM should handle without crashes
2. Rapid state changes - FSM should debounce and not create excessive transitions
3. Echo detection - Commands from FSM should not trigger manual override
"""

import pytest
import sys
import os
import time
from unittest.mock import AsyncMock, MagicMock, patch

# Добавляем parent directory в path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.fsm import FSMEngine, FSMDefinition, Transition, State
from adapters.asyncio_scheduler import AsyncioScheduler
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
    return FSMEngine(event_bus, logger, AsyncioScheduler())


class TestDebounceSpam:
    """Тесты защиты от спама событий (дребезг датчиков)"""

    def test_motion_sensor_spam_100_events(self, fsm, event_bus, logger):
        """
        Тест: Датчик движения генерирует 100 событий за 1 секунду
        FSM должен обработать все события без падения и лишних переключений
        """
        transition_count = [0]
        
        def count_transitions(data):
            transition_count[0] += 1
        
        event_bus.subscribe("fsm.transition", count_transitions)
        
        definition = FSMDefinition(
            entity_id="light.hallway",
            states=("OFF", "ON_MOTION"),
            initial="OFF",
            transitions=(
                Transition(
                    from_state="OFF",
                    to_state="ON_MOTION",
                    trigger="motion_detected",
                    reason="Motion detected"
                ),
                Transition(
                    from_state="ON_MOTION",
                    to_state="OFF",
                    trigger="motion_cleared",
                    reason="Motion cleared"
                ),
            )
        )
        
        fsm.register(definition)
        
        # Эмулируем спам: 100 событий motion_detected подряд
        for i in range(100):
            fsm.trigger("light.hallway", "motion_detected", {"event_num": i})
        
        # FSM должен перейти в ON_MOTION только 1 раз (первое событие)
        # Последующие 99 событий не должны вызывать переходов (уже в ON_MOTION)
        state = fsm.get_state("light.hallway")
        assert state.current == "ON_MOTION"
        assert transition_count[0] == 1, f"Expected 1 transition, got {transition_count[0]}"
    
    def test_rapid_on_off_cycles(self, fsm, event_bus, logger):
        """
        Тест: Быстрые циклы включения/выключения (50 раз)
        FSM должен выдержать без ошибок
        """
        definition = FSMDefinition(
            entity_id="light.test",
            states=("OFF", "ON"),
            initial="OFF",
            transitions=(
                Transition(from_state="OFF", to_state="ON", trigger="turn_on"),
                Transition(from_state="ON", to_state="OFF", trigger="turn_off"),
            )
        )
        
        fsm.register(definition)
        
        # 50 циклов включения/выключения
        for _ in range(50):
            fsm.trigger("light.test", "turn_on", {})
            fsm.trigger("light.test", "turn_off", {})
        
        state = fsm.get_state("light.test")
        assert state.current == "OFF"
        # Проверяем что история содержит 100 переходов
        assert len(state.history) == 20  # Храним последние 20
    
    def test_guard_exception_during_spam(self, fsm, event_bus, logger):
        """
        Тест: Спам событий + падающий guard
        FSM должен продолжать работать после исключений в guard
        """
        call_count = [0]
        
        def faulty_guard(ctx):
            call_count[0] += 1
            if call_count[0] % 2 == 0:
                raise RuntimeError("Guard error!")
            return True
        
        definition = FSMDefinition(
            entity_id="light.test",
            states=("OFF", "ON"),
            initial="OFF",
            transitions=(
                Transition(
                    from_state="OFF",
                    to_state="ON",
                    trigger="event",
                    guard=faulty_guard
                ),
            )
        )
        
        fsm.register(definition)
        
        # 20 событий, каждое второе вызовет исключение в guard
        for i in range(20):
            result = fsm.trigger("light.test", "event", {"i": i})
            # Даже если guard падает, FSM не крашится
        
        # FSM должен быть в рабочем состоянии
        state = fsm.get_state("light.test")
        assert state.current in ("OFF", "ON")


class TestEchoDetection:
    """Тесты обнаружения эха (feedback loop protection)"""
    
    def test_fsm_command_sequence_stable(self, fsm, event_bus, logger):
        """
        Тест: Последовательность команд от FSM не вызывает нестабильности
        """
        transition_events = []
        
        def log_transition(data):
            transition_events.append(data)
        
        event_bus.subscribe("fsm.transition", log_transition)
        
        definition = FSMDefinition(
            entity_id="light.living_room",
            states=("OFF", "ON_SCHEDULE", "MANUAL"),
            initial="OFF",
            transitions=(
                Transition(
                    from_state="OFF",
                    to_state="ON_SCHEDULE",
                    trigger="schedule_on",
                    reason="Schedule activated"
                ),
                Transition(
                    from_state="ON_SCHEDULE",
                    to_state="OFF",
                    trigger="schedule_off",
                    reason="Schedule deactivated"
                ),
                Transition(
                    from_state="*",
                    to_state="MANUAL",
                    trigger="manual_change",
                    reason="Manual override"
                ),
            )
        )
        
        fsm.register(definition)
        
        # FSM включает свет по расписанию
        fsm.trigger("light.living_room", "schedule_on", {})
        assert fsm.get_state("light.living_room").current == "ON_SCHEDULE"
        
        # FSM выключает свет по расписанию
        fsm.trigger("light.living_room", "schedule_off", {})
        assert fsm.get_state("light.living_room").current == "OFF"
        
        # Ключевая проверка: manual_change НЕ был вызван автоматически
        # Это задача внешнего оркестратора - детектировать ручное вмешательство
        # FSM сам по себе не генерирует manual_change на основе своих же команд
        manual_transitions = [e for e in transition_events if e.get("to_state") == "MANUAL"]
        assert len(manual_transitions) == 0, "FSM commands should not trigger manual override"
    
    def test_multiple_triggers_same_state(self, fsm, event_bus, logger):
        """
        Тест: Многократные триггеры для того же состояния
        FSM не должен создавать дублирующиеся переходы
        """
        transition_events = []
        
        def log_transition(data):
            transition_events.append(data)
        
        event_bus.subscribe("fsm.transition", log_transition)
        
        definition = FSMDefinition(
            entity_id="light.bedroom",
            states=("OFF", "ON_MOTION"),
            initial="OFF",
            transitions=(
                Transition(
                    from_state="OFF",
                    to_state="ON_MOTION",
                    trigger="motion",
                    reason="Motion detected"
                ),
            )
        )
        
        fsm.register(definition)
        
        # 10 срабатываний датчика движения
        for i in range(10):
            fsm.trigger("light.bedroom", "motion", {"sensor_id": i})
        
        # Только первое событие должно вызвать переход
        assert len(transition_events) == 1
        assert transition_events[0]["to_state"] == "ON_MOTION"
        
        state = fsm.get_state("light.bedroom")
        assert state.current == "ON_MOTION"


class TestEventBusResilience:
    """Тесты устойчивости EventBus"""
    
    def test_multiple_handlers_one_fails(self):
        """Тест: Множество хендлеров, один падает - остальные работают"""
        from core.event_bus import EventBus
        
        bus = EventBus()
        successful_calls = []
        
        def handler1(data):
            successful_calls.append(1)
        
        def handler2(data):
            raise ValueError("Handler 2 failed")
        
        def handler3(data):
            successful_calls.append(3)
        
        def handler4(data):
            successful_calls.append(4)
        
        bus.subscribe("test.event", handler1)
        bus.subscribe("test.event", handler2)
        bus.subscribe("test.event", handler3)
        bus.subscribe("test.event", handler4)
        
        # Публикуем событие - не должно выбросить исключение
        bus.publish("test.event", {})
        
        # Все хендлеры кроме faulty должны были выполниться
        assert successful_calls == [1, 3, 4]
    
    def test_async_handler_in_sync_context(self):
        """Тест: Async хендлер в синхронном контексте не ломает выполнение"""
        from core.event_bus import EventBus
        import asyncio
        
        bus = EventBus()
        sync_called = [False]
        
        async def async_handler(data):
            await asyncio.sleep(0)
            pass
        
        def sync_handler(data):
            sync_called[0] = True
        
        bus.subscribe("test.event", async_handler)
        bus.subscribe("test.event", sync_handler)
        
        # В синхронном контексте async хендлер не выполнится,
        # но sync должен сработать
        bus.publish("test.event", {})
        
        assert sync_called[0] is True


class TestDebounceFeature:
    """Тесты встроенного debounce на уровне FSM"""
    
    def test_debounce_blocks_rapid_triggers(self, fsm, event_bus, logger):
        """
        Тест: Debounce блокирует быстрые повторные триггеры
        Переход с debounce_sec=0.5 должен игнорировать события в течение 0.5 сек
        """
        transition_events = []
        
        def log_transition(data):
            transition_events.append(data)
        
        event_bus.subscribe("fsm.transition", log_transition)
        
        definition = FSMDefinition(
            entity_id="light.debounce_test",
            states=("OFF", "ON"),
            initial="OFF",
            transitions=(
                Transition(
                    from_state="*",  # Из любого состояния (для циклического переключения)
                    to_state="ON",
                    trigger="motion",
                    reason="Motion detected",
                    debounce_sec=0.5  # 500ms debounce
                ),
            )
        )
        
        fsm.register(definition)
        
        # Первое событие - должно пройти
        fsm.trigger("light.debounce_test", "motion", {})
        assert len(transition_events) == 1
        
        # Быстрые повторные события (в пределах debounce окна) - должны быть заблокированы
        for i in range(10):
            fsm.trigger("light.debounce_test", "motion", {})
        
        # Всё ещё только 1 переход
        assert len(transition_events) == 1
        
        # Ждём окончания debounce окна
        time.sleep(0.6)
        
        # Теперь событие должно пройти (переход в то же состояние, но это новый переход)
        fsm.trigger("light.debounce_test", "motion", {})
        assert len(transition_events) == 2
    
    def test_debounce_per_trigger_type(self, fsm, event_bus, logger):
        """
        Тест: Debounce применяется отдельно к каждому типу триггера
        """
        transition_events = []
        
        def log_transition(data):
            transition_events.append({
                "to_state": data["to_state"],
                "trigger": data["trigger"]
            })
        
        event_bus.subscribe("fsm.transition", log_transition)
        
        definition = FSMDefinition(
            entity_id="light.multi_trigger",
            states=("OFF", "ON_MOTION", "ON_SWITCH"),
            initial="OFF",
            transitions=(
                Transition(
                    from_state="OFF",
                    to_state="ON_MOTION",
                    trigger="motion",
                    reason="Motion",
                    debounce_sec=0.3
                ),
                Transition(
                    from_state="*",  # Из любого состояния
                    to_state="ON_SWITCH",
                    trigger="switch",
                    reason="Switch",
                    debounce_sec=0.3
                ),
            )
        )
        
        fsm.register(definition)
        
        # Motion триггер
        fsm.trigger("light.multi_trigger", "motion", {})
        assert len(transition_events) == 1
        assert transition_events[-1]["to_state"] == "ON_MOTION"
        
        # Switch триггер должен пройти (это другой тип)
        fsm.trigger("light.multi_trigger", "switch", {})
        assert len(transition_events) == 2
        assert transition_events[-1]["to_state"] == "ON_SWITCH"
        
        # Повторный switch - должен быть заблокирован (debounce на тот же триггер)
        fsm.trigger("light.multi_trigger", "switch", {})
        assert len(transition_events) == 2  # Без изменений
    
    def test_debounce_per_trigger_type_independent(self, fsm, event_bus, logger):
        """
        Тест: Debounce применяется отдельно к каждому типу триггера
        (исправленная версия - учитывает что FSM уже в другом состоянии)
        """
        transition_events = []
        
        def log_transition(data):
            transition_events.append({
                "to_state": data["to_state"],
                "trigger": data["trigger"]
            })
        
        event_bus.subscribe("fsm.transition", log_transition)
        
        definition = FSMDefinition(
            entity_id="light.multi_trigger2",
            states=("OFF", "ON_MOTION", "ON_SWITCH"),
            initial="OFF",
            transitions=(
                Transition(
                    from_state="OFF",
                    to_state="ON_MOTION",
                    trigger="motion",
                    reason="Motion",
                    debounce_sec=0.3
                ),
                Transition(
                    from_state="*",  # Из любого состояния
                    to_state="ON_SWITCH",
                    trigger="switch",
                    reason="Switch",
                    debounce_sec=0.3
                ),
            )
        )
        
        fsm.register(definition)
        
        # Motion триггер
        fsm.trigger("light.multi_trigger2", "motion", {})
        assert len(transition_events) == 1
        assert transition_events[-1]["to_state"] == "ON_MOTION"
        
        # Switch триггер должен пройти (это другой тип триггера)
        fsm.trigger("light.multi_trigger2", "switch", {})
        assert len(transition_events) == 2
        assert transition_events[-1]["to_state"] == "ON_SWITCH"
        
        # Повторный switch - должен быть заблокирован (debounce на тот же триггер)
        fsm.trigger("light.multi_trigger2", "switch", {})
        assert len(transition_events) == 2  # Без изменений
    
    def test_no_debounce_when_zero(self, fsm, event_bus, logger):
        """
        Тест: При debounce_sec=0 переходы происходят без задержек
        """
        transition_count = [0]
        
        def count_transitions(data):
            transition_count[0] += 1
        
        event_bus.subscribe("fsm.transition", count_transitions)
        
        definition = FSMDefinition(
            entity_id="light.no_debounce",
            states=("OFF", "ON"),
            initial="OFF",
            transitions=(
                Transition(
                    from_state="OFF",
                    to_state="ON",
                    trigger="event",
                    reason="Event",
                    debounce_sec=0.0  # No debounce
                ),
                Transition(
                    from_state="ON",
                    to_state="OFF",
                    trigger="event",
                    reason="Event",
                    debounce_sec=0.0
                ),
            )
        )
        
        fsm.register(definition)
        
        # 10 быстрых событий - все должны пройти
        for i in range(10):
            fsm.trigger("light.no_debounce", "event", {})
        
        # Из-за того что FSM переключается OFF->ON->OFF..., 
        # будет 5 полных циклов = 10 переходов
        assert transition_count[0] == 10


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
