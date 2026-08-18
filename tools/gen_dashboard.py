#!/usr/bin/env python3
"""Манифест -> Lovelace yaml-дашборд освещения.

На группу: карточка с vlight-тумблером и select'ом режима;
datetime показывается условно (только при select=Время).
Зоны: поле `zone` в манифесте (опционально) + эвристика по id.
"""
import argparse, os
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
            {"entity": "input_datetime.light_%s_off_time" % gid, "name": "Выключить в"}]},
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


def color_view():
    return {
        "title": "Цвет",
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
    }

def service_view():
    return {
        "title": "Сервис",
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
    }


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--manifest", default="manifests/leonid_house.yaml")
    p.add_argument("--out", default="/config/dashboards/lighting-dashboard.yaml")
    args = p.parse_args()

    m = yaml.safe_load(open(args.manifest))
    f = m.get("features", m)
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
            "cards": [group_card(g) for g in gs],
        })
    views.append(color_view())
    views.append(service_view())

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w") as fh:
        yaml.safe_dump({"title": "Освещение", "views": views}, fh,
                       allow_unicode=True, sort_keys=False, default_flow_style=False)
    print("Dashboard written: %s (%d views, %d groups)"
          % (args.out, len(views), len(groups)))


if __name__ == "__main__":
    main()