# ============================================================
# VENTILATION CONTROLLER (Vakio), Этап 2
# ============================================================
# Функции ventilation_fsm_run и ventilation_fsm_get_state доступны глобально после конкатенации
import time

_VENT_BOOST_START = {}
_VENT_FAN_START = {}
_VENT_LAST = {}   # {entity: {"preset": ..., "pct": ...}} - последнее отправленное состояние
_FREE_HEAT_ACTIVE = False   # читает климат-оркестратор

V_BASE_SUMMER = "Рекуперация (лето)"
V_BASE_WINTER ="Рекуперация (зима)"
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
    """Определение режима работы (всегда real, shadow режим удален)."""
    return "real"


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


def _vent_heating_lockout_active(cfg):
    """Проверяет, нужно ли прижать рекуператор из-за активного отопления."""
    lockout = cfg.get("heating_lockout", {}) or {}
    if not lockout.get("enabled", False):
        return None
    if state.get("input_boolean.feature_vent_heating_lockout") != "on":
        return None
    
    outdoor = _vent_get_float(cfg.get("sensors", {}).get("outdoor_temp"))
    street_max = _vent_get_float("input_number.vent_lockout_street_max")
    if street_max is None:
        street_max = lockout.get("street_max", 5)
    
    if outdoor is None or outdoor > street_max:
        return None  # улица тёплая, блокировка не нужна
    
    delta = _vent_get_float("input_number.vent_lockout_delta")
    if delta is None:
        delta = lockout.get("delta", 0.3)
    
    action = state.get("input_select.vent_lockout_action")
    if action in (None, "unknown", "unavailable"):
        action = lockout.get("action", "10")
    
    # Проверяем per-room
    for room in lockout.get("rooms", []) or []:
        room_id = room.get("id")
        temp_sensor = room.get("temp_sensor")
        zone_id = room.get("climate_zone")
        vent_device = room.get("vent_device")
        
        if not temp_sensor or not zone_id:
            continue
        
        room_temp = _vent_get_float(temp_sensor)
        if room_temp is None:
            continue
        
        # Получаем уставку отопления для этой зоны
        heat_setpoint = _clim_get_setpoint(zone_id, "heat")
        if heat_setpoint is None:
            continue
        
        # Условие: температура близка к минимуму
        if room_temp > heat_setpoint + delta:
            continue
        
        # Проверяем, активен ли обогрев в этой зоне
        if _clim_is_heating_active(zone_id):
            why_msg = "lockout: " + str(room_id) + " " + str(round(room_temp, 1)) + "° <= " + str(heat_setpoint) + "°+" + str(delta) + ", outdoor " + str(round(outdoor, 1)) + "°"
            return {
                "action": "lockout",
                "device": vent_device,
                "room": room_id,
                "mode": action,  # "OFF" или "10"/"20"/"30"
                "why": why_msg
            }
    
    return None


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




def _vent_build_fsm_ctx(cfg):
    """Строит контекст для автомата вентиляции.
    
    Args:
        cfg: конфигурация вентиляции из манифеста
        
    Returns:
        словарь контекста для ventilation_fsm_run()
    """
    # Получаем сенсоры
    sensors = cfg.get("sensors", {}) or {}
    outdoor_temp = _vent_get_float(sensors.get("outdoor_temp"))
    
    # Получаем CO2 и влажность (если есть сенсоры)
    co2_sensor = sensors.get("co2")
    humidity_sensor = sensors.get("humidity")
    co2_level = _vent_get_float(co2_sensor) if co2_sensor else 400
    humidity = _vent_get_float(humidity_sensor) if humidity_sensor else 50
    
    # Получаем контекст комнаты
    try:
        room_context = _cv_get_room_context()
    except Exception:
        room_context = "HOME_DAY"
    
    # Проверяем ночное время
    is_night = state.get("sun.sun") == "below_horizon"
    
    # Проверяем ручной режим
    manual_mode = False
    override_remaining_min = 0
    
    # Проверяем heating lockout
    heating_lockout = _vent_heating_lockout_active(cfg) is not None
    
    # Проверяем boost timer
    boost_remaining_min = 0
    for key, start_time in _VENT_BOOST_START.items():
        boost_minutes = cfg.get("boost_minutes", 60)
        remaining = boost_minutes * 60 - (time.monotonic() - start_time)
        if remaining > 0:
            boost_remaining_min = int(remaining / 60)
            break
    
    return {
        "co2_level": co2_level if co2_level else 400,
        "humidity": humidity if humidity else 50,
        "outdoor_temperature": outdoor_temp if outdoor_temp else 0,
        "indoor_temperature": 22.0,
        "manual_mode": manual_mode,
        "override_remaining_min": override_remaining_min,
        "heating_lockout": heating_lockout,
        "is_night": is_night,
        "room_context": room_context,
        "boost_remaining_min": boost_remaining_min,
    }


