# ============================================================
# LIGHTING CONTROLLER v2.9 (nightlight, motion dropdown, motion logging, debug logging)
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

# Глобальная настройка логирования
_LOG_LEVELS = {"CRITICAL": 0, "ERROR": 1, "WARNING": 2, "INFO": 3, "DEBUG": 4}
_LOG_LEVEL = _LOG_LEVELS.get("INFO", 3)  # по умолчанию
_MODULE_LOG_LEVELS = {}


def _lg_init_logging():
    """Инициализация уровней логирования из манифеста"""
    global _LOG_LEVEL, _MODULE_LOG_LEVELS
    if _REGISTRY is None:
        return
    cfg = _REGISTRY.feature("logging") or {}
    level_name = cfg.get("level", "INFO")
    _LOG_LEVEL = _LOG_LEVELS.get(level_name, 3)
    modules = cfg.get("modules", {})
    for mod, lvl in modules.items():
        _MODULE_LOG_LEVELS[mod] = _LOG_LEVELS.get(lvl, 3)


def _lg_log(module, level_name, msg):
    """Логирование с проверкой уровня"""
    level_val = _LOG_LEVELS.get(level_name, 3)
    module_level = _MODULE_LOG_LEVELS.get(module, _LOG_LEVEL)
    if level_val <= module_level:
        if level_name == "DEBUG":
            log.info("[light][DEBUG][" + module + "] " + msg)
        elif level_name == "INFO":
            log.info("[light][" + module + "] " + msg)
        else:
            log.warning("[light][" + module + "] " + msg)

_RGB_SCENES = {
    "Красный": [255, 0, 0],
    "Оранжевый": [255, 120, 0],
    "Зелёный": [0, 255, 0],
    "Синий": [0, 0, 255],
    "Фиолетовый": [160, 0, 255],
    "Розовый": [255, 60, 140],
}
_RGB_APPLIED = {}


# ---------------- безопасное чтение состояний ----------------

def _lg_state(entity):
    st = hass.states.get(entity)
    if st is None:
        return None
    return st.state


def _lg_attr(entity, name):
    st = hass.states.get(entity)
    if st is None:
        return None
    return st.attributes.get(name)


def _resolve_group(g):
    if not isinstance(g, dict) or "features" not in g:
        return g
    r = dict(g)
    f = g.get("features") or {}
    if not isinstance(f, dict):
        return g
    dusk = f.get("dusk")
    if dusk is not None and not isinstance(dusk, dict):
        dusk = {}
    sch = f.get("schedule") or {}
    if not isinstance(sch, dict):
        sch = {}
    mo = f.get("motion")
    if mo is not None and not isinstance(mo, dict):
        mo = None
    nl = f.get("nightlight")
    if nl is not None and not isinstance(nl, dict):
        nl = None
    ct = f.get("ct")
    if ct is not None and not isinstance(ct, dict):
        ct = None

    if dusk is not None:
        r.setdefault("require_dark", bool((dusk or {}).get("require_dark", False)))
        r.setdefault("on", "sunset")
    if sch:
        if sch.get("on") is not None:
            r["on"] = sch["on"]
        if sch.get("off") is not None:
            r["off"] = sch["off"]
        if sch.get("off_end") is not None:
            r["off_end"] = sch["off_end"]
        if sch.get("auto_flag"):
            r["auto_flag"] = sch["auto_flag"]
    if mo:
        r["motion_sensor"] = mo.get("sensor")
        r["motion_mode"] = mo.get("mode", "trigger")
        if mo.get("timeouts") == "own":
            r["motion_timeouts"] = "own"
        if mo.get("no_night_auto"):
            r["no_night_auto_flag"] = mo["no_night_auto"]
    if nl:
        r["nightlight"] = nl
    if ct and ct.get("follow"):
        r["follow_global_ct"] = True

    if "profile" not in r:
        if mo and not sch.get("on") and dusk is None:
            r["profile"] = "motion"
        elif sch.get("auto_flag"):
            r["profile"] = "manual_auto"
        elif str(r.get("off")) == "sunrise":
            r["profile"] = "dusk_till_dawn"
        else:
            r["profile"] = "dusk_till_time"

    if isinstance(r.get("season"), dict):
        se = dict(r["season"])
        for k in ("summer", "winter"):
            if isinstance(se.get(k), dict) and "features" in se[k]:
                se[k] = _resolve_group(se[k])
        r["season"] = se
    return r

