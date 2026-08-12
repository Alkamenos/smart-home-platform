# ============================================================
# CLIMATE ORCHESTRATOR + OVERRIDE MANAGER (MVP, без глобального слушателя)
# Конкатенируется ПОСЛЕ manifest_loader.py.
# ============================================================
import time


def _clim_get_float(entity):
    val = state.get(entity)
    if val is None:
        return None
    sval = str(val)
    if sval in ("unknown", "unavailable", "none", ""):
        return None
    try:
        return float(sval)
    except Exception:
        return None


def _clim_season_is_heating(season_cfg):
    source = season_cfg.get("source")
    if not source:
        return True
    flag_state = state.get(source)
    heating_when = season_cfg.get("heating_when", "on")
    return str(flag_state) == str(heating_when)


def _clim_state(entity):
    try:
        st = hass.states.get(entity)
    except Exception:
        return (None, None)
    if st is None:
        return (None, None)
    mode = st.state
    temp = None
    attrs = st.attributes or {}
    if "temperature" in attrs:
        try:
            temp = float(attrs["temperature"])
        except Exception:
            temp = None
    return (mode, temp)


def _clim_is_on(entity):
    mode, _ = _clim_state(entity)
    if mode is None or mode in ("unknown", "unavailable", "none", ""):
        return False
    domain = str(entity).split(".")[0]
    if domain == "climate":
        return mode != "off"
    return mode == "on"


# ============================================================
# OVERRIDE MANAGER (опросный, без event_trigger)
# ============================================================
_CLIM_LAST = {}
_PLATFORM_CMD = {}
_OVERRIDE = {}
_PREV_STATE = {}
_MANAGED_SET = set()


def _clim_refresh_managed():
    global _MANAGED_SET
    s = set()
    if _REGISTRY is not None:
        climate_cfg = _REGISTRY.feature("climate") or {}
        for zone in climate_cfg.get("zones", []):
            for act in zone.get("actuators", []):
                dev = _REGISTRY.device(act.get("ref")) or {}
                if dev.get("managed_by_platform", True):
                    e = dev.get("entity")
                    if e:
                        s.add(e)
    _MANAGED_SET = s


def _clim_override_timeout():
    if _REGISTRY is None:
        return 3600
    climate_cfg = _REGISTRY.feature("climate") or {}
    try:
        return int(climate_cfg.get("override_timeout_min", 60)) * 60
    except Exception:
        return 3600


def _clim_record_cmd(entity):
    _PLATFORM_CMD[entity] = time.monotonic()


def _clim_override_active(entity):
    until = _OVERRIDE.get(entity)
    if until is None:
        return False
    if time.monotonic() >= until:
        del _OVERRIDE[entity]
        return False
    return True


def _clim_set_override(e, reason):
    timeout = _clim_override_timeout()
    _OVERRIDE[e] = time.monotonic() + timeout
    log.warning("[override] " + str(e) + " manual change (" + reason
                + ") -> block " + str(timeout) + "s")


def _clim_detect_manual(mode):
    if mode != "real":
        return
    now = time.monotonic()
    for e in _MANAGED_SET:
        cur_on = _clim_is_on(e)
        prev = _PREV_STATE.get(e)
        last = _PLATFORM_CMD.get(e)
        recent_cmd = last is not None and (now - last) < 10
        # Блок только если состояние ИЗМЕНИЛОСЬ и это не команда платформы
        if prev is not None and cur_on != prev and not recent_cmd:
            _clim_set_override(e, "state changed externally")
        _PREV_STATE[e] = cur_on

@service
def override_status():
    now = time.monotonic()
    active = {}
    for e, until in list(_OVERRIDE.items()):
        if until > now:
            active[e] = int(until - now)
    return {"ok": True, "active_overrides_sec": active}


@service
def override_clear(entity=None):
    if entity:
        _OVERRIDE.pop(entity, None)
    else:
        _OVERRIDE.clear()
    return {"ok": True}


# ============================================================
# отправка команд
# ============================================================
def _clim_send_on(entity, hvac, temp):
    service.call("climate", "set_temperature", entity_id=entity,
                 temperature=temp, hvac_mode=hvac)
    _CLIM_LAST[entity] = {"mode": hvac, "temp": temp}
    _clim_record_cmd(entity)


