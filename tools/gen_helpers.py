#!/usr/bin/env python3
"""Манифест -> все helpers платформы (освещение, климат, вентиляция, здоровье, глобальные).
--apply: создаёт отсутствующие, обновляет изменившиеся (через удаление+пересоздание).
--orphan: показывает существующие, которых нет в манифесте.
--delete --confirm: удаляет orphan'ы (с защитой).
"""
import argparse
import json
import os
import yaml
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core import ha
rest_get = ha.rest_get
from core.builders import num, bool_, dt, sel
from features.climate import helpers as clim_h
from features.ventilation import helpers as vent_h
from features.lighting import helpers as FH
get_state = ha.state
exists = ha.exists
list_all_states = ha.list_all_states
WS = ha.WS

parser = argparse.ArgumentParser()
parser.add_argument("--start-id", type=int, default=1)
parser.add_argument("--groups", type=str, default=None)
parser.add_argument("--manifest", default="instances/leonid_house/manifest.yaml")
parser.add_argument("--only-missing", action="store_true")
parser.add_argument("--apply", action="store_true")
parser.add_argument("--orphan", action="store_true")
parser.add_argument("--delete", action="store_true")
parser.add_argument("--confirm", action="store_true")
args = parser.parse_args()

HA_URL = os.environ.get("HA_URL", "http://homeassistant.local:8123")
tok = os.path.expanduser("~/.ha_token")
HA_TOKEN = os.environ.get("HA_TOKEN") or (open(tok).read().strip() if os.path.exists(tok) else "")



def needs_update(ws, e):
    """Проверить, нужно ли обновлять существующий helper."""
    dom = e["type"].split("/")[0]
    eid = dom + "." + e["name"]
    st = get_state(eid)
    if st is None:
        return True

    if dom == "input_select":
        cur_opts = st.get("attributes", {}).get("options", [])
        if cur_opts != e["options"]:
            print("  options changed: %s (was %d, now %d)" % (eid, len(cur_opts), len(e["options"])))
            return True

    return False


def create(ws, e):
    dom = e["type"].split("/")[0]
    eid = dom + "." + e["name"]

    # Проверяем, нужно ли обновлять
    if needs_update(ws, e):
        # Удаляем старый
        if exists(eid):
            ws.delete_entity(eid)

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
    print("created/updated:", eid)
    return True

def sync_select_options(ws, e):
    """Если это input_select и он существует, но опции отличаются — обновить."""
    dom = e["type"].split("/")[0]
    if dom != "input_select":
        return False
    eid = "input_select." + e["name"]
    try:
        st = rest_get("/api/states/" + eid)
    except Exception:
        return False
    cur = st.get("attributes", {}).get("options", [])
    want = e.get("options", [])
    if cur == want:
        return False
    ws.call_service("input_select", "set_options",
                    {"entity_id": eid, "options": want})
    print("updated options:", eid, cur, "->", want)
    return True

m = yaml.safe_load(open(args.manifest))
features = m.get("features", m)
lighting = features.get("lighting", {}) or {}
climate = features.get("climate", {}) or {}
ventilation = features.get("ventilation", {}) or {}
sensor_health = features.get("sensor_health", {}) or {}
groups = features.get("groups") or lighting.get("groups", []) or []
from features.lighting import schema as RF
groups = [RF.resolve_group(g) for g in groups]
want = [s.strip() for s in args.groups.split(",")] if args.groups else None

SEL_ON = ["Не включать", "Закат", "Время", "Датчик движения"]
SEL_OFF = ["Время", "Рассвет", "Не выключать", "Датчик движения"]
RGB = ["Белый", "Красный", "Оранжевый", "Зелёный", "Синий", "Фиолетовый", "Розовый"]


# Собрать motion_sensor по комнатам (для dropdown)
motion_by_room = {}
for g in groups:
    room = g.get("room")
    ms = g.get("motion_sensor")
    if room and ms:
        motion_by_room.setdefault(room, []).append(ms)

entries = []
i = args.start_id

# ============================================================
# LIGHTING: per-group
# ============================================================
for g in groups:
    gid = str(g.get("id"))
    if want and gid not in want:
        continue

    entries += [
        bool_(i, "vlight_" + gid, None, "mdi:lightbulb"),
        sel(i + 1, "light_%s_on" % gid, SEL_ON, "Закат", "mdi:form-select"),
        sel(i + 2, "light_%s_off" % gid, SEL_OFF, "Время", "mdi:power-sleep"),
        dt(i + 3, "light_%s_on_time" % gid, "18:00", "mdi:clock-outline"),
        dt(i + 4, "light_%s_off_time" % gid, "23:00", "mdi:clock-outline"),
        dt(i + 5, "light_%s_off_end_time" % gid, "06:00", "mdi:clock-end"),
        num(i + 6, "light_%s_brightness" % gid, 1, 100, 1, 100, "mdi:brightness-percent"),
        bool_(i + 7, "feature_" + gid, "on", "mdi:lightbulb-group"),
    ]
    i += 8

    add, i = FH.group_feature_helpers(g, gid, i, {"motion_by_room": motion_by_room})
    entries += add

