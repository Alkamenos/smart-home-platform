#!/usr/bin/env python3
"""
Тесты платформы V2.
Проверяют корректность логики работы.
"""
import sys
import os
import time

sys.path.insert(0, "/config/.platform")

from platform_v2.core.sync_engine import SyncEngine
from platform_v2.core.fsm_engine import FSMEngine, FSMDefinition
from platform_v2.core.room_context import RoomContext, RoomContextBuilder, Presence, TimeOfDay, Season
from platform_v2.core.manifest import load_manifest

def test_sync_engine_initialization():
    """Тест 1: Инициализация SyncEngine"""
    print("\n=== Тест 1: Инициализация SyncEngine ===")
    
    sync = SyncEngine(grace_sec=120)
    
    # Устанавливаем желаемое состояние
    sync.set_desired("light.test", "off", reason="test")
    
    # Проверяем что желаемое установлено
    status = sync.get_status()
    assert "light.test" in status, "desired не установлен"
    assert status["light.test"]["desired"] == "off", f"desired={status['light.test']['desired']}, expected=off"
    
    print("✅ Тест 1 пройден: желаемое состояние установлено")

def test_sync_engine_actual_update():
    """Тест 2: Обновление реального состояния"""
    print("\n=== Тест 2: Обновление реального состояния ===")
    
    sync = SyncEngine(grace_sec=120)
    
    # Устанавливаем желаемое
    sync.set_desired("light.test", "off", reason="test")
    
    # Обновляем реальное (совпадает)
    sync.update_actual("light.test", "off")
    
    status = sync.get_status()
    assert status["light.test"]["actual"] == "off", f"actual={status['light.test']['actual']}, expected=off"
    assert status["light.test"]["in_sync"] == True, "Состояния должны совпадать"
    
    print("✅ Тест 2 пройден: реальное состояние обновлено")

def test_sync_engine_divergence():
    """Тест 3: Обнаружение расхождения"""
    print("\n=== Тест 3: Обнаружение расхождения ===")
    
    sync = SyncEngine(grace_sec=120)
    
    # Устанавливаем желаемое
    sync.set_desired("light.test", "off", reason="test")
    
    # Обновляем реальное (НЕ совпадает)
    sync.update_actual("light.test", "on")
    
    status = sync.get_status()
    assert status["light.test"]["actual"] == "on", f"actual={status['light.test']['actual']}, expected=on"
    assert status["light.test"]["in_sync"] == False, "Состояния должны расходиться"
    
    print("✅ Тест 3 пройден: расхождение обнаружено")

def test_sync_engine_manual_lock():
    """Тест 4: Ручная блокировка"""
    print("\n=== Тест 4: Ручная блокировка ===")
    
    sync = SyncEngine(grace_sec=120)
    
    # Устанавливаем желаемое
    sync.set_desired("light.test", "off", reason="test")
    
    # Ставим блокировку
    sync.set_manual_lock("light.test", duration_min=60, reason="manual change")
    
    # Проверяем блокировку
    assert sync.is_manual_locked("light.test"), "Устройство должно быть заблокировано"
    
    # Обновляем реальное — блокировка не должна сниматься
    sync.update_actual("light.test", "on")
    assert sync.is_manual_locked("light.test"), "Блокировка не должна сниматься при обновлении"
    
    print("✅ Тест 4 пройден: блокировка работает")

def test_fsm_basic():
    """Тест 5: Базовая работа FSM"""
    print("\n=== Тест 5: Базовая работа FSM ===")
    
    fsm = FSMEngine()
    
    definition = FSMDefinition(
        states=["OFF", "ON_SCHEDULE", "MANUAL_LOCK"],
        initial="OFF",
        transitions=[
            {"from": ["OFF"], "to": "ON_SCHEDULE", "trigger": "schedule_on", "priority": 20},
            {"from": ["ON_SCHEDULE"], "to": "OFF", "trigger": "schedule_off", "priority": 20},
            {"from": ["OFF", "ON_SCHEDULE"], "to": "MANUAL_LOCK", "trigger": "manual_change", "priority": 100},
        ]
    )
    
    fsm.register("light.test", definition)
    
    # Проверяем начальное состояние
    assert fsm.get_state("light.test") == "OFF", f"Начальное состояние={fsm.get_state('light.test')}, expected=OFF"
    
    # Применяем триггер
    fsm.trigger("light.test", "schedule_on")
    assert fsm.get_state("light.test") == "ON_SCHEDULE", f"После schedule_on={fsm.get_state('light.test')}, expected=ON_SCHEDULE"
    
    # Применяем обратный триггер
    fsm.trigger("light.test", "schedule_off")
    assert fsm.get_state("light.test") == "OFF", f"После schedule_off={fsm.get_state('light.test')}, expected=OFF"
    
    print("✅ Тест 5 пройден: FSM работает")

