# pyscript runtime: lighting decide-voters (склейка через build/build_pyscript.py)
# Порядок: после utils освещения, до _lg_decide. Все ссылки — call-time.
def _lg_decide_ctx(g, cfg):
    prof = g.get("profile", "dusk_till_time")
    dark = bool(_DARK)
    now = _lg_now_min()
    night = _lg_night(cfg)
    gid = str(g.get("id"))
    lights = [e for e in (g.get("lights", []) or []) if e]
    any_on = any([_lg_is_on(e) for e in lights])
    ms = _lg_motion_sensor(g, gid)
    men = ms is not None and _lg_state("input_boolean.light_%s_motion" % gid) != "off"
    mday = _lg_state("input_boolean.light_%s_motion_day" % gid) == "on"
    motion = _lg_motion(g, gid) if ms else None
    if g.get("motion_timeouts") == "own":
        day_d = "input_number.light_%s_motion_day_min" % gid
        night_d = "input_number.light_%s_motion_night_min" % gid
    else:
        day_d = "input_number.motion_day_min"
        night_d = "input_number.motion_night_min"
    presence = False
    if ms and men:
        if motion:
            _LG_MOTION_LAST[gid] = time.monotonic()
        last = _LG_MOTION_LAST.get(gid)
        if last is not None:
            mins = _lg_num(night_d, g.get("no_motion_night_min", 2)) if night else _lg_num(day_d, g.get("no_motion_day_min", 5))
            presence = (time.monotonic() - last) < mins * 60
    sel_on = _lg_state("input_select.light_%s_on" % gid)
    sel_off = _lg_state("input_select.light_%s_off" % gid)
    if sel_off is None:
        sel_off = "Рассвет" if g.get("off") == "sunrise" else "Время"
    return {"prof": prof, "dark": dark, "now": now, "night": night, "gid": gid,
            "lights": lights, "any_on": any_on, "ms": ms, "mday": mday,
            "presence": presence, "sel_on": sel_on, "sel_off": sel_off}


ROLE_MAP = {"keep": "Как обычно", "on": "Включить",
             "off": "Выключить", "keep_on": "Держать включённым"}
_FD_ABORT = {"abort": True}


def _lg_feats(g):
    return g.get("features") or {}


def _fd_party(g, cfg, ctx):
    if _lg_state("input_boolean.party_mode") != "on":
        return None
    gid = ctx["gid"]
    role = _lg_state("input_select.light_%s_party_role" % gid)
    if role in (None, "unknown", "unavailable"):
        role = ROLE_MAP.get(((_lg_feats(g)).get("party") or {}).get("role", "keep_on"), "Держать включённым")
    if role == "Выключить":
        return {"on": False, "why": "party: роль выкл"}
    if role == "Включить":
        return {"on": True, "why": "party: роль вкл"}
    if role == "Держать включённым" and ctx["dark"] and ctx["any_on"]:
        return {"on": True, "why": "party: держим до рассвета"}
    return None

def _fd_ne_vkl(g, cfg, ctx):
    if ctx["sel_on"] == "Не включать":
        return {"on": False, "why": "sel_on=Не включать"}
    return None


def _fd_motion(g, cfg, ctx):
    gid = ctx["gid"]
    ms = ctx["ms"]
    active = (ctx["sel_on"] == "Датчик движения" and ms is not None) or ctx["prof"] == "motion"
    if not active:
        return None
    nnf = g.get("no_night_auto_flag")
    if nnf and ctx["night"] and _lg_state(nnf) == "on" and not ctx["any_on"]:
        return {"on": False, "why": "авто ночью отключено"}
    if g.get("motion_mode", "trigger") == "keepalive" and ctx["sel_on"] == "Датчик движения":
        if ctx["any_on"]:
            return {"on": ctx["presence"], "why": "keepalive: держим пока движение"}
        nl_ok = bool(g.get("nightlight")) and _lg_state("input_boolean.feature_%s_nightlight" % gid) == "on"
        if ctx["night"] and nl_ok:
            nl_min = _lg_num("input_number.light_%s_nightlight_off_min" % gid, 3)
            last = _LG_MOTION_LAST.get(gid)
            nl_on = last is not None and (time.monotonic() - last) < nl_min * 60
            return {"on": nl_on, "nightlight": True, "why": "keepalive: ночник"}
        return {"on": False, "why": "keepalive: выключено - не включаем"}
    if not (ctx["dark"] or ctx["mday"]):
        return {"on": False, "why": "motion: светло и motion_day=off"}
    return {"on": ctx["presence"], "why": "motion: presence=" + str(ctx["presence"])}


def _fd_manual_gate(g, cfg, ctx):
    if ctx["prof"] == "manual_auto":
        af = g.get("auto_flag")
        if not (af and _lg_state(af) == "on"):
            return _FD_ABORT
    return None


def _fd_off_window(g, cfg, ctx):
    now = ctx["now"]
    sel_off = ctx["sel_off"]
    gid = ctx["gid"]
    if sel_off == "Рассвет":
        if not ctx["dark"] and not ctx["presence"]:
            return {"on": False, "why": "рассвет: светло"}
        return None
    if sel_off != "Время":
        return None
    off_min = _lg_dt_min("input_datetime.light_%s_off_time" % gid)
    if off_min is None:
        off_min = _lg_hm(g.get("off", "23:00"))
    end_min = _lg_dt_min("input_datetime.light_%s_off_end_time" % gid)
    if end_min is None:
        end_min = _lg_hm(g.get("off_end"))
    if off_min is not None and not ctx["presence"]:
        if end_min is not None:
            if end_min > off_min:
                in_off = now >= off_min and now < end_min
            else:
                in_off = now >= off_min or now < end_min
            if in_off:
                return {"on": False, "why": "окно выкл %s-%s" % (str(off_min), str(end_min))}
        else:
            if now >= off_min:
                return {"on": False, "why": "позже off_time"}
    return None


def _fd_on_time(g, cfg, ctx):
    if ctx["sel_on"] != "Время":
        return None
    t_val = _lg_dt_min("input_datetime.light_%s_on_time" % ctx["gid"])
    if t_val is not None and ctx["now"] >= t_val:
        return {"on": True, "why": "время включения"}
    if ctx["presence"] and ctx["dark"]:
        return {"on": True, "why": "движение в темноте"}
    return {"on": False, "why": "время не пришло"}


def _fd_dusk(g, cfg, ctx):
    gid = ctx["gid"]
    rd = _lg_state("input_boolean.light_%s_require_dark" % gid)
    if rd is not None and rd != "on":
        el = _lg_attr("sun.sun", "elevation")
        if el is not None and el < 0:
            return {"on": True, "why": "закат (без ожидания темноты)"}
        return {"on": False, "why": "солнце выше горизонта"}
    if ctx["dark"]:
        return {"on": True, "why": "темно (закат)"}
    return {"on": False, "why": "светло"}

_FD_CHAIN = [_fd_party, _fd_ne_vkl, _fd_motion, _fd_manual_gate,
             _fd_off_window, _fd_on_time, _fd_dusk]

