#!/usr/bin/env python3
"""Helpers-артефакт фичи ventilation."""
from core.builders import bool_


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
    return entries, i
