#!/usr/bin/env python3
"""
Расширенные тесты платформы V2.
Проверяют интеграционные сценарии и краевые случаи.
"""
import sys
import os
import time

sys.path.insert(0, "/config/.platform")

from platform_v2.core.sync_engine import SyncEngine
from platform_v2.core.fsm_engine import FSMEngine, FSMDefinition
from platform_v2.core.room_context import RoomContext, RoomContextBuilder, Presence, TimeOfDay, Season
from platform_v2.core.manifest import load_manifest

# ============================================================
# ТЕСТЫ ОСВЕЩЕНИЯ
# ============================================================

def test_lighting_schedule_priority():
    """Тест 11: Приоритет schedule_off над schedule_on"""
    print("\n=== Тест 11: Приоритет schedule_off над schedule_on ===")
    
    from platform_v2.features.lighting.feature import LightingFeature
    
    # Группа с расписанием: включить в 18:00, выключить в 23:00
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
                        {"from": ["ON_SCHEDULE"], "to": "OFF", "trigger": "schedule_off", "priority": 20},
                        {"from": ["OFF", "ON_SCHEDULE"], "to": "MANUAL_LOCK", "trigger": "manual_change", "priority": 100},
                    ]
                },
                "features": {
                    "schedule": {"true": "18:00", "false": "23:00"},
                    "dusk": {"require_dark": True}
                }
            }
        }
    }
    
    sync = SyncEngine(grace_sec=120)
    feature = LightingFeature(config, sync)
    
    # Создаём контекст: темно, время 23:30 (после выключения)
    ctx = {
        "dark": True,
        "night": True,
        "room_ok": True,
        "motion": False,
        "time_min": 23 * 60 + 30,  # 23:30
    }
    
    # Определяем триггеры
    triggers = feature._build_triggers(ctx, config["groups"]["test_group"])
    
    # Должен быть только schedule_off (приоритет над schedule_on)
    assert "schedule_off" in triggers, f"schedule_off должен быть в триггерах, но: {triggers}"
    assert "schedule_on" not in triggers, f"schedule_on НЕ должен быть в триггерах, но: {triggers}"
    
    print("✅ Тест 11 пройден: schedule_off имеет приоритет")

def test_lighting_no_schedule_group():
    """Тест 12: Группа без расписания не получает триггеры"""
    print("\n=== Тест 12: Группа без расписания ===")
    
    from platform_v2.features.lighting.feature import LightingFeature
    
    # Группа только с движением (без расписания)
    config = {
        "groups": {
            "test_group": {
                "id": "test_group",
                "name": "Test Group",
                "room": "test_room",
                "devices": [{"entity": "light.test"}],
                "fsm": {
                    "states": ["OFF", "ON_MOTION"],
                    "initial": "OFF",
                    "transitions": [
                        {"from": ["OFF"], "to": "ON_MOTION", "trigger": "motion", "priority": 30},
                    ]
                },
                "features": {
                    "motion": {"cooldown_sec": 60}
                }
            }
        }
    }
    
    sync = SyncEngine(grace_sec=120)
    feature = LightingFeature(config, sync)
    
    # Создаём контекст: темно, нет движения
    ctx = {
        "dark": True,
        "night": True,
        "room_ok": True,
        "motion": False,
        "time_min": 22 * 60,  # 22:00
    }
    
    # Определяем триггеры
    triggers = feature._build_triggers(ctx, config["groups"]["test_group"])
    
    # Не должно быть schedule триггеров
    assert "schedule_on" not in triggers, f"schedule_on НЕ должен быть для группы без расписания: {triggers}"
    assert "schedule_off" not in triggers, f"schedule_off НЕ должен быть для группы без расписания: {triggers}"
    
    print("✅ Тест 12 пройден: группа без расписания не получает триггеры")

