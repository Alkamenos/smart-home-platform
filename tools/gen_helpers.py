#!/usr/bin/env python3
"""Манифест -> helpers (lighting/climate/ventilation/sensor_health/globals).
Режимы:
  --apply            создать отсутствующие
  --orphan           показать существующие, которых нет в манифесте
  --delete --confirm удалить orphan'ы (с защитой whitelist + scope)
"""
import argparse, json, os, urllib.request
import yaml

parser = argparse.ArgumentParser()
parser.add_argument("--manifest", default="manifests/leonid_house.yaml")
parser.add_argument("--apply", action="store_true")
parser.add_argument("--orphan", action="store_true")
parser.add_argument("--delete", action="store_true")
parser.add_argument("--confirm", action="store_true")
parser.add_argument("--start-id", type=int, default=100)
args = parser.parse_args()

HA_URL = os.environ.get("HA_URL", "http://homeassistant.local:8123")
tok = os.path.expanduser("~/.ha_token")
HA_TOKEN = os.environ.get("HA_TOKEN") or (open(tok).read().strip() if os.path.exists(tok) else "")

# ============================================================
# HA API
# ============================================================
def rest_get(path):
    r = urllib.request.Request(HA_URL + path,
        headers={"Authorization": "Bearer " + HA_TOKEN})
    with urllib.request.urlopen(r, timeout=10) as resp:
        return json.load(resp)

def rest_post(path, data):
    r = urllib.request.Request(HA_URL + path,
        data=json.dumps(data).encode(), method="POST",
        headers={"Authorization": "Bearer " + HA_TOKEN,
                 "Content-Type": "application/json"})
    with urllib.request.urlopen(r, timeout=10) as resp:
        return resp.status

def exists(eid):
    try:
        rest_get("/api/states/" + eid)
        return True
    except Exception:
        return False

def list_all_states():
    return rest_get("/api/states")

class WS:
    def __init__(self):
        import websocket
        url = HA_URL.replace("https://", "wss://").replace("http://", "ws://") + "/api/websocket"
        self.ws = websocket.create_connection(url, timeout=15)
        assert json.loads(self.ws.recv()).get("type") == "auth_required"
        self.ws.send(json.dumps({"type": "auth", "access_token": HA_TOKEN}))
        ok = json.loads(self.ws.recv())
        assert ok.get("type") == "auth_ok", ok
        self.mid = 0
    def send(self, cmd):
        self.mid += 1
        cmd = dict(cmd); cmd["id"] = self.mid
        self.ws.send(json.dumps(cmd))
        while True:
            msg = json.loads(self.ws.recv())
            if msg.get("id") == self.mid:
                return msg
    def call_service(self, domain, service, data):
        return self.send({"type": "call_service", "domain": domain,
                          "service": service, "service_data": data})
    def create(self, e):
        dom = e["type"].split("/")[0]
        cmd = {"type": e["type"], "name": e["name"]}
        if e.get("icon"): cmd["icon"] = e["icon"]
        if dom == "input_select": cmd["options"] = e["options"]
        if dom == "input_datetime":
            cmd["has_date"] = e.get("has_date", False)
            cmd["has_time"] = e.get("has_time", True)
        if dom == "input_number":
            cmd.update({"min": e["min"], "max": e["max"], "step": e["step"]})
            if e.get("initial") is not None: cmd["initial"] = e["initial"]
        r = self.send(cmd)
        eid = dom + "." + e["name"]
        if not r.get("success"):
            print("FAILED create:", eid, r.get("error"))
            return False
        init = e.get("initial")
        if dom == "input_datetime" and init:
            self.call_service("input_datetime", "set_datetime",
                              {"entity_id": eid, "time": init})
        elif dom == "input_boolean" and init == "on":
            self.call_service("input_boolean", "turn_on", {"entity_id": eid})
        elif dom == "input_select" and init:
            self.call_service("input_select", "select_option",
                              {"entity_id": eid, "option": init})
        print("created:", eid)
        return True
    def delete(self, entity_id):
        dom = entity_id.split(".")[0]
        name = entity_id.split(".", 1)[1]
        r = self.send({"type": dom + "/delete", "name": name})
        if r.get("success"):
            print("deleted:", entity_id)
            return True
        print("FAILED delete:", entity_id, r.get("error"))
        return False

# ============================================================
# Генерация helpers из манифеста
# ============================================================
SEL_ON  = ["Не включать", "Закат", "Время"]
SEL_OFF = ["Время", "Рассвет", "Не выключать"]
RGB     = ["Белый", "Красный", "Оранжевый", "Зелёный", "Синий", "Фиолетовый", "Розовый"]

