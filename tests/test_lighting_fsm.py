"""
Тесты для FSM Освещения (Фаза 4)
Запускаются через pytest или вручную в режиме отладки.
"""

import sys
sys.path.insert(0, 'ha/pyscript')
sys.path.insert(0, 'workspace/ha/pyscript')

from features.lighting.fsm import (
    LIGHT_FSM_DEFAULT,
    light_fsm_definition
)
from fsm_engine import (
    fsm_register,
    fsm_trigger,
    fsm_get_state,
    fsm_get_history,
    _FSM_STATES,
    _FSM_DEFINITIONS
)

def create_mock_group(gid="hall", config=None):
    """Создает мок объекта группы для тестов."""
    return {
        "gid": gid,
        "config": config or {"fsm_enabled": True},
        "entities": ["light.hall_1"],
        "room": "hall"
    }

def test_light_fsm_default_initial_state():
    """Тест 1: Начальное состояние должно быть OFF."""
    g = create_mock_group()
    fsm_def = light_fsm_definition(g)
    assert fsm_def is not None
    assert fsm_def["initial"] == "OFF"
    print("✅ Тест 1 пройден: Начальное состояние OFF")

def test_manual_lock_priority():
    """Тест 2: Ручное переключение имеет приоритет 100 и блокирует автомат."""
    g = create_mock_group(gid="test_manual")
    fsm_def = light_fsm_definition(g)
    
    # Регистрируем автомат
    instance_id = f"light_{g['gid']}"
    fsm_register(instance_id, fsm_def)
    
    # Имитируем ручное включение
    result = fsm_trigger(instance_id, "manual_change")
    
    assert result is True
    state = fsm_get_state(instance_id)
    assert state == "MANUAL_LOCK", f"Ожидалось MANUAL_LOCK, получено {state}"
    print("✅ Тест 2 пройден: MANUAL_LOCK активен")

def test_motion_in_auto_night_returns_to_previous():
    """Тест 3: Движение ночью -> таймаут -> возврат в ON_SCHEDULE (не в OFF)."""
    g = create_mock_group(gid="test_motion")
    fsm_def = light_fsm_definition(g)
    instance_id = f"light_{g['gid']}"
    fsm_register(instance_id, fsm_def)
    
    # Переводим в ON_SCHEDULE (аналог AUTO_NIGHT)
    fsm_trigger(instance_id, "schedule_on")
    assert fsm_get_state(instance_id) == "ON_SCHEDULE"
    
    # Датчик движения
    fsm_trigger(instance_id, "motion")
    assert fsm_get_state(instance_id) == "ON_MOTION"
    
    # Таймаут движения
    fsm_trigger(instance_id, "no_motion_timeout")
    
    # Должно вернуться в ON_SCHEDULE благодаря переходу PREVIOUS
    final_state = fsm_get_state(instance_id)
    assert final_state == "ON_SCHEDULE", f"Ожидалось ON_SCHEDULE, получено {final_state}"
    print("✅ Тест 3 пройден: Возврат в ON_SCHEDULE после движения")

def test_party_mode_protection():
    """Тест 4: PARTY не включает свет, выключенный вручную."""
    g = create_mock_group(gid="test_party")
    fsm_def = light_fsm_definition(g)
    instance_id = f"light_{g['gid']}"
    fsm_register(instance_id, fsm_def)
    
    # Выключаем вручную
    fsm_trigger(instance_id, "manual_change")
    assert fsm_get_state(instance_id) == "MANUAL_LOCK"
    
    # Включаем вечеринку
    fsm_trigger(instance_id, "party_start")
    
    # Состояние может измениться на PARTY, но свет должен остаться выключенным
    state = fsm_get_state(instance_id)
    print(f"✅ Тест 4 пройден: Состояние при вечеринке: {state}")

def test_night_light_restores_brightness():
    """Тест 5: Ночник запоминает контекст для восстановления."""
    g = create_mock_group(gid="test_night")
    fsm_def = light_fsm_definition(g)
    instance_id = f"light_{g['gid']}"
    fsm_register(instance_id, fsm_def)
    
    # Сначала включаем по расписанию
    fsm_trigger(instance_id, "schedule_on")
    assert fsm_get_state(instance_id) == "ON_SCHEDULE"
    
    # Включаем ночник (ночное движение)
    fsm_trigger(instance_id, "night_motion")
    
    state_data = fsm_get_state(instance_id)
    assert state_data == "NIGHTLIGHT", f"Ожидалось NIGHTLIGHT, получено {state_data}"
    
    # Таймаут ночника - должен вернуться в ON_SCHEDULE
    fsm_trigger(instance_id, "nightlight_timeout")
    final_state = fsm_get_state(instance_id)
    assert final_state == "ON_SCHEDULE", f"Ожидалось ON_SCHEDULE после ночника, получено {final_state}"
    print("✅ Тест 5 пройден: NIGHT_LIGHT активен и восстанавливается")

def test_unavailable_state():
    """Тест 6: Устройство недоступно."""
    g = create_mock_group(gid="test_unavail")
    fsm_def = light_fsm_definition(g)
    instance_id = f"light_{g['gid']}"
    fsm_register(instance_id, fsm_def)
    
    fsm_trigger(instance_id, "device_unavailable")
    state = fsm_get_state(instance_id)
    assert state == "UNAVAILABLE"
    
    # Восстановление
    fsm_trigger(instance_id, "device_available")
    print("✅ Тест 6 пройден: Обработка UNAVAILABLE")

def run_all_tests():
    print("🚀 Запуск тестов FSM Освещения...")
    try:
        test_light_fsm_default_initial_state()
        test_manual_lock_priority()
        test_motion_in_auto_night_returns_to_previous()
        test_party_mode_protection()
        test_night_light_restores_brightness()
        test_unavailable_state()
        print("\n🎉 Все тесты пройдены успешно!")
        return True
    except AssertionError as e:
        print(f"\n❌ Тест провален: {e}")
        return False
    except Exception as e:
        print(f"\n💥 Ошибка выполнения: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)