def _clim_send_off(entity):
    service.call("climate", "set_hvac_mode", entity_id=entity, hvac_mode="off")
    _CLIM_LAST[entity] = {"mode": "off", "temp": None}
    _clim_record_cmd(entity)


def _clim_switch(mode, entity, target_state, zone_id, kind, cur, target):
    msg = ("[" + str(zone_id) + "] " + str(kind) + " " + str(entity)
           + " -> " + str(target_state)
           + " (cur=" + str(cur) + " target=" + str(target) + ")")
    if mode == "shadow":
        log.warning("[climate][SHADOW] " + msg)
        return
    svc = "turn_on" if target_state == "on" else "turn_off"
    service.call(str(entity).split(".")[0], svc, entity_id=entity)
    _clim_record_cmd(entity)
    log.warning("[climate][REAL] " + msg)


def _clim_eval_heat_actuator(mode, dev, cur_temp, heat_target, deadband, zone_id):
    entity = dev.get("entity")
    if not entity or _clim_override_active(entity):
        return
    domain = str(entity).split(".")[0]
    if domain != "climate":
        is_on = _clim_is_on(entity)
        if cur_temp < (heat_target - deadband) and not is_on:
            _clim_switch(mode, entity, "on", zone_id, "HEAT", cur_temp, heat_target)
        elif cur_temp > (heat_target + deadband) and is_on:
            _clim_switch(mode, entity, "off", zone_id, "HEAT", cur_temp, heat_target)
        return
    cur_mode, cur_set = _clim_state(entity)
    is_on = _clim_is_on(entity)
    should_on = cur_temp < (heat_target - deadband)
    should_off = cur_temp > (heat_target + deadband)
    if mode == "shadow":
        if should_on and not is_on:
            log.warning("[climate][SHADOW] [" + str(zone_id) + "] HEAT " + entity + " -> on")
        elif should_off and is_on:
            log.warning("[climate][SHADOW] [" + str(zone_id) + "] HEAT " + entity + " -> off")
        return
    desired = {"mode": "heat", "temp": heat_target}
    last = _CLIM_LAST.get(entity)
    if should_on:
        already_there = (cur_mode == "heat") and (cur_set == heat_target)
        wrong_mode = is_on and (cur_mode != "heat")
        if (not is_on) or wrong_mode or ((last != desired) and not already_there):
            _clim_send_on(entity, "heat", heat_target)
    elif should_off and is_on:
        _clim_send_off(entity)


def _clim_eval_cool_actuator(mode, dev, cur_temp, cool_target, deadband, zone_id):
    entity = dev.get("entity")
    if not entity or _clim_override_active(entity):
        return
    domain = str(entity).split(".")[0]
    if domain != "climate":
        is_on = _clim_is_on(entity)
        if cur_temp > (cool_target + deadband) and not is_on:
            _clim_switch(mode, entity, "on", zone_id, "COOL", cur_temp, cool_target)
        elif cur_temp < (cool_target - deadband) and is_on:
            _clim_switch(mode, entity, "off", zone_id, "COOL", cur_temp, cool_target)
        return
    cur_mode, cur_set = _clim_state(entity)
    is_on = _clim_is_on(entity)
    should_on = cur_temp > (cool_target + deadband)
    should_off = cur_temp < (cool_target - deadband)
    if mode == "shadow":
        if should_on and not is_on:
            log.warning("[climate][SHADOW] [" + str(zone_id) + "] COOL " + entity + " -> on")
        elif should_off and is_on:
            log.warning("[climate][SHADOW] [" + str(zone_id) + "] COOL " + entity + " -> off")
        return
    desired = {"mode": "cool", "temp": cool_target}
    last = _CLIM_LAST.get(entity)
    if should_on:
        already_there = (cur_mode == "cool") and (cur_set == cool_target)
        wrong_mode = is_on and (cur_mode != "cool")
        if (not is_on) or wrong_mode or ((last != desired) and not already_there):
            _clim_send_on(entity, "cool", cool_target)
    elif should_off and is_on:
        _clim_send_off(entity)


