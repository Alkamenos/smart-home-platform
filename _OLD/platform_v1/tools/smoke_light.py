#!/usr/bin/env python3
"""Пост-рестарт проверка освещения: таблица flag/sel/vlight/real по манифесту."""
import json, os, time, urllib.request
import yaml

HA_URL = os.environ.get("HA_URL", "http://homeassistant.local:8123")
tok_path = os.path.expanduser("~/.ha_token")
HA_TOKEN = os.environ.get("HA_TOKEN") or (open(tok_path).read().strip() if os.path.exists(tok_path) else "")

def get(path):
    req = urllib.request.Request(HA_URL + path, headers={"Authorization": "Bearer " + HA_TOKEN})
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.load(r)

def st(eid):
    if not eid:
        return "-"
    try:
        return get("/api/states/" + eid)["state"]
    except Exception:
        return "missing"

for _ in range(60):
    try:
        get("/api/")
        break
    except Exception:
        time.sleep(5)

m = yaml.safe_load(open("manifests/leonid_house.yaml"))
f = m.get("features", m)
groups = (f.get("lighting", {}) or {}).get("groups", [])
print("%-18s %-5s %-12s %-7s %s" % ("group", "flag", "sel", "vlight", "real"))
for g in groups:
    gid = str(g.get("id"))
    fs = st(g.get("feature_flag"))
    fs = "on" if fs == "on" else ("off" if fs == "off" else fs)
    sel = st("input_select.light_%s_on" % gid)
    vl = st("input_boolean.vlight_%s" % gid)
    reals = ",".join(st(e) for e in (g.get("lights") or []) if e) or "-"
    print("%-18s %-5s %-12s %-7s %s" % (gid, fs, sel, vl, reals))
