"""
Scenario-тесты для Lighting Feature

Проверяют полные сценарии работы освещения:
- Включение по расписанию
- Переопределение движением
- Ручное вмешательство
- Режим вечеринки
"""

import pytest
import sys
import os

# Добавляем parent directory в path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.fsm import FSMEngine
from core.event_bus import EventBus
from core.logger import Logger
from features.lighting import create_lighting_automations


@pytest.fixture
def lighting_system():
    """Создать систему освещения с одной комнатой"""
    event_bus = EventBus()
    logger = Logger(component="test", output=None)
    fsm = FSMEngine(event_bus, logger)
    
    # Регистрируем автоматы для living_room
    definitions = create_lighting_automations(["living_room"])
    for definition in definitions:
        fsm.register(definition)
    
    return fsm


class TestLightingScenarios:
    """Сценарные тесты освещения"""
    
    def test_schedule_on(self, lighting_system):
        """Тест включения по расписанию"""
        context = {
            "living_room_is_schedule_time": True,
            "living_room_is_night_time": False
        }
        
        result = lighting_system.trigger("light.living_room", "schedule_on", context)
        
        assert result is True
        state = lighting_system.get_state("light.living_room")
        assert state.current == "ON_SCHEDULE"
        assert state.entered_by == "schedule_on"
    
    def test_schedule_off(self, lighting_system):
        """Тест выключения по расписанию"""
        # Сначала включаем по расписанию
        lighting_system.trigger("light.living_room", "schedule_on", {
            "living_room_is_schedule_time": True,
            "living_room_is_night_time": False
        })
        
        # Выключаем по расписанию
        result = lighting_system.trigger("light.living_room", "schedule_off", {
            "living_room_is_schedule_time": False
        })
        
        assert result is True
        state = lighting_system.get_state("light.living_room")
        assert state.current == "OFF"
    
    def test_motion_overrides_schedule(self, lighting_system):
        """Тест: движение переопределяет расписание"""
        # Включаем по расписанию
        lighting_system.trigger("light.living_room", "schedule_on", {
            "living_room_is_schedule_time": True,
            "living_room_is_night_time": False
        })
        assert lighting_system.get_state("light.living_room").current == "ON_SCHEDULE"
        
 # Обнаружено движение
        context = {
            "living_room_motion_sensor": True,
            "living_room_motion_enabled": True
        }
        result = lighting_system.trigger("light.living_room", "motion_detected", context)
        
        assert result is True
        state = lighting_system.get_state("light.living_room")
        assert state.current == "ON_MOTION"
    
    def test_motion_cleared(self, lighting_system):
        """Тест: выключение при отсутствии движения"""
        # Включаем по движению
        lighting_system.trigger("light.living_room", "motion_detected", {
            "living_room_motion_sensor": True,
            "living_room_motion_enabled": True
        })
        assert lighting_system.get_state("light.living_room").current == "ON_MOTION"
        
        # Движение прекратилось
        result = lighting_system.trigger("light.living_room", "motion_cleared", {
            "living_room_motion_sensor": False
        })
        
        assert result is True
        state = lighting_system.get_state("light.living_room")
        assert state.current == "OFF"
    
    def test_manual_highest_priority(self, lighting_system):
        """Тест: ручное вмешательство имеет наивысший приоритет"""
        # Включаем по расписанию
        lighting_system.trigger("light.living_room", "schedule_on", {
            "living_room_is_schedule_time": True,
            "living_room_is_night_time": False
        })
        
        # Включаем по движению
        lighting_system.trigger("light.living_room", "motion_detected", {
            "living_room_motion_sensor": True,
            "living_room_motion_enabled": True
        })
        
        # Ручное вмешательство
        result = lighting_system.trigger("light.living_room", "manual_change", {})
        
        assert result is True
        state = lighting_system.get_state("light.living_room")
        assert state.current == "MANUAL"
        assert state.entered_why == "Ручное вмешательство"
    
    def test_party_mode(self, lighting_system):
        """Тест режима вечеринки"""
        # Включаем режим вечеринки из любого состояния
        lighting_system.trigger("light.living_room", "schedule_on", {
            "living_room_is_schedule_time": True,
            "living_room_is_night_time": False
        })
        
        result = lighting_system.trigger("light.living_room", "party_mode_on", {})
        
        assert result is True
        state = lighting_system.get_state("light.living_room")
        assert state.current == "PARTY"
        
        # Выключаем режим вечеринки
        lighting_system.trigger("light.living_room", "party_mode_off", {})
        state = lighting_system.get_state("light.living_room")
        assert state.current == "OFF"
    
    def test_night_mode(self, lighting_system):
        """Тест ночного режима"""
        # Ночной режим доступен из любого состояния
        result = lighting_system.trigger("light.living_room", "night_mode_on", {
            "living_room_is_night_time": True
        })
        
        assert result is True
        state = lighting_system.get_state("light.living_room")
        assert state.current == "NIGHTLIGHT"
    
    def test_timeout_from_manual(self, lighting_system):
        """Тест таймаута из ручного режима"""
        import time
        
        # Включаем ручной режим
        lighting_system.trigger("light.living_room", "manual_change", {})
        assert lighting_system.get_state("light.living_room").current == "MANUAL"
        
        # Прошло 60 минут - передаём timestamp ручного вмешательства (61 минуту назад)
        result = lighting_system.trigger("light.living_room", "timeout", {
            "living_room_manual_entered_at": time.time() - 61*60
        })
        
        assert result is True
        state = lighting_system.get_state("light.living_room")
        assert state.current == "OFF"
    
    def test_no_transition_without_guard(self, lighting_system):
        """Тест что переход не происходит без выполнения guard условия"""
        # Пытаемся включить по расписанию, но сейчас не время
        result = lighting_system.trigger("light.living_room", "schedule_on", {
            "living_room_is_schedule_time": False,  # Не время
            "living_room_is_night_time": False
        })
        
        assert result is False
        state = lighting_system.get_state("light.living_room")
        assert state.current == "OFF"  # Состояние не изменилось


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
