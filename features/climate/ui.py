#!/usr/bin/env python3
"""UI-артефакт фичи climate (блоки настроек)."""

def _title(t):
    return {"type": "custom:mushroom-title-card", "title": t}

def _grid(cards, cols):
    return {"type": "grid", "columns": cols, "square": False, "cards": cards}

def _bool(e, n):
    return {"type": "custom:mushroom-entity-card", "entity": e, "name": n}

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
    
    # НОВЫЙ БЛОК: FSM статус для климата
    cards.append({
        "type": "custom:vertical-stack-in-card",
        "cards": [
            _title("🤖 FSM Статус"),
            _grid([
                _bool("input_boolean.feature_climate_fsm_enabled", "FSM включён"),
                _bool("input_boolean.feature_climate_fsm_shadow", "Shadow режим")
            ], 2),
            {
                "type": "custom:mushroom-template-card",
                "entity": "sensor.climate_fsm_state",
                "content": "{{ states(entity) | default('IDLE') }}",
                "name": "Состояние FSM"
            },
            {"type": "entities", "entities": [
                {"entity": "sensor.climate_fsm_state", "name": "Причина", "attribute": "transition_reason"}
            ]}
        ]
    })
    
    return cards
