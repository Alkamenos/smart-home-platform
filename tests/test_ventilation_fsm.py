"""
Тесты для Ventilation FSM (features/ventilation/fsm.py)
Проверка состояний: NORMAL, BOOST, NIGHT, AWAY, WINTER_PAUSE, MANUAL_LOCK
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from features.ventilation.fsm import (
    VENTILATION_FSM_DEFAULT,
    evaluate_guards,
    STATE_VENT_NORMAL,
    STATE_VENT_BOOST,
    STATE_VENT_NIGHT,
    STATE_VENT_AWAY,
    STATE_VENT_MANUAL_LOCK,
    guard_high_co2_or_humidity,
    guard_night_schedule,
    guard_away_mode,
    CO2_BOOST_THRESHOLD,
    HUMIDITY_BOOST_THRESHOLD,
)

def build_vent_ctx(
    co2_level=600,
    humidity=45,
    temp_indoor=22.0,
    temp_outdoor=15.0,
    manual_override=False,
    heating_lockout=False,
    is_night=False,
    away_mode=False,
    room_context="HOME_DAY",
):
    """Вспомогательная функция для построения контекста."""
    return {
        "co2_level": co2_level,
        "humidity": humidity,
        "indoor_temperature": temp_indoor,
        "outdoor_temperature": temp_outdoor,
        "manual_mode": manual_override,
        "override_remaining_min": 60 if manual_override else 0,
        "heating_lockout": heating_lockout,
        "is_night": is_night,
        "away_mode": away_mode,
        "room_context": room_context,
        "winter_pause_timer_expired": True,
    }

def test_initial_state_normal():
    """Тест 1: Начальное состояние NORMAL (нет активных переходов)"""
    ctx = build_vent_ctx()
    transitions = VENTILATION_FSM_DEFAULT["transitions"]
    normal_transitions = [t for t in transitions if t.get("from") == STATE_VENT_NORMAL]
    suitable = evaluate_guards(normal_transitions, ctx)
    
    assert len(suitable) == 0, f"Ожидалось 0 переходов, получено {len(suitable)}"
    print("✅ Тест 1 пройден: Начальное состояние NORMAL")

def test_boost_on_high_co2():
    """Тест 2: Переход в BOOST при высоком CO2"""
    ctx = build_vent_ctx(co2_level=1200, humidity=45)
    transitions = VENTILATION_FSM_DEFAULT["transitions"]
    normal_transitions = [t for t in transitions if t.get("from") == STATE_VENT_NORMAL]
    suitable = evaluate_guards(normal_transitions, ctx)
    
    boost_transition = [t for t in suitable if t[1].get("to") == STATE_VENT_BOOST]
    assert len(boost_transition) > 0, f"Ожидался переход в {STATE_VENT_BOOST}"
    print("✅ Тест 2 пройден: BOOST при высоком CO2")

def test_boost_on_high_humidity():
    """Тест 3: Переход в BOOST при высокой влажности"""
    ctx = build_vent_ctx(co2_level=600, humidity=75)
    transitions = VENTILATION_FSM_DEFAULT["transitions"]
    normal_transitions = [t for t in transitions if t.get("from") == STATE_VENT_NORMAL]
    suitable = evaluate_guards(normal_transitions, ctx)
    
    boost_transition = [t for t in suitable if t[1].get("to") == STATE_VENT_BOOST]
    assert len(boost_transition) > 0, f"Ожидался переход в {STATE_VENT_BOOST}"
    print("✅ Тест 3 пройден: BOOST при высокой влажности")

def test_night_mode():
    """Тест 4: Переход в NIGHT ночью"""
    ctx = build_vent_ctx(is_night=True, co2_level=600, humidity=45)
    transitions = VENTILATION_FSM_DEFAULT["transitions"]
    normal_transitions = [t for t in transitions if t.get("from") == STATE_VENT_NORMAL]
    suitable = evaluate_guards(normal_transitions, ctx)
    
    night_transition = [t for t in suitable if t[1].get("to") == STATE_VENT_NIGHT]
    assert len(night_transition) > 0, f"Ожидался переход в {STATE_VENT_NIGHT}"
    print("✅ Тест 4 пройден: NIGHT ночью")

def test_away_mode():
    """Тест 5: Переход в AWAY когда room_context=EMPTY"""
    ctx = build_vent_ctx(room_context="EMPTY")
    transitions = VENTILATION_FSM_DEFAULT["transitions"]
    normal_transitions = [t for t in transitions if t.get("from") == STATE_VENT_NORMAL]
    suitable = evaluate_guards(normal_transitions, ctx)
    
    away_transition = [t for t in suitable if t[1].get("to") == STATE_VENT_AWAY]
    assert len(away_transition) > 0, f"Ожидался переход в {STATE_VENT_AWAY}"
    print("✅ Тест 5 пройден: AWAY когда EMPTY")

def test_manual_lock_priority():
    """Тест 6: MANUAL_LOCK имеет высокий приоритет"""
    ctx = build_vent_ctx(manual_override=True, co2_level=1200)
    transitions = VENTILATION_FSM_DEFAULT["transitions"]
    normal_transitions = [t for t in transitions if t.get("from") == STATE_VENT_NORMAL]
    suitable = evaluate_guards(normal_transitions, ctx)
    
    assert suitable[0][1].get("to") == STATE_VENT_MANUAL_LOCK, "MANUAL_LOCK первый"
    print("✅ Тест 6 пройден: MANUAL_LOCK приоритет")

def test_guard_high_co2_or_humidity():
    """Тест 7: Проверка guard_high_co2_or_humidity"""
    # Пороги: CO2 > 1000 или humidity > 70
    ctx_low = build_vent_ctx(co2_level=600, humidity=45)
    assert guard_high_co2_or_humidity(ctx_low) == False
    
    ctx_co2_high = build_vent_ctx(co2_level=CO2_BOOST_THRESHOLD + 1, humidity=45)
    assert guard_high_co2_or_humidity(ctx_co2_high) == True, f"CO2={CO2_BOOST_THRESHOLD + 1} должен триггерить"
    
    ctx_humid_high = build_vent_ctx(co2_level=600, humidity=HUMIDITY_BOOST_THRESHOLD + 1)
    assert guard_high_co2_or_humidity(ctx_humid_high) == True, f"Humidity={HUMIDITY_BOOST_THRESHOLD + 1} должна триггерить"
    print(f"✅ Тест 7 пройден: пороги CO2>{CO2_BOOST_THRESHOLD}, Humidity>{HUMIDITY_BOOST_THRESHOLD}")

def test_guard_night_schedule():
    """Тест 8: Проверка guard_night_schedule"""
    ctx_day = build_vent_ctx(is_night=False, room_context="HOME_DAY")
    assert guard_night_schedule(ctx_day) == False
    
    ctx_night = build_vent_ctx(is_night=True)
    assert guard_night_schedule(ctx_night) == True
    
    ctx_sleeping = build_vent_ctx(room_context="SLEEPING")
    assert guard_night_schedule(ctx_sleeping) == True
    print("✅ Тест 8 пройден: guard_night_schedule")

def test_guard_away_mode():
    """Тест 9: Проверка guard_away_mode"""
    ctx_home = build_vent_ctx(room_context="HOME_DAY")
    assert guard_away_mode(ctx_home) == False
    
    ctx_empty = build_vent_ctx(room_context="EMPTY")
    assert guard_away_mode(ctx_empty) == True
    print("✅ Тест 9 пройден: guard_away_mode")

if __name__ == "__main__":
    print("🚀 Запуск тестов FSM Вентиляции...\n")
    test_initial_state_normal()
    test_boost_on_high_co2()
    test_boost_on_high_humidity()
    test_night_mode()
    test_away_mode()
    test_manual_lock_priority()
    test_guard_high_co2_or_humidity()
    test_guard_night_schedule()
    test_guard_away_mode()
    print("\n🎉 Все тесты Ventilation FSM прошли успешно!")
