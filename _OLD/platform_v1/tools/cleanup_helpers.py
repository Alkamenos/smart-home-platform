#!/usr/bin/env python3
"""Удаляет дубли helper'ов (_2.._9) и синхронизирует опции базовых select'ов."""
import argparse, json, os, re, urllib.request
import yaml

parser = argparse.ArgumentParser()
parser.add_argument("--manifest", default="instances/leonid_house/manifest.yaml")
parser.add_argument("--confirm", action="store_true")
args = parser.parse_args()

HA_URL = os.environ.get("HA_URL", "http://homeassistant.local:8123")
tok = os.path.expanduser("~/.ha_token")
HA_TOKEN = os.environ.get("HA_TOKEN") or (open(tok).read().strip() if os.path.exists(tok) else "")

DOMS = ("input_boolean", "input_select", "input_datetime", "input_number")
PREFIX = ("light_", "vlight_", "feature_", "ct_", "imitation_", "vlazhnost_")
SEL_ON = ["Не включать", "Закат", "Время", "Датчик движения"]
SEL_OFF = ["Время", "Рассвет", "Не выключать"]

def rest_get(path):
    r = urllib.request.Request(HA_URL + path, headers={"Authorization": "Bearer " + HA_TOKEN})
    with urllib.request.urlopen(r, timeout=10) as resp:
        return json.load(resp)

class WS:
    def __init__(self):
        import websocket
        url = HA_URL.replace("https://", "wss://").replace("http://", "ws://") + "/api/websocket"
        self.ws = websocket.create_connection(url, timeout=15)
        json.loads(self.ws.recv())
        self.ws.send(json.dumps({"type": "auth", "access_token": HA_TOKEN}))
        json.loads(self.ws.recv())
        self.mid = 0
    def send(self, cmd):
        self.mid += 1
        cmd = dict(cmd); cmd["id"] = self.mid
        self.ws.send(json.dumps(cmd))
        while True:
            msg = json.loads(self.ws.recv())
            if msg.get("id") == self.mid:
                return msg
    def delete(self, eid):
        dom, name = eid.split(".", 1)
        r = None
        for payload in (
            {"type": dom + "/delete", "name": name},
            {"type": dom + "/delete", dom + "_id": name},
            {"type": dom + "/delete", dom + "_id": eid},
        ):
            r = self.send(payload)
            if r.get("success"):
                print("deleted:", eid)
                return True
        print("FAILED:", eid, r.get("error") if r else "?")
        return False
    def set_options(self, eid, options):
        self.send({"type": "call_service", "domain": "input_select",
                   "service": "set_options",
                   "service_data": {"entity_id": eid, "options": options}})
        print("options synced:", eid)

m = yaml.safe_load(open(args.manifest))
groups = (m.get("features", {}).get("lighting", {}) or {}).get("groups", [])
states = rest_get("/api/states")
ids = set(s["entity_id"] for s in states)

# 1) дубли _2.._9
to_delete = []
for eid in sorted(ids):
    dom, name = eid.split(".", 1)
    if dom not in DOMS:
        continue
    mm = re.match(r"^(.+)_[2-9]$", name)
    if mm and mm.group(1).startswith(PREFIX):
        to_delete.append(eid)

# 2) мусор: boolean там, где должен быть select
for g in groups:
    gid = str(g.get("id"))
    for suf in ("_on", "_off"):
        bad = "input_boolean.light_%s%s" % (gid, suf)
        if bad in ids:
            to_delete.append(bad)
to_delete = sorted(set(to_delete))

# 3) базовые select'ы, которым надо обновить опции
to_sync = []
for g in groups:
    gid = str(g.get("id"))
    if "input_select.light_%s_on" % gid in ids:
        to_sync.append(("input_select.light_%s_on" % gid, SEL_ON))
    if "input_select.light_%s_off" % gid in ids:
        to_sync.append(("input_select.light_%s_off" % gid, SEL_OFF))

print("Удалить: %d" % len(to_delete))
for e in to_delete:
    print("  -", e)
print("Синхронизировать опции: %d" % len(to_sync))

if not args.confirm:
    print("Для применения запусти с --confirm")
else:
    ws = WS()
    for e in to_delete:
        ws.delete(e)
    for eid, opts in to_sync:
        ws.set_options(eid, opts)
    ws.ws.close()
    print("Готово. Если чего-то не хватает — python3 tools/gen_helpers.py --apply")