def _clim_eval_zone(zone, mode, min_setpoint, heating_season):
    zone_id = zone.get("id", "unknown")
    temp_sensor = _REGISTRY.device(zone.get("temp_sensor_ref")) or {}
    temp_entity = temp_sensor.get("entity")
    if not temp_entity:
        return
    cur_temp = _clim_get_float(temp_entity)
    if cur_temp is None:
        return

    setpoints = zone.get("setpoints") or {}
    heat_sp = (setpoints.get("heat") or {}).get("source")
    cool_sp = (setpoints.get("cool") or {}).get("source")
    deadband = setpoints.get("deadband", 0.5)

    heat_target = _clim_get_float(heat_sp) if heat_sp else None
    cool_target = _clim_get_float(cool_sp) if cool_sp else None

    if heat_target is not None and min_setpoint is not None and heat_target < min_setpoint:
        log.warning("[climate][" + str(zone_id) + "] setpoint ниже минимума, использую "
                    + str(min_setpoint))
        heat_target = min_setpoint

    for act in zone.get("actuators", []):
        dev = _REGISTRY.device(act.get("ref")) or {}
        if not dev.get("managed_by_platform", True):
            continue
        role = act.get("role", "")
                if role in ("primary_heat", "secondary_heat"):
            if heat_target is not None:
                _clim_eval_heat_actuator(mode, dev, cur_temp, heat_target, deadband, zone_id)
        elif role in ("primary_cool", "free_cooling"):
            if cool_target is not None:
                _clim_eval_cool_actuator(mode, dev, cur_temp, cool_target, deadband, zone_id)
            if cool_target is not None:
                _clim_eval_cool_actuator(mode, dev, cur_temp, cool_target, deadband, zone_id)


def _clim_current_mode(climate_cfg):
    shadow_helper = state.get("input_boolean.climate_shadow_mode")
    if shadow_helper == "on":
        return "shadow"
    if shadow_helper == "off":
        return "real"
    return climate_cfg.get("mode", "real")


def climate_orchestrator_tick():
    if _REGISTRY is None:
        return
    if state.get("input_boolean.feature_climate") == "off":
        return
    climate_cfg = _REGISTRY.feature("climate")
    if not climate_cfg or not climate_cfg.get("enabled", True):
        return
    _clim_refresh_managed()
    mode = _clim_current_mode(climate_cfg)
    _clim_detect_manual(mode)
    safety = climate_cfg.get("safety") or {}
    min_setpoint = safety.get("min_setpoint")
    season_cfg = climate_cfg.get("season") or {}
    heating_season = _clim_season_is_heating(season_cfg)
    for zone in climate_cfg.get("zones", []):
        _clim_eval_zone(zone, mode, min_setpoint, heating_season)


@time_trigger("startup")
def climate_orchestrator_loop():
    log.info("[climate] Orchestrator loop started")
    _clim_refresh_managed()
    while True:
        try:
            climate_orchestrator_tick()
        except Exception as exc:
            log.error("[climate] Orchestrator error: " + str(exc))
        task.sleep(30)


@service
def climate_debug():
    if _REGISTRY is None:
        log.warning("[climate][debug] _REGISTRY is None")
        return
    climate_cfg = _REGISTRY.feature("climate")
    if not climate_cfg:
        log.warning("[climate][debug] climate feature not found")
        return
    log.warning("[climate][debug] mode=" + str(_clim_current_mode(climate_cfg)))
    season_cfg = climate_cfg.get("season") or {}
    log.warning("[climate][debug] heating_season=" + str(_clim_season_is_heating(season_cfg)))
    for zone in climate_cfg.get("zones", []):
        temp_sensor = _REGISTRY.device(zone.get("temp_sensor_ref")) or {}
        temp_entity = temp_sensor.get("entity")
        cur_temp = _clim_get_float(temp_entity) if temp_entity else None
        log.warning("[climate][debug] zone=" + str(zone.get("id")) + " cur_temp=" + str(cur_temp))
    return {"ok": True}