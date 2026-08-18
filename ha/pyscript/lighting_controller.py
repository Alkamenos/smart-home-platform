# ============================================================
# LIGHTING CONTROLLER v2.6 (final: safe reads, no genexpr)
# ============================================================
import time
import random

_LG_PREV = {}
_LG_OVERRIDE = {}
_LG_LAST_CHANGE = {}
_LG_MOTION_LAST = {}
_DARK = None
_CT_LAST = {}
_VLIGHT_PREV = {}
_VLIGHT_SYNC_GUARD = {}
_EXPECTED_REAL_STATE = {}
_BUTTON_MAP = {}
_LG_IM_ACTIVE = {}
_RGB_SCENES = {"Красный": [255, 0, 0], "Оранжевый": [255, 120, 0], "Зелёный": [0, 255, 0],
               "Синий": [0, 0, 255], "Фиолетовый": [160, 0, 255], "Розовый": [255, 60, 140]}
_RGB_APPLIED = {}

# ---------------- безопасное чтение состояний ----------------

def _lg_state(entity):
    """Строка состояния или None, если сущности нет."""
    st = hass.states.get(entity)
    if st is None:
        return None
    return st.state


def _lg_attr(entity, name):
    st = hass.states.get(entity)
    if st is None:
        return None
    return st.attributes.get(name)


def _lg_cfg():
    if _REGISTRY is None:
        return None
    return _REGISTRY.feature("lighting") or None


def _lg_get_float(entity):
    s = _lg_state(entity)
    if s is None:
        return None
    if str(s) in ("unknown", "unavailable", "none", ""):
        return None
    try:
        return float(s)
    except Exception:
        return None


def _lg_now_min():
    t = time.localtime()
    return t.tm_hour * 60 + t.tm_min


def _lg_hm(s):
    try:
        h, m = str(s).split(":")
        return int(h) * 60 + int(m)
    except Exception:
        return None


def _lg_dt_min(entity):
    s = _lg_state(entity)
    if not s:
        return None
    try:
        return _lg_hm(str(s).split(" ")[1][:5])
    except Exception:
        return None


def _lg_is_on(e):
    return _lg_state(e) == "on"


def _lg_unavailable(e):
    s = _lg_state(e)
    return s is None or str(s) in ("unknown", "unavailable")


def _lg_mode(cfg):
    sh = _lg_state("input_boolean.lighting_shadow_mode")
    if sh == "on":
        return "shadow"
    if sh == "off":
        return "real"
    return cfg.get("mode", "real")


def _lg_night(cfg):
    return _lg_state(cfg.get("night_flag", "input_boolean.vecher")) == "on"


def _lg_season(g):
    s = g.get("season")
    if not s:
        return g
    zima = _lg_state("input_boolean.zima") == "on"
    var = s.get("winter") if zima else s.get("summer")
    if not var:
        return g
    merged = dict(g)
    merged.update(var)
    return merged


def _lg_motion(g):
    ms = g.get("motion_sensor")
    if not ms:
        return None
    return _lg_state(ms) in ("on", "true", True)


# ---------------- темнота (гистерезис) ----------------

def _lg_update_dark(cfg):
    global _DARK
    d = cfg.get("dark", {}) or {}
    lux = None
    if d.get("illuminance_sensor"):
        lux = _lg_get_float(d["illuminance_sensor"])
    if lux is not None:
        if _DARK is None:
            _DARK = lux < d.get("dark_lux", 20)
        elif _DARK and lux > d.get("light_lux", 40):
            _DARK = False
        elif (not _DARK) and lux < d.get("dark_lux", 20):
            _DARK = True
        return
    try:
        elev = float(hass.states.get("sun.sun").attributes.get("elevation", 99))
    except Exception:
        return
    if _DARK is None:
        _DARK = elev < d.get("sun_dark_elevation", -3)
    elif _DARK and elev > d.get("sun_light_elevation", 1):
        _DARK = False
    elif (not _DARK) and elev < d.get("sun_dark_elevation", -3):
        _DARK = True


# ---------------- guards / vlight ----------------

def _lg_vlight_entity(g):
    return g.get("vlight_entity") or ("input_boolean.vlight_" + str(g.get("id")))


