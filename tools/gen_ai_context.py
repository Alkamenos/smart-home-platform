#!/usr/bin/env python3
"""Генератор docs/AI_CONTEXT.md — компактного контекста платформы для AI.

Читает манифест + структуру репо, пишет саммари: фичи, группы, инварианты,
CLI, тесты. Использовать первым файлом при входе в проект.
"""
import os
import sys
import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def main():
    mp = os.path.join(ROOT, "instances/leonid_house/manifest.yaml")
    m = yaml.safe_load(open(mp, encoding="utf-8")) or {}
    feats = m.get("features", {}) or {}
    out = []
    w = out.append

    w("# AI_CONTEXT — shplatform (leonid_house)")
    w("")
    w("Декларативная платформа умного дома: манифест -> генерация pyscript-бандла,")
    w("хелперов и дашбордов. Все FSM-фичи собираются в ОДИН бандл ha/pyscript.")
    w("")
    w("## Архитектура")
    w("- instances/leonid_house/manifest.yaml — единственный источник конфигурации")
    w("- features/<name>/{schema,state,decide,fsm,runtime}.py — модули фич (конкатенация)")
    w("- ha/pyscript/fsm_engine.py — универсальный FSM-движок (приоритеты, debounce, persist)")
    w("- build/build_pyscript.py — склейка бандла; tools/check_bundle_symbols.py — CI-чек")
    w("- shplatform/loader/registry.py — RuntimeRegistry: devices/features/groups")
    w("- cli/main.py (./shp) — validate/build/deploy/helpers/dashboards/explain/check")
    w("")
    w("## Инварианты (не нарушать!)")
    w("- Приоритеты триггеров: manual > device_unavailable > schedule/sensor")
    w("- FSM-состояния публикуются в sensor.<entity>_fsm_state с атрибутами entered_by/why")
    w("- Каждое решение логируется в ring-buffer sensor.platform_decisions")
    w("- Ручное управление ставит MANUAL_LOCK; выход — по timeout/override_cleared")
    w("- pyscript НЕ поддерживает: generator expressions, comprehensions, walrus")
    w("- input_text в HA ограничен 255 символами (персист FSM — в файле)")
    w("")
    w("## Фичи")
    for fname, fcfg in feats.items():
        if fname == "groups" or not isinstance(fcfg, dict):
            continue
        w("- %s: enabled=%s" % (fname, fcfg.get("enabled", True)))
    w("")
    w("## Группы света")
    from features.lighting.schema import resolve_group
    for g in feats.get("groups", []) or []:
        rg = resolve_group(dict(g))
        w("- %s (%s): lights=%d%s" % (
            rg.get("id"), rg.get("name", ""), len(rg.get("lights", []) or []),
            ", motion=" + rg["motion_sensor"] if rg.get("motion_sensor") else ""))
    w("")
    w("## CLI")
    w("- ./shp validate|build|deploy|helpers --apply|dashboards|check|explain <id>")
    w("- ./shp explain <group_id> — разбор группы + live-статус")
    w("")
    w("## Тесты")
    w("- python3 -m pytest tests/ -q (57 тестов: FSM-рег, сценарии, движок, персист)")
    w("- features/*/scenarios/*.yaml — YAML-регессии, generic-раннер tests/test_scenarios.py")
    w("")
    w("## Диагностика в HA")
    w("- сервис pyscript.platform_doctor -> sensor.platform_doctor (JSON)")
    w("- админ-дашборд /admin-dashboard: вкладки Фичи/Диагностика/Датчики/Логирование")
    w("")

    dst = os.path.join(ROOT, "docs/AI_CONTEXT.md")
    with open(dst, "w", encoding="utf-8") as f:
        f.write("\n".join(out))
    print("AI context: %s (%d lines)" % (dst, len(out)))


if __name__ == "__main__":
    main()