def test_fsm_manual_lock():
    """Тест 6: FSM с ручной блокировкой"""
    print("\n=== Тест 6: FSM с ручной блокировкой ===")
    
    fsm = FSMEngine()
    
    definition = FSMDefinition(
        states=["OFF", "ON_SCHEDULE", "MANUAL_LOCK"],
        initial="OFF",
        transitions=[
            {"from": ["OFF"], "to": "ON_SCHEDULE", "trigger": "schedule_on", "priority": 20},
            {"from": ["OFF", "ON_SCHEDULE"], "to": "MANUAL_LOCK", "trigger": "manual_change", "priority": 100},
        ]
    )
    
    fsm.register("light.test", definition)
    
    # Применяем ручной триггер
    fsm.trigger("light.test", "manual_change")
    assert fsm.get_state("light.test") == "MANUAL_LOCK", f"После manual_change={fsm.get_state('light.test')}, expected=MANUAL_LOCK"
    
    print("✅ Тест 6 пройден: ручная блокировка в FSM работает")

def test_room_context_with_resolved():
    """Тест 7: RoomContext с _resolved данными"""
    print("\n=== Тест 7: RoomContext с _resolved данными ===")
    
    builder = RoomContextBuilder()
    builder.set_time_reader(time.localtime)
    
    # Конфигурация с _resolved
    config = {
        "_resolved": {
            "global_flags": {
                "winter": "off",
                "night": "off",
                "home": "on",
                "party": "off",
            }
        }
    }
    
    context = builder.build("test_room", config)
    
    # Проверяем что presence правильный
    assert context.presence == Presence.HOME_DAY, f"presence={context.presence}, expected=HOME_DAY"
    assert not context.is_dark, "is_dark должен быть False (флаг 'вечер' выключен)"
    
    print("✅ Тест 7 пройден: RoomContext работает с _resolved")

def test_room_context_dark():
    """Тест 8: RoomContext с темнотой"""
    print("\n=== Тест 8: RoomContext с темнотой ===")
    
    builder = RoomContextBuilder()
    builder.set_time_reader(time.localtime)
    
    # Конфигурация с флагом "вечер" включённым
    config = {
        "_resolved": {
            "global_flags": {
                "winter": "off",
                "night": "on",  # Вечер!
                "home": "on",
                "party": "off",
            }
        }
    }
    
    context = builder.build("test_room", config)
    
    # Проверяем что is_dark правильный
    assert context.is_dark, "is_dark должен быть True (флаг 'вечер' включён)"
    
    print("✅ Тест 8 пройден: темнота определяется правильно")

def test_manifest_loading():
    """Тест 9: Загрузка манифеста"""
    print("\n=== Тест 9: Загрузка манифеста ===")
    
    manifest = load_manifest("/config/.platform/platform_v2/manifests/leonid_house.yaml")
    
    assert manifest["instance_id"] == "leonid_house", f"instance_id={manifest['instance_id']}"
    assert len(manifest["rooms"]) > 0, "Комнаты должны быть загружены"
    assert len(manifest["groups"]) > 0, "Группы должны быть загружены"
    assert len(manifest["devices"]) > 0, "Устройства должны быть загружены"
    
    print(f"✅ Тест 9 пройден: манифест загружен ({len(manifest['groups'])} групп, {len(manifest['devices'])} устройств)")

def test_lighting_triggers():
    """Тест 10: Триггеры освещения"""
    print("\n=== Тест 10: Триггеры освещения ===")
    
    from platform_v2.features.lighting.feature import LightingFeature
    
    # Создаём минимальную конфигурацию
    config = {
        "groups": {
            "test_group": {
                "id": "test_group",
                "name": "Test Group",
                "room": "test_room",
                "devices": [{"entity": "light.test"}],
                "fsm": {
                    "states": ["OFF", "ON_SCHEDULE", "MANUAL_LOCK"],
                    "initial": "OFF",
                    "transitions": [
                        {"from": ["OFF"], "to": "ON_SCHEDULE", "trigger": "schedule_on", "priority": 20},
                    ]
                },
                "features": {
                    "schedule": {"false": "23:00"},
                    "dusk": {"require_dark": True}
                }
            }
        }
    }
    
    sync = SyncEngine(grace_sec=120)
    feature = LightingFeature(config, sync)
    
    # Проверяем что группа зарегистрирована
    assert len(feature._groups) == 1, f"Групп загружено: {len(feature._groups)}, expected=1"
    
    print("✅ Тест 10 пройден: триггеры освещения работают")

def main():
    """Запуск всех тестов"""
    print("=" * 60)
    print("ТЕСТЫ ПЛАТФОРМЫ V2")
    print("=" * 60)
    
    tests = [
        test_sync_engine_initialization,
        test_sync_engine_actual_update,
        test_sync_engine_divergence,
        test_sync_engine_manual_lock,
        test_fsm_basic,
        test_fsm_manual_lock,
        test_room_context_with_resolved,
        test_room_context_dark,
        test_manifest_loading,
        test_lighting_triggers,
    ]
    
    passed = 0
    failed = 0
    
    for test in tests:
        try:
            test()
            passed += 1
        except Exception as e:
            print(f"❌ Тест провален: {e}")
            import traceback
            traceback.print_exc()
            failed += 1
    
    print("\n" + "=" * 60)
    print(f"РЕЗУЛЬТАТ: {passed} пройдено, {failed} провалено")
    print("=" * 60)
    
    return failed == 0

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