def _lg_override_active(e):
    until = _LG_OVERRIDE.get(e)
    if until is None:
        return False
    if time.monotonic() >= until:
        del _LG_OVERRIDE[e]
        return False
    return True


def _lg_vlight_guard_active(v):
    until = _VLIGHT_SYNC_GUARD.get(v, 0)
    if time.monotonic() > until:
        _VLIGHT_SYNC_GUARD.pop(v, None)
        return False
    return True


def _lg_set_vlight(v, on, mode):
    want = "on" if on else "off"
    cur = _lg_state(v)
    if cur is None:
        return
    if cur == want:
        return
    _VLIGHT_SYNC_GUARD[v] = time.monotonic() + 10
    if mode == "shadow":
        log.warning("[light][SHADOW][vlight] " + v + " -> " + want)
    else:
        service.call("input_boolean", "turn_" + want, entity_id=v)
        log.warning("[light][REAL][vlight] " + v + " -> " + want)


def _lg_expected_guard(e):
    exp = _EXPECTED_REAL_STATE.get(e)
    if exp is None:
        return None
    if time.monotonic() > exp["until"]:
        _EXPECTED_REAL_STATE.pop(e, None)
        return None
    return exp["state"]


def _lg_num(entity, default):
    s = _lg_state(entity)
    if s is None:
        return default
    try:
        return float(s)
    except Exception:
        return default


_LIGHT2GID = {}

def _lg_rebuild_light_map(cfg):
    global _LIGHT2GID
    m = {}
    for g in (cfg.get("groups", []) or []):
        for e in (g.get("lights", []) or []):
            if e:
                m[e] = str(g.get("id"))
    _LIGHT2GID = m


def _lg_set_real(e, on, mode, cfg, force=False):
    if _lg_is_on(e) == on:
        return
    if not force:
        last = _LG_LAST_CHANGE.get(e, 0)
        if (time.monotonic() - last) < cfg.get("anti_cycle_min", 2) * 60:
            return
    _EXPECTED_REAL_STATE[e] = {"state": on, "until": time.monotonic() + 30}
    if mode == "shadow":
        log.warning("[light][SHADOW] " + e + " -> " + ("on" if on else "off"))
    else:
        dom = str(e).split(".")[0]
        if on and dom == "light":
            gid = _LIGHT2GID.get(e)
            b = _lg_num("input_number.light_%s_brightness" % gid, 100) if gid else 100
            if b < 100:
                service.call(dom, "turn_on", entity_id=e, brightness_pct=int(b))
            else:
                service.call(dom, "turn_on", entity_id=e)
        else:
            service.call(dom, "turn_on" if on else "turn_off", entity_id=e)
        _LG_LAST_CHANGE[e] = time.monotonic()
        log.warning("[light][REAL] " + e + " -> " + ("on" if on else "off"))


def _lg_manual_command(cfg, g, on, mode):
    v = _lg_vlight_entity(g)
    if _lg_state(v) is not None:
        _VLIGHT_PREV[v] = "on" if on else "off"
        _lg_set_vlight(v, on, mode)
    for e in (g.get("lights", []) or []):
        if not e:
            continue
        if g.get("tolerate_unavailable") and _lg_unavailable(e):
            continue
        _LG_OVERRIDE[e] = time.monotonic() + cfg.get("override_timeout_min", 60) * 60
        _lg_set_real(e, on, mode, cfg, force=True)


# ---------------- решение автоматики ----------------

