# ============================================================
# LIGHTING CONTROLLER v2.4 (vlight bus + select/time UI + buttons)
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


# ---------------- утилиты ----------------

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


def _lg_dt_min(entity):
    s = state.get(entity)
    if not s:
        return None
    try:
        return _lg_hm(str(s).split(" ")[1][:5])
    except Exception:
        return None


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
    """vlight группы: свой helper или усыновлённый легаси-boolean."""
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
    if state.get(v) == want:
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
        service.call(str(e).split(".")[0], "turn_on" if on else "turn_off", entity_id=e)
        _LG_LAST_CHANGE[e] = time.monotonic()
        log.warning("[light][REAL] " + e + " -> " + ("on" if on else "off"))


def _lg_manual_command(cfg, g, on, mode):
    """Ручная команда (vlight из UI/Алисы/кнопки): override + применение."""
    v = _lg_vlight_entity(g)
    if state.get(v) is not None:
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
    motion = _lg_motion(g)
    ov = g.get("override_flag")
    if ov and state.get(ov) == "on":
        return {"on": True}

    gid = str(g.get("id"))
    sel_val = state.get("input_select.light_" + gid + "_on")
    if sel_val == "Не включать":
        return {"on": False}

    if prof == "motion":
        if motion:
            _LG_MOTION_LAST[gid] = time.monotonic()
        last = _LG_MOTION_LAST.get(gid)
        mins = g.get("no_motion_night_min", 2) if night else g.get("no_motion_day_min", 5)
        hold = last is not None and (time.monotonic() - last) < mins * 60
        return {"on": bool(motion) or hold}

    if prof == "manual_auto":
        af = g.get("auto_flag")
        if not (af and state.get(af) == "on"):
            return None  # ручной режим, платформа не решает on/off

    # условие ВЫКЛ
    keep = bool(motion)
    off_mode = g.get("off", "23:00")
    if off_mode == "sunrise":
        if not dark and not keep:
            return {"on": False}
    else:
        off_min = _lg_hm(off_mode)
        if off_min is not None and now >= off_min and not keep:
            return {"on": False}

    # условие ВКЛ
    if sel_val == "Время":
        t_val = _lg_dt_min("input_datetime.light_" + gid + "_on_time")
        if t_val is not None and now >= t_val:
            return {"on": True}
        if motion and dark:
            return {"on": True}
        return {"on": False}

    on_mode = g.get("on", "sunset")
    if on_mode == "sunset":
        return {"on": dark}
    on_min = _lg_hm(on_mode)
    if on_min is not None:
        if now >= on_min and ((not g.get("require_dark", True)) or dark):
            return {"on": True}
        if motion and dark:
            return {"on": True}
    return {"on": False}


# ---------------- тик группы ----------------

def _lg_handle_vlight_change(g, cfg, mode, v, has_v):
    """Реагирует только на ФАКТ изменения vlight (ручная команда)."""
    if not has_v:
        return
    cur = state.get(v)
    prev = _VLIGHT_PREV.get(v)
    _VLIGHT_PREV[v] = cur
    if prev is None or prev == cur:
        return
    if _lg_vlight_guard_active(v):
        return  # наша синхронизация
    log.warning("[light][manual] " + v + " -> " + cur)
    _lg_manual_command(cfg, g, cur == "on", mode)


def _lg_track_real(g, cfg, mode, v, has_v):
    """Детект внешних изменений реальных ламп (физ. выключатель и т.п.)."""
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
                _EXPECTED_REAL_STATE.pop(e, None)  # наша команда подтверждена
            continue
        _LG_OVERRIDE[e] = time.monotonic() + cfg.get("override_timeout_min", 60) * 60
        log.warning("[light][override-manual] " + e + " external -> block")
        if has_v:
            _lg_set_vlight(v, cur, mode)


def _lg_apply_group(g, cfg, mode):
    g = _lg_season(g)
    flag = g.get("feature_flag")
    if flag and state.get(flag) != "on":
        return
    if g.get("shadow"):
        mode = "shadow"  # персональный shadow для постепенной миграции
    lights = [e for e in (g.get("lights", []) or []) if e]
    v = _lg_vlight_entity(g)
    has_v = state.get(v) is not None

    _lg_handle_vlight_change(g, cfg, mode, v, has_v)
    _lg_track_real(g, cfg, mode, v, has_v)

    dec = _lg_decide(g, cfg)
    if dec is None:
        return
    desired = dec["on"]
    if any(_lg_override_active(e) for e in lights):
        return  # ручное действие свежее — автоматика не вмешивается
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
    day = ct.get("day_kelvin", 5000)
    night = ct.get("night_kelvin", 2200)
    warm = _lg_hm(ct.get("warm_from", "21:00"))
    nightf = _lg_hm(ct.get("night_from", "23:00"))
    now = _lg_now_min()
    if warm is None or nightf is None or now <= warm:
        return day
    if now >= nightf:
        return night
    frac = (now - warm) / max(1, (nightf - warm))
    return int(day + (night - day) * frac)


