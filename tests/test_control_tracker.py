"""
Tests for Control Tracker
"""

import pytest
import time
from unittest.mock import MagicMock

from core.control_tracker import (
    ControlTracker,
    ControlEvent,
    TriggerSource
)


class TestControlTracker:
    """Тесты для ControlTracker"""
    
    @pytest.fixture
    def tracker(self):
        return ControlTracker(history_size=100)
    
    def test_records_event(self, tracker):
        """События записываются"""
        tracker.record("light.kitchen", TriggerSource.MANUAL, "turn_on")
        
        last_control = tracker.get_last_control("light.kitchen")
        assert last_control is not None
        assert last_control.entity_id == "light.kitchen"
        assert last_control.source == TriggerSource.MANUAL
        assert last_control.trigger == "turn_on"
    
    def test_get_last_manual(self, tracker):
        """Последнее ручное находится"""
        tracker.record("light.kitchen", TriggerSource.AUTOMATION, "motion")
        tracker.record("light.kitchen", TriggerSource.MANUAL, "turn_on")
        tracker.record("light.kitchen", TriggerSource.AUTOMATION, "timeout")
        
        last_manual = tracker.get_last_manual("light.kitchen")
        assert last_manual is not None
        assert last_manual.source == TriggerSource.MANUAL
        assert last_manual.trigger == "turn_on"
    
    def test_get_last_control(self, tracker):
        """Последнее любое управление находится"""
        tracker.record("light.kitchen", TriggerSource.SCHEDULE, "night_mode")
        
        last_control = tracker.get_last_control("light.kitchen")
        assert last_control is not None
        assert last_control.source == TriggerSource.SCHEDULE
    
    def test_history_limit(self, tracker):
        """История ограничена"""
        # Записываем больше чем лимит
        for i in range(150):
            tracker.record("light.test", TriggerSource.AUTOMATION, f"trigger_{i}")
        
        history = tracker.get_history("light.test", limit=200)
        assert len(history) <= 100  # Лимит истории
    
    def test_stats(self, tracker):
        """Статистика корректна"""
        tracker.record("light.kitchen", TriggerSource.MANUAL, "turn_on")
        tracker.record("light.kitchen", TriggerSource.MANUAL, "turn_off")
        tracker.record("light.kitchen", TriggerSource.AUTOMATION, "motion")
        tracker.record("light.kitchen", TriggerSource.AUTOMATION, "timeout")
        tracker.record("light.kitchen", TriggerSource.AUTOMATION, "schedule")
        
        stats = tracker.get_stats("light.kitchen")
        assert stats[TriggerSource.MANUAL] == 2
        assert stats[TriggerSource.AUTOMATION] == 3
    
    def test_ignores_system_events_for_manual(self, tracker):
        """Системные события не считаются ручными"""
        tracker.record("light.kitchen", TriggerSource.SYSTEM, "restore")
        tracker.record("light.kitchen", TriggerSource.MANUAL, "turn_on")
        
        last_manual = tracker.get_last_manual("light.kitchen")
        assert last_manual is not None
        assert last_manual.source == TriggerSource.MANUAL
        assert last_manual.trigger == "turn_on"
    
    def test_minutes_since_manual(self, tracker):
        """Минуты с последнего ручного вычисляются"""
        tracker.record("light.kitchen", TriggerSource.MANUAL, "turn_on")
        
        mins = tracker.minutes_since_manual("light.kitchen")
        assert mins is not None
        assert mins >= 0
        assert mins < 1  # Только что записали
    
    def test_was_manual_within(self, tracker):
        """Проверка было ли ручное в последние N минут"""
        tracker.record("light.kitchen", TriggerSource.MANUAL, "turn_on")
        
        # Должно быть True для 60 минут
        assert tracker.was_manual_within("light.kitchen", 60) is True
        
        # Должно быть False для устройства без ручных
        assert tracker.was_manual_within("light.other", 60) is False
    
    def test_clear_entity(self, tracker):
        """Очистка конкретного устройства"""
        tracker.record("light.one", TriggerSource.MANUAL, "on")
        tracker.record("light.two", TriggerSource.MANUAL, "on")
        
        tracker.clear("light.one")
        
        assert tracker.get_last_manual("light.one") is None
        assert tracker.get_last_manual("light.two") is not None
    
    def test_clear_all(self, tracker):
        """Очистка всех устройств"""
        tracker.record("light.one", TriggerSource.MANUAL, "on")
        tracker.record("light.two", TriggerSource.MANUAL, "on")
        
        tracker.clear()
        
        assert tracker.get_last_manual("light.one") is None
        assert tracker.get_last_manual("light.two") is None


class TestControlEvent:
    """Тесты для ControlEvent"""
    
    def test_is_manual_property(self):
        """Свойство is_manual работает"""
        manual_event = ControlEvent(
            entity_id="light.test",
            source=TriggerSource.MANUAL,
            trigger="turn_on",
            timestamp=time.time()
        )
        
        auto_event = ControlEvent(
            entity_id="light.test",
            source=TriggerSource.AUTOMATION,
            trigger="motion",
            timestamp=time.time()
        )
        
        assert manual_event.is_manual is True
        assert auto_event.is_manual is False
    
    def test_is_automation_property(self):
        """Свойство is_automation работает"""
        auto_event = ControlEvent(
            entity_id="light.test",
            source=TriggerSource.AUTOMATION,
            trigger="motion",
            timestamp=time.time()
        )
        
        manual_event = ControlEvent(
            entity_id="light.test",
            source=TriggerSource.MANUAL,
            trigger="turn_on",
            timestamp=time.time()
        )
        
        assert auto_event.is_automation is True
        assert manual_event.is_automation is False


class TestTriggerSource:
    """Тесты для констант TriggerSource"""
    
    def test_constants_defined(self):
        """Все константы определены"""
        assert TriggerSource.MANUAL == "manual"
        assert TriggerSource.AUTOMATION == "automation"
        assert TriggerSource.SCHEDULE == "schedule"
        assert TriggerSource.EXTERNAL == "external"
        assert TriggerSource.SYSTEM == "system"
