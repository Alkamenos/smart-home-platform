#!/usr/bin/env python3
"""Манифест -> дашборд "Настройки" (свет по зонам, климат, вентиляция, датчики, цвет)."""
import argparse, os, yaml
import feature_ui as FU
import group_card as GC

ZONE_TITLES = {"street": "Улица", "garden": "Сад", "house": "Дом"}

def default_zone(gid):
    if any([k in gid for k in ("yard", "street", "flood", "container", "xmas")]):
        return "street"
    if any([k in gid for k in ("terrace", "garden", "path")]):
        return "garden"
    return "house"

def nice(gid):
    return gid.replace("_", " ").capitalize()

# ---- карточки-кирпичики ----
def title(t):
    return {"type": "custom:mushroom-title-card", "title": t}

def grid(cards, cols):
    return {"type": "grid", "columns": cols, "square": False, "cards": cards}

def sel_card(entity, name):
    return {"type": "custom:mushroom-select-card", "entity": entity, "name": name}

def num_card(entity, name):
    return {"type": "custom:mushroom-number-card", "entity": entity, "name": name}

def bool_card(entity, name):
    return {"type": "custom:mushroom-entity-card", "entity": entity, "name": name}

# ============================================================
# КАРТОЧКА ГРУППЫ СВЕТА
# ============================================================
def group_settings_card(g):
    return GC.group_card(g)



# ============================================================
# ВКЛАДКИ СВЕТА: Общее + зоны
# ============================================================
def light_views(lighting):
    groups = lighting.get("groups", []) or []
    import resolve_features as RF
    groups = [RF.resolve_group(g) for g in groups]
    zones = {}
    for g in groups:
        z = g.get("zone") or default_zone(str(g.get("id")))
        zones.setdefault(z, []).append(g)
    views = [{
        "title": "💡 Общее", "path": "light_general", "icon": "mdi:lightbulb-group",
        "cards": [{"type": "entities", "title": "Глобально", "entities": [
            {"entity": "input_number.motion_day_min", "name": "Таймаут движения днём"},
            {"entity": "input_number.motion_night_min", "name": "Таймаут движения ночью"},
            {"entity": "input_boolean.feature_color_temp", "name": "Авто color temp"},
            {"entity": "input_boolean.feature_backlight", "name": "Подсветка выключателей"},
            {"entity": "input_boolean.feature_imitation", "name": "Имитация присутствия"},
            {"entity": "input_datetime.imitation_start", "name": "Имитация: начало"},
            {"entity": "input_datetime.imitation_end", "name": "Имитация: конец"},
        ]}],
    }]
    for z in ("street", "garden", "house"):
        gs = zones.get(z, [])
        if not gs:
            continue
        views.append({
            "title": "💡 " + ZONE_TITLES.get(z, z),
            "path": "light_" + z,
            "icon": "mdi:lightbulb",
            "cards": [group_settings_card(g) for g in gs],
        })
    return views

# ============================================================
# MAIN
# ============================================================
def main():
    p = argparse.ArgumentParser()
    p.add_argument("--manifest", default="instances/leonid_house/manifest.yaml")
    p.add_argument("--out", default="/config/dashboards/settings-dashboard.yaml")
    args = p.parse_args()
    m = yaml.safe_load(open(args.manifest))
    features = m.get("features", m)
    lighting = features.get("lighting", {}) or {}
    climate = features.get("climate", {}) or {}
    ventilation = features.get("ventilation", {}) or {}
    sensor_health = features.get("sensor_health", {}) or {}

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
    if climate.get("safety"):
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

    views = light_views({"groups": features.get("groups") or lighting.get("groups") or []}) + [
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