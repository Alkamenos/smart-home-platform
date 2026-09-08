#!/usr/bin/env python3
"""UI-артефакт фичи ventilation (блоки настроек)."""

def _title(t):
    return {"type": "custom:mushroom-title-card", "title": t}

def _grid(cards, cols):
    return {"type": "grid", "columns": cols, "square": False, "cards": cards}

def _bool(e, n):
    return {"type": "custom:mushroom-entity-card", "entity": e, "name": n}

def vent_cards(ventilation):
    cards = [{"type": "entities", "title": "Режимы", "entities": [
        {"entity": "input_boolean.provetrivanie", "name": "Проветривание"},
        {"entity": "input_boolean.provetrivanie_vytyazhka", "name": "Вытяжка"},
        {"entity": "input_boolean.vecher", "name": "Ночной режим"},
        {"entity": "input_boolean.my_doma", "name": "Дома"},
    ]}]
    od = ventilation.get("open_doors", {})
    if od.get("mock_state"):
        cards.append({"type": "entities", "title": "Двери/окна", "entities": [
            {"entity": od["mock_state"], "name": "Mock: открыты"},
        ]})
    
    # НОВЫЙ БЛОК: Heating Lockout (координация с отоплением)
    lockout = ventilation.get("heating_lockout") or {}
    if lockout.get("enabled", False):
        lockout_entities = [
            {"entity": "input_boolean.feature_vent_heating_lockout", 
             "name": "Включить блокировку"},
            {"entity": "input_number.vent_lockout_street_max", 
             "name": "Порог улицы (°C)"},
            {"entity": "input_number.vent_lockout_delta", 
             "name": "Дельта до уставки (°C)"},
            {"entity": "input_select.vent_lockout_action", 
             "name": "Действие"},
        ]
        cards.append({"type": "entities", "title": "Координация с отоплением", "entities": lockout_entities})
    
    # НОВЫЙ БЛОК: FSM статус для вентиляции
    cards.append({
        "type": "custom:vertical-stack-in-card",
        "cards": [
            _title("🤖 FSM Статус"),
            _grid([
                _bool("input_boolean.feature_ventilation_fsm_enabled", "FSM включён")
            ], 1),
            {
                "type": "custom:mushroom-template-card",
                "entity": "sensor.ventilation_fsm_state",
                "content": "{{ states(entity) | default('NORMAL') }}",
                "name": "Состояние FSM"
            },
            {"type": "entities", "entities": [
                {"entity": "sensor.ventilation_fsm_state", "name": "Причина", "attribute": "transition_reason"}
            ]}
        ]
    })
    
    return cards