def _lg_decide(g, cfg):
    g = _lg_season(g)
    prof = g.get("profile", "dusk_till_time")
    dark = bool(_DARK)
    now = _lg_now_min()
    night = _lg_night(cfg)
    gid = str(g.get("id"))

    ms = g.get("motion_sensor")
    men = ms is not None and _lg_state("input_boolean.light_%s_motion" % gid) != "off"
    mday = _lg_state("input_boolean.light_%s_motion_day" % gid) == "on"
    motion = _lg_motion(g) if ms else None
    presence = False
    if ms and men:
        if motion:
            _LG_MOTION_LAST[gid] = time.monotonic()
        last = _LG_MOTION_LAST.get(gid)
        if last is not None:
            mins = _lg_num("input_number.light_%s_motion_night_min" % gid,
                           g.get("no_motion_night_min", 2)) if night else \
                   _lg_num("input_number.light_%s_motion_day_min" % gid,
                           g.get("no_motion_day_min", 5))
            presence = (time.monotonic() - last) < mins * 60

    ov = g.get("override_flag")
    if ov and _lg_state(ov) == "on":
        return {"on": True}

    sel_on = _lg_state("input_select.light_%s_on" % gid)
    if sel_on == "Не включать":
        return {"on": False}

    if prof == "motion":
        if not (dark or mday):
            return {"on": False}
        return {"on": presence}

    if prof == "manual_auto":
        af = g.get("auto_flag")
        if not (af and _lg_state(af) == "on"):
            return None

    # условие ВЫКЛ (настраивается с дашборда)
    sel_off = _lg_state("input_select.light_%s_off" % gid)
    if sel_off is None:
        sel_off = "Рассвет" if g.get("off") == "sunrise" else "Время"
    if sel_off == "Рассвет":
        if not dark and not presence:
            return {"on": False}
    elif sel_off == "Время":
        off_min = _lg_dt_min("input_datetime.light_%s_off_time" % gid)
        if off_min is None:
            off_min = _lg_hm(g.get("off", "23:00"))
        if off_min is not None and now >= off_min and not presence:
            return {"on": False}
    # «Не выключать» — не выключаем

    # условие ВКЛ
    if sel_on == "Время":
        t_val = _lg_dt_min("input_datetime.light_%s_on_time" % gid)
        if t_val is not None and now >= t_val:
            return {"on": True}
        if presence and dark:
            return {"on": True}
        return {"on": False}
    if dark:
        return {"on": True}
    return {"on": False}



# ---------------- тик группы ----------------

def _lg_handle_vlight_change(g, cfg, mode, v, has_v):
    if not has_v:
        return
    cur = _lg_state(v)
    if cur is None:
        return
    prev = _VLIGHT_PREV.get(v)
    _VLIGHT_PREV[v] = cur
    if prev is None or prev == cur:
        return
    if _lg_vlight_guard_active(v):
        return
    log.warning("[light][manual] " + v + " -> " + cur)
    _lg_manual_command(cfg, g, cur == "on", mode)


def _lg_track_real(g, cfg, mode, v, has_v):
    for e in (g.get("lights", []) or []):
        if not e:
            continue
        cur = _lg_is_on(e)
        prev = _LG_PREV.get(e)
        _LG_PREV[e] = cur
        if prev is None or cur == prev:
            continue
        exp = _lg_expected_guard(e)
        if exp is not None:
            if exp == cur:
                _EXPECTED_REAL_STATE.pop(e, None)
            continue
        _LG_OVERRIDE[e] = time.monotonic() + cfg.get("override_timeout_min", 60) * 60
        log.warning("[light][override-manual] " + e + " external -> block")
        if has_v:
            _lg_set_vlight(v, cur, mode)


def _lg_apply_group(g, cfg, mode):
    g = _lg_season(g)
    if g.get("shadow"):
        mode = "shadow"
    lights = [e for e in (g.get("lights", []) or []) if e]
    v = _lg_vlight_entity(g)
    has_v = _lg_state(v) is not None

    # ручное управление и трекинг работают ВСЕГДА (даже до миграции)
    _lg_handle_vlight_change(g, cfg, mode, v, has_v)
    _lg_track_real(g, cfg, mode, v, has_v)

    # автоматика — только для мигрированных групп
    flag = g.get("feature_flag")
    if flag and _lg_state(flag) != "on":
        return

    dec = _lg_decide(g, cfg)
    if dec is None:
        return
    desired = dec["on"]
    if any([_lg_override_active(e) for e in lights]):
        return
    if has_v:
        _lg_set_vlight(v, desired, mode)
    for e in lights:
        if g.get("tolerate_unavailable") and _lg_unavailable(e):
            continue
        if _lg_expected_guard(e) is not None:
            continue
        if _lg_is_on(e) != desired:
            _lg_set_real(e, desired, mode, cfg)

# ---------------- color temp ----------------


