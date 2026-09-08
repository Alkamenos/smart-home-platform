#!/usr/bin/env python3
"""Helpers-артефакт фичи ventilation."""
from core.builders import bool_, num, sel


def vent_lockout_entries(i):
    """Генерация helpers для heating lockout."""
    entries = [
        bool_(i, "feature_vent_heating_lockout", "on", "mdi:snowflake-alert"),
        num(i + 1, "vent_lockout_street_max", -20, 10, 1, 5, "mdi:thermometer-minus"),
        num(i + 2, "vent_lockout_delta", 0, 2, 0.1, 0.3, "mdi:delta"),
        sel(i + 3, "vent_lockout_action", 
            ["OFF", "10", "20", "30", "40", "50"], "10", "mdi:fan-alert"),
    ]
    return entries, i + 4


def vent_entries(ventilation, i):
    entries = []
    flags = (ventilation.get("flags", {}) or {})
    entries += [
        bool_(i, "feature_ventilation", "on", "mdi:fan"),
        bool_(i + 1, "ventilation_shadow_mode", "off", "mdi:eye-off-outline"),
    ]
    i += 2

    for key in ("boost_intake", "boost_exhaust", "night", "away_home"):
        ent = flags.get(key)
        if ent and ent.startswith("input_boolean."):
            name = ent.split(".", 1)[1]
            init = "off" if key.startswith("boost") else ("on" if key == "away_home" else "off")
            entries.append(bool_(i, name, init, "mdi:fan"))
            i += 1

    od = (ventilation.get("open_doors", {}) or {})
    if od.get("enabled_flag", "").startswith("input_boolean."):
        entries.append(bool_(i, od["enabled_flag"].split(".", 1)[1], "on", "mdi:door-open"))
        i += 1
    if od.get("mock_state", "").startswith("input_boolean."):
        entries.append(bool_(i, od["mock_state"].split(".", 1)[1], "off", "mdi:door"))
        i += 1

    bf = (ventilation.get("bathroom_fan", {}) or {})
    if bf.get("enabled_flag", "").startswith("input_boolean."):
        entries.append(bool_(i, bf["enabled_flag"].split(".", 1)[1], "on", "mdi:fan"))
        i += 1
    
    # Добавляем heating lockout helpers если фича включена
    lockout = ventilation.get("heating_lockout") or {}
    if lockout.get("enabled", False):
        lockout_entries, i = vent_lockout_entries(i)
        entries += lockout_entries
    
    return entries, i
