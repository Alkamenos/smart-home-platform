# ============================================================
# CLIMATE ORCHESTRATOR
# Конкатенируется ПОСЛЕ manifest_loader.py.
# Использует _REGISTRY, state, service, log, hass, task из общего контекста.
# ============================================================


# ---------- чтение числовых состояний ----------
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


# ---------- сезон ----------
def _clim_season_is_heating(season_cfg):
    source = season_cfg.get("source")
    if not source:
        return True
    flag_state = state.get(source)
    heating_when = season_cfg.get("heating_when", "on")
    return str(flag_state) == str(heating_when)


# ---------- чтение состояния устройства ----------
def _clim_state(entity):
    """Возвращает (hvac_mode/state, целевая_температура)."""
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


# ---------- отправка команд (только при переходе) ----------
_CLIM_LAST = {}


def _clim_send_on(entity, hvac, temp):
    service.call("climate", "set_temperature", entity_id=entity,
                 temperature=temp, hvac_mode=hvac)
    _CLIM_LAST[entity] = {"mode": hvac, "temp": temp}


def _clim_send_off(entity):
    service.call("climate", "set_hvac_mode", entity_id=entity, hvac_mode="off")
    _CLIM_LAST[entity] = {"mode": "off", "temp": None}


def _clim_switch(mode, entity, target_state, zone_id, kind, cur, target):
    msg = ("[" + str(zone_id) + "] " + str(kind) + " " + str(entity)
           + " -> " + str(target_state)
           + " (cur=" + str(cur) + " target=" + str(target) + ")")
    if mode == "shadow":
        log.warning("[climate][SHADOW] " + msg)
        return
    svc = "turn_on" if target_state == "on" else "turn_off"
    service.call(str(entity).split(".")[0], svc, entity_id=entity)
    log.warning("[climate][REAL] " + msg)


# ---------- оценка актуаторов нагрева ----------
def _clim_eval_heat_actuator(mode, dev, cur_temp, heat_target, deadband, zone_id):
    entity = dev.get("entity")
    if not entity:
        return
    domain = str(entity).split(".")[0]

    # Не-climate (switch/конвектор)
    if domain != "climate":
        is_on = _clim_is_on(entity)
        if cur_temp < (heat_target - deadband) and not is_on:
            _clim_switch(mode, entity, "on", zone_id, "HEAT", cur_temp, heat_target)
        elif cur_temp > (heat_target + deadband) and is_on:
            _clim_switch(mode, entity, "off", zone_id, "HEAT", cur_temp, heat_target)
        return

    # climate
    cur_mode, cur_set = _clim_state(entity)
    is_on = _clim_is_on(entity)
    should_on = cur_temp < (heat_target - deadband)
    should_off = cur_temp > (heat_target + deadband)
    if mode == "shadow":
        if should_on and not is_on:
            log.warning("[climate][SHADOW] [" + str(zone_id) + "] HEAT " + entity
                        + " -> on (cur=" + str(cur_temp) + " target=" + str(heat_target) + ")")
        elif should_off and is_on:
            log.warning("[climate][SHADOW] [" + str(zone_id) + "] HEAT " + entity
                        + " -> off (cur=" + str(cur_temp) + " target=" + str(heat_target) + ")")
        return
    desired = {"mode": "heat", "temp": heat_target}
    last = _CLIM_LAST.get(entity)
    if should_on:
        already_there = (cur_mode == "heat") and (cur_set == heat_target)
        wrong_mode = is_on and (cur_mode != "heat")
        if (not is_on) or wrong_mode or ((last != desired) and not already_there):
            log.warning("[climate][REAL] [" + str(zone_id) + "] HEAT " + entity
                        + " -> heat@" + str(heat_target))
            _clim_send_on(entity, "heat", heat_target)
    elif should_off and is_on:
        log.warning("[climate][REAL] [" + str(zone_id) + "] HEAT " + entity + " -> off")
        _clim_send_off(entity)