def _lg_cfg():
    if _REGISTRY is None:
        return None
    # Инициализация логирования при первом вызове
    _lg_init_logging()
    cfg = _REGISTRY.feature("lighting") or None
    if not cfg:
        return None
    out = dict(cfg)
    raw_groups = _REGISTRY.feature("groups") or out.get("groups") or []
    groups = []
    for g in raw_groups:
        if not isinstance(g, dict):
            continue
        try:
            groups.append(_resolve_group(g))
        except Exception as ex:
            log.warning("[light] resolve failed: %s: %s" % (str(g.get("id")), str(ex)))
    out["groups"] = groups
    im_cfg = out.get("imitation")
    if im_cfg:
        im_cfg = dict(im_cfg)
        gl = list(im_cfg.get("groups", []) or [])
        for g in groups:
            if ((g.get("features") or {}).get("imitation") or {}).get("participate"):
                if str(g.get("id")) not in gl:
                    gl.append(str(g.get("id")))
        im_cfg["groups"] = gl
        out["imitation"] = im_cfg
    return out


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
        parts = str(s).split(" ")
        t = parts[1] if len(parts) > 1 else parts[0]
        return _lg_hm(t[:5])
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


def _lg_motion_sensor(g, gid):
    """Прочитать текущий датчик движения из helper'а или манифеста."""
    helper = "input_select.light_%s_motion_sensor" % gid
    val = _lg_state(helper)
    if val and val not in ("unknown", "unavailable", ""):
        return val
    return g.get("motion_sensor")


def _lg_motion(g, gid):
    ms = _lg_motion_sensor(g, gid)
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

def lg_vlight_entity(g):
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


_LG_NL_ACTIVE = set()


def _lg_group(cfg, gid):
    for g in (cfg.get("groups", []) or []):
        if str(g.get("id")) == gid:
            return g
    return None


def _lg_set_real(e, on, mode, cfg, force=False, nightlight=False, gid=None):
    already = _lg_is_on(e) == on
    restoring = on and not nightlight and (e in _LG_NL_ACTIVE)
    
    # Если восстанавливаем свет после ночника - нужно применить профиль
    if restoring:
        log.warning("[light][REAL][restore] " + e + " applying profile after nightlight")
        _LG_NL_ACTIVE.discard(e)
        # Не возвращаем, продолжаем применять настройки профиля
    elif already:
        return
    
    if not force and not restoring:
        last = _LG_LAST_CHANGE.get(e, 0)
        if (time.monotonic() - last) < cfg.get("anti_cycle_min", 2) * 60:
            return
    _EXPECTED_REAL_STATE[e] = {"state": on, "until": time.monotonic() + 30}
    if mode == "shadow" and not force:
        log.warning("[light][SHADOW] " + e + " -> " + ("on" if on else "off"))
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
            log.warning("[light][REAL][nightlight] " + e + " -> on b=" + str(b))
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
    log.warning("[light][REAL] " + e + " -> " + ("on" if on else "off"))



def _lg_manual_command(cfg, g, on, mode):
    v = lg_vlight_entity(g)
    if _lg_state(v) is not None:
        _VLIGHT_PREV[v] = "on" if on else "off"
        _lg_set_vlight(v, on, "real")   # было: mode
    for e in (g.get("lights", []) or []):
        if not e:
            continue
        if g.get("tolerate_unavailable") and _lg_unavailable(e):
            continue
        _LG_OVERRIDE[e] = time.monotonic() + cfg.get("override_timeout_min", 60) * 60
        _lg_set_real(e, on, "real", cfg, force=True)   # было: mode

# ---------------- решение автоматики ----------------


_LG_CAPS = {}

RGB_MODES = ["rgb", "hs", "xy", "rgbw", "rgbww"]


def _lg_caps(g):
    gid = str(g.get("id"))
    if gid in _LG_CAPS:
        return _LG_CAPS[gid]
    caps = {}
    ov = g.get("caps") or {}
    for e in (g.get("lights", []) or []):
        if not e or str(e).split(".")[0] != "light":
            continue
        scm = _lg_attr(e, "supported_color_modes") or []
        caps = {"dim": any([m != "on_off" for m in scm]),
                "ct": "color_temp" in scm,
                "rgb": any([m in RGB_MODES for m in scm])}
        break
    if not caps:
        caps = {"dim": False, "ct": False, "rgb": False}
    for k in ("dim", "ct", "rgb"):
        if k in ov:
            caps[k] = bool(ov[k])
    _LG_CAPS[gid] = caps
    return caps


@service
def light_caps():
    cfg = _lg_cfg()
    if cfg is None:
        return
    out = {}
    for g in (cfg.get("groups", []) or []):
        out[str(g.get("id"))] = _lg_caps(g)
    state.set("sensor.light_caps", "ok", caps=out)
    log.warning("[light][caps] %s" % str(out))


