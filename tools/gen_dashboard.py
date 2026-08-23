#!/usr/bin/env python3
"""Манифест -> полный Lovelace дашборд (обзор, освещение, климат, вентиляция,
здоровье, фичи, сервис).
"""
import argparse
import os
import yaml

ZONE_TITLES = {"street": "Улица", "garden": "Сад", "house": "Дом"}


def default_zone(gid):
    if any([k in gid for k in ("yard", "street", "flood", "container", "xmas")]):
        return "street"
    if any([k in gid for k in ("terrace", "garden", "path")]):
        return "garden"
    return "house"


def nice(gid):
    return gid.replace("_", " ").capitalize()


# ============================================================
# ОСВЕЩЕНИЕ: карточка группы
# ============================================================
def group_card(g):
    gid = str(g.get("id"))
    sel_on = "input_select.light_%s_on" % gid
    sel_off = "input_select.light_%s_off" % gid
    ents = [
        {"entity": "input_boolean.vlight_%s" % gid, "name": "Свет"},
        {"entity": sel_on, "name": "Включение"},
        {"entity": sel_off, "name": "Выключение"},
        {"entity": "input_number.light_%s_brightness" % gid, "name": "Яркость"},
    ]
    cards = [{
        "type": "entities", "title": g.get("name", nice(gid)), "entities": ents,
    }]

    cards.append({
        "type": "conditional",
        "conditions": [{"entity": sel_on, "state": "Время"}],
        "card": {"type": "entities", "entities": [
            {"entity": "input_datetime.light_%s_on_time" % gid, "name": "Включить в"}]},
    })

    cards.append({
        "type": "conditional",
        "conditions": [{"entity": sel_off, "state": "Время"}],
        "card": {"type": "entities", "entities": [
            {"entity": "input_datetime.light_%s_off_time" % gid, "name": "Выключить в"},
            {"entity": "input_datetime.light_%s_off_end_time" % gid, "name": "Конец окна выкл"}]},
    })

    # Датчик движения (если есть)
    if g.get("motion_sensor"):
        cards.append({
            "type": "custom:mushroom-select-card",
            "entity": "input_select.light_%s_motion_sensor" % gid,
            "name": "Датчик движения",
        })
        cards.append({
            "type": "entities", "title": "Датчик движения", "entities": [
                {"entity": "input_boolean.light_%s_motion" % gid, "name": "Учитывать"},
                {"entity": "input_boolean.light_%s_motion_day" % gid, "name": "Включать днём"},
                {"entity": "input_number.light_%s_motion_day_min" % gid, "name": "Таймаут днём, мин"},
                {"entity": "input_number.light_%s_motion_night_min" % gid, "name": "Таймаут ночью, мин"},
            ],
        })

        # Ночник
        if g.get("nightlight"):
            cards.append({
                "type": "conditional",
                "conditions": [
                    {"entity": "input_boolean.feature_%s_nightlight" % gid, "state": "on"},
                    {"entity": sel_on, "state": "Датчик движения"},
                ],
                "card": {
                    "type": "vertical-stack",
                    "cards": [
                        {"type": "custom:mushroom-title-card", "title": "🌙 Ночной режим"},
                        {"type": "custom:mushroom-entity-card",
                         "entity": "input_boolean.feature_%s_nightlight" % gid,
                         "name": "Включено"},
                        {"type": "custom:mushroom-number-card",
                         "entity": "input_number.light_%s_nightlight_brightness" % gid,
                         "name": "Яркость"},
                        {"type": "custom:mushroom-number-card",
                         "entity": "input_number.light_%s_nightlight_off_min" % gid,
                         "name": "Таймаут, мин"},
                        {"type": "horizontal-stack", "cards": [
                            {"type": "custom:mushroom-number-card",
                             "entity": "input_number.light_%s_nightlight_r" % gid, "name": "R"},
                            {"type": "custom:mushroom-number-card",
                             "entity": "input_number.light_%s_nightlight_g" % gid, "name": "G"},
                            {"type": "custom:mushroom-number-card",
                             "entity": "input_number.light_%s_nightlight_b" % gid, "name": "B"},
                        ]},
                    ],
                },
            })

    return {"type": "vertical-stack", "cards": cards}


