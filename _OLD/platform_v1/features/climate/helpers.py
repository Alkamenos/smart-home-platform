#!/usr/bin/env python3
"""Helpers-артефакт фичи climate."""
from core.builders import num, bool_


def climate_entries(climate, i):
    entries = [
        bool_(i, "feature_climate", "on", "mdi:thermometer"),
        bool_(i + 1, "climate_shadow_mode", "off", "mdi:eye-off-outline"),
    ]
    i += 2

    seen_sp = set()
    for zone in (climate.get("zones", []) or []):
        for sp in (zone.get("setpoints") or {}).values():
            if isinstance(sp, dict):
                src = sp.get("source", "")
                if isinstance(src, str) and src.startswith("input_number.") and src not in seen_sp:
                    seen_sp.add(src)
                    name = src.split(".", 1)[1]
                    entries.append(num(i, name, 5, 35, 0.5, 22, "mdi:thermometer"))
                    i += 1

    entries.append(num(i, "vlazhnost_v_dome", 0, 100, 1, 50, "mdi:water-percent"))
    i += 1
    return entries, i
