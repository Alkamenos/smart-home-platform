#!/usr/bin/env python3
"""Resolver: раскрывает features группы (новый формат манифеста) в legacy-поля.
Группа без features возвращается как есть (старый формат)."""

def resolve_group(g):
    if not isinstance(g, dict) or "features" not in g:
        return g
    r = dict(g)
    f = g.get("features") or {}
    dusk = f.get("dusk")
    sch = f.get("schedule") or {}
    mo = f.get("motion")
    nl = f.get("nightlight")
    ct = f.get("ct")

    if dusk is not None:
        r.setdefault("require_dark", bool((dusk or {}).get("require_dark", False)))
        r.setdefault("on", "sunset")
    if sch:
        if sch.get("on") is not None:
            r["on"] = sch["on"]
        if sch.get("off") is not None:
            r["off"] = sch["off"]
        if sch.get("off_end") is not None:
            r["off_end"] = sch["off_end"]
        if sch.get("auto_flag"):
            r["auto_flag"] = sch["auto_flag"]
    if mo:
        r["motion_sensor"] = mo.get("sensor")
        r["motion_mode"] = mo.get("mode", "trigger")
        if mo.get("timeouts") == "own":
            r["motion_timeouts"] = "own"
        if mo.get("no_night_auto"):
            r["no_night_auto_flag"] = mo["no_night_auto"]
    if nl:
        r["nightlight"] = nl
    if ct and ct.get("follow"):
        r["follow_global_ct"] = True

    if "profile" not in r:
        if mo and not sch.get("on") and dusk is None:
            r["profile"] = "motion"
        elif sch.get("auto_flag"):
            r["profile"] = "manual_auto"
        elif str(r.get("off")) == "sunrise":
            r["profile"] = "dusk_till_dawn"
        else:
            r["profile"] = "dusk_till_time"

    if isinstance(r.get("season"), dict):
        se = dict(r["season"])
        for k in ("summer", "winter"):
            if isinstance(se.get(k), dict) and "features" in se[k]:
                se[k] = resolve_group(se[k])
        r["season"] = se
    return r