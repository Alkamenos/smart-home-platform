#!/usr/bin/env python3
"""
Манифест V2 — единый источник истины для всей платформы.
"""
import yaml
from typing import Any, Optional

def load_manifest(path: str) -> dict:
    """Загрузить манифест из YAML файла"""
    with open(path, encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    
    manifest = {
        "instance_id": raw.get("instance", {}).get("id", "leonid_house"),
        "rooms": raw.get("rooms", []),
        "devices": {},
        "groups": {},
        "features": {},
        "global_flags": raw.get("global_flags", {}),
    }
    
    # Парсим устройства (могут быть списком словарей или словарём)
    raw_devices = raw.get("devices", [])
    if isinstance(raw_devices, list):
        for d in raw_devices:
            if not isinstance(d, dict):
                continue
            dev_id = d.get("id", "unknown")
            manifest["devices"][dev_id] = {
                "id": dev_id,
                "entity": d.get("entity"),
                "name": d.get("name", dev_id),
                "room": d.get("room", "unknown"),
                "capabilities": d.get("capabilities", {}),
                "managed_by_platform": d.get("managed_by_platform", True),
            }
    elif isinstance(raw_devices, dict):
        for dev_id, d in raw_devices.items():
            if not isinstance(d, dict):
                continue
            manifest["devices"][dev_id] = {
                "id": dev_id,
                "entity": d.get("entity"),
                "name": d.get("name", dev_id),
                "room": d.get("room", "unknown"),
                "capabilities": d.get("capabilities", {}),
                "managed_by_platform": d.get("managed_by_platform", True),
            }
    
    # Парсим группы (могут быть списком словарей или словарём)
    raw_groups = raw.get("groups", [])
    if isinstance(raw_groups, list):
        for g in raw_groups:
            if not isinstance(g, dict):
                continue
            group_id = str(g.get("id", "unknown"))
            manifest["groups"][group_id] = {
                "id": group_id,
                "name": g.get("name", group_id),
                "room": g.get("room", "unknown"),
                "devices": g.get("devices", []),
                "fsm": g.get("fsm"),
                "features": g.get("features", {}),
            }
    elif isinstance(raw_groups, dict):
        for group_id, g in raw_groups.items():
            if not isinstance(g, dict):
                continue
            manifest["groups"][group_id] = {
                "id": group_id,
                "name": g.get("name", group_id),
                "room": g.get("room", "unknown"),
                "devices": g.get("devices", []),
                "fsm": g.get("fsm"),
                "features": g.get("features", {}),
            }
    
    # Парсим фичи (могут быть списком или словарём)
    raw_features = raw.get("features", {})
    if isinstance(raw_features, dict):
        for fname, fconfig in raw_features.items():
            if not isinstance(fconfig, dict):
                continue
            manifest["features"][fname] = {
                "name": fname,
                "enabled": fconfig.get("enabled", True),
                "config": fconfig,
                "flags": fconfig.get("flags", {}),
            }
    
    return manifest