def _lg_ct_target(cfg):
    ct = cfg.get("color_temp", {}) or {}
    day = int(_lg_num("input_number.ct_day_kelvin", ct.get("day_kelvin", 5000)))
    night = int(_lg_num("input_number.ct_night_kelvin", ct.get("night_kelvin", 2200)))
    warm = _lg_dt_min("input_datetime.ct_warm_from") or _lg_hm(ct.get("warm_from", "21:00"))
    nightf = _lg_dt_min("input_datetime.ct_night_from") or _lg_hm(ct.get("night_from", "23:00"))
    now = _lg_now_min()
    if warm is None or nightf is None or now <= warm:
        return day
    if now >= nightf:
        return night
    frac = (now - warm) / max(1, (nightf - warm))
    return int(day + (night - day) * frac)



def _lg_rgb_tick(cfg, mode):
    if _lg_state("input_boolean.feature_rgb") != "on":
        return
    scene = _lg_state("input_select.light_rgb_scene") or "Белый"
    for g in (cfg.get("groups", []) or []):
        for e in (g.get("lights", []) or []):
            if not e or str(e).split(".")[0] != "light":
                continue
            if not _lg_is_on(e):
                _RGB_APPLIED.pop(e, None)
                continue
            st = hass.states.get(e)
            modes = (st.attributes.get("supported_color_modes", []) or []) if st else []
            if not any([("rgb" in mm) for mm in modes]):
                continue
            if _RGB_APPLIED.get(e) == scene:
                continue
            _RGB_APPLIED[e] = scene
            rgb = _RGB_SCENES.get(scene, [255, 255, 255])
            if mode == "shadow":
                log.warning("[light][SHADOW][rgb] " + e + " -> " + scene)
            else:
                service.call("light", "turn_on", entity_id=e, rgb_color=rgb)
                log.warning("[light][REAL][rgb] " + e + " -> " + scene)

def _lg_ct_tick(cfg, mode):
    ct = cfg.get("color_temp", {}) or {}
    flag = ct.get("enabled_flag")
    if flag and _lg_state(flag) != "on":
        return
    target = _lg_ct_target(cfg)
    for g in (cfg.get("groups", []) or []):
        if not g.get("follow_global_ct"):
            continue
        gf = g.get("feature_flag")
        if gf and _lg_state(gf) != "on":
            continue
        for e in (g.get("lights", []) or []):
            if not e or str(e).split(".")[0] != "light":
                continue
            if not _lg_is_on(e):
                continue
            cur = _lg_attr(e, "color_temp_kelvin")
            if cur is None:
                continue
            if abs(cur - target) < 200:
                continue
            last = _CT_LAST.get(e, 0)
            if (time.monotonic() - last) < 300:
                continue
            _CT_LAST[e] = time.monotonic()
            if mode == "shadow":
                log.warning("[light][SHADOW][ct] " + e + " -> " + str(target) + "K")
            else:
                service.call("light", "turn_on", entity_id=e, color_temp_kelvin=target)
                log.warning("[light][REAL][ct] " + e + " -> " + str(target) + "K")


# ---------------- backlight выключателей ----------------

def _lg_backlight_tick(cfg, mode):
    bl = cfg.get("backlight", {}) or {}
    flag = bl.get("enabled_flag")
    if flag and _lg_state(flag) != "on":
        return
    now = _lg_now_min()
    for it in (bl.get("items", []) or []):
        e = it.get("entity")
        if not e:
            continue
        m = it.get("mode", "always")
        if m == "always":
            desired = True
        elif m == "off":
            desired = False
        elif m == "schedule":
            off = _lg_hm(it.get("off", "23:00"))
            on = _lg_hm(it.get("on", "07:00"))
            if off is None or on is None:
                continue
            inwin = (now >= off or now < on) if off > on else (now >= off and now < on)
            desired = not inwin
        else:
            continue
        cur = _lg_is_on(e)
        if cur == desired:
            continue
        if mode == "shadow":
            log.warning("[light][SHADOW][backlight] " + e + " -> " + ("on" if desired else "off"))
        else:
            service.call(str(e).split(".")[0], "turn_on" if desired else "turn_off", entity_id=e)
            log.warning("[light][REAL][backlight] " + e + " -> " + ("on" if desired else "off"))


