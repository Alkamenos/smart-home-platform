#!/usr/bin/env python3
"""Сервисы для управления освещением."""



@service
def light_caps():
    """Получение caps всех групп в sensor.light_caps."""
    cfg = _lg_cfg()
    if cfg is None:
        return
    out = {}
    for g in (cfg.get("groups", []) or []):
        out[str(g.get("id"))] = _lg_caps(g)
    state.set("sensor.light_caps", "ok", caps=out)
    log.warning("[light][caps] %s" % str(out))


@service
def light_debug():
    """Диагностика состояния освещения."""
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
    """Сброс блокировок override."""
    if entity:
        _LG_OVERRIDE.pop(entity, None)
    else:
        _LG_OVERRIDE.clear()
    return {"ok": True}


@service
def light_override_debug():
    """Отладка блокировок override."""
    now = time.monotonic()
    out = []
    for e, until in _LG_OVERRIDE.items():
        remain = max(0, int((until - now) / 60))
        src = "motion"
        out.append({"entity": e, "until_min": remain})
    state.set("sensor.light_override_debug", "ok", overrides=out)
    log.warning("[light][override-debug] %s" % str(out))
    return {"ok": True, "overrides": out}


@service
def vlight_toggle(group_id=None, on=None):
    """Ручное переключение vlight группы."""
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
