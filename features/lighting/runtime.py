#!/usr/bin/env python3
"""Runtime: главный цикл и применение решений к группам."""

from .fsm import light_fsm_run, light_fsm_get_state, _LIGHT_FSM_STATE


# Хранилище предыдущих состояний FSM для каждой группы
_LIGHT_FSM_PREV_STATE = {}


def _lg_publish_fsm_states():
    """Публикует состояния FSM всех групп в сенсоры sensor.<group>_fsm_state."""
    for gid, state_info in _LIGHT_FSM_STATE.items():
        entity_id = "sensor.light_%s_fsm_state" % gid
        state = state_info.get("state", "OFF")
        why = state_info.get("why", "")
        last_transition = state_info.get("last_transition", 0)
        
        # Формируем атрибуты
        attrs = {
            "friendly_name": "FSM состояние группы %s" % gid,
            "last_transition": last_transition,
            "transition_reason": why
        }
        
        # Публикуем состояние
        try:
            state.set(entity_id, state, attributes=attrs)
        except Exception as e:
            log.error("[light] Failed to publish FSM state for group %s: %s" % (gid, str(e)))


def _lg_update_fsm_overview():
    """Обновляет агрегированный сенсор fsm_overview состояниями освещения."""
    try:
        overview = {}
        for gid, state_info in _LIGHT_FSM_STATE.items():
            entity_id = "light_%s" % gid
            overview[entity_id] = state_info.get("state", "OFF")
        
        # Публикуем в сенсор fsm_overview с обновлением таймстампа
        from datetime import datetime
        state.set("sensor.fsm_overview", str(len(overview)),
                  count=str(len(overview)),
                  states=str(overview),
                  updated_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    except Exception as e:
        log.error("[light] Failed to update fsm_overview: %s" % str(e))


def _lg_fsm_status_all():
    """Возвращает краткий статус всех автоматов освещения.
    
    Returns:
        словарь {gid: {"state": ..., "why": ...}, ...}
    """
    result = {}
    for gid, state_info in _LIGHT_FSM_STATE.items():
        result[gid] = {
            "state": state_info.get("state", "OFF"),
            "why": state_info.get("why", ""),
            "last_transition": state_info.get("last_transition", 0)
        }
    return result


def _lg_fsm_debug(gid):
    """Полная диагностика автомата для конкретной группы.
    
    Args:
        gid: идентификатор группы
    
    Returns:
        словарь с полной информацией об автомате
    """
    from .fsm import light_fsm_definition, fsm_build_events
    
    # Находим группу по gid
    cfg = _lg_cfg()
    group = None
    if cfg:
        for g in (cfg.get("groups", []) or []):
            if str(g.get("id")) == str(gid):
                group = g
                break
    
    if not group:
        return {"error": "Группа %s не найдена" % gid}
    
    fsm_def = light_fsm_definition(group)
    current_state = light_fsm_get_state(gid)
    state_info = _LIGHT_FSM_STATE.get(gid, {})
    
    # Строим текущий контекст
    ctx = _lg_decide_ctx(group, cfg)
    fsm_ctx = _lg_build_fsm_ctx(group, ctx)
    events = fsm_build_events(fsm_ctx)
    
    return {
        "group_id": gid,
        "fsm_type": fsm_def.get("states", []),
        "current_state": current_state,
        "last_transition": state_info.get("last_transition", 0),
        "transition_reason": state_info.get("why", ""),
        "active_events": events,
        "fsm_enabled": group.get("fsm_enabled", False)
    }


def _lg_build_fsm_ctx(g, ctx):
    """Преобразует контекст decide.py в контекст для FSM.
    
    Args:
        g: конфигурация группы
        ctx: контекст из _lg_decide_ctx
    
    Returns:
        словарь событий для fsm_build_events
    """
    gid = str(g.get("id"))
    features = g.get("features") or {}
    
    # Чтение контекста комнаты
    try:
        room_ctx = _cv_get_room_context()
    except Exception:
        room_ctx = "EMPTY"  # Fallback при отсутствии контекста
    
    # Определяем профиль включения/выключения
    sel_on = ctx.get("sel_on", "")
    sel_off = ctx.get("sel_off", "")
    prof = ctx.get("prof", "")
    
    # События расписания
    schedule_on = False
    schedule_off = False
    
    if sel_on == "Время":
        # Проверяем время включения
        t_val = _lg_dt_min("input_datetime.light_%s_on_time" % gid)
        if t_val is not None and ctx.get("now") >= t_val:
            schedule_on = True
    elif sel_on == "Закат" or prof == "dusk_till_time":
        if ctx.get("dark"):
            schedule_on = True
    
    if sel_off == "Рассвет":
        if not ctx.get("dark") and not ctx.get("presence"):
            schedule_off = True
    elif sel_off == "Время":
        off_min = _lg_dt_min("input_datetime.light_%s_off_time" % gid)
        if off_min is not None and ctx.get("now") >= off_min:
            schedule_off = True
    
    # События движения
    motion = ctx.get("presence", False)
    no_motion_timeout = not motion and ctx.get("ms") is not None
    nightlight_timeout = False  # Обрабатывается отдельно
    
    # Вечеринка
    party_mode = _lg_state("input_boolean.party_mode") == "on"
    party_ended = False
    
    # Имитация присутствия
    imitation_on = False
    imitation_off = False
    
    # Ручное вмешательство
    manual_change = False
    
    # Проверка доступности устройств
    device_available = True
    for e in (g.get("lights", []) or []):
        if e and _lg_unavailable(e):
            device_available = False
            break
    
    return {
        "schedule_on": schedule_on,
        "schedule_off": schedule_off,
        "motion": motion,
        "no_motion_timeout": no_motion_timeout,
        "nightlight_timeout": nightlight_timeout,
        "night": ctx.get("night", False),
        "nightlight_enabled": bool(features.get("nightlight")),
        "motion_day": ctx.get("mday", False),
        "dark": ctx.get("dark", False),
        "party_mode": party_mode,
        "party_ended": party_ended,
        "imitation_on": imitation_on,
        "imitation_off": imitation_off,
        "manual_change": manual_change,
        "away": room_ctx == "EMPTY",  # AWAY когда комната EMPTY
        "timeout_expired": False,
        "override_cleared": False,
        "room_context": room_ctx,
        "device_available": device_available
    }


def _lg_decide(g, cfg):
    """Принятие решения для группы через voters или FSM."""
    g = _lg_season(g)
    ctx = _lg_decide_ctx(g, cfg)
    ov = g.get("override_flag")
    if ov and _lg_state(ov) == "on":
        return {"on": True, "why": "override_flag"}
    gid = str(g.get("id"))
    
    # Проверяем, включен ли FSM для этой группы
    use_fsm = g.get("fsm_enabled", False)
    fsm_shadow = g.get("fsm_shadow", False)
    
    if use_fsm:
        # Используем FSM
        fsm_ctx = _lg_build_fsm_ctx(g, ctx)
        fsm_result = light_fsm_run(g, fsm_ctx)
        
        if fsm_result and fsm_result.get("action"):
            action = fsm_result["action"]
            why = fsm_result.get("why", "FSM")
            state = fsm_result.get("state", "UNKNOWN")
            
            if fsm_shadow:
                # Shadow mode: логируем решение FSM, но исполняем старую логику
                _lg_log("fsm", "INFO", "gid=%s: SHADOW state=%s why=%s" % (gid, state, why))
                # Продолжаем со старой логикой decide.py
            else:
                # Реальный режим: исполняем решение FSM
                _lg_log("fsm", "INFO", "gid=%s: state=%s why=%s" % (gid, state, why))
                return {"on": action.get("on", False), "why": why}
        elif fsm_result and fsm_shadow:
            # FSM не принял решение, но мы в shadow mode
            _lg_log("fsm", "DEBUG", "gid=%s: SHADOW no action from FSM" % gid)
    
    # Используем старую логику voters
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
    """Обработка изменения vlight (ручная команда)."""
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
    log_event("lighting", "Инфо", v + " -> " + cur, why="изменение vlight", src="ручное")
    _lg_manual_command(cfg, g, cur == "on", mode)


def _lg_track_real(g, cfg, mode, v, has_v):
    """Отслеживание изменений реальных ламп (детект ручного вмешательства)."""
    
    gid = str(g.get("id"))
    ms = _lg_motion_sensor(g, gid)
    motion_mode = None
    if ms:
        motion_mode = _lg_state("input_select.light_%s_motion_mode" % gid)
    has_motion = ms is not None and motion_mode not in (None, "unknown", "unavailable", "Выкл")

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

        # Переход из unavailable не считать ручным вмешательством
        if prev is None and _lg_unavailable(e):
            log_event("lighting", "Инфо", "gid=" + gid + ": skip override (from unavailable)", why="восстановление доступности", src="датчик")
            continue

        # Для групп с датчиком — своя логика override
        if has_motion:
            respect = _lg_state("input_boolean.light_%s_manual_respect" % gid)
            if respect == "off":
                log_event("lighting", "Инфо", "gid=" + gid + ": manual_respect=off, skip override", why="настройка группы", src="ручное")
                continue

            if cur:
                # Ручное ВКЛ — пауза manual_on_min
                mins = int(_lg_num("input_number.light_%s_manual_on_min" % gid, 60))
                _LG_OVERRIDE[e] = time.monotonic() + mins * 60
                log_event("lighting", "Инфо", "gid=" + gid + ": manual ON, block " + str(mins) + " min", why="ручное ВКЛ", src="ручное")
            else:
                # Ручное ВЫКЛ — пауза manual_off_min
                mins = int(_lg_num("input_number.light_%s_manual_off_min" % gid, 2))
                _LG_OVERRIDE[e] = time.monotonic() + mins * 60
                log_event("lighting", "Инфо", "gid=" + gid + ": manual OFF, block " + str(mins) + " min", why="ручное ВЫКЛ", src="ручное")
        else:
            # Группы без датчика — глобальные 60 мин
            _LG_OVERRIDE[e] = time.monotonic() + cfg.get("override_timeout_min", 60) * 60
            log_event("lighting", "Инфо", "gid=" + gid + ": external -> block 60 min", why="внешнее изменение", src="ручное")

        if has_v:
            _lg_set_vlight(v, cur, mode)


def _lg_apply_group(g, cfg, mode):
    """Применение автоматики к группе."""
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
    why = dec.get("why", "")
    
    # Логирование решения
    log_event("lighting", "Отладка", "gid=" + gid + " decided=" + str(desired) + " why=" + why, why=why, src="автоматика")
    
    if mode == "shadow":
        cur = [_lg_is_on(e) for e in lights]
        if any([c != desired for c in cur]):
            log_event("lighting", "Инфо", "gid=" + gid + " shadow: desired=" + str(desired) + " why=" + why, why="shadow-режим", src="автоматика")

    nightlight = dec.get("nightlight", False)

    if any([_lg_override_active(e) for e in lights]):
        log_event("lighting", "Инфо", "gid=" + gid + " skipped (override active)", why="override 60 мин", src="ручное")
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


def _lg_tick():
    """Основной такт цикла освещения (вызывается каждые 30 сек)."""
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
    
    # Публикация состояний FSM после каждого тика
    try:
        _lg_publish_fsm_states()
        _lg_update_fsm_overview()
    except Exception as exc:
        log.error("[light] Failed to publish FSM states: " + str(exc))
    
    try:
        _lg_ct_tick(cfg, mode)
        _lg_rgb_tick(cfg, mode)
        _lg_backlight_tick(cfg, mode)
        _lg_imitation_tick(cfg, mode)
    except Exception as exc:
        log.error("[light] tick error: " + str(exc))


@time_trigger("startup")
def lighting_controller_loop():
    """Главный цикл контроллера освещения."""
    log.info("[light] Controller loop started")
    while True:
        try:
            _lg_tick()
        except Exception as exc:
            log.error("[light] Controller error: " + str(exc))
        task.sleep(30)
