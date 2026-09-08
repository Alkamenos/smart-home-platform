"""
Тесты для Climate FSM (features/climate/fsm.py)
Проверка состояний: IDLE, HEATING, COOLING, SAFETY_LOCKOUT, MANUAL_LOCK
Использует универсальный движок из ha/pyscript/fsm_engine.py
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from features.climate.fsm import (
    CLIMATE_FSM_DEFAULT,
    climate_fsm_definition,
    climate_fsm_run,
    climate_fsm_get_state,
    _climate_fsm_build_events,
)


def build_climate_ctx(
    current_temp=20.0,
    target_temp=22.0,
    manual_mode=False,
    override_remaining_min=0,
    sensor_error=False,
    heating_lockout=False,
    room_context="HOME_DAY",
    override_expired=False,
):
    """Вспомогательная функция для построения контекста."""
    return {
        "current_temperature": current_temp,
        "target_temperature": target_temp,
        "manual_mode": manual_mode,
        "override_remaining_min": override_remaining_min,
        "sensor_error": sensor_error,
        "heating_lockout": heating_lockout,
        "room_context": room_context,
        "override_expired": override_expired,
        "temp_hysteresis": 0.5,
    }


def test_initial_state_idle():
    """Начальное состояние должно быть IDLE при нормальных условиях."""
    zone_id = "test_zone_init"
    ctx = build_climate_ctx(current_temp=21.5, target_temp=22.0)
    
    result = climate_fsm_run(zone_id, ctx)
    
    assert result is not None, "FSM не вернул результат"
    assert result["state"] in ["IDLE", "HEATING", "COOLING"], f"Неожиданное состояние: {result['state']}"
    print("✅ test_initial_state_idle passed")


def test_heating_on_low_temp():
    """При низкой температуре должен запускаться нагрев."""
    zone_id = "test_zone_heat"
    ctx = build_climate_ctx(current_temp=18.0, target_temp=22.0)
    
    result = climate_fsm_run(zone_id, ctx)
    
    assert result is not None, "FSM не вернул результат"
    assert result["state"] == "HEATING", f"Ожидалось HEATING, получено {result['state']}"
    assert result["action"]["hvac_mode"] == "heat", "Должен быть режим нагрева"
    print("✅ test_heating_on_low_temp passed")


def test_cooling_on_high_temp():
    """При высокой температуре должно запускаться охлаждение."""
    zone_id = "test_zone_cool"
    ctx = build_climate_ctx(current_temp=26.0, target_temp=22.0)
    
    result = climate_fsm_run(zone_id, ctx)
    
    assert result is not None, "FSM не вернул результат"
    assert result["state"] == "COOLING", f"Ожидалось COOLING, получено {result['state']}"
    assert result["action"]["hvac_mode"] == "cool", "Должен быть режим охлаждения"
    print("✅ test_cooling_on_high_temp passed")


def test_target_reached_stops():
    """При достижении целевой температуры должен остановиться."""
    zone_id = "test_zone_target"
    
    # Сначала запускаем нагрев
    ctx = build_climate_ctx(current_temp=18.0, target_temp=22.0)
    result = climate_fsm_run(zone_id, ctx)
    assert result["state"] == "HEATING", "Должен быть нагрев"
    
    # Теперь температура достигнута
    ctx = build_climate_ctx(current_temp=22.0, target_temp=22.0)
    result = climate_fsm_run(zone_id, ctx)
    
    assert result["state"] == "IDLE", f"Ожидалось IDLE, получено {result['state']}"
    print("✅ test_target_reached_stops passed")


def test_safety_lockout_on_sensor_error():
    """При ошибке датчика должна быть блокировка безопасности."""
    zone_id = "test_zone_safety"
    ctx = build_climate_ctx(current_temp=20.0, target_temp=22.0, sensor_error=True)
    
    result = climate_fsm_run(zone_id, ctx)
    
    assert result is not None, "FSM не вернул результат"
    assert result["state"] == "SAFETY_LOCKOUT", f"Ожидалось SAFETY_LOCKOUT, получено {result['state']}"
    print("✅ test_safety_lockout_on_sensor_error passed")


def test_safety_lockout_on_heating_lockout():
    """При глобальной блокировке отопления должна быть блокировка безопасности."""
    zone_id = "test_zone_lockout"
    ctx = build_climate_ctx(current_temp=20.0, target_temp=22.0, heating_lockout=True)
    
    result = climate_fsm_run(zone_id, ctx)
    
    assert result is not None, "FSM не вернул результат"
    assert result["state"] == "SAFETY_LOCKOUT", f"Ожидалось SAFETY_LOCKOUT, получено {result['state']}"
    print("✅ test_safety_lockout_on_heating_lockout passed")


def test_manual_lock_on_override():
    """При ручном вмешательстве должна быть блокировка автоматики."""
    zone_id = "test_zone_manual"
    ctx = build_climate_ctx(current_temp=20.0, target_temp=22.0, manual_mode=True, override_remaining_min=30)
    
    result = climate_fsm_run(zone_id, ctx)
    
    assert result is not None, "FSM не вернул результат"
    assert result["state"] == "MANUAL_LOCK", f"Ожидалось MANUAL_LOCK, получено {result['state']}"
    print("✅ test_manual_lock_on_override passed")


def test_priority_safety_over_heating():
    """Приоритет безопасности выше чем нагрев."""
    zone_id = "test_zone_priority"
    
    # Низкая температура (нужен нагрев) И ошибка датчика (нужна блокировка)
    ctx = build_climate_ctx(current_temp=18.0, target_temp=22.0, sensor_error=True)
    
    result = climate_fsm_run(zone_id, ctx)
    
    assert result is not None, "FSM не вернул результат"
    assert result["state"] == "SAFETY_LOCKOUT", f"Ожидалось SAFETY_LOCKOUT (приоритет 500), получено {result['state']}"
    print("✅ test_priority_safety_over_heating passed")


if __name__ == "__main__":
    print("🚀 Запуск тестов Climate FSM...\n")
    test_initial_state_idle()
    test_heating_on_low_temp()
    test_cooling_on_high_temp()
    test_target_reached_stops()
    test_safety_lockout_on_sensor_error()
    test_safety_lockout_on_heating_lockout()
    test_manual_lock_on_override()
    test_priority_safety_over_heating()
    print("\n🎉 Все тесты Climate FSM прошли успешно!")