def _lg_ct_tick(cfg, mode):
    ct = cfg.get("color_temp", {}) or {}
    flag = ct.get("enabled_flag")
    if flag and state.get(flag) != "on":
        return
    target = _lg_ct_target(cfg)
    for g in (cfg.get("groups", []) or []):
        if not g.get("follow_global_ct"):
            continue
        gf = g.get("feature_flag")
        if gf and state.get(gf) != "on":
            continue
        for e in (g.get("lights", []) or []):
            if not e or str(e).split(".")[0] != "light":
                continue
            if not _lg_is_on(e):
                continue
            try:
                cur = hass.states.get(e).attributes.get("color_temp_kelvin")
            except Exception:
                cur = None
            if cur is None or abs(cur - target) < 200:
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
    if flag and state.get(flag) != "on":
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
    if flag and state.get(flag) != "on":
        return
    home = state.get(im.get("away_flag", "input_boolean.my_doma")) == "on"
    groups = {str(g["id"]): g for g in (cfg.get("groups", []) or [])}

    def _kill(e, gid, why):
        g = groups.get(str(gid))
        v = _lg_vlight_entity(g) if g else None
        if mode == "real":
            _lg_set_real(e, False, mode, cfg, force=True)
        _LG_OVERRIDE.pop(e, None)
        if v and state.get(v) is not None:
            _VLIGHT_PREV[v] = "off"
            _lg_set_vlight(v, False, mode)
        log.warning("[light][imit] " + e + " off (" + why + ")")

    if home or not bool(_DARK):
        for e, (exp, gid) in list(_LG_IM_ACTIVE.items()):
            _kill(e, gid, "home/light")
        _LG_IM_ACTIVE.clear()
        return

    ws = _lg_dt_min(im.get("window_start"))
    we = _lg_dt_min(im.get("window_end"))
    now = _lg_now_min()
    if ws is not None and we is not None:
        inwin = (ws <= now < we) if we > ws else (now >= ws or now < we)
        if not inwin:
            return

    for e, (exp, gid) in list(_LG_IM_ACTIVE.items()):
        if time.monotonic() >= exp:
            _kill(e, gid, "expired")
            _LG_IM_ACTIVE.pop(e, None)

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
                if v and state.get(v) is not None:
                    _VLIGHT_PREV[v] = "on"
                    _lg_set_vlight(v, True, mode)
                _LG_IM_ACTIVE[e] = (time.monotonic() + mins * 60, gid)
                log.warning("[light][imit] " + e + " on (" + str(mins) + "m)")


# ---------------- главный цикл ----------------

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
    for g in (cfg.get("groups", []) or []):
        try:
            _lg_apply_group(g, cfg, mode)
        except Exception as exc:
            log.error("[light] group " + str(g.get("id")) + " error: " + str(exc))
    try:
        _lg_ct_tick(cfg, mode)
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


# ---------------- кнопки (future: entity появится позже) ----------------

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
    groups = {str(g["id"]): g for g in (cfg.get("groups", []) or [])}
    g = groups.get(str(cmd.get("toggle")))
    if not g:
        return
    v = _lg_vlight_entity(g)
    sv = state.get(v)
    cur_on = (sv == "on") if sv is not None else any(
        _lg_is_on(e) for e in (g.get("lights", []) or []) if not _lg_unavailable(e))
    log.warning("[button] " + var_name + " " + str(action) + " -> toggle " + str(cmd.get("toggle")))
    _lg_manual_command(cfg, g, not cur_on, _lg_mode(cfg))


# ---------------- сервисы диагностики ----------------

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
        reals = ",".join(
            ("on" if _lg_is_on(e) else "off") if not _lg_unavailable(e) else "unavail"
            for e in (g2.get("lights", []) or []) if e)
        ovr = [e for e in (g2.get("lights", []) or []) if e and _lg_override_active(e)]
        sel = state.get("input_select.light_" + gid + "_on")
        log.warning("[light][debug] %s sel=%s vlight=%s real=[%s] desired=%s override=%s"
                    % (gid, sel, state.get(v), reals, dec, ovr))
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
    groups = {str(g["id"]): g for g in (cfg.get("groups", []) or [])}
    g = groups.get(str(group_id))
    if not g:
        return {"error": "group not found: " + str(group_id)}
    if on is not None:
        on_val = str(on) in ("on", "true", "1", "True")
    else:
        v = _lg_vlight_entity(g)
        sv = state.get(v)
        on_val = (sv != "on") if sv is not None else not any(
            _lg_is_on(e) for e in (g.get("lights", []) or []) if not _lg_unavailable(e))
    _lg_manual_command(cfg, g, on_val, _lg_mode(cfg))
    return {"ok": True}