def _vent_convert_fsm_action(result):
    """Конвертирует действие FSM в формат для _vent_apply.
    
    Args:
        result: результат работы автомата {"state": ..., "action": ..., "why": ...}
        
    Returns:
        словарь в формате для _vent_apply()
    """
    state = result.get("state")
    action = result.get("action")
    why = result.get("why", "")
    
    if action is None:
        return None
    
    preset = action.get("preset")
    pct = action.get("pct")
    
    # Конвертируем preset в формат вентиляции
    if preset == "OFF":
        return {"action": "off", "why": why}
    elif preset == "Приток MAX":
        return {"preset": "Приток MAX", "pct": 100, "why": why}
    elif preset == "Рекуперация":
        # Определяем сезон
        zima = state.get("input_boolean.zima") == "on"
        preset_name = "Рекуперация (зима)" if zima else "Рекуперация (лето)"
        return {"preset": preset_name, "pct": pct, "why": why}
    else:
        return {"preset": preset, "pct": pct, "why": why}


def _vent_decide(cfg):
    global _FREE_HEAT_ACTIVE
    _FREE_HEAT_ACTIVE = False
    flags = cfg.get("flags", {}) or {}
    if state.get(flags.get("boost_intake")) =="on":
        return {"preset": V_BOOST_IN}
    if state.get(flags.get("boost_exhaust")) =="on":
        return {"preset": V_BOOST_EX}
    
    # НОВАЯ ПРОВЕРКА: heating lockout (приоритет выше обычных режимов, ниже boost)
    lockout = _vent_heating_lockout_active(cfg)
    if lockout is not None:
        device = lockout.get("device")
        mode = lockout.get("mode")
        if mode == "OFF":
            return {"action":"off", "device": device, "why": lockout.get("why")}
        else:
            pct = int(mode)  # "10" -> 10
            return {"action": "lockout", "device": device, "pct": pct, 
                    "preset": V_BASE_WINTER, "why": lockout.get("why")}
    
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

    # Night mode: умный выбор режима на основе температуры и сезона
    if state.get(flags.get("night")) =="on":
        # Ночью минимальная вентиляция, но с учётом условий
        night_speed = 10  # Минимальная скорость (10% вместо 1% для комфорта)
        if zima:
            # Зимой ночью: Рекуперация (зима) с минимальной скоростью
            return {"preset": V_BASE_WINTER, "pct": night_speed}
        else:
            # Летом ночью: проверяем, нужно ли охлаждение или просто вентиляция
            if temps and outdoor is not None:
                # Если на улице прохладнее чем дома - свободное охлаждение
                if max(temps) > (cool_target or 25) and outdoor < min(temps) - 2:
                    return {"preset": V_INTAKE, "pct": night_speed}
                # Иначе обычная рекуперация
            return {"preset": V_BASE_SUMMER, "pct": night_speed}
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
        
        # Получаем последнее отправленное состояние для этого устройства
        last = _VENT_LAST.get(entity, {})
        last_preset = last.get("preset")
        last_pct = last.get("pct")
        last_action = last.get("action")
        
        # НОВАЯ ПРОВЕРКА: применяем lockout только к нужному устройству
        if desired.get("action") == "lockout":
            if desired.get("device") != entity:
                continue  # пропускаем другие рекуператоры
            pct = desired.get("pct")
            preset = desired.get("preset", V_BASE_WINTER)
            why = desired.get("why", "lockout")
            service.call("fan", "set_preset_mode", entity_id=entity, preset_mode=preset)
            service.call("fan", "set_percentage", entity_id=entity, percentage=int(pct))
            _VENT_LAST[entity] = {"preset": preset, "pct": pct, "action": "lockout"}
            log_event("ventilation", "Предупреждения", str(entity) + " -> " + str(preset) + " pct=" + str(pct), why=why, src="автоматика")
            continue
        
        if desired.get("action") =="off":
            # Проверяем, нужно ли выключать (сравниваем с последним состоянием)
            should_turn_off = (cur_state != "off") and (last_action != "off")
            if should_turn_off:
                service.call("fan","turn_off", entity_id=entity)
                _VENT_LAST[entity] = {"action": "off"}
                log_event("ventilation", "Предупреждения", str(entity) + " -> off", why="решение автоматики", src="автоматика")
            continue
        
        preset = desired.get("preset")
        pct = desired.get("pct")
        
        # Проверяем, изменилось ли состояние по сравнению с последним отправленным
        preset_changed = (preset is not None) and (preset != last_preset)
        pct_changed = (pct is not None) and (last_pct is None or abs(pct - last_pct) > 2)
        
        # Также учитываем случай, когда устройство выключено
        state_changed = (cur_state == "off")
        
        if not (state_changed or preset_changed or pct_changed):
            continue
        
        if preset:
            service.call("fan","set_preset_mode", entity_id=entity, preset_mode=preset)
        if pct is not None:
            service.call("fan","set_percentage", entity_id=entity, percentage=int(pct))
        # Обновляем последнее отправленное состояние
        _VENT_LAST[entity] = {"preset": preset, "pct": pct}
        log_event("ventilation", "Предупреждения", str(entity) + " -> " + str(preset) + " pct=" + str(pct), why="смена режима", src="автоматика")

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
        service.call("fan","turn_on", entity_id=entity)
        _VENT_FAN_START[entity] = time.monotonic()
        log_event("ventilation", "Предупреждения", str(entity) + " -> on", why="влажность в ванной", src="датчик")
    elif is_on and ((not need) or (
            _VENT_FAN_START.get(entity) is not None
            and (time.monotonic() - _VENT_FAN_START[entity]) > run_min * 60)):
        service.call("fan","turn_off", entity_id=entity)
        _VENT_FAN_START.pop(entity, None)
        log_event("ventilation", "Предупреждения", str(entity) + " -> off", why="окончание вентиляции ванной", src="датчик")