def num(i, name, mn, mx, step, init, icon):
    return {"id": i, "type": "input_number/create", "name": name,
            "min": mn, "max": mx, "step": step, "initial": init, "icon": icon}

def bool_(i, name, init, icon):
    return {"id": i, "type": "input_boolean/create", "name": name,
            "initial": init, "icon": icon}

def dt(i, name, init, icon):
    return {"id": i, "type": "input_datetime/create", "name": name,
            "has_date": False, "has_time": True, "initial": init, "icon": icon}

def sel(i, name, options, init, icon):
    return {"id": i, "type": "input_select/create", "name": name,
            "options": options, "initial": init, "icon": icon}

def generate(manifest):
    f = manifest.get("features", {}) or {}
    entries = []
    i = args.start_id

    # ---- Lighting: per-group ----
    lighting = f.get("lighting", {}) or {}
    for g in (lighting.get("groups", []) or []):
        gid = str(g.get("id"))
        entries += [
            bool_(i, "vlight_" + gid, None, "mdi:lightbulb"),
            sel(i+1, "light_" + gid + "_on", SEL_ON, "Закат", "mdi:form-select"),
            sel(i+2, "light_" + gid + "_off", SEL_OFF, "Время", "mdi:power-sleep"),
            dt(i+3, "light_" + gid + "_on_time", "18:00", "mdi:clock-outline"),
            dt(i+4, "light_" + gid + "_off_time", "23:00", "mdi:clock-outline"),
            dt(i+5, "light_" + gid + "_off_end_time", "06:00", "mdi:clock-end"),
            num(i+6, "light_" + gid + "_brightness", 1, 100, 1, 100, "mdi:brightness-percent"),
            bool_(i+7, "feature_" + gid, "on", "mdi:lightbulb-group"),
        ]
        i += 8
        if g.get("motion_sensor"):
            entries += [
                bool_(i, "light_" + gid + "_motion", "on", "mdi:motion-sensor"),
                bool_(i+1, "light_" + gid + "_motion_day", "off", "mdi:weather-sunny"),
                num(i+2, "light_" + gid + "_motion_day_min", 1, 120, 1, 5, "mdi:timer-outline"),
                num(i+3, "light_" + gid + "_motion_night_min", 1, 60, 1, 2, "mdi:timer-outline"),
            ]
            i += 4

    # ---- Lighting: color temp / RGB ----
    entries += [
        num(i, "ct_day_kelvin", 2000, 6000, 50, 5000, "mdi:thermometer-sun"),
        num(i+1, "ct_night_kelvin", 2000, 6000, 50, 2200, "mdi:thermometer-moon"),
        dt(i+2, "ct_warm_from", "21:00", "mdi:clock-outline"),
        dt(i+3, "ct_night_from", "23:00", "mdi:clock-outline"),
        bool_(i+4, "feature_rgb", "off", "mdi:palette"),
        sel(i+5, "light_rgb_scene", RGB, "Белый", "mdi:palette"),
    ]
    i += 6

    # ---- Lighting: global flags ----
    entries += [
        bool_(i, "feature_lighting", "on", "mdi:lightbulb-auto"),
        bool_(i+1, "lighting_shadow_mode", "off", "mdi:eye-off-outline"),
        bool_(i+2, "feature_color_temp", "on", "mdi:thermometer-lines"),
        bool_(i+3, "feature_backlight", "on", "mdi:led-on"),
        bool_(i+4, "feature_imitation", "off", "mdi:account-eye"),
        dt(i+5, "imitation_start", "20:00", "mdi:clock-start"),
        dt(i+6, "imitation_end", "07:00", "mdi:clock-end"),
    ]
    i += 7

    # ---- Climate ----
    climate = f.get("climate", {}) or {}
    entries += [
        bool_(i, "feature_climate", "on", "mdi:thermometer"),
        bool_(i+1, "climate_shadow_mode", "off", "mdi:eye-off-outline"),
        bool_(i+2, "zima", "off", "mdi:snowflake"),
    ]
    i += 3
    # setpoints из зон
    seen_sp = set()
    for zone in (climate.get("zones", []) or []):
        for sp in (zone.get("setpoints") or {}).values():
            if isinstance(sp, dict):
                src = sp.get("source", "")
                if isinstance(src, str) and src.startswith("input_number.") and src not in seen_sp:
                    seen_sp.add(src)
                    name = src.split(".", 1)[1]
                    entries.append(num(i, name, 5, 35, 0.5, 22, "mdi:thermometer"))
                    i += 1
    # humidity
    entries.append(num(i, "vlazhnost_v_dome", 0, 100, 1, 50, "mdi:water-percent"))
    i += 1

    # ---- Ventilation ----
    vent = f.get("ventilation", {}) or {}
    flags = (vent.get("flags", {}) or {})
    entries += [
        bool_(i, "feature_ventilation", "on", "mdi:fan"),
        bool_(i+1, "ventilation_shadow_mode", "off", "mdi:eye-off-outline"),
    ]
    i += 2
    for key in ("boost_intake", "boost_exhaust", "night", "away_home"):
        ent = flags.get(key)
        if ent and ent.startswith("input_boolean."):
            name = ent.split(".", 1)[1]
            init = "off" if key.startswith("boost") else ("on" if key == "away_home" else "off")
            entries.append(bool_(i, name, init, "mdi:fan"))
            i += 1
    od = (vent.get("open_doors", {}) or {})
    if od.get("enabled_flag", "").startswith("input_boolean."):
        entries.append(bool_(i, od["enabled_flag"].split(".", 1)[1], "on", "mdi:door-open"))
        i += 1
    if od.get("mock_state", "").startswith("input_boolean."):
        entries.append(bool_(i, od["mock_state"].split(".", 1)[1], "off", "mdi:door"))
        i += 1
    bf = (vent.get("bathroom_fan", {}) or {})
    if bf.get("enabled_flag", "").startswith("input_boolean."):
        entries.append(bool_(i, bf["enabled_flag"].split(".", 1)[1], "on", "mdi:fan"))
        i += 1

    # ---- Sensor health ----
    sh = f.get("sensor_health", {}) or {}
    if sh:
        entries.append(bool_(i, "feature_sensor_health", "on", "mdi:heart-pulse"))
        i += 1

    # ---- Globals ----
    globals_cfg = (manifest.get("globals", {}) or {}).get("modes", {}) or {}
    for mname, mcfg in globals_cfg.items():
        ent = (mcfg or {}).get("entity", "")
        if ent.startswith("input_boolean."):
            name = ent.split(".", 1)[1]
            if not any(e["name"] == name for e in entries):
                entries.append(bool_(i, name, "off", "mdi:toggle-switch"))
                i += 1
    # party_mode — всегда нужен
    if not any(e["name"] == "party_mode" for e in entries):
        entries.append(bool_(i, "party_mode", "off", "mdi:party-popper"))
        i += 1

    return entries

