#!/usr/bin/env python3
"""Детерминированная склейка pyscript (вместо tools/deploy.sh)."""
import os
import subprocess
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

ORDER = [
    "ha/pyscript/registry.py",
    "ha/pyscript/manifest_loader.py",
    "features/climate/runtime.py",
    "features/ventilation/runtime.py",
    "features/health/runtime.py",
    # Lighting: __init__ -> state -> caps -> schema -> helpers -> decide -> control -> ticks -> runtime -> services -> triggers -> ui -> card
    "features/lighting/__init__.py",
    "features/lighting/state.py",
    "features/lighting/caps.py",
    "features/lighting/schema.py",
    "features/lighting/helpers.py",
    "features/lighting/decide.py",
    "features/lighting/control.py",
    "features/lighting/ticks.py",
    "features/lighting/runtime.py",
    "features/lighting/services.py",
    "features/lighting/triggers.py",
    "features/lighting/ui.py",
    "features/lighting/card.py",
    "features/covers/runtime.py",
]

OUT = "/config/pyscript/manifest_loader.py"

def main():
    parts = []
    for rel in ORDER:
        p = os.path.join(REPO_ROOT, rel)
        assert os.path.exists(p), "нет исходника: " + rel
        parts.append("# ==== %s ====\n" % rel + open(p, encoding="utf-8").read())
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    open(OUT, "w", encoding="utf-8").write("\n\n".join(parts))
    print("built:", OUT, "(%d modules)" % len(ORDER))
    rc = subprocess.call([sys.executable or "python3", "-m", "py_compile", OUT])
    if rc != 0:
        raise SystemExit("py_compile FAILED")
    print("py_compile OK")

if __name__ == "__main__":
    main()