def lighting_view(manifest):
    lighting = (manifest.get("features", {}) or {}).get("lighting", {}) or {}
    groups = lighting.get("groups", []) or []
    zones = {}
    for g in groups:
        z = g.get("zone") or default_zone(str(g.get("id")))
        zones.setdefault(z, []).append(g)

    views = []
    for z in ("street", "garden", "house"):
        gs = zones.get(z, [])
        if not gs:
            continue
        views.append({
            "title": "💡 " + ZONE_TITLES.get(z, z),
            "path": "light_" + z,
            "icon": "mdi:lightbulb",
            "cards": [group_card(g) for g in gs],
        })

    views.append({
        "title": "🎨 Цвет",
        "path": "light_color",
        "icon": "mdi:palette",
        "cards": [{
            "type": "entities",
            "title": "Температура и цвет",
            "entities": [
                {"entity": "input_number.ct_day_kelvin", "name": "Дневная, K"},
                {"entity": "input_number.ct_night_kelvin", "name": "Ночная, K"},
                {"entity": "input_datetime.ct_warm_from", "name": "Смягчать с"},
                {"entity": "input_datetime.ct_night_from", "name": "Ночная с"},
                {"entity": "input_boolean.feature_rgb", "name": "RGB-сцены"},
                {"entity": "input_select.light_rgb_scene", "name": "Сцена"},
            ],
        }],
    })
    return views


# ============================================================
# ОБЗОР
# ============================================================
def overview_view(manifest):
    features = manifest.get("features", {}) or {}
    feature_cards = []
    for fname in sorted(features.keys()):
        feature_cards.append({
            "type": "custom:mushroom-entity-card",
            "entity": "input_boolean.feature_" + fname,
            "name": nice(fname),
            "icon": "mdi:toggle-switch",
        })

    return {
        "title": "🏠 Обзор",
        "path": "overview",
        "icon": "mdi:home-assistant",
        "cards": [
            {"type": "custom:mushroom-title-card",
             "title": "Дом Леонида"},
            {"type": "custom:mushroom-chips-card", "chips": [
                {"type": "template",
                 "content": "{% if is_state('input_boolean.zima', 'on') %}❄️ Зима{% else %}☀️ Лето{% endif %}"},
                {"type": "template",
                 "content": "{% if is_state('input_boolean.my_doma', 'on') %}🏡 Дома{% else %}✈️ Нет{% endif %}"},
                {"type": "template",
                 "content": "{% if is_state('input_boolean.vecher', 'on') %}🌙 Вечер{% else %}☀️ День{% endif %}"},
                {"type": "template",
                 "content": "{% if is_state('input_boolean.party_mode', 'on') %}🎉 Вечеринка{% endif %}"},
            ]},
            {"type": "custom:mushroom-title-card", "title": "Глобальные режимы"},
            {"type": "horizontal-stack", "cards": [
                {"type": "custom:mushroom-entity-card",
                 "entity": "input_boolean.zima", "name": "Зима", "icon": "mdi:snowflake"},
                {"type": "custom:mushroom-entity-card",
                 "entity": "input_boolean.vecher", "name": "Вечер", "icon": "mdi:weather-night"},
                {"type": "custom:mushroom-entity-card",
                 "entity": "input_boolean.my_doma", "name": "Дома", "icon": "mdi:account-home"},
                {"type": "custom:mushroom-entity-card",
                 "entity": "input_boolean.party_mode", "name": "Вечеринка", "icon": "mdi:party-popper"},
            ]},
            {"type": "custom:mushroom-title-card", "title": "Фичи платформы"},
            {"type": "vertical-stack", "cards": feature_cards},
        ],
    }


