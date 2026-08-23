#!/usr/bin/env python3
"""Манифест -> дашборд "Настройки" (свет, климат, вентиляция, датчики, цвет)."""
import argparse, os, yaml

def nice(gid):
    return gid.replace("_", " ").capitalize()

def light_settings_card(g):
    gid = str(g.get("id"))
    sel_on = "input_select.light_%s_on" % gid
    sel_off = "input_select.light_%s_off" % gid
    ents = [
        {"entity": sel_on, "name": "Включение"},
        {"entity": sel_off, "name": "Выключение"},
        {"entity": "input_number.light_%s_brightness" % gid, "name": "Яркость"},
    ]
    cards = [{"type": "entities", "title": g.get("name", nice(gid)), "entities": ents}]
    # Время включения
    cards.append({"type": "conditional",
                  "conditions": [{"entity": sel_on, "state": "Время"}],
                  "card": {"type": "entities", "entities": [
                      {"entity": "input_datetime.light_%s_on_time" % gid, "name": "Включить в"}]}})
    # Время выключения + окно
    cards.append({"type": "conditional",
                  "conditions": [{"entity": sel_off, "state": "Время"}],
                  "card": {"type": "entities", "entities": [
                      {"entity": "input_datetime.light_%s_off_time" % gid, "name": "Выключить в"},
                      {"entity": "input_datetime.light_%s_off_end_time" % gid, "name": "Конец окна"}]}})
    # Датчик движения
    if g.get("motion_sensor"):
        # motion_ents = [
        #     {"entity": "input_select.light_%s_motion_sensor" % gid, "name": "Датчик"},
        #     {"entity": "input_boolean.light_%s_motion" % gid, "name": "Учитывать"},
        #     {"entity": "input_boolean.light_%s_motion_day" % gid, "name": "Включать днём"},
        #     {"entity": "input_number.light_%s_motion_day_min" % gid, "name": "Таймаут день"},
        #     {"entity": "input_number.light_%s_motion_night_min" % gid, "name": "Таймаут ночь"},
        # ]
        # cards.append({"type": "entities", "title": "Датчик движения", "entities": motion_ents})
        cards.append({"type": "custom:mushroom-select-card",
                      "entity": "input_select.light_%s_motion_sensor" % gid,
                      "name": "Датчик движения"})
        ents = [{"entity": "input_boolean.light_%s_motion" % gid, "name": "Учитывать"},
                {"entity": "input_boolean.light_%s_motion_day" % gid, "name": "Включать днём"}]
        if g.get("no_night_auto_flag"):
            ents.append({"entity": g["no_night_auto_flag"], "name": "Не включать ночью авто"})
        if g.get("motion_timeouts") == "own":
            ents += [{"entity": "input_number.light_%s_motion_day_min" % gid, "name": "Таймаут днём"},
                     {"entity": "input_number.light_%s_motion_night_min" % gid, "name": "Таймаут ночью"}]
        cards.append({"type": "entities", "title": "Датчик движения", "entities": ents})
        
        
        # Ночник
        if g.get("nightlight"):
            cards.append({"type": "conditional",
                          "conditions": [{"entity": "input_boolean.feature_%s_nightlight" % gid, "state": "on"}],
                          "card": {"type": "entities", "title": "🌙 Ночник", "entities": [
                              {"entity": "input_boolean.feature_%s_nightlight" % gid, "name": "Включено"},
                              {"entity": "input_number.light_%s_nightlight_brightness" % gid, "name": "Яркость"},
                              {"entity": "input_number.light_%s_nightlight_off_min" % gid, "name": "Таймаут"},
                              {"entity": "input_number.light_%s_nightlight_r" % gid, "name": "R"},
                              {"entity": "input_number.light_%s_nightlight_g" % gid, "name": "G"},
                              {"entity": "input_number.light_%s_nightlight_b" % gid, "name": "B"},
                          ]}})
            cards.append({"type": "custom:mushroom-entity-card",
                          "entity": "input_boolean.feature_%s_nightlight" % gid,
                          "name": "Ночник вкл/выкл"})
    return {"type": "vertical-stack", "cards": cards}

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--manifest", default="manifests/leonid_house.yaml")
    p.add_argument("--out", default="/config/dashboards/settings-dashboard.yaml")
    args = p.parse_args()
    m = yaml.safe_load(open(args.manifest))
    features = m.get("features", {})
    lighting = features.get("lighting", {}) or {}
    climate = features.get("climate", {}) or {}
    ventilation = features.get("ventilation", {}) or {}
    sensor_health = features.get("sensor_health", {}) or {}

    # --- Свет ---
    light_cards = [light_settings_card(g) for g in lighting.get("groups", [])]
    light_cards.insert(0, {"type": "entities", "title": "Общие", "entities": [
        {"entity": "input_boolean.feature_color_temp", "name": "Авто color temp"},
        {"entity": "input_boolean.feature_backlight", "name": "Подсветка выключателей"},
        {"entity": "input_boolean.feature_imitation", "name": "Имитация присутствия"},
        {"entity": "input_datetime.imitation_start", "name": "Имитация начало"},
        {"entity": "input_datetime.imitation_end", "name": "Имитация конец"},
        {"entity": "input_number.motion_day_min", "name": "Таймаут движения днём (глобально)"},
        {"entity": "input_number.motion_night_min", "name": "Таймаут движения ночью (глобально)"},
    ]})

    # --- Климат ---
    climate_cards = [{"type": "entities", "title": "Управление", "entities": [
        {"entity": "input_boolean.zima", "name": "Сезон (зима)"},
    ]}]
    seen_sp = set()
    sp_ents = []
    for zone in climate.get("zones", []):
        for sp in (zone.get("setpoints") or {}).values():
            if isinstance(sp, dict):
                src = sp.get("source", "")
                if src.startswith("input_number.") and src not in seen_sp:
                    seen_sp.add(src)
                    sp_ents.append({"entity": src})
    climate_cards.append({"type": "entities", "title": "Уставки", "entities": sp_ents})
    safety = climate.get("safety", {})
    if safety:
        climate_cards.append({"type": "entities", "title": "Безопасность", "entities": [
            {"entity": "input_number.vlazhnost_v_dome", "name": "Влажность в доме"},
        ]})

    # --- Вентиляция ---
    vent_cards = [{"type": "entities", "title": "Режимы", "entities": [
        {"entity": "input_boolean.provetrivanie", "name": "Проветривание"},
        {"entity": "input_boolean.provetrivanie_vytyazhka", "name": "Вытяжка"},
        {"entity": "input_boolean.vecher", "name": "Ночной режим"},
        {"entity": "input_boolean.my_doma", "name": "Дома"},
    ]}]
    od = ventilation.get("open_doors", {})
    if od.get("mock_state"):
        vent_cards.append({"type": "entities", "title": "Двери/окна", "entities": [
            {"entity": od["mock_state"], "name": "Mock: открыты"},
        ]})

    # --- Датчики ---
    sensor_cards = [{"type": "entities", "title": "Здоровье датчиков", "entities": [
        {"entity": "input_boolean.feature_sensor_health", "name": "Мониторинг"},
    ]}]
    sh_ents = []
    for s in sensor_health.get("sensors", []):
        ent = s.get("entity") if isinstance(s, dict) else s
        if ent:
            sh_ents.append({"entity": ent})
    if sh_ents:
        sensor_cards.append({"type": "entities", "title": "Список датчиков", "entities": sh_ents})

    # --- Цвет ---
    color_cards = [{"type": "entities", "title": "Температура света", "entities": [
        {"entity": "input_number.ct_day_kelvin", "name": "Дневная, K"},
        {"entity": "input_number.ct_night_kelvin", "name": "Ночная, K"},
        {"entity": "input_datetime.ct_warm_from", "name": "Смягчать с"},
        {"entity": "input_datetime.ct_night_from", "name": "Ночная с"},
        {"entity": "input_boolean.feature_rgb", "name": "RGB-сцены"},
        {"entity": "input_select.light_rgb_scene", "name": "Сцена"},
    ]}]

    views = [
        {"title": "💡 Свет", "path": "light", "icon": "mdi:lightbulb", "cards": light_cards},
        {"title": "🌡️ Климат", "path": "climate", "icon": "mdi:thermometer", "cards": climate_cards},
        {"title": "💨 Вентиляция", "path": "vent", "icon": "mdi:fan", "cards": vent_cards},
        {"title": "📡 Датчики", "path": "sensors", "icon": "mdi:access-point", "cards": sensor_cards},
        {"title": "🎨 Цвет", "path": "color", "icon": "mdi:palette", "cards": color_cards},
    ]
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w") as fh:
        yaml.safe_dump({"title": "Настройки", "views": views}, fh,
                       allow_unicode=True, sort_keys=False, default_flow_style=False)
    print("Settings dashboard: %s (%d views)" % (args.out, len(views)))

if __name__ == "__main__":
    main()