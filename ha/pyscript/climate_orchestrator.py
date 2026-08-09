# ============================================================
# CLIMATE ORCHESTRATOR
# Конкатенируется ПОСЛЕ manifest_loader.py.
# Использует _REGISTRY, state, service, log из общего контекста.
# ============================================================

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


def _clim_actuate(mode, entity, target_state, zone_id, kind, cur, target):
    msg = ("[" + str(zone_id) + "] " + str(kind) + " " + str(entity)
           + " -> " + str(target_state)
           + " (cur=" + str(cur) + " target=" + str(target) + ")")
    if mode == "shadow":
        log.warning("[climate][SHADOW] " + msg)
        return
    domain = str(entity).split(".")[0]
    svc = "turn_on" if target_state == "on" else "turn_off"
    service.call(domain, svc, entity_id=entity)
    log.warning("[climate][REAL] " + msg)


def _clim_eval_heat_actuator(mode, dev, cur_temp, heat_target, deadband, zone_id):
    entity = dev.get("entity")
    if not entity:
        return
    cur_state = state.get(entity)
    should_on = cur_temp < (heat_target - deadband)
    should_off = cur_temp > (heat_target + deadband)
    if should_on and cur_state != "on":
        _clim_actuate(mode, entity, "on", zone_id, "HEAT", cur_temp, heat_target)
    elif should_off and cur_state == "on":
        _clim_actuate(mode, entity, "off", zone_id, "HEAT", cur_temp, heat_target)


def _clim_eval_cool_actuator(mode, dev, cur_temp, cool_target, deadband, zone_id):
    entity = dev.get("entity")
    if not entity:
        return
    cur_state = state.get(entity)
    should_on = cur_temp > (cool_target + deadband)
    should_off = cur_temp < (cool_target - deadband)
    if should_on and cur_state != "on":
        _clim_actuate(mode, entity, "on", zone_id, "COOL", cur_temp, cool_target)
    elif should_off and cur_state == "on":
        _clim_actuate(mode, entity, "off", zone_id, "COOL", cur_temp, cool_target)


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


def climate_orchestrator_tick():
    if _REGISTRY is None:
        return
    climate_cfg = _REGISTRY.feature("climate")
    if not climate_cfg:
        return
    if not climate_cfg.get("enabled", True):
        return
    mode = climate_cfg.get("mode", "real")
    safety = climate_cfg.get("safety") or {}
    min_setpoint = safety.get("min_setpoint")
    season_cfg = climate_cfg.get("season") or {}
    heating_season = _clim_season_is_heating(season_cfg)

    for zone in climate_cfg.get("zones", []):
        _clim_eval_zone(zone, mode, min_setpoint, heating_season)


@time_trigger("startup")
def climate_orchestrator_loop():
    """Фоновый цикл: опрос зон климата каждые 30 секунд."""
    log.info("[climate] Orchestrator loop started")
    while True:
        try:
            climate_orchestrator_tick()
        except Exception as exc:
            log.error("[climate] Orchestrator error: " + str(exc))
        task.sleep(30)

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

    log.warning("[climate][debug] mode=" + str(climate_cfg.get("mode")))
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
            cur_state = None
            if entity:
                cur_state = state.get(entity)
            managed = dev.get("managed_by_platform", True)
            log.warning("[climate][debug]   actuator ref=" + str(act_ref)
                        + " entity=" + str(entity)
                        + " state=" + str(cur_state)
                        + " managed=" + str(managed)
                        + " role=" + str(act.get("role")))
    return {"ok": True}