# ============================================================
# LIGHTING CONTROLLER v2 (vlight + select+time UI)
# ============================================================
import time
import random


_LG_PREV = {}
_LG_OVERRIDE = {}
_LG_LAST_CHANGE = {}
_LG_LAST_LOG = {}
_LG_MOTION_LAST = {}
_DARK = None
_CT_LAST = {}
_CT_APPLIED = {}
_VLIGHT_STATE = {}  # desired state для vlight
_SELECT_TIME_CACHE = {}  # кэш решений select+time


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
    for g in cfg.get("groups", []) or []:
        if not g.get("follow_global_ct"):
            continue
        gf = g.get("feature_flag")
        if gf and state.get(gf) != "on":
            continue
        for e in g.get("lights", []) or []:
            if not e or str(e).split(".")[0] != "light":
                continue
            if not _lg_is_on(e):
                continue
            try:
                cur = hass.states.get(e).attributes.get("color_temp_kelvin")
            except Exception:
                cur = None
            if cur is None:
                continue
            if abs(cur - target) < 200:
                continue
            last = _CT_LAST.get(e, 0)
            if (time.monotonic() - last) < 300:   # не чаще 5 мин
                continue
            _CT_LAST[e] = time.monotonic()
            if mode == "shadow":
                log.warning("[light][SHADOW][ct] " + e + " -> " + str(target) + "K")
            else:
                service.call("light", "turn_on", entity_id=e, color_temp_kelvin=target)
                log.warning("[light][REAL][ct] " + e + " -> " + str(target) + "K")


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

    # Проверяем select+time UI
    select_entity = "input_select.light_" + str(g.get("id")) + "_on"
    time_entity = "input_datetime.light_" + str(g.get("id")) + "_on_time"
    sel_val = state.get(select_entity)
    
    if sel_val == "Не включать":
        return {"on": False}
    elif sel_val == "Время":
        t_val = _lg_dt_min(time_entity)
        if t_val is not None:
            if now >= t_val:
                return {"on": True}
            else:
                return {"on": False}
    # sunset / Закат обрабатывается ниже как on_mode="sunset"

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
    
    # vlight-слой: обновляем виртуальную сущность
    gid = g.get("id")
    vlight_entity = "input_boolean.vlight_" + str(gid)
    cur_vlight = state.get(vlight_entity)
    if cur_vlight is not None:
        vlight_on = (cur_vlight == "on")
        # если vlight отличается от desired — это ручной override через UI/Алису
        if vlight_on != desired:
            # проверяем, не заблокированы ли мы
            for e in g.get("lights", []) or []:
                if not e:
                    continue
                if _lg_override_active(e):
                    continue  # всё ещё в override
            # это новая команда через vlight — применяем
            for e in g.get("lights", []) or []:
                if not e:
                    continue
                if g.get("tolerate_unavailable") and _lg_unavailable(e):
                    continue
                last_ch = _LG_LAST_CHANGE.get(e, 0)
                if (time.monotonic() - last_ch) < cfg.get("anti_cycle_min", 2) * 60:
                    continue
                if mode == "shadow":
                    log.warning("[light][SHADOW][vlight] " + e + " -> " + ("on" if desired else "off"))
                else:
                    _lg_set(e, desired, mode)
                    _LG_LAST_CHANGE[e] = time.monotonic()
                    log.warning("[light][REAL][vlight] " + e + " -> " + ("on" if desired else "off"))
            # синхронизируем кэш
            _VLIGHT_STATE[gid] = desired
    
    # основной цикл для реальных ламп (без vlight)
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


def _lg_backlight_tick(cfg, mode):
    bl = cfg.get("backlight", {}) or {}
    flag = bl.get("enabled_flag")
    if flag and state.get(flag) != "on":
        return
    now = _lg_now_min()
    for it in bl.get("items", []) or []:
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


_LG_IM_ACTIVE = {}


def _lg_dt_min(entity):
    s = state.get(entity)
    if not s:
        return None
    try:
        return _lg_hm(str(s).split(" ")[1][:5])
    except Exception:
        return None


def _lg_imitation_tick(cfg, mode):
    im = cfg.get("imitation", {}) or {}
    flag = im.get("enabled_flag")
    if flag and state.get(flag) != "on":
        return
    home = state.get(im.get("away_flag", "input_boolean.my_doma")) == "on"
    # гасим имитацию, если дома или флаг выкл
    if home or not bool(_DARK):
        for e in list(_LG_IM_ACTIVE):
            if mode == "real" and _lg_is_on(e):
                service.call(str(e).split(".")[0], "turn_off", entity_id=e)
                log.warning("[light][REAL][imit] " + e + " -> off")
            _LG_IM_ACTIVE.pop(e, None)
        return
    ws = _lg_dt_min(im.get("window_start"))
    we = _lg_dt_min(im.get("window_end"))
    now = _lg_now_min()
    if ws is not None and we is not None:
        inwin = (ws <= now < we) if we > ws else (now >= ws or now < we)
        if not inwin:
            return
    # гасим просроченные
    for e, exp in list(_LG_IM_ACTIVE.items()):
        if time.monotonic() >= exp:
            if mode == "real" and _lg_is_on(e):
                service.call(str(e).split(".")[0], "turn_off", entity_id=e)
                log.warning("[light][REAL][imit] " + e + " -> off")
            _LG_IM_ACTIVE.pop(e, None)
    # случайно включаем одну группу
    if not _LG_IM_ACTIVE and random.random() < 0.3:
        groups = {g["id"]: g for g in cfg.get("groups", []) or []}
        ids = [i for i in im.get("groups", []) or [] if i in groups]
        if ids:
            gid = random.choice(ids)
            lights = groups[gid].get("lights", []) or []
            if lights:
                e = lights[0]
                mins = random.randint(im.get("min_on_min", 10), im.get("max_on_min", 30))
                if mode == "real":
                    service.call(str(e).split(".")[0], "turn_on", entity_id=e)
                    log.warning("[light][REAL][imit] " + e + " -> on (" + str(mins) + "m)")
                else:
                    log.warning("[light][SHADOW][imit] " + e + " -> on (" + str(mins) + "m)")
                _LG_IM_ACTIVE[e] = time.monotonic() + mins * 60

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
    _lg_ct_tick(cfg, mode)
    _lg_backlight_tick(cfg, mode)
    _lg_imitation_tick(cfg, mode)


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
        gid = g.get("id")
        vlight_entity = "input_boolean.vlight_" + str(gid)
        vlight_state = state.get(vlight_entity)
        log.warning("[light][debug] " + str(gid) + " desired=" + str(d) + " vlight=" + str(vlight_state))
    return {"ok": True}

@service
def light_override_clear(entity=None):
    if entity:
        _LG_OVERRIDE.pop(entity, None)
    else:
        _LG_OVERRIDE.clear()
    return {"ok": True}

@service
def vlight_toggle(group_id=None):
    """Toggle vlight для группы. Вызывается кнопками."""
    if group_id is None:
        return {"error": "group_id required"}
    cfg = _lg_cfg()
    if not cfg:
        return {"error": "no config"}
    groups = {g["id"]: g for g in cfg.get("groups", []) or []}
    if group_id not in groups:
        return {"error": "group not found: " + str(group_id)}
    vlight_entity = "input_boolean.vlight_" + str(group_id)
    cur = state.get(vlight_entity)
    new_state = "off" if cur == "on" else "on"
    service.call("input_boolean", "turn_" + new_state, entity_id=vlight_entity)
    log.warning("[vlight][toggle] " + vlight_entity + " -> " + new_state)
    return {"ok": True, "entity": vlight_entity, "new_state": new_state}