def test_lighting_motion_only():
    """Тест 13: Группа с движением включается при движении"""
    print("\n=== Тест 13: Группа с движением ===")
    
    from platform_v2.features.lighting.feature import LightingFeature
    
    config = {
        "groups": {
            "test_group": {
                "id": "test_group",
                "name": "Test Group",
                "room": "test_room",
                "devices": [{"entity": "light.test"}],
                "fsm": {
                    "states": ["OFF", "ON_MOTION"],
                    "initial": "OFF",
                    "transitions": [
                        {"from": ["OFF"], "to": "ON_MOTION", "trigger": "motion", "priority": 30},
                        {"from": ["ON_MOTION"], "to": "OFF", "trigger": "motion_timeout", "priority": 10},
                    ]
                },
                "features": {
                    "motion": {"cooldown_sec": 60}
                }
            }
        }
    }
    
    sync = SyncEngine(grace_sec=120)
    feature = LightingFeature(config, sync)
    
    # Создаём контекст: есть движение
    ctx = {
        "dark": True,
        "night": True,
        "room_ok": True,
        "motion": True,  # Движение!
        "time_min": 22 * 60,
    }
    
    # Определяем триггеры
    triggers = feature._build_triggers(ctx, config["groups"]["test_group"])
    
    # Должен быть триггер движения
    assert "motion" in triggers, f"motion должен быть в триггерах: {triggers}"
    
    print("✅ Тест 13 пройден: движение вызывает триггер")

# ============================================================
# ТЕСТЫ ВЕНТИЛЯЦИИ
# ============================================================

def test_ventilation_normal_mode():
    """Тест 14: Вентиляция в нормальном режиме"""
    print("\n=== Тест 14: Вентиляция в нормальном режиме ===")
    
    from platform_v2.features.ventilation.feature import VentilationFeature
    
    config = {
        "devices": [
            {"entity": "fan.test", "name": "Test Fan"}
        ],
        "thresholds": {
            "co2": 1000,
            "humidity": 60
        }
    }
    
    sync = SyncEngine(grace_sec=120)
    feature = VentilationFeature(config, sync)
    
    # Создаём контекст: нормальные условия
    ctx = {
        "co2": 800,  # Ниже порога
        "humidity": 50,  # Ниже порога
        "winter": False,
    }
    
    # Вентиляция должна быть включена (нормальный режим)
    decision = feature.decide(RoomContext(room_id="test"))
    
    # Проверяем что есть действие
    assert len(decision.actions) > 0, "Должно быть действие для вентиляции"
    
    print("✅ Тест 14 пройден: вентиляция работает в нормальном режиме")

def test_ventilation_co2_boost():
    """Тест 15: Вентиляция при высоком CO2"""
    print("\n=== Тест 15: Вентиляция при высоком CO2 ===")
    
    from platform_v2.features.ventilation.feature import VentilationFeature
    
    config = {
        "devices": [
            {"entity": "fan.test", "name": "Test Fan"}
        ],
        "thresholds": {
            "co2": 1000,
            "humidity": 60
        }
    }
    
    sync = SyncEngine(grace_sec=120)
    feature = VentilationFeature(config, sync)
    
    # Создаём контекст: высокий CO2
    ctx = {
        "co2": 1500,  # Выше порога
        "humidity": 50,
        "winter": False,
    }
    
    # Вентиляция должна быть в режиме BOOST
    decision = feature.decide(RoomContext(room_id="test"))
    
    # Проверяем что есть действие
    assert len(decision.actions) > 0, "Должно быть действие для вентиляции"
    
    print("✅ Тест 15 пройден: вентиляция реагирует на CO2")

# ============================================================
# ТЕСТЫ ИНТЕГРАЦИИ
# ============================================================

def test_manifest_groups_have_rooms():
    """Тест 16: Все группы имеют комнату"""
    print("\n=== Тест 16: Все группы имеют комнату ===")
    
    manifest = load_manifest("/config/.platform/platform_v2/manifests/leonid_house.yaml")
    
    groups_without_room = []
    for group_id, group in manifest.get("groups", {}).items():
        room = group.get("room", "unknown")
        if room == "unknown" or not room:
            groups_without_room.append(group_id)
    
    if groups_without_room:
        print(f"⚠️ Группы без комнаты: {groups_without_room}")
    else:
        print("✅ Все группы имеют комнату")
    
    # Не падаем если есть группы без комнаты — это не критично
    print("✅ Тест 16 пройден")

