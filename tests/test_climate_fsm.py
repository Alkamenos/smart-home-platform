"""
Тесты для Climate FSM (features/climate/fsm.py)
Проверка состояний: IDLE, HEATING, COOLING, SAFETY_LOCKOUT, MANUAL_LOCK
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from features.climate.fsm import (
    CLIMATE_FSM_DEFAULT, 
    evaluate_guards,
    build_context,
    get_guard_function,
    guard_needs_heating,
    guard_needs_cooling,
    guard_safety_violation,
    guard_manual_override_active,
)

def test_guard_needs_heating():
    """Проверка guardNeedsHeating - температура ниже уставки"""
    ctx = build_context("zone1", current_temp=18.0, target_temp=22.0)
    assert guard_needs_heating(ctx) == True, "Должен требоваться нагрев"
    
    ctx = build_context("zone1", current_temp=23.0, target_temp=22.0)
    assert guard_needs_heating(ctx) == False, "Нагрев не требуется"
    print("✅ test_guard_needs_heating passed")

def test_guard_needs_cooling():
    """Проверка guardNeedsCooling - температура выше уставки"""
    ctx = build_context("zone1", current_temp=26.0, target_temp=22.0, hvac_mode="cool")
    assert guard_needs_cooling(ctx) == True, "Должно требоваться охлаждение"
    
    ctx = build_context("zone1", current_temp=20.0, target_temp=22.0, hvac_mode="cool")
    assert guard_needs_cooling(ctx) == False, "Охлаждение не требуется"
    print("✅ test_guard_needs_cooling passed")

def test_guard_safety_violation():
    """Проверка guardSafetyViolation - sensor_error или heating_lockout"""
    ctx = build_context("zone1", current_temp=20.0, target_temp=22.0, sensor_error=True)
    assert guard_safety_violation(ctx) == True, "Должна быть ошибка сенсора"
    
    ctx = build_context("zone1", current_temp=20.0, target_temp=22.0, heating_lockout=True)
    assert guard_safety_violation(ctx) == True, "Должен быть lockout"
    
    ctx = build_context("zone1", current_temp=20.0, target_temp=22.0)
    assert guard_safety_violation(ctx) == False, "Нарушений нет"
    print("✅ test_guard_safety_violation passed")

def test_guard_manual_override_active():
    """Проверка guardManualOverrideActive - ручной режим активен + override_remaining > 0"""
    ctx = build_context("zone1", current_temp=20.0, target_temp=22.0, manual_mode=True, override_remaining_min=30)
    assert guard_manual_override_active(ctx) == True, "Ручной режим активен"
    
    ctx = build_context("zone1", current_temp=20.0, target_temp=22.0, manual_mode=False)
    assert guard_manual_override_active(ctx) == False, "Ручной режим не активен"
    
    ctx = build_context("zone1", current_temp=20.0, target_temp=22.0, manual_mode=True, override_remaining_min=0)
    assert guard_manual_override_active(ctx) == False, "Override истёк"
    print("✅ test_guard_manual_override_active passed")

def test_evaluate_guards_priority():
    """Проверка приоритетов переходов - safety выше heating"""
    transitions = [
        {"guard": "needs_heating", "priority": 20},
        {"guard": "safety_violation", "priority": 500},
    ]
    ctx = build_context("zone1", current_temp=18.0, target_temp=22.0, sensor_error=True)
    
    suitable = evaluate_guards(transitions, ctx)
    assert len(suitable) == 2, "Оба перехода доступны"
    assert suitable[0][1]["guard"] == "safety_violation", "Safety должен быть первым (приоритет 500)"
    assert suitable[1][1]["guard"] == "needs_heating", "Heating должен быть вторым"
    print("✅ test_evaluate_guards_priority passed")

def test_room_context_sleeping_setback():
    """Проверка что в режиме SLEEPING есть отдельная уставка target_temperature_sleep"""
    ctx_normal = build_context("zone1", current_temp=20.0, target_temp=22.0, room_context="HOME_DAY")
    ctx_sleep = build_context("zone1", current_temp=20.0, target_temp=22.0, room_context="SLEEPING")
    
    # В контексте должны быть разные уставки для разных режимов
    assert "target_temperature_sleep" in ctx_sleep, "Должна быть уставка для SLEEPING"
    assert ctx_sleep["target_temperature_sleep"] < ctx_normal["target_temperature"], \
        f"Уставка SLEEPING ({ctx_sleep['target_temperature_sleep']}) должна быть ниже базовой ({ctx_normal['target_temperature']})"
    print("✅ test_room_context_sleeping_setback passed")

def test_initial_state_idle():
    """Начальное состояние должно быть IDLE при нормальных условиях"""
    ctx = build_context("zone1", current_temp=21.5, target_temp=22.0)
    needs_heat = guard_needs_heating(ctx)
    needs_cool = guard_needs_cooling(ctx)
    safety = guard_safety_violation(ctx)
    manual = guard_manual_override_active(ctx)
    
    assert needs_heat == False, "Нагрев не требуется"
    assert needs_cool == False, "Охлаждение не требуется"
    assert safety == False, "Нарушений безопасности нет"
    assert manual == False, "Ручной режим не активен"
    print("✅ test_initial_state_idle passed")

if __name__ == "__main__":
    test_guard_needs_heating()
    test_guard_needs_cooling()
    test_guard_safety_violation()
    test_guard_manual_override_active()
    test_evaluate_guards_priority()
    test_room_context_sleeping_setback()
    test_initial_state_idle()
    print("\n🎉 Все тесты Climate FSM прошли успешно!")
