"""
Тесты для Ventilation FSM (features/ventilation/fsm.py)
Проверка состояний: NORMAL, BOOST, NIGHT, AWAY, WINTER_PAUSE, MANUAL_LOCK
Использует универсальный движок из ha/pyscript/fsm_engine.py
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from features.ventilation.fsm import (
    VENTILATION_FSM_DEFAULT,
    ventilation_fsm_definition,
    ventilation_fsm_run,
    ventilation_fsm_get_state,
    _vent_fsm_build_events,
    CO2_BOOST_THRESHOLD,
    HUMIDITY_BOOST_THRESHOLD,
    CO2_CRITICAL,
    WINTER_PAUSE_TEMP_OUTDOOR,
)


def build_vent_ctx(
    co2_level=600,
    humidity=45,
    outdoor_temp=15.0,
    indoor_temp=22.0,
    manual_mode=False,
    override_remaining_min=0,
    heating_lockout=False,
    is_night=False,
    room_context="HOME_DAY",
    boost_remaining_min=0,
):
    """Вспомогательная функция для построения контекста."""
    return {
        "co2_level": co2_level,
        "humidity": humidity,
        "outdoor_temperature": outdoor_temp,
        "indoor_temperature": indoor_temp,
        "manual_mode": manual_mode,
        "override_remaining_min": override_remaining_min,
        "heating_lockout": heating_lockout,
        "is_night": is_night,
        "room_context": room_context,
        "boost_remaining_min": boost_remaining_min,
    }


def test_initial_state_normal():
    """Начальное состояние должно быть NORMAL при нормальных условиях."""
    device_id = "test_vent_init"
    ctx = build_vent_ctx(co2_level=600, humidity=45)
    
    result = ventilation_fsm_run(device_id, ctx)
    
    assert result is not None, "FSM не вернул результат"
    assert result["state"] in ["NORMAL", "NIGHT"], f"Неожиданное состояние: {result['state']}"
    print("✅ test_initial_state_normal passed")


def test_boost_on_high_co2():
    """При высоком CO2 должен запускаться BOOST."""
    device_id = "test_vent_boost_co2"
    ctx = build_vent_ctx(co2_level=CO2_BOOST_THRESHOLD + 1, humidity=45)
    
    result = ventilation_fsm_run(device_id, ctx)
    
    assert result is not None, "FSM не вернул результат"
    assert result["state"] == "BOOST", f"Ожидалось BOOST, получено {result['state']}"
    assert result["action"]["preset"] == "Приток MAX", "Должен быть режим BOOST"
    print("✅ test_boost_on_high_co2 passed")


def test_boost_on_high_humidity():
    """При высокой влажности должен запускаться BOOST."""
    device_id = "test_vent_boost_humid"
    ctx = build_vent_ctx(co2_level=600, humidity=HUMIDITY_BOOST_THRESHOLD + 1)
    
    result = ventilation_fsm_run(device_id, ctx)
    
    assert result is not None, "FSM не вернул результат"
    assert result["state"] == "BOOST", f"Ожидалось BOOST, получено {result['state']}"
    print("✅ test_boost_on_high_humidity passed")


def test_night_mode_on_schedule():
    """Ночью должен быть режим NIGHT."""
    device_id = "test_vent_night"
    ctx = build_vent_ctx(co2_level=600, humidity=45, is_night=True)
    
    result = ventilation_fsm_run(device_id, ctx)
    
    assert result is not None, "FSM не вернул результат"
    assert result["state"] == "NIGHT", f"Ожидалось NIGHT, получено {result['state']}"
    assert result["action"]["pct"] == 10, "Ночной режим должен быть 10%"
    print("✅ test_night_mode_on_schedule passed")


def test_away_mode_when_empty():
    """В режиме EMPTY должен быть AWAY."""
    device_id = "test_vent_away"
    ctx = build_vent_ctx(co2_level=600, humidity=45, room_context="EMPTY")
    
    result = ventilation_fsm_run(device_id, ctx)
    
    assert result is not None, "FSM не вернул результат"
    assert result["state"] == "AWAY", f"Ожидалось AWAY, получено {result['state']}"
    assert result["action"]["pct"] == 20, "Режим AWAY должен быть 20%"
    print("✅ test_away_mode_when_empty passed")


def test_winter_pause_on_cold():
    """При очень низкой температуре должна быть зимняя пауза."""
    device_id = "test_vent_winter"
    ctx = build_vent_ctx(co2_level=600, humidity=45, outdoor_temp=WINTER_PAUSE_TEMP_OUTDOOR - 1)
    
    result = ventilation_fsm_run(device_id, ctx)
    
    assert result is not None, "FSM не вернул результат"
    assert result["state"] == "WINTER_PAUSE", f"Ожидалось WINTER_PAUSE, получено {result['state']}"
    print("✅ test_winter_pause_on_cold passed")


def test_manual_lock_on_override():
    """При ручном вмешательстве должна быть блокировка автоматики."""
    device_id = "test_vent_manual"
    ctx = build_vent_ctx(co2_level=600, humidity=45, manual_mode=True, override_remaining_min=30)
    
    result = ventilation_fsm_run(device_id, ctx)
    
    assert result is not None, "FSM не вернул результат"
    assert result["state"] == "MANUAL_LOCK", f"Ожидалось MANUAL_LOCK, получено {result['state']}"
    print("✅ test_manual_lock_on_override passed")


def test_priority_manual_over_boost():
    """Приоритет ручного режима выше чем boost."""
    device_id = "test_vent_priority"
    
    # Высокий CO2 (нужен boost) И ручной режим
    ctx = build_vent_ctx(co2_level=CO2_BOOST_THRESHOLD + 1, manual_mode=True, override_remaining_min=30)
    
    result = ventilation_fsm_run(device_id, ctx)
    
    assert result is not None, "FSM не вернул результат"
    assert result["state"] == "MANUAL_LOCK", f"Ожидалось MANUAL_LOCK (приоритет 100), получено {result['state']}"
    print("✅ test_priority_manual_over_boost passed")


def test_boost_to_normal_on_co2_drop():
    """После снижения CO2 должен быть возврат из BOOST в NORMAL."""
    device_id = "test_vent_boost_normal"
    
    # Сначала запускаем BOOST
    ctx = build_vent_ctx(co2_level=CO2_BOOST_THRESHOLD + 1, humidity=45)
    result = ventilation_fsm_run(device_id, ctx)
    assert result["state"] == "BOOST", "Должен быть BOOST"
    
    # Теперь CO2 снизился
    ctx = build_vent_ctx(co2_level=600, humidity=45)
    result = ventilation_fsm_run(device_id, ctx)
    
    assert result["state"] == "NORMAL", f"Ожидалось NORMAL, получено {result['state']}"
    print("✅ test_boost_to_normal_on_co2_drop passed")


if __name__ == "__main__":
    print("🚀 Запуск тестов Ventilation FSM...\n")
    test_initial_state_normal()
    test_boost_on_high_co2()
    test_boost_on_high_humidity()
    test_night_mode_on_schedule()
    test_away_mode_when_empty()
    test_winter_pause_on_cold()
    test_manual_lock_on_override()
    test_priority_manual_over_boost()
    test_boost_to_normal_on_co2_drop()
    print("\n🎉 Все тесты Ventilation FSM прошли успешно!")
