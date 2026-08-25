#!/usr/bin/env python3
"""Клиент HA: REST + WebSocket (helpers, сервисы). Каноническая версия для CLI и tools."""
import json
import os
import urllib.request

def ha_url():
    return os.environ.get("HA_URL", "http://homeassistant.local:8123")

def ha_token():
    tok = os.environ.get("HA_TOKEN")
    if tok:
        return tok
    p = os.path.expanduser("~/.ha_token")
    if os.path.exists(p):
        return open(p).read().strip()
    return ""

def _req(path, data=None):
    headers = {"Authorization": "Bearer " + ha_token()}
    if data is not None:
        headers["Content-Type"] = "application/json"
    r = urllib.request.Request(ha_url() + path,
                               data=json.dumps(data).encode() if data is not None else None,
                               headers=headers, method="POST" if data is not None else "GET")
    with urllib.request.urlopen(r, timeout=10) as resp:
        return json.load(resp)

def rest_get(path):
    return _req(path)

def all_entity_ids():
    return set(s["entity_id"] for s in rest_get("/api/states"))

def list_all_states():
    return rest_get("/api/states")


def exists(eid):
    return state(eid) is not None


def state(eid):
    try:
        return rest_get("/api/states/" + eid)
    except Exception:
        return None

class WS:
    def __init__(self):
        import websocket
        url = ha_url().replace("https://", "wss://").replace("http://", "ws://") + "/api/websocket"
        self.ws = websocket.create_connection(url, timeout=15)
        json.loads(self.ws.recv())
        self.ws.send(json.dumps({"type": "auth", "access_token": ha_token()}))
        json.loads(self.ws.recv())
        self.mid = 0

    def send(self, cmd):
        self.mid += 1
        cmd = dict(cmd)
        cmd["id"] = self.mid
        self.ws.send(json.dumps(cmd))
        while True:
            msg = json.loads(self.ws.recv())
            if msg.get("id") == self.mid:
                return msg

    def call_service(self, domain, service, data):
        return self.send({"type": "call_service", "domain": domain,
                          "service": service, "service_data": data})

    def create(self, entry):
        cmd = {"type": entry["type"], "name": entry["name"]}
        for k in ("options", "initial", "icon", "min", "max", "step", "has_date", "has_time"):
            if k in entry:
                cmd[k] = entry[k]
        return self.send(cmd).get("success", False)

    def delete(self, eid):
        dom, name = eid.split(".", 1)
        for payload in ({"type": dom + "/delete", "name": name},
                        {"type": dom + "/delete", dom + "_id": name},
                        {"type": dom + "/delete", dom + "_id": eid}):
            if self.send(payload).get("success"):
                return True
        return False

    delete_entity = delete

    def set_options(self, eid, options):
        self.call_service("input_select", "set_options", {"entity_id": eid, "options": options})

    def close(self):
        try:
            self.ws.close()
        except Exception:
            pass