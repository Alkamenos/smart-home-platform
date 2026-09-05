#!/usr/bin/env python3
"""Детерминированная склейка pyscript (вместо tools/deploy.sh)."""
import os
import subprocess
import sys
import yaml
import json
import glob

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

ORDER = [
    # === Ядро FSM ===
    "ha/pyscript/registry.py",
    "ha/pyscript/fsm_engine.py",
    "ha/pyscript/manifest_loader.py",
    # === Контекст: комната (уровень 1) ===
    "features/room/fsm.py",
    "features/room/runtime.py",
    # === Фичи (уровень 2): климат, вентиляция, шторы, освещение ===
    "features/climate/fsm.py",
    "features/climate/runtime.py",
    "features/ventilation/fsm.py",
    "features/ventilation/runtime.py",
    "features/covers/fsm.py",
    "features/covers/runtime.py",
    # Lighting: state -> caps -> schema -> fsm -> control -> ticks -> runtime -> services -> triggers
    "features/lighting/state.py",
    "features/lighting/caps.py",
    "features/lighting/schema.py",
    "features/lighting/fsm.py",
    "features/lighting/decide.py",
    "features/lighting/control.py",
    "features/lighting/ticks.py",
    "features/lighting/runtime.py",
    "features/lighting/services.py",
    "features/lighting/triggers.py",
    # === Системные фичи ===
    "features/health/runtime.py",
]

OUT = sys.argv[2] if len(sys.argv) > 2 else "/config/pyscript/manifest_loader.py"

def main():
    # 0. Копируем дашборды в /config/dashboards/
    dashboards_src = os.path.join(REPO_ROOT, "ha", "dashboards")
    dashboards_dst = "/config/dashboards"
    
    if os.path.exists(dashboards_src) and os.path.isdir("/config"):
        os.makedirs(dashboards_dst, exist_ok=True)
        
        # Список дашбордов для копирования
        dashboard_files = [
            "climate.yaml",
            "smart_home.yaml",
            "fsm_dashboard.yaml",
        ]
        
        for dashboard_file in dashboard_files:
            src = os.path.join(dashboards_src, dashboard_file)
            if os.path.exists(src):
                dst = os.path.join(dashboards_dst, dashboard_file.replace("_", "-"))
                import shutil
                shutil.copy2(src, dst)
                print("copied:", src, "->", dst)
    
    # 1. Читаем манифест на этапе сборки (здесь blocking I/O разрешен)
    MANIFEST_SRC = os.path.join(REPO_ROOT, "instances", "leonid_house", "manifest.yaml")
    if not os.path.exists(MANIFEST_SRC):
        matches = glob.glob(os.path.join(REPO_ROOT, "instances", "*", "manifest.yaml"))
        if matches:
            MANIFEST_SRC = matches[0]

    INJECTED_MANIFEST = "None"
    if os.path.exists(MANIFEST_SRC):
        try:
            with open(MANIFEST_SRC, "r", encoding="utf-8") as f:
                manifest_data = yaml.safe_load(f)
            INJECTED_MANIFEST = repr(manifest_data)
        except Exception as e:
            print("Warning: Could not read manifest for injection:", e)

    parts = []
    for rel in ORDER:
        p = os.path.join(REPO_ROOT, rel)
        assert os.path.exists(p), "нет исходника: " + rel

        file_content = open(p, encoding="utf-8").read()

        # 2. Вставляем данные ТОЛЬКО в начало manifest_loader.py
        # (registry.py идет первым и содержит __future__, его не трогаем)
        if rel == "ha/pyscript/manifest_loader.py":
            file_content = (
                "# ==== INJECTED MANIFEST DATA (0 blocking I/O in runtime) ====\n"
                "INJECTED_MANIFEST_DATA = " + INJECTED_MANIFEST + "\n"
                "# ============================================================\n\n"
            ) + file_content

        parts.append("# ==== %s ====\n" % rel + file_content)

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    open(OUT, "w", encoding="utf-8").write("\n\n".join(parts))
    print("built:", OUT, "(%d modules)" % len(ORDER))

    rc = subprocess.call([sys.executable or "python3", "-m", "py_compile", OUT])
    if rc != 0:
        raise SystemExit("py_compile FAILED")
    print("py_compile OK")

if __name__ == "__main__":
    main()