# ---------------- имитация присутствия ----------------

def _lg_imitation_tick(cfg, mode):
    im = cfg.get("imitation", {}) or {}
    flag = im.get("enabled_flag")
    if flag and _lg_state(flag) != "on":
        return
    home = _lg_state(im.get("away_flag", "input_boolean.my_doma")) == "on"
    groups = {}
    for g in (cfg.get("groups", []) or []):
        groups[str(g["id"])] = g

    if home or not bool(_DARK):
        for e in list(_LG_IM_ACTIVE.keys()):
            pair = _LG_IM_ACTIVE.pop(e, None)
            if pair is None:
                continue
            if mode == "real":
                _lg_set_real(e, False, mode, cfg, force=True)
            _LG_OVERRIDE.pop(e, None)
            g = groups.get(str(pair[1]))
            if g is not None:
                v = _lg_vlight_entity(g)
                if _lg_state(v) is not None:
                    _VLIGHT_PREV[v] = "off"
                    _lg_set_vlight(v, False, mode)
            log.warning("[light][imit] " + e + " off (home/light)")
        return

    ws = _lg_dt_min(im.get("window_start"))
    we = _lg_dt_min(im.get("window_end"))
    now = _lg_now_min()
    if ws is not None and we is not None:
        inwin = (ws <= now < we) if we > ws else (now >= ws or now < we)
        if not inwin:
            return

    for e in list(_LG_IM_ACTIVE.keys()):
        pair = _LG_IM_ACTIVE.get(e)
        if pair is not None and time.monotonic() >= pair[0]:
            _LG_IM_ACTIVE.pop(e, None)
            if mode == "real":
                _lg_set_real(e, False, mode, cfg, force=True)
            _LG_OVERRIDE.pop(e, None)
            g = groups.get(str(pair[1]))
            if g is not None:
                v = _lg_vlight_entity(g)
                if _lg_state(v) is not None:
                    _VLIGHT_PREV[v] = "off"
                    _lg_set_vlight(v, False, mode)
            log.warning("[light][imit] " + e + " off (expired)")

    if not _LG_IM_ACTIVE and random.random() < 0.3:
        ids = [i for i in (im.get("groups", []) or []) if str(i) in groups]
        if ids:
            gid = random.choice(ids)
            lights = (groups[str(gid)].get("lights", []) or [])
            if lights:
                e = lights[0]
                mins = random.randint(im.get("min_on_min", 10), im.get("max_on_min", 30))
                g = groups[str(gid)]
                v = _lg_vlight_entity(g)
                _LG_OVERRIDE[e] = time.monotonic() + mins * 60
                if mode == "real":
                    _lg_set_real(e, True, mode, cfg, force=True)
                if _lg_state(v) is not None:
                    _VLIGHT_PREV[v] = "on"
                    _lg_set_vlight(v, True, mode)
                _LG_IM_ACTIVE[e] = (time.monotonic() + mins * 60, gid)
                log.warning("[light][imit] " + e + " on (" + str(mins) + "m)")


# ---------------- главный цикл ----------------

def _lg_tick():
    if _REGISTRY is None:
        return
    if _lg_state("input_boolean.feature_lighting") == "off":
        return
    cfg = _lg_cfg()
    if not cfg or not cfg.get("enabled", True):
        return
    _lg_update_dark(cfg)
    _lg_rebuild_light_map(cfg)
    mode = _lg_mode(cfg)
    for g in (cfg.get("groups", []) or []):
        try:
            _lg_apply_group(g, cfg, mode)
        except Exception as exc:
            log.error("[light] group " + str(g.get("id")) + " error: " + str(exc))
    try:
        _lg_ct_tick(cfg, mode)
        _lg_rgb_tick(cfg, mode)
        _lg_backlight_tick(cfg, mode)
        _lg_imitation_tick(cfg, mode)
    except Exception as exc:
        log.error("[light] tick error: " + str(exc))


@time_trigger("startup")
def lighting_controller_loop():
    log.info("[light] Controller loop started")
    while True:
        try:
            _lg_tick()
        except Exception as exc:
            log.error("[light] Controller error: " + str(exc))
        task.sleep(30)


