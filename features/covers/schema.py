#!/usr/bin/env python3
"""Schema: валидация секции covers в манифесте."""

REQUIRED_COVER_FIELDS = ["id", "name", "cover"]
OPTIONAL_COVER_FIELDS = ["door", "away_closed_pct"]

def validate_cover(c):
    """Валидация одной шторы."""
    if not isinstance(c, dict):
        return False, "cover must be a dict"
    for f in REQUIRED_COVER_FIELDS:
        if f not in c:
            return False, "missing required field: " + f
    if not isinstance(c.get("cover"), str) or not c["cover"].startswith("cover."):
        return False, "cover entity must start with 'cover.'"
    if c.get("door") and not isinstance(c.get("away_closed_pct"), (int, float)):
        # Если door=true, away_closed_pct должен быть числом или дефолт 60
        if "away_closed_pct" not in c:
            c["away_closed_pct"] = 60  # дефолт
    return True, None

def validate_covers_feature(cfg):
    """Валидация всей секции covers."""
    if not isinstance(cfg, dict):
        return False, "covers config must be a dict"
    
    errors = []
    
    # Проверка обязательных полей
    if "enabled" not in cfg:
        cfg["enabled"] = True
    
    if "mode" not in cfg:
        cfg["mode"] = "real"
    
    if "presence_flag" not in cfg:
        cfg["presence_flag"] = "input_boolean.my_doma"
    
    if "defaults" not in cfg:
        cfg["defaults"] = {"open_time": "08:00", "close_time": "00:00"}
    
    # Проверка списка штор
    covers = cfg.get("covers", [])
    if not isinstance(covers, list):
        return False, "covers must be a list"
    
    ids_seen = set()
    for i, c in enumerate(covers):
        ok, err = validate_cover(c)
        if not ok:
            errors.append("cover[%d]: %s" % (i, err))
            continue
        
        cid = str(c.get("id"))
        if cid in ids_seen:
            errors.append("duplicate cover id: " + cid)
        ids_seen.add(cid)
        
        # Валидация away_closed_pct для дверей
        if c.get("door"):
            pct = c.get("away_closed_pct", 60)
            if not (0 <= pct <= 100):
                errors.append("cover[%d]: away_closed_pct must be 0-100" % i)
    
    if errors:
        return False, "; ".join(errors)
    
    return True, None