# ============================================================
# LIGHTING: глобальные (color temp, RGB, imitation, backlight)
# ============================================================
entries += [
    num(i, "ct_day_kelvin", 2000, 6000, 50, 5000, "mdi:thermometer-sun"),
    num(i + 1, "ct_night_kelvin", 2000, 6000, 50, 2200, "mdi:thermometer-moon"),
    dt(i + 2, "ct_warm_from", "21:00", "mdi:clock-outline"),
    dt(i + 3, "ct_night_from", "23:00", "mdi:clock-outline"),
    bool_(i + 4, "feature_rgb", "off", "mdi:palette"),
    sel(i + 5, "light_rgb_scene", RGB, "Белый", "mdi:palette"),
    bool_(i + 6, "feature_lighting", "on", "mdi:lightbulb-auto"),
    bool_(i + 7, "lighting_shadow_mode", "off", "mdi:eye-off-outline"),
    bool_(i + 8, "feature_color_temp", "on", "mdi:thermometer-lines"),
    bool_(i + 9, "feature_backlight", "on", "mdi:led-on"),
    bool_(i + 10, "feature_imitation", "off", "mdi:account-eye"),
    dt(i + 11, "imitation_start", "20:00", "mdi:clock-start"),
    dt(i + 12, "imitation_end", "07:00", "mdi:clock-end"),
    num(i + 13, "motion_day_min", 1, 120, 1, 5, "mdi:timer-outline"),
    num(i + 14, "motion_night_min", 1, 60, 1, 2, "mdi:timer-outline")
]
i += 15

add, i = clim_h.climate_entries(climate, i)
entries += add

add, i = vent_h.vent_entries(ventilation, i)
entries += add

# ============================================================
# FEATURES & SHADOW MODES (для дашборда)
# ============================================================
created_names = set([e["name"] for e in entries])
for fname in features.keys():
    if fname == "groups":
        continue
    f_name = "feature_" + fname
    if f_name not in created_names:
        entries.append(bool_(i, f_name, "on", "mdi:toggle-switch"))
        i += 1
        created_names.add(f_name)

    s_name = fname + "_shadow_mode"
    if s_name not in created_names:
        entries.append(bool_(i, s_name, "off", "mdi:eye-off-outline"))
        i += 1
        created_names.add(s_name)

# ============================================================
# GLOBALS (zima, vecher, my_doma, party_mode)
# ============================================================
for extra in ("zima", "vecher", "my_doma", "party_mode"):
    if extra not in created_names:
        entries.append(bool_(i, extra, "off", "mdi:toggle-switch"))
        i += 1
        created_names.add(extra)

expected_ids = [e["type"].split("/")[0] + "." + e["name"] for e in entries]

# ============================================================
# Orphan detection
# ============================================================
WHITELIST_NAMES = {"zima", "vecher", "my_doma", "party_mode"}
ORPHAN_PREFIXES = (
    "vlight_", "light_", "feature_", "ct_", "light_rgb_",
    "imitation_", "vlazhnost_",
)
SHADOW_SUFFIX = "_shadow_mode"


def is_orphan_candidate(eid):
    if eid.split(".")[0] not in ("input_boolean", "input_select",
                                  "input_datetime", "input_number"):
        return False
    name = eid.split(".", 1)[1]
    if name in WHITELIST_NAMES:
        return False
    return any([name.startswith(p) for p in ORPHAN_PREFIXES]) or name.endswith(SHADOW_SUFFIX)


def find_orphans():
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


if args.orphan or args.delete:
    orphans = find_orphans()
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
            if ws.delete_entity(o):
                done += 1
        ws.ws.close()
        print("deleted: %d" % done)
    raise SystemExit(0)

missing = [e for e in entries if not exists(e["type"].split("/")[0] + "." + e["name"])]
print("Expected: %d, missing: %d" % (len(entries), len(missing)))


if args.apply:
    if not HA_TOKEN:
        raise SystemExit("Нужен ~/.ha_token")
    missing = [e for e in entries if not exists(e["type"].split("/")[0] + "." + e["name"])]
    ws = WS()
    done = 0
    for e in missing:
        if create(ws, e):
            done += 1
    upd = 0
    for e in entries:
        if sync_select_options(ws, e):
            upd += 1
    ws.ws.close()
    print("total created: %d, options updated: %d" % (done, upd))

else:
    print(json.dumps(missing if args.only_missing else entries,
                     ensure_ascii=False, indent=2))