# ---------------- кнопки ----------------

def _btn_build():
    global _BUTTON_MAP
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
    v = _lg_vlight_entity(g)
    sv = _lg_state(v)
    if sv is not None:
        cur_on = (sv == "on")
    else:
        lights_list = [e for e in (g.get("lights", []) or []) if e and not _lg_unavailable(e)]
        cur_on = any([_lg_is_on(e) for e in lights_list])
    log.warning("[button] " + var_name + " " + str(action) + " -> toggle " + str(cmd.get("toggle")))
    _lg_manual_command(cfg, g, not cur_on, _lg_mode(cfg))


# ---------------- мгновенная реакция на vlight ----------------

def _vlight_build_list():
    cfg = _lg_cfg() or {}
    out = []
    for g in (cfg.get("groups", []) or []):
        out.append(_lg_vlight_entity(g))
    return out if out else ["input_boolean.feature_lighting"]


_VLIGHT_LIST = _vlight_build_list()


@state_trigger(*_VLIGHT_LIST)
def _lg_vlight_handler(var_name=None, **kwargs):
    if _lg_state("input_boolean.feature_lighting") == "off":
        return
    cfg = _lg_cfg()
    if not cfg:
        return
    mode = _lg_mode(cfg)
    for g in (cfg.get("groups", []) or []):
        v = _lg_vlight_entity(g)
        if v != var_name:
            continue
        g2 = _lg_season(g)
        m = "shadow" if (mode == "shadow" or g2.get("shadow")) else "real"
        _lg_handle_vlight_change(g2, cfg, m, v, True)
        return
# ---------------- сервисы ----------------

@service
def light_debug():
    cfg = _lg_cfg()
    if not cfg:
        log.warning("[light][debug] no config")
        return {"ok": False}
    _lg_update_dark(cfg)
    log.warning("[light][debug] mode=" + str(_lg_mode(cfg)) + " dark=" + str(_DARK))
    for g in (cfg.get("groups", []) or []):
        g2 = _lg_season(g)
        gid = str(g.get("id"))
        v = _lg_vlight_entity(g2)
        dec = _lg_decide(g2, cfg)
        reals_parts = []
        for e in (g2.get("lights", []) or []):
            if not e:
                continue
            if _lg_unavailable(e):
                reals_parts.append("unavail")
            else:
                reals_parts.append("on" if _lg_is_on(e) else "off")
        reals = ",".join(reals_parts)
        ovr = [e for e in (g2.get("lights", []) or []) if e and _lg_override_active(e)]
        sel = _lg_state("input_select.light_" + gid + "_on")
        if sel is None:
            sel = "missing"
        vstate = _lg_state(v)
        if vstate is None:
            vstate = "missing"
        flag = g2.get("feature_flag")
        auto = "on" if (not flag or _lg_state(flag) == "on") else "off"
        log.warning("[light][debug] %s auto=%s sel=%s vlight=%s real=[%s] desired=%s override=%s"
                    % (gid, auto, sel, vstate, reals, dec, ovr))
    return {"ok": True}


@service
def light_override_clear(entity=None):
    if entity:
        _LG_OVERRIDE.pop(entity, None)
    else:
        _LG_OVERRIDE.clear()
    return {"ok": True}


@service
def vlight_toggle(group_id=None, on=None):
    """Ручная команда группе: toggle или явный on/off."""
    if group_id is None:
        return {"error": "group_id required"}
    cfg = _lg_cfg()
    if not cfg:
        return {"error": "no config"}
    groups = {}
    for g in (cfg.get("groups", []) or []):
        groups[str(g["id"])] = g
    g = groups.get(str(group_id))
    if not g:
        return {"error": "group not found: " + str(group_id)}
    if on is not None:
        on_val = str(on) in ("on", "true", "1", "True")
    else:
        v = _lg_vlight_entity(g)
        sv = _lg_state(v)
        if sv is not None:
            on_val = (sv != "on")
        else:
            lights_list = [e for e in (g.get("lights", []) or []) if e and not _lg_unavailable(e)]
            on_val = not any([_lg_is_on(e) for e in lights_list])
    _lg_manual_command(cfg, g, on_val, _lg_mode(cfg))
    return {"ok": True}