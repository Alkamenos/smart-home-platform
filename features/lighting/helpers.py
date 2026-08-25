from features.lighting.schema import _feats_of  # noqa: F401

#!/usr/bin/env python3
"""Helpers-артефакт фич освещения: какие input_* создавать для подключённых фич."""

def _num(i, name, mn, mx, step, init, icon):
    return {"id": i, "type": "input_number/create", "name": name,
            "min": mn, "max": mx, "step": step, "initial": init, "icon": icon}

def _bool(i, name, init, icon):
    return {"id": i, "type": "input_boolean/create", "name": name,
            "initial": init, "icon": icon}

def _sel(i, name, options, init, icon):
    return {"id": i, "type": "input_select/create", "name": name,
            "options": options, "initial": init, "icon": icon}


def helpers_schedule(g, gid, i, ctx):
    return [], i

def helpers_motion(g, gid, i, ctx):
    mo = _feats_of(g).get("motion") or {}
    ms = mo.get("sensor") or g.get("motion_sensor")
    if not ms:
        return [], i
    out = []
    room = g.get("room")
    options = ctx.get("motion_by_room", {}).get(room, [ms]) if room else [ms]
    out.append(_sel(i, "light_%s_motion_sensor" % gid, options, ms, "mdi:motion-sensor"))
    i += 1
    out += [
        _bool(i, "light_%s_motion" % gid, "on", "mdi:motion-sensor"),
        _bool(i + 1, "light_%s_motion_day" % gid, "off", "mdi:weather-sunny"),
        _num(i + 2, "light_%s_motion_day_min" % gid, 1, 120, 1, 5, "mdi:timer-outline"),
        _num(i + 3, "light_%s_motion_night_min" % gid, 1, 60, 1, 2, "mdi:timer-outline"),
    ]
    i += 4
    if mo.get("no_night_auto"):
        out.append(_bool(i, mo["no_night_auto"].split(".", 1)[1], "off", "mdi:weather-night"))
        i += 1
    return out, i

def helpers_nightlight(g, gid, i, ctx):
    nl = _feats_of(g).get("nightlight") or {}
    nl_b = nl.get("brightness", 40)
    nl_c = nl.get("color", [255, 150, 60])
    out = [
        _bool(i, "feature_%s_nightlight" % gid, "off", "mdi:weather-night"),
        _num(i + 1, "light_%s_nightlight_brightness" % gid, 1, 100, 1, nl_b, "mdi:brightness-percent"),
        _num(i + 2, "light_%s_nightlight_off_min" % gid, 1, 30, 1, 3, "mdi:timer-outline"),
        _num(i + 3, "light_%s_nightlight_r" % gid, 0, 255, 1, nl_c[0], "mdi:palette"),
        _num(i + 4, "light_%s_nightlight_g" % gid, 0, 255, 1, nl_c[1], "mdi:palette"),
        _num(i + 5, "light_%s_nightlight_b" % gid, 0, 255, 1, nl_c[2], "mdi:palette"),
    ]
    return out, i + 6

PARTY_ROLES = ["Как обычно", "Включить", "Выключить", "Держать включённым"]
ROLE_MAP = {"keep": "Как обычно", "on": "Включить",
            "off": "Выключить", "keep_on": "Держать включённым"}
ALWAYS = {"party"}


def helpers_party(g, gid, i, ctx):
    role = (_feats_of(g).get("party") or {}).get("role", "keep_on")
    return [_sel(i, "light_%s_party_role" % gid, PARTY_ROLES,
                 ROLE_MAP.get(role, "Держать включённым"), "mdi:party-popper")], i + 1


def helpers_dusk(g, gid, i, ctx):
    d = _feats_of(g).get("dusk") or {}
    return [_bool(i, "light_%s_require_dark" % gid,
                  "on" if d.get("require_dark") else "off", "mdi:weather-night")], i + 1


def helpers_ct(g, gid, i, ctx):
    c = _feats_of(g).get("ct") or {}
    return [_bool(i, "light_%s_ct_follow" % gid,
                  "on" if c.get("follow") else "off", "mdi:thermometer")], i + 1


def helpers_imitation(g, gid, i, ctx):
    im = _feats_of(g).get("imitation") or {}
    return [_bool(i, "light_%s_imitation" % gid,
                  "on" if im.get("participate") else "off", "mdi:mask")], i + 1


FEATURE_HELPERS = {"party": helpers_party, "dusk": helpers_dusk,
                   "ct": helpers_ct, "imitation": helpers_imitation,"schedule": helpers_schedule, "motion": helpers_motion,
                   "nightlight": helpers_nightlight}
FEATURE_ORDER = ["party", "schedule", "dusk", "motion", "nightlight", "ct", "imitation"]

def group_feature_helpers(g, gid, i, ctx):
    feats = _feats_of(g)
    out = []
    for fname in FEATURE_ORDER:
        if fname in feats or fname in ALWAYS:
            add, i = FEATURE_HELPERS[fname](g, gid, i, ctx)
            out += add
    return out, i