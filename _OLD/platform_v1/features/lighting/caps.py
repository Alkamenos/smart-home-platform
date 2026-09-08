#!/usr/bin/env python3
"""Caps для генераторов: авто по supported_color_modes + override из манифеста.
Ленивый кэш; если HA недоступен -> всё разрешено (безопасный фолбэк)."""
import os
import sys

RGB_MODES = ["rgb", "hs", "xy", "rgbw", "rgbww"]
ALL_ON = {"dim": True, "ct": True, "rgb": True}
_CACHE = {"loaded": False, "modes": None}

_LG_CAPS = {}


class _CapsWrapper:
    """Обёртка для совместимости с legacy-кодом, ожидающим CAPS.group_caps(g)."""
    @staticmethod
    def group_caps(g):
        return group_caps(g)


CAPS = _CapsWrapper()


def _lg_caps(g):
    """Runtime caps: авто по supported_color_modes + override caps:. Без внешних зависимостей."""
    gid = str(g.get("id"))
    if gid in _LG_CAPS:
        return _LG_CAPS[gid]
    caps = {}
    ov = g.get("caps") or {}
    for e in (g.get("lights", []) or []):
        if not e or str(e).split(".")[0] != "light":
            continue
        scm = _lg_attr(e, "supported_color_modes") or []
        caps = {"dim": any([m != "on_off" for m in scm]),
                "ct": "color_temp" in scm,
                "rgb": any([m in RGB_MODES for m in scm])}
        break
    if not caps:
        caps = {"dim": False, "ct": False, "rgb": False}
    for k in ("dim", "ct", "rgb"):
        if k in ov:
            caps[k] = bool(ov[k])
    _LG_CAPS[gid] = caps
    return caps

def caps_from_modes(scm):
    if not scm:
        return {"dim": False, "ct": False, "rgb": False}
    return {"dim": any([m != "on_off" for m in scm]),
            "ct": "color_temp" in scm,
            "rgb": any([m in RGB_MODES for m in scm])}

def fetch_modes(force=False):
    if _CACHE["loaded"] and not force:
        return _CACHE["modes"]
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
    modes = None
    try:
        from core import ha
        modes = {}
        for s in ha.list_all_states():
            eid = s.get("entity_id", "")
            if eid.startswith("light."):
                modes[eid] = (s.get("attributes") or {}).get("supported_color_modes") or []
    except Exception:
        modes = None
    _CACHE["modes"] = modes
    _CACHE["loaded"] = True
    return modes

def group_caps(g, modes_by_entity=None):
    if modes_by_entity is None:
        modes_by_entity = fetch_modes()
    if modes_by_entity is None:
        return dict(ALL_ON)
    caps = {}
    ov = g.get("caps") or {}
    for e in (g.get("lights", []) or []):
        if not e or str(e).split(".")[0] != "light":
            continue
        caps = caps_from_modes(modes_by_entity.get(e))
        break
    if not caps:
        caps = {"dim": False, "ct": False, "rgb": False}
    for k in ("dim", "ct", "rgb"):
        if k in ov:
            caps[k] = bool(ov[k])
    return caps
