#!/usr/bin/env python3
"""Манифест -> дашборд "Дом" (повседневный, по комнатам)."""
import argparse, os, yaml
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from features.lighting import schema as RF

ROOM_ORDER = ["gostinnaia", "spalnia", "kabinet", "sanuzel", "outdoor"]
ROOM_TITLES = {
    "gostinnaia": "🛋️ Гостиная",
    "spalnia": "🛏️ Спальня",
    "kabinet": "💼 Кабинет",
    "sanuzel": "🚿 Санузел",
    "outdoor": "🏡 Улица",
}
# Дефолтный маппинг групп света к комнатам
DEFAULT_ROOM = {
    "yard_floodlights": "outdoor", "street_night": "outdoor",
    "office": "kabinet", "bedroom": "spalnia",
    "kitchen_work": "gostinnaia", "table": "gostinnaia",
    "container": "outdoor", "bathroom": "sanuzel",
    "garland_terrace": "outdoor", "garland_street": "outdoor",
    "garland_windows": "outdoor", "xmas_a2": "outdoor",
}

def nice(gid):
    return gid.replace("_", " ").capitalize()

def light_card(g):
    gid = str(g.get("id"))
    return {
        "type": "custom:mushroom-light-card",
        "entity": "input_boolean.vlight_%s" % gid,
        "name": g.get("name", nice(gid)),
        "show_brightness_control": True,
        "use_light_color": False,
    }

def room_view(room_id, title, light_groups, climate_zone=None, vent_devices=None):
    cards = []
    # Свет
    if light_groups:
        cards.append({"type": "custom:mushroom-title-card", "title": "💡 Свет"})
        for g in light_groups:
            cards.append(light_card(g))
    # Климат
    if climate_zone:
        cards.append({"type": "custom:mushroom-title-card", "title": "🌡️ Климат"})
        temp_entity = climate_zone.get("temp_entity")
        if temp_entity:
            cards.append({"type": "custom:mushroom-template-card",
                          "primary": "Температура",
                          "secondary": "{{ states('%s') }} °C" % temp_entity,
                          "icon": "mdi:thermometer"})
        for act in climate_zone.get("actuators", []):
            cards.append({"type": "custom:mushroom-entity-card",
                          "entity": act, "name": "Обогреватель"})
        if climate_zone.get("ac"):
            cards.append({"type": "custom:mushroom-climate-card",
                          "entity": climate_zone["ac"], "name": "Кондиционер"})
    # Вентиляция
    if vent_devices:
        cards.append({"type": "custom:mushroom-title-card", "title": "💨 Вентиляция"})
        for v in vent_devices:
            cards.append({"type": "custom:mushroom-fan-card",
                          "entity": v, "name": "Рекуператор"})
    return {"title": title, "path": room_id, "icon": "mdi:home-variant", "cards": cards}

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--manifest", default="instances/leonid_house/manifest.yaml")
    p.add_argument("--out", default="/config/dashboards/home-dashboard.yaml")
    args = p.parse_args()
    m = yaml.safe_load(open(args.manifest))
    features = m.get("features", m)
    lighting = dict(features.get("lighting", {}) or {})
    groups = [RF.resolve_group(g) for g in
              (features.get("groups") or lighting.get("groups", []) or [])]
    lighting["groups"] = groups
    climate = features.get("climate", {}) or {}
    ventilation = features.get("ventilation", {}) or {}
    devices = m.get("devices", {})
    sensors_map = {d.get("id"): d.get("entity") for d in devices.get("sensors", [])}
    actuators_map = {d.get("id"): d.get("entity") for d in devices.get("actuators", [])}

    # Группировка света по комнатам
    rooms_light = {r: [] for r in ROOM_ORDER}
    for g in groups:
        gid = str(g.get("id"))
        room = g.get("room") or DEFAULT_ROOM.get(gid, "outdoor")
        if room in rooms_light:
            rooms_light[room].append(g)

    # Климат по комнатам
    rooms_climate = {}
    for zone in climate.get("zones", []):
        zid = zone.get("id")
        temp_ref = zone.get("temp_sensor_ref")
        temp_entity = sensors_map.get(temp_ref)
        acts = []
        ac = None
        for a in zone.get("actuators", []):
            ent = actuators_map.get(a.get("ref"))
            if not ent:
                continue
            if ent.startswith("climate."):
                ac = ent
            else:
                acts.append(ent)
        rooms_climate[zid] = {"temp_entity": temp_entity, "actuators": acts, "ac": ac}

    # Вентиляция по комнатам
    rooms_vent = {}
    for dev in ventilation.get("devices", []):
        did = str(dev.get("id", ""))
        for r in ventilation.get("rooms", []):
            if did == "rek_" + str(r.get("id")):
                rooms_vent.setdefault(r.get("id"), []).append(dev.get("entity"))

    views = []
    for room_id in ROOM_ORDER:
        title = ROOM_TITLES.get(room_id, room_id)
        views.append(room_view(room_id, title, rooms_light.get(room_id, []),
                               rooms_climate.get(room_id), rooms_vent.get(room_id)))

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w") as fh:
        yaml.safe_dump({"title": "Дом", "views": views}, fh,
                       allow_unicode=True, sort_keys=False, default_flow_style=False)
    print("Home dashboard: %s (%d rooms)" % (args.out, len(views)))

if __name__ == "__main__":
    main()