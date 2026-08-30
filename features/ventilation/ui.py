#!/usr/bin/env python3
"""UI-артефакт фичи ventilation (блоки настроек)."""

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
    
    return cards
