#!/usr/bin/env python3
"""Манифест -> Lovelace yaml-дашборд (полный: обзор, освещение, климат, вентиляция, здоровье, фичи, сервис).
Mushroom cards + стандартные cards для conditional logic.
"""
import argparse
import os
import yaml

ZONE_TITLES = {"street": "Улица", "garden": "Сад", "house": "Дом"}

def default_zone(gid):
    if any(k in gid for k in ("yard", "street", "flood", "container", "xmas")):
        return "street"
    if any(k in gid for k in ("terrace", "garden", "path")):
        return "garden"
    return "house"

def nice(gid):
    return gid.replace("_", " ").capitalize()

# ============================================================
# ОБЗОР
# ============================================================
def overview_view(manifest):
    features = manifest.get("features", {})
    feature_flags = []
    for fname in features:
        feature_flags.append({
            "type": "custom:mushroom-entity-card",
            "entity": "input_boolean.feature_" + fname,
            "name": fname.replace("_", " ").title(),
            "icon": "mdi:toggle-switch",
            "layout": "horizontal",
        })
    
    return {
        "title": "🏠 Обзор",
        "path": "overview",
        "icon": "mdi:home-assistant",
        "cards": [
            {
                "type": "custom:mushroom-title-card",
                "title": "Дом Леонида",
                "subtitle": "Платформа v{{ states('sensor.pyscript_manifest_status') }}",
            },
            {
                "type": "custom:mushroom-chips-card",
                "chips": [
                    {
                        "type": "template",
                        "content": "{% if is_state('input_boolean.zima', 'on') %}❄️ Зима{% else %}☀️ Лето{% endif %}",
                        "icon": "mdi:weather-sunny",
                    },
                    {
                        "type": "template",
                        "content": "{% if is_state('input_boolean.my_doma', 'on') %}🏡 Дома{% else %}✈️ Нет{% endif %}",
                        "icon": "mdi:account-home",
                    },
                    {
                        "type": "template",
                        "content": "{% if is_state('input_boolean.vecher', 'on') %}🌙 Вечер{% else %}☀️ День{% endif %}",
                        "icon": "mdi:weather-night",
                    },
                ],
            },
            {
                "type": "custom:mushroom-title-card",
                "title": "Глобальные режимы",
            },
            {
                "type": "horizontal-stack",
                "cards": [
                    {
                        "type": "custom:mushroom-entity-card",
                        "entity": "input_boolean.zima",
                        "name": "Зима",
                        "icon": "mdi:snowflake",
                    },
                    {
                        "type": "custom:mushroom-entity-card",
                        "entity": "input_boolean.vecher",
                        "name": "Вечер",
                        "icon": "mdi:weather-night",
                    },
                    {
                        "type": "custom:mushroom-entity-card",
                        "entity": "input_boolean.my_doma",
                        "name": "Дома",
                        "icon": "mdi:account-home",
                    },
                    {
                        "type": "custom:mushroom-entity-card",
                        "entity": "input_boolean.party_mode",
                        "name": "Вечеринка",
                        "icon": "mdi:party-popper",
                    },
                ],
            },
            {
                "type": "custom:mushroom-title-card",
                "title": "Фичи платформы",
            },
            {
                "type": "vertical-stack",
                "cards": feature_flags,
            },
        ],
    }

# ============================================================
# ОСВЕЩЕНИЕ
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
    if g.get("motion_sensor"):
        cards.append({
            "type": "entities", "title": "Датчик движения", "entities": [
                {"entity": "input_boolean.light_%s_motion" % gid, "name": "Учитывать"},
                {"entity": "input_boolean.light_%s_motion_day" % gid, "name": "Включать днём"},
                {"entity": "input_number.light_%s_motion_day_min" % gid, "name": "Таймаут днём, мин"},
                {"entity": "input_number.light_%s_motion_night_min" % gid, "name": "Таймаут ночью, мин"},
            ],
        })
    return {"type": "vertical-stack", "cards": cards}

