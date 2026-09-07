#!/usr/bin/env python3
"""Тесты для FSM Engine V2"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

import pytest
from platform_v2.core.fsm_engine import FSMEngine, FSMDefinition

def create_light_fsm():
    """Создать тестовый автомат освещения"""
    return FSMDefinition(
        states=["OFF", "ON_MOTION", "MANUAL_LOCK"],
        initial="OFF",
        transitions=[
            {
                "from": ["OFF"],
                "to": "ON_MOTION",
                "trigger": "motion",
                "guard": "dark and motion_mode != 'Выкл'",
                "priority": 30,
                "why": "Включение по датчику движения"
            },
            {
                "from": ["ON_MOTION"],
                "to": "OFF",
                "trigger": "no_motion_timeout",
                "priority": 10,
                "why": "Выключение по таймеру"
            },
            {
                "from": ["OFF", "ON_MOTION"],
                "to": "MANUAL_LOCK",
                "trigger": "manual_change",
                "priority": 100,
                "why": "Ручное вмешательство"
            },
            {
                "from": "MANUAL_LOCK",
                "to": "PREVIOUS",
                "trigger": "timeout",
                "priority": 5,
                "why": "Таймер блокировки истёк"
            }
        ]
    )

class TestFSMEngine:
    def test_initial_state(self):
        """Автомат должен инициализироваться в начальном состоянии"""
        engine = FSMEngine()
        engine.register("light.test", create_light_fsm())
        assert engine.get_state("light.test") == "OFF"
    
    def test_motion_trigger_with_guard(self):
        """Движение должно включать свет только если темно"""
        engine = FSMEngine()
        engine.register("light.test", create_light_fsm())
        
        # Темно и режим не выключен — должен включиться
        ctx = {"dark": True, "motion_mode": "Включать и выключать"}
        result = engine.trigger("light.test", "motion", ctx=ctx)
        assert result is True
        assert engine.get_state("light.test") == "ON_MOTION"
        
        # Сброс
        engine._states["light.test"].state = "OFF"
        
        # Светло — не должен включиться
        ctx = {"dark": False, "motion_mode": "Включать и выключать"}
        result = engine.trigger("light.test", "motion", ctx=ctx)
        assert result is False
        assert engine.get_state("light.test") == "OFF"
    
    def test_guard_blocks_when_mode_disabled(self):
        """Движение не должно работать если режим выключен"""
        engine = FSMEngine()
        engine.register("light.test", create_light_fsm())
        
        ctx = {"dark": True, "motion_mode": "Выкл"}
        result = engine.trigger("light.test", "motion", ctx=ctx)
        assert result is False
        assert engine.get_state("light.test") == "OFF"
    
    def test_manual_lock_priority(self):
        """Ручное вмешательство должно иметь наивысший приоритет"""
        engine = FSMEngine()
        engine.register("light.test", create_light_fsm())
        
        # Включаем свет движением
        ctx = {"dark": True, "motion_mode": "Включать и выключать"}
        engine.trigger("light.test", "motion", ctx=ctx)
        assert engine.get_state("light.test") == "ON_MOTION"
        
        # Ручное вмешательство блокирует автоматику
        engine.trigger("light.test", "manual_change", ctx={})
        assert engine.get_state("light.test") == "MANUAL_LOCK"
        
        # Движение не работает во время блокировки
        result = engine.trigger("light.test", "motion", ctx=ctx)
        assert result is False
    
    def test_timeout_returns_to_previous(self):
        """После истечения блокировки возврат к предыдущему состоянию"""
        engine = FSMEngine()
        engine.register("light.test", create_light_fsm())
        
        # Включаем свет
        ctx = {"dark": True, "motion_mode": "Включать и выключать"}
        engine.trigger("light.test", "motion", ctx=ctx)
        
        # Ручная блокировка
        engine.trigger("light.test", "manual_change", ctx={})
        assert engine.get_state("light.test") == "MANUAL_LOCK"
        
        # Истечение таймера возвращает к предыдущему состоянию
        engine.trigger("light.test", "timeout", ctx={})
        assert engine.get_state("light.test") == "ON_MOTION"
    
    def test_history_tracked(self):
        """История переходов должна сохраняться"""
        engine = FSMEngine()
        engine.register("light.test", create_light_fsm())
        
        ctx = {"dark": True, "motion_mode": "Включать и выключать"}
        engine.trigger("light.test", "motion", ctx=ctx)
        
        history = engine.get_history("light.test")
        assert len(history) == 1
        assert history[0]["from"] == "OFF"
        assert history[0]["to"] == "ON_MOTION"
        assert history[0]["trigger"] == "motion"
    
    def test_guard_with_and_or_normalization(self):
        """Проверка нормализации AND/OR в guard"""
        engine = FSMEngine()
        
        # Тест с использованием AND
        fsm_def = FSMDefinition(
            states=["OFF", "ON"],
            initial="OFF",
            transitions=[
                {
                    "from": ["OFF"],
                    "to": "ON",
                    "trigger": "activate",
                    "guard": "flag_a AND flag_b OR flag_c",
                    "priority": 10,
                    "why": "Тест"
                }
            ]
        )
        engine.register("test.entity", fsm_def)
        
        # flag_a AND flag_b = True
        ctx = {"flag_a": True, "flag_b": True, "flag_c": False}
        result = engine.trigger("test.entity", "activate", ctx=ctx)
        assert result is True

if __name__ == "__main__":
    pytest.main([__file__, "-v"])
