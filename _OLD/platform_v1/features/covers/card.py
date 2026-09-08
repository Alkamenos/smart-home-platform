#!/usr/bin/env python3
"""Card-артефакт фичи covers: цельная карточка для каждой шторы."""

from features.covers.ui import cover_card, covers_global_card


def generate_covers_cards(cfg):
    """Генерация карточек для дашборда."""
    if not cfg or not cfg.get("enabled", True):
        return []
    
    out = [covers_global_card()]
    
    defaults = cfg.get("defaults", {"open_time": "08:00", "close_time": "00:00"})
    covers = cfg.get("covers", [])
    
    for c in covers:
        out.append(cover_card(c, defaults))
    
    return out