# ---------- оценка актуаторов охлаждения ----------
def _clim_eval_cool_actuator(mode, dev, cur_temp, cool_target, deadband, zone_id):
    entity = dev.get("entity")
    if not entity:
        return
    domain = str(entity).split(".")[0]

    # Не-climate (switch)
    if domain != "climate":
        is_on = _clim_is_on(entity)
        if cur_temp > (cool_target + deadband) and not is_on:
            _clim_switch(mode, entity, "on", zone_id, "COOL", cur_temp, cool_target)
        elif cur_temp < (cool_target - deadband) and is_on:
            _clim_switch(mode, entity, "off", zone_id, "COOL", cur_temp, cool_target)
        return

    # climate (кондиционер): конкретный режим, без auto
    cur_mode, cur_set = _clim_state(entity)
    is_on = _clim_is_on(entity)
    should_on = cur_temp > (cool_target + deadband)
    should_off = cur_temp < (cool_target - deadband)
    if mode == "shadow":
        if should_on and not is_on:
            log.warning("[climate][SHADOW] [" + str(zone_id) + "] COOL " + entity
                        + " -> on (cur=" + str(cur_temp) + " target=" + str(cool_target) + ")")
        elif should_off and is_on:
            log.warning("[climate][SHADOW] [" + str(zone_id) + "] COOL " + entity
                        + " -> off (cur=" + str(cur_temp) + " target=" + str(cool_target) + ")")
        return
    desired = {"mode": "cool", "temp": cool_target}
    last = _CLIM_LAST.get(entity)
    if should_on:
        already_there = (cur_mode == "cool") and (cur_set == cool_target)
        wrong_mode = is_on and (cur_mode != "cool")   # напр. застрял в auto
        if (not is_on) or wrong_mode or ((last != desired) and not already_there):
            log.warning("[climate][REAL] [" + str(zone_id) + "] COOL " + entity
                        + " -> cool@" + str(cool_target))
            _clim_send_on(entity, "cool", cool_target)
    elif should_off and is_on:
        log.warning("[climate][REAL] [" + str(zone_id) + "] COOL " + entity + " -> off")
        _clim_send_off(entity)


# ---------- оценка зоны ----------
def _clim_eval_zone(zone, mode, min_setpoint, heating_season):
    zone_id = zone.get("id", "unknown")

    temp_sensor_ref = zone.get("temp_sensor_ref")
    temp_sensor = _REGISTRY.device(temp_sensor_ref) or {}
    temp_entity = temp_sensor.get("entity")
    if not temp_entity:
        return
    cur_temp = _clim_get_float(temp_entity)
    if cur_temp is None:
        return

    setpoints = zone.get("setpoints") or {}
    heat_sp_entity = (setpoints.get("heat") or {}).get("source")
    cool_sp_entity = (setpoints.get("cool") or {}).get("source")
    deadband = setpoints.get("deadband", 0.5)

    heat_target = None
    if heat_sp_entity:
        heat_target = _clim_get_float(heat_sp_entity)
    cool_target = None
    if cool_sp_entity:
        cool_target = _clim_get_float(cool_sp_entity)

    # Аварийный минимум для нагрева
    if heat_target is not None and min_setpoint is not None:
        if heat_target < min_setpoint:
            log.warning("[climate][" + str(zone_id) + "] setpoint "
                        + str(heat_target)
                        + " ниже аварийного минимума, использую " + str(min_setpoint))
            heat_target = min_setpoint

    actuators = zone.get("actuators") or []
    for act in actuators:
        act_ref = act.get("ref")
        dev = _REGISTRY.device(act_ref) or {}
        if not dev.get("managed_by_platform", True):
            continue
        role = act.get("role", "")
        if heating_season and role in ("primary_heat", "secondary_heat"):
            if heat_target is not None:
                _clim_eval_heat_actuator(mode, dev, cur_temp, heat_target, deadband, zone_id)
        elif (not heating_season) and role in ("primary_cool", "free_cooling"):
            if cool_target is not None:
                _clim_eval_cool_actuator(mode, dev, cur_temp, cool_target, deadband, zone_id)