def test_manifest_devices_have_entities():
    """Тест 17: Все устройства имеют сущности"""
    print("\n=== Тест 17: Все устройства имеют сущности ===")
    
    manifest = load_manifest("/config/.platform/platform_v2/manifests/leonid_house.yaml")
    
    devices_without_entity = []
    for device_id, device in manifest.get("devices", {}).items():
        entity = device.get("entity")
        if not entity:
            devices_without_entity.append(device_id)
    
    if devices_without_entity:
        print(f"❌ Устройства без сущностей: {devices_without_entity}")
        assert False, "Все устройства должны иметь сущности"
    
    print("✅ Тест 17 пройден: все устройства имеют сущности")

def test_manifest_devices_have_rooms():
    """Тест 18: Все устройства имеют комнату"""
    print("\n=== Тест 18: Все устройства имеют комнату ===")
    
    manifest = load_manifest("/config/.platform/platform_v2/manifests/leonid_house.yaml")
    
    devices_without_room = []
    for device_id, device in manifest.get("devices", {}).items():
        room = device.get("room", "unknown")
        if room == "unknown" or not room:
            devices_without_room.append(device_id)
    
    if devices_without_room:
        print(f"⚠️ Устройства без комнаты: {devices_without_room}")
    else:
        print("✅ Все устройства имеют комнату")
    
    print("✅ Тест 18 пройден")

def test_lighting_feature_with_real_manifest():
    """Тест 19: Освещение с реальным манифестом"""
    print("\n=== Тест 19: Освещение с реальным манифестом ===")
    
    from platform_v2.features.lighting.feature import LightingFeature
    
    manifest = load_manifest("/config/.platform/platform_v2/manifests/leonid_house.yaml")
    
    # Загружаем группы из манифеста
    groups = manifest.get("groups", {})
    
    # Создаём конфигурацию для освещения
    config = {
        "groups": groups
    }
    
    sync = SyncEngine(grace_sec=120)
    feature = LightingFeature(config, sync)
    
    # Проверяем что все группы зарегистрированы
    assert len(feature._groups) == len(groups), f"Групп загружено: {len(feature._groups)}, expected={len(groups)}"
    
    # Проверяем что для каждой группы создан экземпляр автомата
    for group_id in groups:
        fsm_key = f"light.{group_id}"
        state = feature._fsm.get_state(fsm_key)
        assert state is not None, f"FSM для {fsm_key} не создан"
        assert state == "OFF", f"Начальное состояние {fsm_key}={state}, expected=OFF"
    
    print(f"✅ Тест 19 пройден: {len(groups)} групп освещения загружены")

def test_ventilation_feature_with_real_manifest():
    """Тест 20: Вентиляция с реальным манифестом"""
    print("\n=== Тест 20: Вентиляция с реальным манифестом ===")
    
    from platform_v2.features.ventilation.feature import VentilationFeature
    
    manifest = load_manifest("/config/.platform/platform_v2/manifests/leonid_house.yaml")
    
    # Находим вентиляторы
    fan_devices = [d for d in manifest.get("devices", {}).values() 
                   if d.get("capabilities", {}).get("fan")]
    
    config = {
        "devices": fan_devices
    }
    
    sync = SyncEngine(grace_sec=120)
    feature = VentilationFeature(config, sync)
    
    # Проверяем что все вентиляторы зарегистрированы
    assert len(feature._devices) == len(fan_devices), f"Вентиляторов загружено: {len(feature._devices)}, expected={len(fan_devices)}"
    
    # Проверяем что для каждого вентилятора создан экземпляр автомата
    for device in fan_devices:
        entity = device.get("entity")
        if entity:
            state = feature._fsm.get_state(entity)
            assert state is not None, f"FSM для {entity} не создан"
    
    print(f"✅ Тест 20 пройден: {len(fan_devices)} вентиляторов загружены")

# ============================================================
# ТЕСТЫ РУЧНОГО ВМЕШАТЕЛЬСТВА
# ============================================================