def _vent_tick():
    if _REGISTRY is None:
        return
    if state.get("input_boolean.feature_ventilation") =="off":
        return
    cfg = _vent_cfg()
    if not cfg or not cfg.get("enabled", True):
        return
    mode = _vent_mode(cfg)
    # Используем FSM для вентиляции (для каждого устройства)
    fsm_ctx = _vent_build_fsm_ctx(cfg)
    fsm_result = None
    
    for dev in cfg.get("devices", []) or []:
        entity = dev.get("entity")
        if not entity:
            continue
        device_id = entity.replace("fan.", "")
        result = ventilation_fsm_run(device_id, fsm_ctx)
        if result and result.get("action") and fsm_result is None:
            fsm_result = result
    
    if fsm_result and fsm_result.get("action"):
        return _vent_convert_fsm_action(fsm_result)
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
        log_event("ventilation", "Отладка", "no ventilation config", why="инициализация", src="сервис")
        return
    lockout = _vent_heating_lockout_active(cfg)
    log_event("ventilation", "Отладка", "mode=" + str(_vent_mode(cfg))
                +" open_doors=" + str(_vent_open_doors(cfg))
                +" heating=" + str(_vent_any_heating())
                +" lockout=" + str(lockout is not None)
                +" free_heat=" + str(_FREE_HEAT_ACTIVE), why="диагностика", src="сервис")
    
    if lockout:
        log_event("ventilation", "Отладка", "lockout_reason=" + lockout.get("why"), why="блокировка нагревом", src="сервис")
    
    log_event("ventilation", "Отладка", "decide=" + str(_vent_decide(cfg)), why="диагностика", src="сервис")
    for dev in cfg.get("devices", []) or []:
        e = dev.get("entity")
        s, p, pct, _a = _vent_current(e)
        log_event("ventilation", "Отладка", str(e) + " state=" + str(s)
                    +" preset=" + str(p) +" pct=" + str(pct), why="диагностика", src="сервис")
    return {"ok": True}