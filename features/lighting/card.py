#!/usr/bin/env python3
"""Цельная карточка группы: база + блоки фич сверху вниз.
Яркость показывается только для диммируемых устройств (caps)."""
from features.lighting import ui as FU
from features.lighting import caps as CAPS

CARD_TYPE = "custom:vertical-stack-in-card"

def _grid(cards, cols):
    return {"type": "grid", "columns": cols, "square": False, "cards": cards}

def _sel(e, n):
    return {"type": "custom:mushroom-select-card", "entity": e, "name": n}

def _num(e, n):
    return {"type": "custom:mushroom-number-card", "entity": e, "name": n}

def group_card(g):
    gid = str(g.get("id"))
    caps = CAPS.group_caps(g)
    cards = [
        {"type": "custom:mushroom-title-card", "title": "💡 " + g.get("name", gid)},
        _grid([_sel("input_select.light_%s_on" % gid, "Включение"),
               _sel("input_select.light_%s_off" % gid, "Выключение")], 2),
    ]
    if caps.get("dim"):
        cards.append(_num("input_number.light_%s_brightness" % gid, "Яркость %"))
    cards += FU.group_feature_blocks(g, gid)
    return {"type": CARD_TYPE, "cards": cards}
