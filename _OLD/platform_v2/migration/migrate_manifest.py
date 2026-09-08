#!/usr/bin/env python3
"""
Скрипт миграции манифеста со старого формата на новый.

Читает instances/leonid_house/manifest.yaml
и создаёт platform_v2/manifests/leonid_house.yaml
"""
import yaml
import sys
import os

def migrate_manifest(old_path: str, new_path: str):
    """Мигрировать манифест"""
    # Читаем старый манифест
    with open(old_path, encoding="utf-8") as f:
        old = yaml.safe_load(f)
    
    # Создаём новый манифест
    new = {
        "instance_id": old.get("instance_id", "leonid_house"),
        "rooms": [],
        "devices": [],
        "groups": [],
        "features": {},
        "global_flags": {}
    }
    
    # Мигрируем комнаты
    rooms = set()
    for group in old.get("groups", []):
        room = group.get("room", group.get("zone", "unknown"))
        rooms.add(room)
    new["rooms"] = sorted(rooms)
    
    # Мигрируем устройства
    device_id_counter = 0
    for group in old.get("groups", []):
        for light_entity in group.get("lights", []):
            device_id = f"light_{device_id_counter}"
            device_id_counter += 1
            
            new["devices"].append({
                "id": device_id,
                "entity": light_entity,
                "name": light_entity.split(".")[-1].replace("_", " ").title(),
                "room": group.get("room", group.get("zone", "unknown")),
                "capabilities": {
                    "dim": True,
                    "ct": True,
                    "rgb": False
                },
                "managed_by_platform": True
            })
    
    # Мигрируем группы
    for group in old.get("groups", []):
        group_id = str(group.get("id", "group"))
        
        # Создаём FSM на основе фич группы
        fsm = None
        features = group.get("features", {})
        
        if features.get("motion"):
            # Группа с датчиком движения
            fsm = {
                "states": ["OFF", "ON_MOTION", "ON_SCHEDULE", "NIGHTLIGHT", "MANUAL_LOCK", "UNAVAILABLE"],
                "initial": "OFF",
                "debounce_sec": 2.0,
                "transitions": [
                    {
                        "from": ["OFF", "ON_SCHEDULE"],
                        "to": "ON_MOTION",
                        "trigger": "motion",
                        "guard": "room_ok and motion_mode != 'Выкл' and (dark or motion_day)",
                        "priority": 30,
                        "why": "Включение по датчику движения"
                    },
                    {
                        "from": ["ON_MOTION"],
                        "to": "OFF",
                        "trigger": "no_motion_timeout",
                        "priority": 10,
                        "why": "Выключение по таймеру отсутствия движения"
                    },
                    {
                        "from": ["OFF", "ON_SCHEDULE"],
                        "to": "NIGHTLIGHT",
                        "trigger": "night_motion",
                        "guard": "motion_mode != 'Выкл' and nightlight_enabled",
                        "priority": 35,
                        "why": "Ночник: минимальная яркость ночью"
                    },
                    {
                        "from": ["OFF", "ON_SCHEDULE", "ON_MOTION", "NIGHTLIGHT"],
                        "to": "MANUAL_LOCK",
                        "trigger": "manual_change",
                        "priority": 100,
                        "why": "Ручное вмешательство"
                    },
                    {
                        "from": ["MANUAL_LOCK"],
                        "to": "PREVIOUS",
                        "trigger": "timeout",
                        "priority": 5,
                        "why": "Таймер блокировки истёк"
                    },
                ]
            }
        else:
            # Группа без датчика движения (только расписание)
            fsm = {
                "states": ["OFF", "ON_SCHEDULE", "MANUAL_LOCK"],
                "initial": "OFF",
                "transitions": [
                    {
                        "from": ["OFF"],
                        "to": "ON_SCHEDULE",
                        "trigger": "schedule_on",
                        "guard": "room_ok and dark",
                        "priority": 20,
                        "why": "Включение по расписанию"
                    },
                    {
                        "from": ["ON_SCHEDULE"],
                        "to": "OFF",
                        "trigger": "schedule_off",
                        "priority": 20,
                        "why": "Выключение по расписанию"
                    },
                    {
                        "from": ["OFF", "ON_SCHEDULE"],
                        "to": "MANUAL_LOCK",
                        "trigger": "manual_change",
                        "priority": 100,
                        "why": "Ручное вмешательство"
                    },
                    {
                        "from": ["MANUAL_LOCK"],
                        "to": "PREVIOUS",
                        "trigger": "timeout",
                        "priority": 5,
                        "why": "Таймер блокировки истёк"
                    },
                ]
            }
        
        # Определяем устройства группы
        group_devices = []
        for i, light_entity in enumerate(group.get("lights", [])):
            group_devices.append(f"light_{i}")
        
        new["groups"].append({
            "id": group_id,
            "name": group.get("name", group_id),
            "room": group.get("room", group.get("zone", "unknown")),
            "devices": group_devices,
            "fsm": fsm,
            "features": {
                "motion": features.get("motion"),
                "nightlight": features.get("nightlight"),
                "ct": features.get("ct"),
                "schedule": features.get("schedule"),
            }
        })
    
    # Мигрируем фичи
    if old.get("lighting"):
        lighting = old["lighting"]
        new["features"]["lighting"] = {
            "enabled": lighting.get("enabled", True),
            "color_temp": lighting.get("color_temp", {}),
            "override_timeout_min": lighting.get("override_timeout_min", 60),
            "anti_cycle_min": lighting.get("anti_cycle_min", 2),
        }
    
    if old.get("ventilation"):
        vent = old["ventilation"]
        new["features"]["ventilation"] = {
            "enabled": vent.get("enabled", True),
            "sensors": vent.get("sensors", {}),
            "setpoints": vent.get("setpoints", {}),
        }
    
    if old.get("climate"):
        climate = old["climate"]
        new["features"]["climate"] = {
            "enabled": climate.get("enabled", True),
            "safety": climate.get("safety", {}),
        }
    
    # Мигрируем глобальные флаги
    new["global_flags"] = {
        "winter": old.get("winter_flag", "input_boolean.zima"),
        "night": old.get("night_flag", "input_boolean.vecher"),
        "home": old.get("home_flag", "input_boolean.my_doma"),
        "party": old.get("party_flag", "input_boolean.party_mode"),
    }
    
    # Сохраняем новый манифест
    os.makedirs(os.path.dirname(new_path), exist_ok=True)
    with open(new_path, "w", encoding="utf-8") as f:
        yaml.safe_dump(new, f, allow_unicode=True, sort_keys=False, default_flow_style=False)
    
    print(f"✅ Манифест мигрирован: {new_path}")
    print(f"   Комнат: {len(new['rooms'])}")
    print(f"   Устройств: {len(new['devices'])}")
    print(f"   Групп: {len(new['groups'])}")
    print(f"   Фич: {len(new['features'])}")

if __name__ == "__main__":
    old_path = sys.argv[1] if len(sys.argv) > 1 else "instances/leonid_house/manifest.yaml"
    new_path = sys.argv[2] if len(sys.argv) > 2 else "platform_v2/manifests/leonid_house.yaml"
    
    if not os.path.exists(old_path):
        print(f"❌ Файл не найден: {old_path}")
        sys.exit(1)
    
    migrate_manifest(old_path, new_path)
