"""
End-to-End Tests - Сценарные тесты платформы с MockAdapter

Эти тесты проверяют полный цикл работы платформы:
1. MockAdapter эмулирует события от устройств
2. FSM обрабатывает события и принимает решения
3. Проверяем что в логе команд MockAdapter появились правильные вызовы
"""

import pytest
from core.event_bus import EventBus
from core.fsm import FSMEngine, FSMDefinition, Transition
from core.logger import Logger
from adapters.mock_adapter import MockAdapter
from adapters.asyncio_scheduler import AsyncioScheduler
from adapters.bridge import ActionBridge


logger = Logger(component="test_e2e", output=None)


def create_lighting_fsm(entity_id: str) -> FSMDefinition:
    """Создать FSM для управления светом"""
    return FSMDefinition(
        entity_id=entity_id,
        states=("OFF", "ON_SCHEDULE", "ON_MOTION", "MANUAL"),
        initial="OFF",
        transitions=(
            Transition(
                from_state="OFF",
                to_state="ON_MOTION",
                trigger="motion_detected",
                guard=lambda ctx: ctx.get("motion", False),
                reason="Движение обнаружено",
                attributes={"brightness": 100}
            ),
            Transition(
                from_state="ON_MOTION",
                to_state="OFF",
                trigger="no_motion",
                reason="Движение прекратилось",
                timeout_sec=60
            ),
            Transition(
                from_state="OFF",
                to_state="ON_SCHEDULE",
                trigger="schedule_on",
                reason="Включение по расписанию",
                attributes={"brightness": 50}
            ),
            Transition(
                from_state="*",
                to_state="OFF",
                trigger="schedule_off",
                reason="Выключение по расписанию"
            ),
            Transition(
                from_state="*",
                to_state="MANUAL",
                trigger="manual_change",
                reason="Ручное управление",
                manual_lockout_min=5.0  # Блокировка автоматики на 5 минут
            )
        )
    )


