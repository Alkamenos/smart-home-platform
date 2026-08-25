# ============================================================
# VENTILATION CONTROLLER (Vakio), Этап 2
# ============================================================
import time

_VENT_BOOST_START = {}
_VENT_FAN_START = {}
_FREE_HEAT_ACTIVE = False   # читает климат-оркестратор

V_BASE_SUMMER = "Рекуперация (лето)"
V_BASE_WINTER ="Рекуперация (зима)"
V_NIGHT ="Ночной"
V_BOOST_IN ="Приток MAX"
V_BOOST_EX ="Вытяжка MAX"
V_INTAKE ="Приток"


def _vent_cfg():
    if _REGISTRY is None:
        return None
    return _REGISTRY.feature("ventilation") or None


def _vent_get_float(entity):
    v = state.get(entity)
    if v is None:
        return None
    s = str(v)
    if s in ("unknown","unavailable","none",""):
        return None
    try:
        return float(s)
    except Exception:
        return None


def _vent_current(entity):
    try:
        st = hass.states.get(entity)
    except Exception:
        return (None, None, None, {})
    if st is None:
        return (None, None, None, {})
    attrs = st.attributes or {}
    return (st.state, attrs.get("preset_mode"), attrs.get("percentage"), attrs)


def _vent_mode(cfg):
    sh = state.get("input_boolean.ventilation_shadow_mode")
    if sh =="on":
        return"shadow"
    if sh =="off":
        return"real"
    return cfg.get("mode","real")


def _vent_open_doors(cfg):
    od = cfg.get("open_doors", {}) or {}
    flag = od.get("enabled_flag")
    if flag and state.get(flag) !="on":
        return False
    if od.get("mock"):
        return state.get(od.get("mock_state")) =="on"
    opened = False
    for s in od.get("sensors", []) or []:
        if state.get(s.get("entity")) in ("on","open","true", True):
            opened = True
    return opened


def _vent_any_heating():
    if _REGISTRY is None:
        return False
    climate_cfg = _REGISTRY.feature("climate") or {}
    for zone in climate_cfg.get("zones", []):
        for act in zone.get("actuators", []):
            if act.get("role") in ("primary_heat","secondary_heat"):
                dev = _REGISTRY.device(act.get("ref")) or {}
                if dev.get("managed_by_platform", True) and _clim_is_on(dev.get("entity")):
                    return True
    return False


def _vent_room_temps(cfg):
    temps = []
    for r in cfg.get("rooms", []) or []:
        t = _vent_get_float(r.get("temp"))
        if t is not None:
            temps.append(t)
    return temps


def _vent_free_pct(delta):
    return max(30, min(100, 30 + int(delta * 10)))


def _vent_winter_pct(cfg, outdoor, indoor):
    day = cfg["speeds"].get("day", 40)
    if outdoor is None:
        return day
    if outdoor >= 0:
        return day
    cold = min(abs(outdoor), 20)
    pct = day - cold * 2
    if indoor is not None and indoor < 20:
        pct -= 10
    return max(0, pct)


def _vent_decide(cfg):
    global _FREE_HEAT_ACTIVE
    _FREE_HEAT_ACTIVE = False
    flags = cfg.get("flags", {}) or {}
    if state.get(flags.get("boost_intake")) =="on":
        return {"preset": V_BOOST_IN}
    if state.get(flags.get("boost_exhaust")) =="on":
        return {"preset": V_BOOST_EX}
    zima = state.get("input_boolean.zima") =="on"
    sensors = cfg.get("sensors", {}) or {}
    outdoor = _vent_get_float(sensors.get("outdoor_temp"))
    temps = _vent_room_temps(cfg)
    sp_ref = cfg.get("setpoints_ref", {}) or {}
    heat_target = _vent_get_float(sp_ref.get("heat"))
    cool_target = _vent_get_float(sp_ref.get("cool"))
    deltas = cfg.get("deltas", {}) or {}

    if zima and outdoor is not None and outdoor < cfg.get("winter_pause_outdoor_max", -5):
        if _vent_any_heating():
            return {"action":"off"}
    if _vent_open_doors(cfg):
        return {"action":"off"}

    # Free heating: дома прохладно, на улице теплее → греем уличным теплом
    if temps and heat_target is not None and outdoor is not None:
        if min(temps) < heat_target and outdoor > max(temps) + deltas.get("free_heat", 2):
            _FREE_HEAT_ACTIVE = True
            return {"preset": V_INTAKE,"pct": _vent_free_pct(outdoor - max(temps))}
    # Free cooling: дома жарко, на улице холоднее → охлаждаем уличным воздухом
    if temps and cool_target is not None and outdoor is not None:
        if max(temps) > cool_target and outdoor < min(temps) - deltas.get("free_cool", 2):
            return {"preset": V_INTAKE,"pct": _vent_free_pct(min(temps) - outdoor)}

    if state.get(flags.get("night")) =="on":
        return {"preset": V_NIGHT}
    if zima:
        indoor = temps[0] if temps else None
        pct = _vent_winter_pct(cfg, outdoor, indoor)
        if pct <= 0:
            return {"action":"off"}
        return {"preset": V_BASE_WINTER,"pct": pct}
    if state.get(flags.get("away_home")) !="on":
        return {"preset": V_BASE_SUMMER,"pct": cfg["speeds"].get("away", 20)}
    return {"preset": V_BASE_SUMMER,"pct": cfg["speeds"].get("day", 40)}