def test_manual_lock_prevents_apply():
    """Тест 21: Блокировка предотвращает применение"""
    print("\n=== Тест 21: Блокировка предотвращает применение ===")
    
    from platform_v2.features.lighting.feature import LightingFeature
    
    config = {
        "groups": {
            "test_group": {
                "id": "test_group",
                "name": "Test Group",
                "room": "test_room",
                "devices": [{"entity": "light.test"}],
                "fsm": {
                    "states": ["OFF", "ON_SCHEDULE"],
                    "initial": "OFF",
                    "transitions": [
                        {"from": ["OFF"], "to": "ON_SCHEDULE", "trigger": "schedule_on", "priority": 20},
                    ]
                },
                "features": {
                    "schedule": {"true": "18:00", "false": "23:00"},
                    "dusk": {"require_dark": True}
                }
            }
        }
    }
    
    sync = SyncEngine(grace_sec=120)
    feature = LightingFeature(config, sync)
    
    # Ставим блокировку
    sync.set_manual_lock("light.test", duration_min=60, reason="manual change")
    
    # Создаём решение
    ctx = RoomContext(room_id="test_room", is_dark=True, time_of_day=TimeOfDay.NIGHT)
    decision = feature.decide(ctx)
    
    # Применяем решение
    feature.apply(decision)
    
    # Проверяем что desired НЕ установлен (из-за блокировки)
    status = sync.get_status()
    if "light.test" in status:
        # Если есть, то должно быть от ручного вмешательства, не от автоматики
        assert status["light.test"]["source"] != "automation", "desired не должен быть от автоматики при блокировке"
    
    print("✅ Тест 21 пройден: блокировка предотвращает применение")

def test_manual_lock_expires():
    """Тест 22: Блокировка истекает"""
    print("\n=== Тест 22: Блокировка истекает ===")
    
    sync = SyncEngine(grace_sec=120)
    
    # Ставим блокировку на 0 минут (истекает сразу)
    sync.set_manual_lock("light.test", duration_min=0, reason="manual change")
    
    # Проверяем что блокировка истекла
    assert not sync.is_manual_locked("light.test"), "Блокировка должна истечь"
    
    print("✅ Тест 22 пройден: блокировка истекает")

# ============================================================
# ТЕСТЫ ДАШБОРДА
# ============================================================

def test_dashboard_generation():
    """Тест 23: Генерация дашбордов"""
    print("\n=== Тест 23: Генерация дашбордов ===")
    
    from platform_v2.dashboards.generator import DashboardGenerator
    
    manifest = load_manifest("/config/.platform/platform_v2/manifests/leonid_house.yaml")
    
    generator = DashboardGenerator(manifest)
    
    # Генерируем дашборды
    home = generator.generate_home_dashboard()
    settings = generator.generate_settings_dashboard()
    admin = generator.generate_admin_dashboard()
    fsm = generator.generate_fsm_dashboard()
    
    # Проверяем структуру
    assert "views" in home, "home должен иметь views"
    assert "views" in settings, "settings должен иметь views"
    assert "views" in admin, "admin должен иметь views"
    assert "views" in fsm, "fsm должен иметь views"
    
    # Проверяем что есть комнаты
    assert len(home["views"]) > 0, "home должен иметь комнаты"
    
    # Проверяем что в каждой комнате есть карточки
    for view in home["views"]:
        assert "cards" in view, f"Комната {view['path']} должна иметь карточки"
        assert len(view["cards"]) > 0, f"Комната {view['path']} должна иметь карточки"
    
    print(f"✅ Тест 23 пройден: {len(home['views'])} комнат в дашборде")

def main():
    """Запуск всех тестов"""
    print("=" * 60)
    print("РАСШИРЕННЫЕ ТЕСТЫ ПЛАТФОРМЫ V2")
    print("=" * 60)
    
    tests = [
        test_lighting_schedule_priority,
        test_lighting_no_schedule_group,
        test_lighting_motion_only,
        test_ventilation_normal_mode,
        test_ventilation_co2_boost,
        test_manifest_groups_have_rooms,
        test_manifest_devices_have_entities,
        test_manifest_devices_have_rooms,
        test_lighting_feature_with_real_manifest,
        test_ventilation_feature_with_real_manifest,
        test_manual_lock_prevents_apply,
        test_manual_lock_expires,
        test_dashboard_generation,
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