class TestEndToEndScenarios:
    """E2E тесты сценариев работы платформы"""
    
    def test_motion_activates_light(self):
        """
        Сценарий: Пришло событие motion_detected -> FSM сработал -> 
        В MockAdapter появилась команда turn_on для light.hallway
        """
        # Инициализация компонентов
        event_bus = EventBus()
        logger = Logger(component="test_e2e", output=None)
        mock_adapter = MockAdapter()
        fsm_engine = FSMEngine(event_bus, logger, AsyncioScheduler())
        
        # Регистрируем FSM
        fsm_def = create_lighting_fsm("light.hallway")
        fsm_engine.register(fsm_def)
        
        # Создаём мост для выполнения действий
        bridge = ActionBridge(event_bus, mock_adapter, logger)
        
        # Эмулируем событие движения
        event_bus.publish("fsm.trigger", {
            "entity_id": "light.hallway",
            "trigger": "motion_detected",
            "context": {"motion": True}
        })
        
        # Триггерим FSM (в реальном коде это делает оркестратор)
        fsm_engine.trigger("light.hallway", "motion_detected", {"motion": True})
        
        # Проверяем что команда была отправлена
        commands = mock_adapter.get_commands_log()
        assert len(commands) > 0, "Команды не были отправлены"
        
        # Находим последнюю команду типа "command" (а не "state_change")
        command_entries = [c for c in commands if c.get("type") == "command"]
        assert len(command_entries) > 0, "Команды не были найдены в логе"
        
        last_command = command_entries[-1]
        assert last_command["entity_id"] == "light.hallway"
        assert last_command["command"] == "turn_on"
        assert last_command["attributes"]["brightness"] == 100
        
        # Проверяем состояние FSM
        state = fsm_engine.get_state("light.hallway")
        assert state.current == "ON_MOTION"
    
    def test_manual_override_blocks_automation(self):
        """
        Сценарий: Пользователь включил свет вручную -> 
        Автоматика заблокирована на 5 минут -> 
        Событие schedule_off игнорируется
        """
        event_bus = EventBus()
        logger = Logger(component="test_e2e", output=None)
        mock_adapter = MockAdapter()
        fsm_engine = FSMEngine(event_bus, logger, AsyncioScheduler())
        
        fsm_def = create_lighting_fsm("light.bedroom")
        fsm_engine.register(fsm_def)
        bridge = ActionBridge(event_bus, mock_adapter, logger)
        
        # Сначала включаем по расписанию
        fsm_engine.trigger("light.bedroom", "schedule_on", {})
        state = fsm_engine.get_state("light.bedroom")
        assert state.current == "ON_SCHEDULE"
        
        # Пользователь вмешивается вручную
        fsm_engine.trigger("light.bedroom", "manual_change", {"source": "user"})
        state = fsm_engine.get_state("light.bedroom")
        assert state.current == "MANUAL"
        
        # Проверяем что manual_override_until установлен в будущее (используем monotonic)
        import time
        assert state.manual_override_until > time.monotonic()
        
        # Пытаемся выключить по расписанию (должно быть заблокировано)
        result = fsm_engine.trigger("light.bedroom", "schedule_off", {})
        assert result is False, "Автоматическое выключение не должно сработать"
        
        # Состояние не изменилось
        state = fsm_engine.get_state("light.bedroom")
        assert state.current == "MANUAL"
    
    def test_cooldown_prevents_rapid_transitions(self):
        """
        Сценарий: Быстрая серия событий motion_detected ->
        Cooldown предотвращает множественные переходы
        """
        event_bus = EventBus()
        logger = Logger(component="test_e2e", output=None)
        mock_adapter = MockAdapter()
        
        # Создаём FSM с cooldown - используем состояние ON_MOTION чтобы ActionBridge сработал
        fsm_def = FSMDefinition(
            entity_id="light.kitchen",
            states=("OFF", "ON_MOTION"),
            initial="OFF",
            transitions=(
                Transition(
                    from_state="OFF",
                    to_state="ON_MOTION",
                    trigger="motion",
                    cooldown_sec=5.0,  # 5 секунд cooldown
                    attributes={"brightness": 80}
                ),
                Transition(
                    from_state="ON_MOTION",
                    to_state="OFF",
                    trigger="timeout",
                    reason="Таймаут"
                )
            )  # tuple из 2 элементов
        )
        
        fsm_engine = FSMEngine(event_bus, logger, AsyncioScheduler())
        fsm_engine.register(fsm_def)
        bridge = ActionBridge(event_bus, mock_adapter, logger)
        
        # Первое событие - должно сработать
        result1 = fsm_engine.trigger("light.kitchen", "motion", {})
        assert result1 is True
        
        state1 = fsm_engine.get_state("light.kitchen")
        assert state1.current == "ON_MOTION"
        
        # Второе событие сразу же - должно быть заблокировано cooldown
        result2 = fsm_engine.trigger("light.kitchen", "motion", {})
        assert result2 is False
        
        # Состояние не изменилось
        state2 = fsm_engine.get_state("light.kitchen")
        assert state2.current == "ON_MOTION"
        
        # Проверяем лог команд - должна быть только одна команда типа "command"
        commands = mock_adapter.get_commands_log()
        command_entries = [c for c in commands if c.get("type") == "command"]
        assert len(command_entries) == 1
    
    def test_debounce_blocks_duplicate_triggers(self):
        """
        Сценарий: Датчик движения генерирует несколько событий подряд ->
        Debounce фильтрует дубликаты
        """
        event_bus = EventBus()
        logger = Logger(component="test_e2e", output=None)
        mock_adapter = MockAdapter()
        
        # FSM с debounce
        fsm_def = FSMDefinition(
            entity_id="light.corridor",
            states=("OFF", "ON"),
            initial="OFF",
            transitions=(
                Transition(
                    from_state="OFF",
                    to_state="ON",
                    trigger="motion",
                    debounce_sec=2.0,  # 2 секунды debounce
                    reason="Движение"
                ),  # Запятая обязательна для tuple из 1 элемента!
            )
        )
        
        fsm_engine = FSMEngine(event_bus, logger, AsyncioScheduler())
        fsm_engine.register(fsm_def)
        bridge = ActionBridge(event_bus, mock_adapter, logger)
        
        # Первое событие - проходит
        result1 = fsm_engine.trigger("light.corridor", "motion", {})
        assert result1 is True
        
        # Второе событие сразу - блокируется debounce
        result2 = fsm_engine.trigger("light.corridor", "motion", {})
        assert result2 is False
        
        # Третье событие тоже блокируется
        result3 = fsm_engine.trigger("light.corridor", "motion", {})
        assert result3 is False
    
    def test_full_day_scenario(self):
        """
        Полный сценарий дня:
        1. Утро: включение по расписанию
        2. День: выключение по расписанию
        3. Вечер: движение включает свет
        4. Ночь: пользователь выключает вручную
        """
        event_bus = EventBus()
        logger = Logger(component="test_e2e", output=None)
        mock_adapter = MockAdapter()
        
        fsm_def = create_lighting_fsm("light.living_room")
        fsm_engine = FSMEngine(event_bus, logger, AsyncioScheduler())
        fsm_engine.register(fsm_def)
        bridge = ActionBridge(event_bus, mock_adapter, logger)
        
        # 1. Утро: включение по расписанию
        fsm_engine.trigger("light.living_room", "schedule_on", {})
        state = fsm_engine.get_state("light.living_room")
        assert state.current == "ON_SCHEDULE"
        
        # 2. День: выключение по расписанию
        fsm_engine.trigger("light.living_room", "schedule_off", {})
        state = fsm_engine.get_state("light.living_room")
        assert state.current == "OFF"
        
        # 3. Вечер: движение включает свет
        fsm_engine.trigger("light.living_room", "motion_detected", {"motion": True})
        state = fsm_engine.get_state("light.living_room")
        assert state.current == "ON_MOTION"
        
        # 4. Движение прекратилось - таймаут
        fsm_engine.trigger("light.living_room", "no_motion", {})
        state = fsm_engine.get_state("light.living_room")
        assert state.current == "OFF"
        
        # 5. Ночь: пользователь включает вручную
        fsm_engine.trigger("light.living_room", "manual_change", {"source": "user"})
        state = fsm_engine.get_state("light.living_room")
        assert state.current == "MANUAL"
        
        # Проверяем историю переходов
        assert len(state.history) >= 5
        
        # Проверяем что все команды были отправлены
        commands = mock_adapter.get_commands_log()
        assert len(commands) >= 4  # минимум 4 команды (on, off, on, off/on manual)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
