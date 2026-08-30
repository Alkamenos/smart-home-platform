#!/usr/bin/env python3
"""Runtime: главный цикл и применение решений к группам."""

from features.lighting.state import (
    _lg_state, _lg_cfg, _lg_mode, _lg_update_dark, _lg_season,
    _lg_decide_ctx, _lg_log, _DARK, _FD_REGISTRY, _FD_ABORT,
)
from features.lighting.control import (
    _lg_set_real, _lg_manual_command, _lg_rebuild_light_map,
    _lg_override_active, _lg_expected_guard, _lg_set_vlight, lg_vlight_entity,
)
from features.lighting.ticks import (
    _lg_ct_tick, _lg_rgb_tick, _lg_backlight_tick, _lg_imitation_tick,
)


def _lg_decide(g, cfg):
    """Принятие решения для группы через voters."""
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
    """Обработка изменения vlight (ручная команда)."""
    from features.lighting.state import _VLIGHT_PREV
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
    """Отслеживание изменений реальных ламп (детект ручного вмешательства)."""
    from features.lighting.state import _LG_PREV, _EXPECTED_REAL_STATE, _LG_OVERRIDE
    
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
            _lg_log("override", "INFO", "gid=%s: skip override (from unavailable)" % gid)
            continue

        # Для групп с датчиком — своя логика override
        if has_motion:
            respect = _lg_state("input_boolean.light_%s_manual_respect" % gid)
            if respect == "off":
                _lg_log("override", "INFO", "gid=%s: manual_respect=off, skip override" % gid)
                continue

            if cur:
                # Ручное ВКЛ — пауза manual_on_min
                mins = int(_lg_num("input_number.light_%s_manual_on_min" % gid, 60))
                _LG_OVERRIDE[e] = time.monotonic() + mins * 60
                _lg_log("override", "INFO", "gid=%s: manual ON, block %d min" % (gid, mins))
            else:
                # Ручное ВЫКЛ — пауза manual_off_min
                mins = int(_lg_num("input_number.light_%s_manual_off_min" % gid, 2))
                _LG_OVERRIDE[e] = time.monotonic() + mins * 60
                _lg_log("override", "INFO", "gid=%s: manual OFF, block %d min" % (gid, mins))
        else:
            # Группы без датчика — глобальные 60 мин
            _LG_OVERRIDE[e] = time.monotonic() + cfg.get("override_timeout_min", 60) * 60
            _lg_log("override", "INFO", "gid=%s: external -> block 60 min" % gid)

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
