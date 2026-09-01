#!/usr/bin/env python3
"""Манифест -> дашборд "Платформа" (фичи, диагностика, здоровье)."""
import argparse, os, yaml

def nice(name):
    return name.replace("_", " ").capitalize()

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--manifest", default="instances/leonid_house/manifest.yaml")
    p.add_argument("--out", default="/config/dashboards/admin-dashboard.yaml")
    args = p.parse_args()
    m = yaml.safe_load(open(args.manifest))
    features = m.get("features", m)

    # --- Фичи ---
    feature_ents = []
    for fname in sorted(features.keys()):
        if fname == "groups":
            continue
        feature_ents.append({"entity": "input_boolean.feature_%s" % fname, "name": nice(fname)})
        shadow = "input_boolean.%s_shadow_mode" % fname
        feature_ents.append({"entity": shadow, "name": nice(fname) + " (shadow)"})

    # --- Глобальные режимы ---
    global_ents = [
        {"entity": "input_boolean.zima", "name": "Зима"},
        {"entity": "input_boolean.vecher", "name": "Вечер"},
        {"entity": "input_boolean.my_doma", "name": "Дома"},
        {"entity": "input_boolean.party_mode", "name": "Вечеринка"},
    ]

    # --- Диагностика ---
    diag_ents = [
        {"entity": "sensor.pyscript_manifest_status", "name": "Манифест"},
        {"entity": "sensor.pyscript_climate_debug", "name": "Климат"},
        {"entity": "sensor.pyscript_vent_debug", "name": "Вентиляция"},
        {"entity": "sensor.pyscript_light_debug", "name": "Свет"},
        {"entity": "sensor.pyscript_override_status", "name": "Override"},
    ]
    diag_buttons = {
        "type": "horizontal-stack", "cards": [
            {"type": "button", "name": "Reload", "icon": "mdi:reload",
             "tap_action": {"action": "call-service", "service": "pyscript.manifest_reload"}},
            {"type": "button", "name": "Light debug", "icon": "mdi:bug",
             "tap_action": {"action": "call-service", "service": "pyscript.light_debug"}},
            {"type": "button", "name": "Override clear", "icon": "mdi:lock-open",
             "tap_action": {"action": "call-service", "service": "pyscript.override_clear"}},
        ]}

    # --- Здоровье датчиков ---
    sh = features.get("sensor_health", {}) or {}
    health_ents = [{"entity": "sensor.sensor_health_status", "name": "Статус"}]
    for s in sh.get("sensors", []):
        ent = s.get("entity") if isinstance(s, dict) else s
        if ent:
            health_ents.append({"entity": ent})

    # --- Группы света (быстрый доступ) ---
    lighting = features.get("lighting", {}) or {}
    light_flags = []
    for g in (features.get("groups") or lighting.get("groups", []) or []):
        gid = str(g.get("id"))
        light_flags.append({"entity": "input_boolean.feature_%s" % gid,
                            "name": g.get("name", nice(gid))})

    # --- Логирование ---
    log_ents = []
    log_ents.append({"entity": "input_select.loglevel_platform", "name": "Платформа"})
    for fname in sorted(features.keys()):
        if fname == "groups":
            continue
        log_ents.append({"entity": "input_select.loglevel_" + fname, "name": nice(fname)})
    
    # --- Буфер решений ---
    decisions_card = {
        "type": "markdown",
        "title": "📋 Последние решения платформы",
        "content": """{% set decisions = state_attr('sensor.platform_decisions', 'decisions') or [] %}
{% if decisions | length == 0 %}
Пока нет записей в журнале решений.
{% else %}
| Время | Домен | Решение | Причина | Источник |
|-------|-------|---------|---------|----------|
{% for d in decisions | slice(20) %}
| {{ d.get('time', '')[:19] }} | {{ d.get('domain', '') }} | {{ d.get('decision', '') }} | {{ d.get('reason', '') }} | {{ d.get('source', '') }} |
{% endfor %}
{% if decisions | length > 20 %}

_... и ещё {{ decisions | length - 20 }} записей в полном списке_
{% endif %}
{% endif %}"""
    }

    views = [
        {"title": "⚙️ Фичи", "path": "features", "icon": "mdi:toggle-switch",
         "cards": [
             {"type": "entities", "title": "Платформенные", "entities": feature_ents},
             {"type": "entities", "title": "Глобальные режимы", "entities": global_ents},
             {"type": "entities", "title": "Группы света", "entities": light_flags},
         ]},
        {"title": "🔧 Диагностика", "path": "diag", "icon": "mdi:wrench",
         "cards": [
             {"type": "entities", "title": "Состояние", "entities": diag_ents},
             diag_buttons,
         ]},
        {"title": "🔋 Датчики", "path": "health", "icon": "mdi:heart-pulse",
         "cards": [{"type": "entities", "title": "Здоровье", "entities": health_ents}]},
        {"title": "📝 Логирование", "path": "logging", "icon": "mdi:file-document",
         "cards": [
             {"type": "entities", "title": "Уровни логирования", "entities": log_ents},
             decisions_card,
         ]},
    ]
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w") as fh:
        yaml.safe_dump({"title": "Платформа", "views": views}, fh,
                       allow_unicode=True, sort_keys=False, default_flow_style=False)
    print("Admin dashboard: %s (%d views)" % (args.out, len(views)))

if __name__ == "__main__":
    main()