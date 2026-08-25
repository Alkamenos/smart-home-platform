#!/usr/bin/env python3
"""UI-артефакт фичи climate (блоки настроек)."""

def climate_cards(climate):
    cards = [{"type": "entities", "title": "Управление", "entities": [
        {"entity": "input_boolean.zima", "name": "Сезон (зима)"},
    ]}]
    seen_sp = set()
    sp_ents = []
    for zone in climate.get("zones", []):
        for sp in (zone.get("setpoints") or {}).values():
            if isinstance(sp, dict):
                src = sp.get("source", "")
                if src.startswith("input_number.") and src not in seen_sp:
                    seen_sp.add(src)
                    sp_ents.append({"entity": src})
    cards.append({"type": "entities", "title": "Уставки", "entities": sp_ents})
    if climate.get("safety"):
        cards.append({"type": "entities", "title": "Безопасность", "entities": [
            {"entity": "input_number.vlazhnost_v_dome", "name": "Влажность в доме"},
        ]})
    return cards
