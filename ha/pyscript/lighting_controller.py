# ============================================================
# LIGHTING CONTROLLER v1
# ============================================================
import time

_LG_PREV = {}
_LG_OVERRIDE = {}
_LG_LAST_CHANGE = {}
_LG_LAST_LOG = {}
_LG_MOTION_LAST = {}
_DARK = None


def _lg_cfg():
    if _REGISTRY is None:
        return None
    return _REGISTRY.feature("lighting") or None


def _lg_get_float(entity):
    v = state.get(entity)
    if v is None:
        return None
    s = str(v)
    if s in ("unknown", "unavailable", "none", ""):
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


def _lg_is_on(e):
    return state.get(e) == "on"


def _lg_unavailable(e):
    s = state.get(e)
    return s is None or str(s) in ("unknown", "unavailable")


def _lg_mode(cfg):
    sh = state.get("input_boolean.lighting_shadow_mode")
    if sh == "on":
        return "shadow"
    if sh == "off":
        return "real"
    return cfg.get("mode", "real")


def _lg_night(cfg):
    return state.get(cfg.get("night_flag", "input_boolean.vecher")) == "on"


def _lg_season(g):
    s = g.get("season")
    if not s:
        return g
    zima = state.get("input_boolean.zima") == "on"
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
    return state.get(ms) in ("on", "true", True)


def _lg_override_active(e):
    until = _LG_OVERRIDE.get(e)
    if until is None:
        return False
    if time.monotonic() >= until:
        del _LG_OVERRIDE[e]
        return False
    return True


def _lg_decide(g, cfg):
    g = _lg_season(g)
    prof = g.get("profile", "dusk_till_time")
    dark = bool(_DARK)
    now = _lg_now_min()
    night = _lg_night(cfg)
    motion = _lg_motion(g)
    ov = g.get("override_flag")
    if ov and state.get(ov) == "on":
        return {"on": True}

    if prof == "motion":
        if motion:
            _LG_MOTION_LAST[g["id"]] = time.monotonic()
        last = _LG_MOTION_LAST.get(g["id"])
        mins = g.get("no_motion_night_min", 2) if night else g.get("no_motion_day_min", 5)
        hold = last is not None and (time.monotonic() - last) < mins * 60
        return {"on": bool(motion) or hold}

    if prof == "manual_auto":
        af = g.get("auto_flag")
        if not (af and state.get(af) == "on"):
            return None  # ручной режим, платформа не решает

    # dusk_till_time / dusk_till_dawn / manual_auto(auto)
    keep = bool(motion)  # присутствие держит свет
    off_mode = g.get("off", "23:00")
    if off_mode == "sunrise":
        if not dark and not keep:
            return {"on": False}
    else:
        off_min = _lg_hm(off_mode)
        if off_min is not None and now >= off_min and not keep:
            return {"on": False}

    on_mode = g.get("on", "sunset")
    if on_mode == "sunset":
        if dark:
            return {"on": True}
        return {"on": False}
    on_min = _lg_hm(on_mode)
    if on_min is not None:
        if now >= on_min and ((not g.get("require_dark", True)) or dark):
            return {"on": True}
        if motion and dark:  # стемнело + кто-то есть → раньше
            return {"on": True}
    return {"on": False}


def _lg_set(e, on, mode):
    dom = str(e).split(".")[0]
    if on:
        service.call(dom, "turn_on", entity_id=e)
    else:
        service.call(dom, "turn_off", entity_id=e)


def _lg_apply_group(g, cfg, mode):
    g = _lg_season(g)
    flag = g.get("feature_flag")
    if flag and state.get(flag) != "on":
        return
    dec = _lg_decide(g, cfg)
    if dec is None:
        return
    desired = dec["on"]
    for e in g.get("lights", []) or []:
        if not e:
            continue
        if g.get("tolerate_unavailable") and _lg_unavailable(e):
            continue
        if _lg_override_active(e):
            continue
        cur = _lg_is_on(e)
        prev = _LG_PREV.get(e)
        if prev is not None and cur != prev and mode == "real":
            _LG_OVERRIDE[e] = time.monotonic() + cfg.get("override_timeout_min", 60) * 60
            log.warning("[light][override] " + e + " manual -> block")
        _LG_PREV[e] = cur
        if desired == cur:
            continue
        last_ch = _LG_LAST_CHANGE.get(e, 0)
        if (time.monotonic() - last_ch) < cfg.get("anti_cycle_min", 2) * 60:
            continue
        key = e
        if _LG_LAST_LOG.get(key) == desired:
            continue
        _LG_LAST_LOG[key] = desired
        if mode == "shadow":
            log.warning("[light][SHADOW] " + e + " -> " + ("on" if desired else "off"))
        else:
            _lg_set(e, desired, mode)
            _LG_LAST_CHANGE[e] = time.monotonic()
            log.warning("[light][REAL] " + e + " -> " + ("on" if desired else "off"))


def _lg_tick():
    if _REGISTRY is None:
        return
    if state.get("input_boolean.feature_lighting") == "off":
        return
    cfg = _lg_cfg()
    if not cfg or not cfg.get("enabled", True):
        return
    _lg_update_dark(cfg)
    mode = _lg_mode(cfg)
    for g in cfg.get("groups", []) or []:
        try:
            _lg_apply_group(g, cfg, mode)
        except Exception as exc:
            log.error("[light] group " + str(g.get("id")) + " error: " + str(exc))


@time_trigger("startup")
def lighting_controller_loop():
    log.info("[light] Controller loop started")
    while True:
        try:
            _lg_tick()
        except Exception as exc:
            log.error("[light] Controller error: " + str(exc))
        task.sleep(30)


@service
def light_debug():
    cfg = _lg_cfg()
    if not cfg:
        log.warning("[light][debug] no config")
        return
    _lg_update_dark(cfg)
    log.warning("[light][debug] mode=" + str(_lg_mode(cfg)) + " dark=" + str(_DARK))
    for g in cfg.get("groups", []) or []:
        d = _lg_decide(_lg_season(g), cfg)
        log.warning("[light][debug] " + str(g.get("id")) + " desired=" + str(d))
    return {"ok": True}