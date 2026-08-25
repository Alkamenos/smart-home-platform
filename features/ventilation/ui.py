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
    return cards
