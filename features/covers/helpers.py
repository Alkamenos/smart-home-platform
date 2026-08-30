#!/usr/bin/env python3
"""Helpers-артефакт фичи covers: какие input_* создавать для штор."""

def _bool(i, name, init, icon):
    return {"id": i, "type": "input_boolean/create", "name": name,
            "initial": init, "icon": icon}

def _sel(i, name, options, init, icon):
    return {"id": i, "type": "input_select/create", "name": name,
            "options": options, "initial": init, "icon": icon}

def _dt(i, name, init, icon):
    return {"id": i, "type": "input_datetime/create", "name": name,
            "has_date": False, "initial": init, "icon": icon}

def _num(i, name, mn, mx, step, init, icon):
    return {"id": i, "type": "input_number/create", "name": name,
            "min": mn, "max": mx, "step": step, "initial": init, "icon": icon}


def helpers_for_cover(c, defaults, i):
    """Генерация helpers для одной шторы."""
    cid = str(c.get("id"))
    out = []
    
    # Автоматика этой шторы
    out.append(_bool(i, "cover_%s_auto" % cid, "on", "mdi:robot"))
    i += 1
    
    # Закрытие: ["Время", "Не закрывать"]
    close_init = "Время"
    out.append(_sel(i, "cover_%s_close" % cid, ["Время", "Не закрывать"], close_init, "mdi:cursor-down"))
    i += 1
    
    # Время закрытия (из манифеста или дефолт)
    close_time = defaults.get("close_time", "00:00")
    out.append(_dt(i, "cover_%s_close_time" % cid, close_time, "mdi:clock-outline"))
    i += 1
    
    # Открытие: ["Время", "Не открывать"]
    open_init = "Время"
    out.append(_sel(i, "cover_%s_open" % cid, ["Время", "Не открывать"], open_init, "mdi:cursor-up"))
    i += 1
    
    # Время открытия (из манифеста или дефолт)
    open_time = defaults.get("open_time", "08:00")
    out.append(_dt(i, "cover_%s_open_time" % cid, open_time, "mdi:clock-outline"))
    i += 1
    
    # Если дверь — добавляем away_closed_pct
    if c.get("door"):
        away_pct = c.get("away_closed_pct", 60)
        out.append(_num(i, "cover_%s_away_closed_pct" % cid, 0, 100, 5, away_pct, "mdi:percent"))
        i += 1
    
    return out, i


def generate_covers_helpers(cfg, ctx):
    """Генерация всех helpers для фичи covers."""
    if not cfg or not cfg.get("enabled", True):
        return []
    
    out = []
    i = 0
    
    # Глобальные флаги
    # dogs_home — создаём если нет
    out.append(_bool(i, "dogs_home", "off", "mdi:dog-side"))
    i += 1
    
    # feature_covers — флаг включения автоматики
    out.append(_bool(i, "feature_covers", "on", "mdi:window-shutter"))
    i += 1
    
    # covers_shadow_mode — теневой режим
    out.append(_bool(i, "covers_shadow_mode", "off", "mdi:ghost"))
    i += 1
    
    # Helpers для каждой шторы
    defaults = cfg.get("defaults", {"open_time": "08:00", "close_time": "00:00"})
    covers = cfg.get("covers", [])
    
    for c in covers:
        add, i = helpers_for_cover(c, defaults, i)
        out.extend(add)
    
    return out
