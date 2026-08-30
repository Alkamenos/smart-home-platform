#!/usr/bin/env python3
"""Тики фоновых задач: CT, RGB, backlight, imitation."""

from features.lighting.state import (
    _lg_state, _lg_attr, _lg_is_on, _lg_num, _lg_hm, _lg_dt_min, _lg_now_min,
    _lg_cfg, _lg_log, _lg_group, lg_vlight_entity,
    _CT_LAST, _RGB_APPLIED, _LG_IM_ACTIVE, _LG_OVERRIDE, _VLIGHT_PREV,
)
from features.lighting.control import _lg_set_real, _lg_set_vlight


# RGB сцены
_RGB_SCENES = {
    "Красный": [255, 0, 0],
    "Оранжевый": [255, 120, 0],
    "Зелёный": [0, 255, 0],
    "Синий": [0, 0, 255],
    "Фиолетовый": [160, 0, 255],
    "Розовый": [255, 60, 140],
}


def _lg_ct_target(cfg):
    """Расчёт целевой цветовой температуры по времени суток."""
    ct = cfg.get("color_temp", {}) or {}
    day = int(_lg_num("input_number.ct_day_kelvin", ct.get("day_kelvin", 5000)))
    night = int(_lg_num("input_number.ct_night_kelvin", ct.get("night_kelvin", 2200)))
    warm = _lg_dt_min("input_datetime.ct_warm_from") or _lg_hm(ct.get("warm_from", "21:00"))
    nightf = _lg_dt_min("input_datetime.ct_night_from") or _lg_hm(ct.get("night_from", "23:00"))
    now = _lg_now_min()
    if warm is None or nightf is None or now <= warm:
        return day
    if now >= nightf:
        return night
    frac = (now - warm) / max(1, (nightf - warm))
    return int(day + (night - day) * frac)


def _lg_rgb_tick(cfg, mode):
    """Обработка RGB сцен."""
    if _lg_state("input_boolean.feature_rgb") != "on":
        return
    scene = _lg_state("input_select.light_rgb_scene") or "Белый"
    for g in (cfg.get("groups", []) or []):
        for e in (g.get("lights", []) or []):
            if not e or str(e).split(".")[0] != "light":
                continue
            if not _lg_is_on(e):
                _RGB_APPLIED.pop(e, None)
                continue
            st = hass.states.get(e)
            modes = (st.attributes.get("supported_color_modes", []) or []) if st else []
            if not any([("rgb" in mm) for mm in modes]):
                continue
            if _RGB_APPLIED.get(e) == scene:
                continue
            _RGB_APPLIED[e] = scene
            rgb = _RGB_SCENES.get(scene, [255, 255, 255])
            if mode == "shadow":
                log.warning("[light][SHADOW][rgb] " + e + " -> " + scene)
            else:
                service.call("light", "turn_on", entity_id=e, rgb_color=rgb)
                log.warning("[light][REAL][rgb] " + e + " -> " + scene)


def _lg_ct_tick(cfg, mode):
    """Обработка цветовой температуры."""
    ct = cfg.get("color_temp", {}) or {}
    flag = ct.get("enabled_flag")
    if flag and _lg_state(flag) != "on":
        return
    target = _lg_ct_target(cfg)
    for g in (cfg.get("groups", []) or []):
        gid = str(g.get("id"))
        cf = _lg_state("input_boolean.light_%s_ct_follow" % gid)
        if cf is None:
            cf = "on" if g.get("follow_global_ct") else "off"
        if cf != "on":
            continue
        gf = g.get("feature_flag")
        if gf and _lg_state(gf) != "on":
            continue
        for e in (g.get("lights", []) or []):
            if not e or str(e).split(".")[0] != "light":
                continue
            if not _lg_is_on(e):
                continue
            cur = _lg_attr(e, "color_temp_kelvin")
            if cur is None:
                continue
            if abs(cur - target) < 200:
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


def _lg_backlight_tick(cfg, mode):
    """Обработка подсветки выключателей."""
    bl = cfg.get("backlight", {}) or {}
    flag = bl.get("enabled_flag")
    if flag and _lg_state(flag) != "on":
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


def _lg_imitation_tick(cfg, mode):
    """Обработка имитации присутствия."""
    import random
    im = cfg.get("imitation", {}) or {}
    flag = im.get("enabled_flag")
    if flag and _lg_state(flag) != "on":
        return
    home = _lg_state(im.get("away_flag", "input_boolean.my_doma")) == "on"
    groups = {}
    for g in (cfg.get("groups", []) or []):
        groups[str(g["id"])] = g

    if home or not bool(_DARK):
        for e in list(_LG_IM_ACTIVE.keys()):
            pair = _LG_IM_ACTIVE.pop(e, None)
            if pair is None:
                continue
            if mode == "real":
                _lg_set_real(e, False, mode, cfg, force=True)
            _LG_OVERRIDE.pop(e, None)
            g = groups.get(str(pair[1]))
            if g is not None:
                v = lg_vlight_entity(g)
                if _lg_state(v) is not None:
                    _VLIGHT_PREV[v] = "off"
                    _lg_set_vlight(v, False, mode)
            log.warning("[light][imit] " + e + " off (home/light)")
        return

    ws = _lg_dt_min(im.get("window_start"))
    we = _lg_dt_min(im.get("window_end"))
    now = _lg_now_min()
    if ws is not None and we is not None:
        inwin = (ws <= now < we) if we > ws else (now >= ws or now < we)
        if not inwin:
            return

    for e in list(_LG_IM_ACTIVE.keys()):
        pair = _LG_IM_ACTIVE.get(e)
        if pair is not None and time.monotonic() >= pair[0]:
            _LG_IM_ACTIVE.pop(e, None)
            if mode == "real":
                _lg_set_real(e, False, mode, cfg, force=True)
            _LG_OVERRIDE.pop(e, None)
            g = groups.get(str(pair[1]))
            if g is not None:
                v = lg_vlight_entity(g)
                if _lg_state(v) is not None:
                    _VLIGHT_PREV[v] = "off"
                    _lg_set_vlight(v, False, mode)
            log.warning("[light][imit] " + e + " off (expired)")

    if not _LG_IM_ACTIVE and random.random() < 0.3:
        ids = []
        for i in (im.get("groups", []) or []):
            i = str(i)
            if i not in groups:
                continue
            hh = _lg_state("input_boolean.light_%s_imitation" % i)
            if hh is not None and hh != "on":
                continue
            ids.append(i)
        if ids:
            gid = random.choice(ids)
            lights = (groups[str(gid)].get("lights", []) or [])
            if lights:
                e = lights[0]
                mins = random.randint(im.get("min_on_min", 10), im.get("max_on_min", 30))
                g = groups[str(gid)]
                v = lg_vlight_entity(g)
                _LG_OVERRIDE[e] = time.monotonic() + mins * 60
                if mode == "real":
                    _lg_set_real(e, True, mode, cfg, force=True)
                if _lg_state(v) is not None:
                    _VLIGHT_PREV[v] = "on"
                    _lg_set_vlight(v, True, mode)
                _LG_IM_ACTIVE[e] = (time.monotonic() + mins * 60, gid)
                log.warning("[light][imit] " + e + " on (" + str(mins) + "m)")