def _lg_decide(g, cfg):
    g = _lg_season(g)
    ctx = _lg_decide_ctx(g, cfg)
    ov = g.get("override_flag")
    if ov and _lg_state(ov) == "on":
        return {"on": True, "why": "override_flag"}
    gid = str(g.get("id"))
    _lg_log("decide", "DEBUG", "gid=%s: started, prof=%s dark=%s night=%s any_on=%s" % (gid, ctx.get("prof"), ctx.get("dark"), ctx.get("night"), ctx.get("any_on")))
    for voter in _FD_REGISTRY:
        vote = voter(g, cfg, ctx)
        voter_name = getattr(voter, "__name__", str(voter))
        if vote is _FD_ABORT:
            _lg_log("decide", "DEBUG", "gid=%s: voter %s aborted" % (gid, voter_name))
            return None
        if vote is not None:
            _lg_log("decide", "DEBUG", "gid=%s: voter %s returned %s" % (gid, voter_name, str(vote)))
            return vote
    result = {"on": False, "why": "нет решения"}
    _lg_log("decide", "DEBUG", "gid=%s: no voters matched, result=%s" % (gid, str(result)))
    return result



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
    v = lg_vlight_entity(g)
    has_v = _lg_state(v) is not None
    gid = str(g.get("id"))

    _lg_handle_vlight_change(g, cfg, mode, v, has_v)
    _lg_track_real(g, cfg, mode, v, has_v)

    flag = g.get("feature_flag")
    if flag and _lg_state(flag) != "on":
        return

    dec = _lg_decide(g, cfg)
    if dec is None:
        return
    desired = dec["on"]
    if mode == "shadow":
        cur = [_lg_is_on(e) for e in lights]
        if any([c != desired for c in cur]):
            log.warning("[light][SHADOW][decide] %s desired=%s why=%s dark=%s"
                        % (str(g.get("id")), str(desired), str(dec.get("why", "")), str(bool(_DARK))))
    
    nightlight = dec.get("nightlight", False)

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
            _lg_set_real(e, desired, mode, cfg, nightlight=nightlight, gid=gid)


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
        gid = str(g.get("id"))
        cf = _lg_state("input_boolean.light_%s_ct_follow" % gid)
        if cf is None:
            cf = "on" if g.get("follow_global_ct") else "off"
        if cf != "on":
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
                v = lg_vlight_entity(g)
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
                v = lg_vlight_entity(g)
                if _lg_state(v) is not None:
                    _VLIGHT_PREV[v] = "off"
                    _lg_set_vlight(v, False, mode)
            log.warning("[light][imit] " + e + " off (expired)")

    if not _LG_IM_ACTIVE and random.random() < 0.3:
        ids = []
        for i in (im.get("groups", []) or []):
            i = str(i)
            if i not in groups:
                continue
            hh = _lg_state("input_boolean.light_%s_imitation" % i)
            if hh is not None and hh != "on":
                continue
            ids.append(i)
        if ids:
            gid = random.choice(ids)
            lights = (groups[str(gid)].get("lights", []) or [])
            if lights:
                e = lights[0]
                mins = random.randint(im.get("min_on_min", 10), im.get("max_on_min", 30))
                g = groups[str(gid)]
                v = lg_vlight_entity(g)
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
    v = lg_vlight_entity(g)
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
        out.append(lg_vlight_entity(g))
    return out if out else ["input_boolean.feature_lighting"]


_VLIGHT_LIST = _vlight_build_list()


@state_trigger(*_VLIGHT_LIST)
def _lg_vlight_handler(var_name=None, **kwargs):
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


# ---------------- мгновенная реакция на движение ----------------

def _motion_build_list():
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
        v = lg_vlight_entity(g2)
        dec = _lg_decide(g2, cfg)
        reals_parts = []
        for e in (g2.get("lights", []) or []):
            if not e:
                continue
            if _lg_unavailable(e):
                reals_parts.append("unavail")
            else:
                reals_parts.append("on" if _lg_is_on(e) else "off")
        reals = ", ".join(reals_parts)
        ovr = [e for e in (g2.get("lights", []) or []) if e and _lg_override_active(e)]
        sel = _lg_state("input_select.light_" + gid + "_on")
        if sel is None:
            sel = "missing"
        vstate = _lg_state(v)
        if vstate is None:
            vstate = "missing"
        flag = g2.get("feature_flag")
        auto = "on" if (not flag or _lg_state(flag) == "on") else "off"
        ms = _lg_motion_sensor(g2, gid)
        log.warning("[light][debug] %s auto=%s sel=%s vlight=%s real=[%s] desired=%s override=%s motion_sensor=%s"
                    % (gid, auto, sel, vstate, reals, dec, ovr, ms))
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
        v = lg_vlight_entity(g)
        sv = _lg_state(v)
        if sv is not None:
            on_val = (sv != "on")
        else:
            lights_list = [e for e in (g.get("lights", []) or []) if e and not _lg_unavailable(e)]
            on_val = not any([_lg_is_on(e) for e in lights_list])
    _lg_manual_command(cfg, g, on_val, _lg_mode(cfg))
    return {"ok": True}