def _vent_apply(cfg, desired, mode):
    for dev in cfg.get("devices", []) or []:
        entity = dev.get("entity")
        if not entity:
            continue
        cur_state, cur_preset, cur_pct, _a = _vent_current(entity)
        if desired.get("action") =="off":
            if cur_state !="off":
                if mode =="shadow":
                    log.warning("[vent][SHADOW]" + entity + " -> off")
                else:
                    service.call("fan","turn_off", entity_id=entity)
                    log.warning("[vent][REAL]" + entity + " -> off")
            continue
        preset = desired.get("preset")
        pct = desired.get("pct")
        changed = (cur_state =="off") or (preset and preset != cur_preset) \
            or (pct is not None and (cur_pct is None or abs(cur_pct - pct) > 2))
        if not changed:
            continue
        if mode =="shadow":
            log.warning("[vent][SHADOW]" + entity + " ->" + str(preset) + " pct=" + str(pct))
        else:
            if preset:
                service.call("fan","set_preset_mode", entity_id=entity, preset_mode=preset)
            if pct is not None:
                service.call("fan","set_percentage", entity_id=entity, percentage=int(pct))
            log.warning("[vent][REAL]" + entity + " ->" + str(preset) + " pct=" + str(pct))

def _vent_bathroom_fan(cfg, mode):
    bf = cfg.get("bathroom_fan", {}) or {}
    flag = bf.get("enabled_flag")
    if flag and state.get(flag) !="on":
        return
    entity = bf.get("entity")
    if not entity:
        return
    t = _vent_get_float(bf.get("temp_sensor"))
    h = _vent_get_float(bf.get("humidity_sensor"))
    if t is None or h is None:
        return
    t_min = bf.get("temp_min", 26)
    h_min = bf.get("humidity_min", 60)
    run_min = bf.get("run_minutes", 15)
    is_on = _clim_is_on(entity)
    need = (t > t_min) and (h > h_min)
    if need and not is_on:
        if mode =="shadow":
            log.warning("[vent][SHADOW][bath]" + entity + " -> on")
        else:
            service.call("fan","turn_on", entity_id=entity)
            _VENT_FAN_START[entity] = time.monotonic()
            log.warning("[vent][REAL][bath]" + entity + " -> on")
    elif is_on and ((not need) or (
            _VENT_FAN_START.get(entity) is not None
            and (time.monotonic() - _VENT_FAN_START[entity]) > run_min * 60)):
        if mode =="shadow":
            log.warning("[vent][SHADOW][bath]" + entity + " -> off")
        else:
            service.call("fan","turn_off", entity_id=entity)
            _VENT_FAN_START.pop(entity, None)
            log.warning("[vent][REAL][bath]" + entity + " -> off")

def _vent_tick():
    if _REGISTRY is None:
        return
    if state.get("input_boolean.feature_ventilation") =="off":
        return
    cfg = _vent_cfg()
    if not cfg or not cfg.get("enabled", True):
        return
    mode = _vent_mode(cfg)
    desired = _vent_decide(cfg)
    if desired.get("preset") in (V_BOOST_IN, V_BOOST_EX):
        key ="intake" if desired["preset"] == V_BOOST_IN else"exhaust"
        if key not in _VENT_BOOST_START:
            _VENT_BOOST_START[key] = time.monotonic()
        flags = cfg.get("flags", {}) or {}
        ent = flags.get("boost_" + key)
        if ent and (time.monotonic() - _VENT_BOOST_START[key]) > cfg.get("boost_minutes", 60) * 60:
            service.call("input_boolean","turn_off", entity_id=ent)
            _VENT_BOOST_START.pop(key, None)
    else:
        _VENT_BOOST_START.clear()
    _vent_apply(cfg, desired, mode)
    _vent_bathroom_fan(cfg, mode)


@time_trigger("startup")
def ventilation_controller_loop():
    log.info("[vent] Controller loop started")
    while True:
        try:
            _vent_tick()
        except Exception as exc:
            log.error("[vent] Controller error:" + str(exc))
        task.sleep(30)


@service
def vent_debug():
    cfg = _vent_cfg()
    if not cfg:
        log.warning("[vent][debug] no ventilation config")
        return
    log.warning("[vent][debug] mode=" + str(_vent_mode(cfg))
                +" open_doors=" + str(_vent_open_doors(cfg))
                +" heating=" + str(_vent_any_heating())
                +" free_heat=" + str(_FREE_HEAT_ACTIVE))
    log.warning("[vent][debug] decide=" + str(_vent_decide(cfg)))
    for dev in cfg.get("devices", []) or []:
        e = dev.get("entity")
        s, p, pct, _a = _vent_current(e)
        log.warning("[vent][debug]" + str(e) + " state=" + str(s)
                    +" preset=" + str(p) +" pct=" + str(pct))
    return {"ok": True}