# ============================================================
# КЛИМАТ
# ============================================================
def climate_view(manifest):
    climate = (manifest.get("features", {}) or {}).get("climate", {}) or {}
    zones = climate.get("zones", []) or []
    devices = manifest.get("devices", {}) or {}
    sensors = devices.get("sensors", []) or []
    actuators = devices.get("actuators", []) or []

    zone_cards = []
    for zone in zones:
        zid = zone.get("id")
        temp_entity = None
        for dev in sensors:
            if dev.get("id") == zone.get("temp_sensor_ref"):
                temp_entity = dev.get("entity")
                break

        glance_ents = []
        if temp_entity:
            glance_ents.append({"entity": temp_entity, "name": "Сейчас"})
        for act in (zone.get("actuators", []) or []):
            for dev in actuators:
                if dev.get("id") == act.get("ref"):
                    glance_ents.append({"entity": dev.get("entity"), "name": act.get("role", "")})
                    break

        zone_cards.append({
            "type": "vertical-stack",
            "cards": [
                {"type": "custom:mushroom-title-card",
                 "title": nice(zid),
                 "subtitle": "{{ states('sensor.climate_" + str(zid) + "_status') }}"},
                {"type": "glance", "entities": glance_ents,
                 "columns": min(len(glance_ents), 3)},
            ],
        })

    setpoints = []
    seen = set()
    for zone in zones:
        for sp in (zone.get("setpoints") or {}).values():
            if isinstance(sp, dict):
                src = sp.get("source", "")
                if src.startswith("input_number.") and src not in seen:
                    seen.add(src)
                    setpoints.append({"entity": src})

    cards = [
        {"type": "entities", "title": "⚙️ Управление",
         "entities": [
             {"entity": "input_boolean.feature_climate", "name": "Климат (платформа)"},
             {"entity": "input_boolean.climate_shadow_mode", "name": "Режим наблюдения"},
             {"entity": "input_boolean.zima", "name": "Сезон (зима)"},
         ]},
        {"type": "entities", "title": "🎯 Уставки",
         "entities": setpoints},
    ] + zone_cards

    return {
        "title": "🌡️ Климат",
        "path": "climate",
        "icon": "mdi:thermometer",
        "cards": cards,
    }


# ============================================================
# ВЕНТИЛЯЦИЯ
# ============================================================
def ventilation_view(manifest):
    vent = (manifest.get("features", {}) or {}).get("ventilation", {}) or {}
    devices = vent.get("devices", []) or []
    flags = vent.get("flags", {}) or {}
    bf = vent.get("bathroom_fan", {}) or {}

    device_cards = []
    for dev in devices:
        entity = dev.get("entity")
        did = dev.get("id")
        room_temp = None
        for r in (vent.get("rooms", []) or []):
            if did == "rek_" + str(r.get("id")):
                room_temp = r.get("temp")
                break
        glance_ents = []
        if room_temp:
            glance_ents.append({"entity": room_temp, "name": "t°"})
        glance_ents.append({"entity": entity, "name": "Fan"})
        device_cards.append({
            "type": "vertical-stack",
            "cards": [
                {"type": "custom:mushroom-title-card",
                 "title": nice(did),
                 "subtitle": "{{ states('" + str(entity) + "') }}"},
                {"type": "glance", "entities": glance_ents,
                 "columns": len(glance_ents)},
            ],
        })

    flag_ents = []
    for key in ("boost_intake", "boost_exhaust", "night", "away_home"):
        ent = flags.get(key)
        if ent:
            flag_ents.append({"entity": ent})
    od = vent.get("open_doors", {}) or {}
    if od.get("mock_state"):
        flag_ents.append({"entity": od["mock_state"], "name": "Mock: двери/окна"})

    cards = [
        {"type": "entities", "title": "💨 Управление",
         "toggle_entity": "input_boolean.feature_ventilation",
         "entities": flag_ents},
    ] + device_cards

    bath_ents = []
    if bf.get("entity"):
        bath_ents.append({"entity": bf["entity"], "name": "Вентилятор"})
    if bf.get("temp_sensor"):
        bath_ents.append({"entity": bf["temp_sensor"], "name": "t°"})
    if bf.get("humidity_sensor"):
        bath_ents.append({"entity": bf["humidity_sensor"], "name": "Влажность"})
    if bath_ents:
        cards.append({"type": "entities", "title": "🚿 Санузел", "entities": bath_ents})

    return {
        "title": "💨 Вентиляция",
        "path": "ventilation",
        "icon": "mdi:fan",
        "cards": cards,
    }


