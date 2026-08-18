#!/usr/bin/env python3
"""Манифест -> helpers освещения.
По умолчанию печатает provisioning JSON (для внешнего инструмента).
--apply: создаёт отсутствующие сам, через HA websocket API."""
import argparse, json, os, urllib.request
import yaml

parser = argparse.ArgumentParser()
parser.add_argument("--start-id", type=int, default=1)
parser.add_argument("--groups", type=str, default=None)
parser.add_argument("--manifest", default="manifests/leonid_house.yaml")
parser.add_argument("--only-missing", action="store_true")
parser.add_argument("--apply", action="store_true")
args = parser.parse_args()

HA_URL = os.environ.get("HA_URL", "http://homeassistant.local:8123")
tok = os.path.expanduser("~/.ha_token")
HA_TOKEN = os.environ.get("HA_TOKEN") or (open(tok).read().strip() if os.path.exists(tok) else "")


def rest_get(path):
    r = urllib.request.Request(HA_URL + path,
                               headers={"Authorization": "Bearer " + HA_TOKEN})
    with urllib.request.urlopen(r, timeout=10) as resp:
        return json.load(resp)


def exists(eid):
    try:
        rest_get("/api/states/" + eid)
        return True
    except Exception:
        return False


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

    def _recv(self, mid):
        while True:
            msg = json.loads(self.ws.recv())
            if msg.get("id") == mid:
                return msg

    def send(self, cmd):
        self.mid += 1
        cmd = dict(cmd)
        cmd["id"] = self.mid
        self.ws.send(json.dumps(cmd))
        return self._recv(self.mid)

    def call_service(self, domain, service, data):
        return self.send({"type": "call_service", "domain": domain,
                          "service": service, "service_data": data})


def create(ws, e):
    dom = e["type"].split("/")[0]
    cmd = {"type": e["type"], "name": e["name"]}
    if e.get("icon"):
        cmd["icon"] = e["icon"]
    if dom == "input_select":
        cmd["options"] = e["options"]
    if dom == "input_datetime":
        cmd["has_date"] = e.get("has_date", False)
        cmd["has_time"] = e.get("has_time", True)
    if dom == "input_number":
        cmd.update({"min": e["min"], "max": e["max"], "step": e["step"]})
        if e.get("initial") is not None:
            cmd["initial"] = e["initial"]
    r = ws.send(cmd)
    eid = dom + "." + e["name"]
    if not r.get("success"):
        print("FAILED:", eid, r.get("error"))
        return False
    init = e.get("initial")
    if dom == "input_datetime" and init:
        ws.call_service("input_datetime", "set_datetime", {"entity_id": eid, "time": init})
    elif dom == "input_boolean" and init == "on":
        ws.call_service("input_boolean", "turn_on", {"entity_id": eid})
    elif dom == "input_select" and init:
        ws.call_service("input_select", "select_option", {"entity_id": eid, "option": init})
    print("created:", eid)
    return True


m = yaml.safe_load(open(args.manifest))
f = m.get("features", m)
groups = (f.get("lighting", {}) or {}).get("groups", [])
want = [s.strip() for s in args.groups.split(",")] if args.groups else None

SEL_ON = ["Не включать", "Закат", "Время"]
SEL_OFF = ["Время", "Рассвет", "Не выключать"]
RGB = ["Белый", "Красный", "Оранжевый", "Зелёный", "Синий", "Фиолетовый", "Розовый"]


def num(i, name, mn, mx, step, init, icon):
    return {"id": i, "type": "input_number/create", "name": name,
            "min": mn, "max": mx, "step": step, "initial": init, "icon": icon}


entries = []
i = args.start_id
for g in groups:
    gid = str(g.get("id"))
    if want and gid not in want:
        continue
    entries += [
        {"id": i, "type": "input_select/create", "name": "light_%s_off" % gid,
         "options": SEL_OFF, "initial": "Время", "icon": "mdi:power-sleep"},
        {"id": i + 1, "type": "input_datetime/create", "name": "light_%s_off_time" % gid,
         "has_date": False, "has_time": True, "initial": "23:00", "icon": "mdi:clock-outline"},
        num(i + 2, "light_%s_brightness" % gid, 1, 100, 1, 100, "mdi:brightness-percent"),
    ]
    i += 3
    if g.get("motion_sensor"):
        entries += [
            {"id": i, "type": "input_boolean/create", "name": "light_%s_motion" % gid,
             "initial": "on", "icon": "mdi:motion-sensor"},
            {"id": i + 1, "type": "input_boolean/create", "name": "light_%s_motion_day" % gid,
             "initial": "off", "icon": "mdi:weather-sunny"},
            num(i + 2, "light_%s_motion_day_min" % gid, 1, 120, 1, 5, "mdi:timer-outline"),
            num(i + 3, "light_%s_motion_night_min" % gid, 1, 60, 1, 2, "mdi:timer-outline"),
        ]
        i += 4

entries += [
    num(i, "ct_day_kelvin", 2000, 6000, 50, 5000, "mdi:thermometer-sun"),
    num(i + 1, "ct_night_kelvin", 2000, 6000, 50, 2200, "mdi:thermometer-moon"),
    {"id": i + 2, "type": "input_datetime/create", "name": "ct_warm_from",
     "has_date": False, "has_time": True, "initial": "21:00", "icon": "mdi:clock-outline"},
    {"id": i + 3, "type": "input_datetime/create", "name": "ct_night_from",
     "has_date": False, "has_time": True, "initial": "23:00", "icon": "mdi:clock-outline"},
    {"id": i + 4, "type": "input_boolean/create", "name": "feature_rgb",
     "initial": "off", "icon": "mdi:palette"},
    {"id": i + 5, "type": "input_select/create", "name": "light_rgb_scene",
     "options": RGB, "initial": "Белый", "icon": "mdi:palette"},
]

missing = [e for e in entries if not exists(e["type"].split("/")[0] + "." + e["name"])]

if args.apply:
    if not HA_TOKEN:
        raise SystemExit("Нужен ~/.ha_token")
    if not missing:
        print("all helpers exist")
    else:
        ws = WS()
        done = 0
        for e in missing:
            if create(ws, e):
                done += 1
        ws.ws.close()
        print("total created: %d" % done)
else:
    print(json.dumps(missing if args.only_missing else entries,
                     ensure_ascii=False, indent=2))