# ---------- режим из helper'ов дашборда ----------
def _clim_current_mode(climate_cfg):
    shadow_helper = state.get("input_boolean.climate_shadow_mode")
    if shadow_helper == "on":
        return "shadow"
    if shadow_helper == "off":
        return "real"
    return climate_cfg.get("mode", "real")


# ---------- тик ----------
def climate_orchestrator_tick():
    if _REGISTRY is None:
        return
    # Мастер-выключатель фичи с дашборда
    if state.get("input_boolean.feature_climate") == "off":
        return
    climate_cfg = _REGISTRY.feature("climate")
    if not climate_cfg:
        return
    if not climate_cfg.get("enabled", True):
        return
    mode = _clim_current_mode(climate_cfg)
    safety = climate_cfg.get("safety") or {}
    min_setpoint = safety.get("min_setpoint")
    season_cfg = climate_cfg.get("season") or {}
    heating_season = _clim_season_is_heating(season_cfg)

    for zone in climate_cfg.get("zones", []):
        _clim_eval_zone(zone, mode, min_setpoint, heating_season)


# ---------- фоновый цикл ----------
@time_trigger("startup")
def climate_orchestrator_loop():
    log.info("[climate] Orchestrator loop started")
    while True:
        try:
            climate_orchestrator_tick()
        except Exception as exc:
            log.error("[climate] Orchestrator error: " + str(exc))
        task.sleep(30)


# ---------- диагностика ----------
@service
def climate_debug():
    """Диагностика: текущее состояние всех зон климата."""
    if _REGISTRY is None:
        log.warning("[climate][debug] _REGISTRY is None")
        return
    climate_cfg = _REGISTRY.feature("climate")
    if not climate_cfg:
        log.warning("[climate][debug] climate feature not found")
        return

    log.warning("[climate][debug] mode=" + str(_clim_current_mode(climate_cfg)))
    season_cfg = climate_cfg.get("season") or {}
    heating_season = _clim_season_is_heating(season_cfg)
    log.warning("[climate][debug] heating_season=" + str(heating_season)
                + " (season source=" + str(season_cfg.get("source"))
                + ", flag=" + str(state.get(season_cfg.get("source"))) + ")")

    for zone in climate_cfg.get("zones", []):
        zone_id = zone.get("id", "unknown")
        temp_sensor_ref = zone.get("temp_sensor_ref")
        temp_sensor = _REGISTRY.device(temp_sensor_ref) or {}
        temp_entity = temp_sensor.get("entity")
        cur_temp = None
        if temp_entity:
            cur_temp = _clim_get_float(temp_entity)

        setpoints = zone.get("setpoints") or {}
        heat_sp_entity = (setpoints.get("heat") or {}).get("source")
        cool_sp_entity = (setpoints.get("cool") or {}).get("source")
        heat_target = None
        cool_target = None
        if heat_sp_entity:
            heat_target = _clim_get_float(heat_sp_entity)
        if cool_sp_entity:
            cool_target = _clim_get_float(cool_sp_entity)

        log.warning("[climate][debug] zone=" + str(zone_id)
                    + " temp_entity=" + str(temp_entity)
                    + " cur_temp=" + str(cur_temp)
                    + " heat_target=" + str(heat_target)
                    + " cool_target=" + str(cool_target))

        actuators = zone.get("actuators") or []
        for act in actuators:
            act_ref = act.get("ref")
            dev = _REGISTRY.device(act_ref) or {}
            entity = dev.get("entity")
            cur_mode, cur_set = (None, None)
            if entity:
                cur_mode, cur_set = _clim_state(entity)
            managed = dev.get("managed_by_platform", True)
            log.warning("[climate][debug]   actuator ref=" + str(act_ref)
                        + " entity=" + str(entity)
                        + " state=" + str(cur_mode)
                        + " set=" + str(cur_set)
                        + " managed=" + str(managed)
                        + " role=" + str(act.get("role")))
    return {"ok": True}