# ============================================================
# ЗДОРОВЬЕ
# ============================================================
def health_view(manifest):
    sh = (manifest.get("features", {}) or {}).get("sensor_health", {}) or {}
    sensors = sh.get("sensors", []) or []
    ents = []
    for s in sensors:
        entity = s.get("entity") if isinstance(s, dict) else s
        if entity:
            ents.append({"entity": entity})

    return {
        "title": "🔋 Здоровье",
        "path": "health",
        "icon": "mdi:heart-pulse",
        "cards": [
            {"type": "entities", "title": "Статус", "entities": [
                {"entity": "sensor.sensor_health_status", "name": "Общий статус"},
            ]},
            {"type": "entities", "title": "Датчики", "entities": ents},
        ],
    }


# ============================================================
# ФИЧИ
# ============================================================
def features_view(manifest):
    features = manifest.get("features", {}) or {}
    cards = []
    for fname in sorted(features.keys()):
        ents = [
            {"entity": "input_boolean.feature_" + fname, "name": "Включено"},
        ]
        shadow = "input_boolean." + fname + "_shadow_mode"
        ents.append({"entity": shadow, "name": "Shadow mode"})
        cards.append({
            "type": "entities",
            "title": nice(fname),
            "entities": ents,
        })
    return {
        "title": "⚙️ Фичи",
        "path": "features",
        "icon": "mdi:tune",
        "cards": cards,
    }


# ============================================================
# СЕРВИС
# ============================================================
def service_view():
    return {
        "title": "🔧 Сервис",
        "path": "service",
        "icon": "mdi:wrench",
        "cards": [
            {"type": "entities", "title": "Диагностика", "entities": [
                {"entity": "sensor.pyscript_manifest_status", "name": "Манифест"},
                {"entity": "sensor.pyscript_climate_debug", "name": "Климат"},
                {"entity": "sensor.pyscript_vent_debug", "name": "Вентиляция"},
                {"entity": "sensor.pyscript_light_debug", "name": "Свет"},
                {"entity": "sensor.pyscript_override_status", "name": "Override"},
            ]},
            {"type": "horizontal-stack", "cards": [
                {"type": "button", "name": "Manifest reload", "icon": "mdi:reload",
                 "tap_action": {"action": "call-service", "service": "pyscript.manifest_reload"}},
                {"type": "button", "name": "Light debug", "icon": "mdi:bug-outline",
                 "tap_action": {"action": "call-service", "service": "pyscript.light_debug"}},
                {"type": "button", "name": "Override clear", "icon": "mdi:lock-open-outline",
                 "tap_action": {"action": "call-service", "service": "pyscript.override_clear"}},
            ]},
        ],
    }


# ============================================================
# MAIN
# ============================================================
def main():
    p = argparse.ArgumentParser()
    p.add_argument("--manifest", default="manifests/leonid_house.yaml")
    p.add_argument("--out", default="/config/dashboards/smart-home-full.yaml")
    args = p.parse_args()

    m = yaml.safe_load(open(args.manifest))

    views = []
    views.append(overview_view(m))
    for v in lighting_view(m):
        views.append(v)
    views.append(climate_view(m))
    views.append(ventilation_view(m))
    views.append(health_view(m))
    views.append(features_view(m))
    views.append(service_view())

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w") as fh:
        yaml.safe_dump({"title": "Умный дом", "views": views}, fh,
                       allow_unicode=True, sort_keys=False, default_flow_style=False)
    print("Dashboard written: %s (%d views)" % (args.out, len(views)))


if __name__ == "__main__":
    main()