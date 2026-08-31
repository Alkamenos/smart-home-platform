#!/usr/bin/env python3
"""Управление реальными устройствами освещения."""



def _lg_override_active(e):
    """Проверка активной блокировки override для entity."""
    until = _LG_OVERRIDE.get(e)
    if until is None:
        return False
    if time.monotonic() >= until:
        del _LG_OVERRIDE[e]
        return False
    return True


def _lg_vlight_guard_active(v):
    """Проверка guard для vlight sync."""
    until = _VLIGHT_SYNC_GUARD.get(v, 0)
    if time.monotonic() > until:
        _VLIGHT_SYNC_GUARD.pop(v, None)
        return False
    return True


def _lg_set_vlight(v, on, mode):
    """Установка состояния vlight с guard."""
    want = "on" if on else "off"
    cur = _lg_state(v)
    if cur is None:
        return
    if cur == want:
        return
    _VLIGHT_SYNC_GUARD[v] = time.monotonic() + 10
    if mode == "shadow":
        log_event("lighting", "Инфо", "vlight " + v + " -> " + want, why="shadow-режим", src="автоматика")
    else:
        service.call("input_boolean", "turn_" + want, entity_id=v)
        log_event("lighting", "Инфо", "vlight " + v + " -> " + want, why="ручная команда", src="ручное")


def _lg_expected_guard(e):
    """Получение ожидаемого состояния из guard."""
    exp = _EXPECTED_REAL_STATE.get(e)
    if exp is None:
        return None
    if time.monotonic() > exp["until"]:
        _EXPECTED_REAL_STATE.pop(e, None)
        return None
    return exp["state"]


def _lg_set_real(e, on, mode, cfg, force=False, nightlight=False, gid=None):
    """Применение состояния к реальному устройству."""
    already = _lg_is_on(e) == on
    restoring = on and not nightlight and (e in _LG_NL_ACTIVE)
    
    # Если восстанавливаем свет после ночника - нужно применить профиль
    if restoring:
        log_event("lighting", "Инфо", e + " applying profile after nightlight", why="восстановление после ночника", src="автоматика")
        _LG_NL_ACTIVE.discard(e)
        # Не возвращаем, продолжаем применять настройки профиля
    elif already:
        return
    
    if not force and not restoring:
        last = _LG_LAST_CHANGE.get(e, 0)
        if (time.monotonic() - last) < cfg.get("anti_cycle_min", 2) * 60:
            log_event("lighting", "Отладка", e + " skip (anti-cycle)", why="анти-цикл 2 мин", src="таймер")
            return
    
    _EXPECTED_REAL_STATE[e] = {"state": on, "until": time.monotonic() + 60}
    
    if mode == "shadow" and not force:
        log_event("lighting", "Инфо", e + " -> " + ("on" if on else "off"), why="shadow-режим", src="автоматика")
        return
    
    dom = str(e).split(".")[0]
    if on and dom == "light":
        if nightlight and gid:
            gr = _lg_group(cfg, gid)
            caps = _lg_caps(gr) if gr is not None else {"dim": True, "ct": False, "rgb": True}
            b = int(_lg_num("input_number.light_%s_nightlight_brightness" % gid, 40))
            r = int(_lg_num("input_number.light_%s_nightlight_r" % gid, 255))
            g_val = int(_lg_num("input_number.light_%s_nightlight_g" % gid, 150))
            bl = int(_lg_num("input_number.light_%s_nightlight_b" % gid, 60))
            if caps.get("rgb") and caps.get("dim"):
                service.call(dom, "turn_on", entity_id=e, brightness_pct=b, rgb_color=[r, g_val, bl])
            elif caps.get("rgb"):
                service.call(dom, "turn_on", entity_id=e, rgb_color=[r, g_val, bl])
            elif caps.get("dim"):
                service.call(dom, "turn_on", entity_id=e, brightness_pct=b)
            else:
                service.call(dom, "turn_on", entity_id=e)
            _LG_NL_ACTIVE.add(e)
            log_event("lighting", "Инфо", e + " -> on b=" + str(b), why="ночник", src="автоматика")
        else:
            gid_real = _LIGHT2GID.get(e)
            gr = _lg_group(cfg, gid_real) if gid_real else None
            caps = _lg_caps(gr) if gr is not None else {"dim": True, "ct": False, "rgb": False}
            b = _lg_num("input_number.light_%s_brightness" % gid_real, 100) if gid_real else 100
            k = None
            if caps.get("ct"):
                k = _lg_ct_target(cfg)
                if k is not None:
                    k = int(k)
            # Применяем яркость и температуру всегда при включении или восстановлении
            if caps.get("dim"):
                if k is not None:
                    service.call(dom, "turn_on", entity_id=e, brightness_pct=int(b), color_temp_kelvin=k)
                else:
                    service.call(dom, "turn_on", entity_id=e, brightness_pct=int(b))
            else:
                if k is not None:
                    service.call(dom, "turn_on", entity_id=e, color_temp_kelvin=k)
                else:
                    service.call(dom, "turn_on", entity_id=e)
            _LG_NL_ACTIVE.discard(e)
    else:
        service.call(dom, "turn_on" if on else "turn_off", entity_id=e)
        if not on:
            _LG_NL_ACTIVE.discard(e)
    
    _LG_LAST_CHANGE[e] = time.monotonic()
    log_event("lighting", "Инфо", e + " -> " + ("on" if on else "off"), why="решение автоматики", src="автоматика")


