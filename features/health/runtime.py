# ============================================================
# SENSOR HEALTH: unavailable + батарейки -> одно обновляемое
# уведомление + агрегированный список покупок
# ============================================================
import time


def _sh_cfg():
    if _REGISTRY is None:
        return None
    return _REGISTRY.feature("sensor_health") or None


def _sh_battery(attrs):
    for k in ("battery","battery_level","Battery"):
        if k in attrs:
            try:
                return float(attrs[k])
            except Exception:
                return None
    return None


def _sh_problems(cfg):
    thr = cfg.get("battery_threshold", 20)
    problems = []
    for s in cfg.get("sensors", []) or []:
        entity = s.get("entity") if isinstance(s, dict) else s
        if not entity:
            continue
        batt_type = s.get("battery") if isinstance(s, dict) else None
        cnt = s.get("count", 1) if isinstance(s, dict) else 1
        try:
            st = hass.states.get(entity)
        except Exception:
            st = None
        if st is None or str(st.state) in ("unknown","unavailable"):
            problems.append({"entity": entity,"reason":"недоступен","battery": batt_type,"count": cnt})
        else:
            b = _sh_battery(st.attributes or {})
            if b is not None and b <= thr:
                problems.append({"entity": entity,"reason":"батарея " + str(int(b)) +"%","battery": batt_type,"count": cnt})
    return problems


def _sh_aggregate(problems):
    agg = {}
    for p in problems:
        t = p.get("battery")
        if not t:
            continue
        agg[t] = agg.get(t, 0) + p.get("count", 1)
    return agg


def _sh_render(problems, agg):
    lines = ["Проблемы:"]
    for p in problems:
        lines.append("-" + str(p["entity"]) +": " + str(p["reason"]))
    if agg:
        lines.append("")
        lines.append("Купить:")
        for t in sorted(agg):
            lines.append("Батарейка" + str(t) + " -" + str(agg[t]) + " шт")
    return"\n".join(lines)


def _sh_publish(problems, agg):
    if problems:
        service.call("persistent_notification","create",
                     notification_id="sensor_health",
                     title="Sensor Health",
                     message=_sh_render(problems, agg))
    else:
        service.call("persistent_notification","dismiss",
                     notification_id="sensor_health")


def _sh_run(cfg):
    problems = _sh_problems(cfg)
    agg = _sh_aggregate(problems)
    _sh_publish(problems, agg)
    return problems, agg


@time_trigger("startup")
def sensor_health_loop():
    log.info("[sensor_health] loop started")
    while True:
        try:
            cfg = _sh_cfg()
            if cfg and cfg.get("enabled", True) \
                    and state.get("input_boolean.feature_sensor_health") !="off":
                problems, agg = _sh_run(cfg)
                if problems:
                    log.warning("[sensor_health] problems=" + str(len(problems)))
        except Exception as exc:
            log.error("[sensor_health] error:" + str(exc))
        cfg = _sh_cfg()
        task.sleep((cfg or {}).get("check_interval_min", 10) * 60)


@service
def sensor_health_status():
    cfg = _sh_cfg()
    if not cfg:
        log.warning("[sensor_health] no config")
        return {"ok": False,"error":"no config"}
    problems, agg = _sh_run(cfg)
    log.warning("[sensor_health] problems=" + str(problems) +" buy=" + str(agg))
    return {"ok": True,"problems": problems,"buy": agg}