def lighting_view(manifest):
    f = manifest.get("features", {})
    groups = (f.get("lighting", {}) or {}).get("groups", [])
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
            "title": ZONE_TITLES.get(z, z),
            "path": "light_" + z,
            "icon": "mdi:lightbulb",
            "cards": [group_card(g) for g in gs],
        })
    
    # Цвет
    views.append({
        "title": "Цвет",
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
    
    # Сервис
    views.append({
        "title": "Сервис",
        "path": "light_service",
        "icon": "mdi:cog",
        "cards": [
            {
                "type": "entities",
                "title": "Платформа",
                "entities": [
                    {"entity": "input_boolean.feature_lighting", "name": "Мастер-флаг освещения"},
                    {"entity": "input_boolean.lighting_shadow_mode", "name": "Shadow mode (весь свет)"},
                ],
            },
            {
                "type": "horizontal-stack",
                "cards": [
                    {
                        "type": "button",
                        "name": "Debug",
                        "icon": "mdi:bug-outline",
                        "tap_action": {"action": "call-service", "service": "pyscript.light_debug"},
                    },
                    {
                        "type": "button",
                        "name": "Сброс override",
                        "icon": "mdi:lock-open-outline",
                        "tap_action": {"action": "call-service", "service": "pyscript.light_override_clear"},
                    },
                ],
            },
        ],
    })
    
    return views

# ============================================================
# КЛИМАТ
# ============================================================
def climate_view(manifest):
    climate_cfg = manifest.get("features", {}).get("climate", {})
    zones = climate_cfg.get("zones", [])
    
    zone_cards = []
    for zone in zones:
        zid = zone.get("id")
        temp_sensor_ref = zone.get("temp_sensor_ref")
        temp_sensor = None
        for dev in manifest.get("devices", {}).get("sensors", []):
            if dev.get("id") == temp_sensor_ref:
                temp_sensor = dev.get("entity")
                break
        
        actuators = zone.get("actuators", [])
        glance_entities = []
        if temp_sensor:
            glance_entities.append({"entity": temp_sensor, "name": "Сейчас"})
        for act in actuators:
            dev = None
            for d in manifest.get("devices", {}).get("actuators", []):
                if d.get("id") == act.get("ref"):
                    dev = d
                    break
            if dev:
                glance_entities.append({"entity": dev.get("entity"), "name": act.get("role", "")})
        
        if glance_entities:
            zone_cards.append({
                "type": "vertical-stack",
                "cards": [
                    {
                        "type": "custom:mushroom-title-card",
                        "title": nice(zid),
                        "subtitle": "{{ states('sensor.climate_" + zid + "_status') }}",
                    },
                    {
                        "type": "glance",
                        "entities": glance_entities,
                        "columns": min(len(glance_entities), 3),
                    },
                ],
            })
    
    setpoints = []
    for zone in zones:
        zid = zone.get("id")
        sp = zone.get("setpoints", {})
        heat_src = sp.get("heat", {}).get("source")
        cool_src = sp.get("cool", {}).get("source")
        if heat_src:
            setpoints.append({"entity": heat_src, "name": "Нагрев " + nice(zid)})
        if cool_src:
            setpoints.append({"entity": cool_src, "name": "Охлаждение " + nice(zid)})
    
    safety = climate_cfg.get("safety", {})
    
    return {
        "title": "🌡️ Климат",
        "path": "climate",
        "icon": "mdi:thermometer",
        "cards": [
            {
                "type": "entities",
                "title": "Управление",
                "show_header_toggle": False,
                "entities": [
                    {"entity": "input_boolean.feature_climate", "name": "Климат (платформа)"},
                    {"entity": "input_boolean.climate_shadow_mode", "name": "Режим наблюдения (shadow)"},
                    {"entity": "input_boolean.zima", "name": "Сезон (зима)"},
                ],
            },
            {
                "type": "entities",
                "title": "Уставки температуры",
                "entities": setpoints,
            },
            {
                "type": "entities",
                "title": "Безопасность",
                "entities": [
                    {"entity": "input_number.vlazhnost_v_dome", "name": "Влажность в доме"},
                ],
            },
        ] + zone_cards,
    }

# ============================================================
# ВЕНТИЛЯЦИЯ
# ============================================================
def ventilation_view(manifest):
    vent_cfg = manifest.get("features", {}).get("ventilation", {})
    devices = vent_cfg.get("devices", [])
    flags = vent_cfg.get("flags", {})
    bathroom_fan = vent_cfg.get("bathroom_fan", {})
    
    device_cards = []
    for dev in devices:
        entity = dev.get("entity")
        did = dev.get("id")
        room = None
        for r in vent_cfg.get("rooms", []):
            if did == "rek_" + r.get("id"):
                room = r
                break
        temp_entity = room.get("temp") if room else None
        
        glance_ents = []
        if temp_entity:
            glance_ents.append({"entity": temp_entity, "name": "t°"})
        glance_ents.append({"entity": entity, "name": "Fan"})
        
        device_cards.append({
            "type": "vertical-stack",
            "cards": [
                {
                    "type": "custom:mushroom-title-card",
                    "title": nice(did),
                    "subtitle": "Рекуператор: {{ states('" + entity + "') }}",
                },
                {
                    "type": "glance",
                    "entities": glance_ents,
                    "columns": len(glance_ents),
                },
            ],
        })
    
    flag_entities = []
    if flags.get("boost_intake"):
        flag_entities.append({"entity": flags["boost_intake"], "name": "Проветривание (приток boost)"})
    if flags.get("boost_exhaust"):
        flag_entities.append({"entity": flags["boost_exhaust"], "name": "Вытяжка boost"})
    if flags.get("night"):
        flag_entities.append({"entity": flags["night"], "name": "Ночной режим"})
    if flags.get("away_home"):
        flag_entities.append({"entity": flags["away_home"], "name": "Дома"})
    
    open_doors = vent_cfg.get("open_doors", {})
    if open_doors.get("mock"):
        flag_entities.append({"entity": open_doors.get("mock_state"), "name": "Mock: открытые двери/окна"})
    
    bath_entities = []
    if bathroom_fan.get("entity"):
        bath_entities.append({"entity": bathroom_fan["entity"], "name": "Вентилятор санузла"})
    if bathroom_fan.get("temp_sensor"):
        bath_entities.append({"entity": bathroom_fan["temp_sensor"], "name": "Температура"})
    if bathroom_fan.get("humidity_sensor"):
        bath_entities.append({"entity": bathroom_fan["humidity_sensor"], "name": "Влажность"})
    
    return {
        "title": "💨 Вентиляция",
        "path": "ventilation",
        "icon": "mdi:fan",
        "cards": [
            {
                "type": "entities",
                "title": "Управление",
                "show_header_toggle": True,
                "toggle_entity": "input_boolean.feature_ventilation",
                "entities": flag_entities,
            },
        ] + device_cards + ([{
            "type": "entities",
            "title": "Вентилятор санузла",
            "entities": bath_entities,
        }] if bath_entities else []),
    }

# ============================================================
# ЗДОРОВЬЕ
# ============================================================
def health_view(manifest):
    sh_cfg = manifest.get("features", {}).get("sensor_health", {})
    sensors = sh_cfg.get("sensors", [])
    
    sensor_entities = []
    for s in sensors:
        entity = s.get("entity") if isinstance(s, dict) else s
        if entity:
            sensor_entities.append({"entity": entity, "name": entity.split(".")[-1].replace("_", " ").title()})
    
    return {
        "title": "🔋 Здоровье",
        "path": "health",
        "icon": "mdi:heart-pulse",
        "cards": [
            {
                "type": "entities",
                "title": "Статус",
                "entities": [
                    {"entity": "sensor.sensor_health_status", "name": "Общий статус"},
                    {"entity": "sensor.battery_shopping_list", "name": "Список покупок (батарейки)"},
                ],
            },
            {
                "type": "entities",
                "title": "Датчики",
                "entities": sensor_entities,
            },
        ],
    }

# ============================================================
# ФИЧИ
# ============================================================
def features_view(manifest):
    features = manifest.get("features", {})
    
    feature_cards = []
    for fname, fcfg in features.items():
        ents = [
            {"entity": "input_boolean.feature_" + fname, "name": "Включено"},
        ]
        shadow_entity = "input_boolean." + fname + "_shadow_mode"
        if shadow_entity:
            ents.append({"entity": shadow_entity, "name": "Shadow mode"})
        
        feature_cards.append({
            "type": "entities",
            "title": nice(fname),
            "entities": ents,
        })
    
    return {
        "title": "⚙️ Фичи",
        "path": "features",
        "icon": "mdi:tune",
        "cards": feature_cards,
    }

# ============================================================
# СЕРВИС
# ============================================================
def service_view(manifest):
    return {
        "title": "🔧 Сервис",
        "path": "service",
        "icon": "mdi:wrench",
        "cards": [
            {
                "type": "entities",
                "title": "Диагностика",
                "entities": [
                    {"entity": "sensor.pyscript_manifest_status", "name": "Манифест загружен"},
                    {"entity": "sensor.pyscript_climate_debug", "name": "Климат debug"},
                    {"entity": "sensor.pyscript_vent_debug", "name": "Вентиляция debug"},
                    {"entity": "sensor.pyscript_light_debug", "name": "Свет debug"},
                    {"entity": "sensor.pyscript_override_status", "name": "Override статус"},
                    {"entity": "sensor.pyscript_sensor_health_status", "name": "Sensor health status"},
                ],
            },
            {
                "type": "horizontal-stack",
                "cards": [
                    {
                        "type": "button",
                        "name": "Manifest reload",
                        "icon": "mdi:reload",
                        "tap_action": {"action": "call-service", "service": "pyscript.manifest_reload"},
                    },
                    {
                        "type": "button",
                        "name": "Override clear (all)",
                        "icon": "mdi:lock-open-variant",
                        "tap_action": {"action": "call-service", "service": "pyscript.override_clear"},
                    },
                ],
            },
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
    views.extend(lighting_view(m))
    views.append(climate_view(m))
    views.append(ventilation_view(m))
    views.append(health_view(m))
    views.append(features_view(m))
    views.append(service_view(m))
    
    dashboard = {
        "title": "Умный дом",
        "views": views,
    }
    
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w") as fh:
        yaml.safe_dump(dashboard, fh, allow_unicode=True, sort_keys=False, default_flow_style=False)
    
    print("Dashboard written: %s (%d views)" % (args.out, len(views)))

if __name__ == "__main__":
    main()