# Маппинг light -> gid (заполняется в runtime)
_LIGHT2GID = {}


def _lg_rebuild_light_map(cfg):
    """Перестроение маппинга light entity -> group id."""
    global _LIGHT2GID
    m = {}
    for g in (cfg.get("groups", []) or []):
        for e in (g.get("lights", []) or []):
            if e:
                m[e] = str(g.get("id"))
    _LIGHT2GID = m


def _lg_group(cfg, gid):
    """Поиск группы по gid."""
    for g in (cfg.get("groups", []) or []):
        if str(g.get("id")) == gid:
            return g
    return None


def _lg_manual_command(cfg, g, on, mode):
    """Обработка ручной команды (кнопка/дашборд/голос)."""
    
    gid = str(g.get("id"))
    ms = _lg_motion_sensor(g, gid)
    motion_mode = None
    if ms:
        motion_mode = _lg_state("input_select.light_%s_motion_mode" % gid)
    has_motion = ms is not None and motion_mode not in (None, "unknown", "unavailable", "Выкл")
    
    v = lg_vlight_entity(g)
    if _lg_state(v) is not None:
        _VLIGHT_PREV[v] = "on" if on else "off"
        _lg_set_vlight(v, on, "real")
    
    for e in (g.get("lights", []) or []):
        if not e:
            continue
        if g.get("tolerate_unavailable") and _lg_unavailable(e):
            continue
        
        # Для групп с датчиком — своя логика override
        if has_motion:
            respect = _lg_state("input_boolean.light_%s_manual_respect" % gid)
            if respect == "off":
                log_event("lighting", "Инфо", "gid=" + gid + ": manual_respect=off, skip override", why="настройка группы", src="ручное")
            elif on:
                mins = int(_lg_num("input_number.light_%s_manual_on_min" % gid, 60))
                _LG_OVERRIDE[e] = time.monotonic() + mins * 60
                log_event("lighting", "Инфо", "gid=" + gid + ": manual ON command, block " + str(mins) + " min", why="ручное ВКЛ", src="ручное")
            else:
                mins = int(_lg_num("input_number.light_%s_manual_off_min" % gid, 2))
                _LG_OVERRIDE[e] = time.monotonic() + mins * 60
                log_event("lighting", "Инфо", "gid=" + gid + ": manual OFF command, block " + str(mins) + " min", why="ручное ВЫКЛ", src="ручное")
        else:
            _LG_OVERRIDE[e] = time.monotonic() + cfg.get("override_timeout_min", 60) * 60
            log_event("lighting", "Инфо", "gid=" + gid + ": manual command, block 60 min", why="ручная команда", src="ручное")
        
        _lg_set_real(e, on, "real", cfg, force=True)