# ============================================================
# Orphan / delete
# ============================================================
# Whitelist: никогда не трогаем
WHITELIST_NAMES = {"zima", "vecher", "my_doma", "party_mode"}
# Scope: удаляем только с этими префиксами имени
ORPHAN_PREFIXES = (
    "vlight_", "light_", "feature_", "ct_", "light_rgb_",
    "imitation_", "vlazhnost_",
)
# Shadow-режимы тоже в scope (но не из whitelist)
SHADOW_SUFFIX = "_shadow_mode"

def is_orphan_candidate(eid):
    if eid.split(".")[0] not in ("input_boolean", "input_select",
                                  "input_datetime", "input_number"):
        return False
    name = eid.split(".", 1)[1]
    if name in WHITELIST_NAMES:
        return False
    return any(name.startswith(p) for p in ORPHAN_PREFIXES) or name.endswith(SHADOW_SUFFIX)

def find_orphans(expected_ids):
    expected = set(expected_ids)
    states = list_all_states()
    orphans = []
    for s in states:
        eid = s.get("entity_id", "")
        if eid in expected:
            continue
        if is_orphan_candidate(eid):
            orphans.append(eid)
    return sorted(orphans)

# ============================================================
# Main
# ============================================================
m = yaml.safe_load(open(args.manifest))
entries = generate(m)
expected_ids = [e["type"].split("/")[0] + "." + e["name"] for e in entries]

if args.orphan or args.delete:
    orphans = find_orphans(expected_ids)
    print("Orphan helpers (exist but not in manifest): %d" % len(orphans))
    for o in orphans:
        print("  -", o)
    if args.delete:
        if not args.confirm:
            print("\nPass --confirm to actually delete.")
            raise SystemExit(1)
        if not HA_TOKEN:
            raise SystemExit("Нужен ~/.ha_token")
        ws = WS()
        done = 0
        for o in orphans:
            if ws.delete(o):
                done += 1
        ws.ws.close()
        print("deleted: %d" % done)
    raise SystemExit(0)

missing = [e for e in entries if not exists(e["type"].split("/")[0] + "." + e["name"])]
print("Expected: %d, missing: %d" % (len(entries), len(missing)))

if args.apply:
    if not HA_TOKEN:
        raise SystemExit("Нужен ~/.ha_token")
    if not missing:
        print("all helpers exist")
    else:
        ws = WS()
        done = 0
        for e in missing:
            if ws.create(e):
                done += 1
        ws.ws.close()
        print("created: %d" % done)
else:
    print(json.dumps(missing, ensure_ascii=False, indent=2))