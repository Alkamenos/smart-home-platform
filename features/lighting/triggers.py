#!/usr/bin/env python3
"""Обработчики событий: кнопки, vlight, motion."""



# ==================== КНОПКИ ====================

def _btn_build():
    """Построение списка entity кнопок для триггеров."""
    m = {}
    try:
        cfg = _lg_cfg() or {}
        for b in (cfg.get("buttons", []) or []):
            ent = b.get("entity")
            if ent:
                m[ent] = b.get("mapping", {}) or {}
    except Exception:
        m = {}
    _BUTTON_MAP = m
    return sorted(m.keys()) if m else ["input_boolean.feature_lighting"]


_BTN_LIST = _btn_build()


@state_trigger(*_BTN_LIST)
def _lg_button_handler(var_name=None, **kwargs):
    """Обработка нажатий кнопок."""
    if not var_name or var_name not in _BUTTON_MAP:
        return
    st = hass.states.get(var_name)
    if st is None:
        return
    action = st.attributes.get("event_type") or st.attributes.get("type")
    if not action:
        return
    cmd = (_BUTTON_MAP.get(var_name) or {}).get(str(action))
    if not cmd:
        return
    cfg = _lg_cfg()
    if not cfg:
        return
    groups = {}
    for g in (cfg.get("groups", []) or []):
        groups[str(g["id"])] = g
    g = groups.get(str(cmd.get("toggle")))
    if not g:
        return
    v = lg_vlight_entity(g)
    sv = _lg_state(v)
    if sv is not None:
        cur_on = (sv == "on")
    else:
        lights_list = [e for e in (g.get("lights", []) or []) if e and not _lg_unavailable(e)]
        cur_on = any([_lg_is_on(e) for e in lights_list])
    log.warning("[button] " + var_name + " " + str(action) + " -> toggle " + str(cmd.get("toggle")))
    _lg_manual_command(cfg, g, not cur_on, _lg_mode(cfg))


# ==================== VLIGHT ====================

def _vlight_build_list():
    """Построение списка vlight entity для триггеров."""
    cfg = _lg_cfg() or {}
    out = []
    for g in (cfg.get("groups", []) or []):
        out.append(lg_vlight_entity(g))
    return out if out else ["input_boolean.feature_lighting"]


_VLIGHT_LIST = _vlight_build_list()


@state_trigger(*_VLIGHT_LIST)
def _lg_vlight_handler(var_name=None, **kwargs):
    """Обработка изменений vlight."""
    #if _lg_state("input_boolean.feature_lighting") == "off":
    #    return
    cfg = _lg_cfg()
    if not cfg:
        return
    mode = _lg_mode(cfg)
    for g in (cfg.get("groups", []) or []):
        v = lg_vlight_entity(g)
        if v != var_name:
            continue
        g2 = _lg_season(g)
        m = "shadow" if (mode == "shadow" or g2.get("shadow")) else "real"
        _lg_handle_vlight_change(g2, cfg, m, v, True)
        return


# ==================== MOTION ====================

def _motion_build_list():
    """Построение списка motion сенсоров для триггеров."""
    cfg = _lg_cfg() or {}
    out = []
    for g in (cfg.get("groups", []) or []):
        ms = g.get("motion_sensor")
        if ms:
            out.append(ms)
    return out if out else ["input_boolean.feature_lighting"]


_MOTION_LIST = _motion_build_list()


@state_trigger(*_MOTION_LIST)
def _lg_motion_handler(var_name=None, **kwargs):
    """Обработка срабатывания датчиков движения."""
    cur_state = _lg_state(var_name)
    _lg_log("motion", "INFO", "sensor=%s state=%s" % (str(var_name), str(cur_state)))

    if _lg_state("input_boolean.feature_lighting") == "off":
        _lg_log("motion", "DEBUG", "feature_lighting=off, skip")
        return
    cfg = _lg_cfg()
    if not cfg:
        _lg_log("motion", "DEBUG", "no config, skip")
        return
    mode = _lg_mode(cfg)
    for g in (cfg.get("groups", []) or []):
        gid = str(g.get("id"))
        # Читаем датчик из dropdown helper'а, если есть, иначе из манифеста
        ms = _lg_state("input_select.light_%s_motion_sensor" % gid)
        if not ms or ms in ("unknown", "unavailable"):
            ms = g.get("motion_sensor")
        if ms != var_name:
            continue
        _LG_MOTION_LAST[gid] = time.monotonic()
        _lg_log("motion", "DEBUG", "gid=%s: motion detected, last=%s" % (gid, str(_LG_MOTION_LAST[gid])))
        g2 = _lg_season(g)
        m = "shadow" if (mode == "shadow" or g2.get("shadow")) else "real"
        _lg_apply_group(g2, cfg, m)
        return
