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


class TestMonotonicTime:
    """Тесты на использование монотонного времени"""
    
    def test_monotonic_time_resistance(self, event_bus, logger, monkeypatch):
        """
        Тест проверяет что при 'прыжке' системного времени cooldown не ломается.
        
        Сценарий:
        1. Регистрируем автомат с cooldown_sec = 5 секунд
        2. Выполняем первый переход
        3. Эмулируем прыжок времени (time.time() изменилось на +1 час)
        4. Пытаемся выполнить второй переход - он должен быть заблокирован cooldown
           потому что time.monotonic() не изменился
        
        Это доказывает что cooldown использует монотонное время, а не абсолютное.
        """
        import time as time_module
        
        # Фиксированное монотонное время (не будет меняться)
        base_mono_time = [100.0]  # Начинаем с 100
        
        # Абсолютное время которое будем эмулировать с прыжком
        abs_time_jump = [5000.0]  # Начальное абсолютное время
        
        # Создаём моки для time.time() и time.monotonic()
        def mock_time():
            return abs_time_jump[0]
        
        def mock_monotonic():
            return base_mono_time[0]
        
        # Патчим time.time и time.monotonic ДО создания FSM
        monkeypatch.setattr(time_module, "time", mock_time)
        monkeypatch.setattr(time_module, "monotonic", mock_monotonic)
        
        # Создаём FSM после патчинга
        from core.fsm import FSMEngine
        fsm = FSMEngine(event_bus, logger)
        
        # Регистрируем автомат с cooldown 5 секунд
        # from_state="*" позволяет выполнять переход из любого состояния
        definition = FSMDefinition(
            entity_id="test.cooldown",
            states=("OFF", "ON"),
            initial="OFF",
            transitions=(
                Transition(
                    from_state="*",  # Из любого состояния
                    to_state="ON",
                    trigger="turn_on",
                    cooldown_sec=5.0
                ),
            )
        )
        
        fsm.register(definition)
        
        # Увеличиваем монотонное время на 10 секунд перед первым переходом
        # Чтобы cooldown не блокировал первый переход (last_transition_at=100, now=110)
        base_mono_time[0] = 110.0
        
        # Первый переход - должен пройти
        result1 = fsm.trigger("test.cooldown", "turn_on", {})
        assert result1 is True
        assert fsm.get_state("test.cooldown").current == "ON"
        
        # Запоминаем last_transition_at после первого перехода
        last_transition_after_first = fsm.get_state("test.cooldown").last_transition_at
        
        # Эмулируем прыжок системного времени на 1 час вперёд
        abs_time_jump[0] += 3600.0
        # Монотонное время НЕ меняем - оно должно остаться тем же
        
        # Второй переход - должен быть заблокирован cooldown
        # Потому что монотонное время не изменилось (прошло 0 секунд)
        result2 = fsm.trigger("test.cooldown", "turn_on", {})
        assert result2 is False  # Заблокировано cooldown
        
        # Теперь увеличиваем монотонное время на 6 секунд (больше cooldown)
        base_mono_time[0] = last_transition_after_first + 6.0
        
        # Третий переход - должен пройти (cooldown истёк)
        result3 = fsm.trigger("test.cooldown", "turn_on", {})
        assert result3 is True
    
    def test_manual_lockout_uses_monotonic_time(self, event_bus, logger, monkeypatch):
        """
        Тест проверяет что manual_lockout использует монотонное время.
        
        Сценарий:
        1. Регистрируем автомат с manual_lockout_min = 1 минута
        2. Выполняем переход с ручным источником
        3. Эмулируем прыжок системного времени
        4. Автоматический триггер должен всё ещё быть заблокирован
        """
        import time as time_module
        
        base_mono_time = [1000.0]
        abs_time = [5000.0]
        
        def mock_time():
            return abs_time[0]
        
        def mock_monotonic():
            return base_mono_time[0]
        
        # Патчим ДО создания FSM
        monkeypatch.setattr(time_module, "time", mock_time)
        monkeypatch.setattr(time_module, "monotonic", mock_monotonic)
        
        # Создаём FSM после патчинга
        from core.fsm import FSMEngine
        fsm = FSMEngine(event_bus, logger)
        
        # Регистрируем автомат с manual_lockout 1 минута
        # from_state="*" позволяет выполнять переход из любого состояния
        definition = FSMDefinition(
            entity_id="test.lockout",
            states=("OFF", "ON"),
            initial="OFF",
            transitions=(
                Transition(
                    from_state="*",  # Из любого состояния
                    to_state="ON",
                    trigger="turn_on",
                    manual_lockout_min=1.0  # 1 минута блокировки
                ),
            )
        )
        
        fsm.register(definition)
        
        # Выполняем переход с source="manual"
        result1 = fsm.trigger("test.lockout", "turn_on", {"source": "manual"})
        assert result1 is True
        
        # Эмулируем прыжок времени на 10 минут вперёд
        abs_time[0] += 600.0
        
        # Но монотонное время увеличиваем только на 30 секунд
        base_mono_time[0] += 30.0
        
        # Автоматический триггер должен быть заблокирован
        # (прошло только 30 секунд монотонного времени, а lockout на 60 секунд)
        result2 = fsm.trigger("test.lockout", "turn_on", {"source": "auto"})
        assert result2 is False
        
        # Увеличиваем монотонное время ещё на 31 секунду (итого 61 секунда)
        base_mono_time[0] += 31.0
        
        # Теперь автоматический триггер должен пройти
        result3 = fsm.trigger("test.lockout", "turn_on", {"source": "auto"})
        assert result3 is True
