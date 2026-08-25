#!/usr/bin/env python3
"""Scaffold: new instance / feature / group (без правок руками)."""
import os

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

INSTANCE_TPL = '''instance:
  id: {id}
  name: "{name}"
  timezone: Europe/Moscow
  locale: ru-RU
  version: "0.1.0"

devices:
  sensors: []
  actuators: []

features:
  lighting:
    enabled: true
    mode: shadow
  groups: []
'''

def new_instance(id):
    d = os.path.join(REPO_ROOT, "instances", id)
    os.makedirs(d, exist_ok=True)
    p = os.path.join(d, "manifest.yaml")
    if os.path.exists(p):
        raise SystemExit("уже есть: " + p)
    open(p, "w", encoding="utf-8").write(INSTANCE_TPL.format(id=id, name=id.capitalize()))
    print("created:", p)
    print("далее: ./shp validate --instance %s && ./shp helpers --instance %s --apply" % (id, id))

def new_feature(id):
    d = os.path.join(REPO_ROOT, "features", id)
    os.makedirs(d, exist_ok=True)
    w = lambda n, s: open(os.path.join(d, n), "w", encoding="utf-8").write(s)
    w("schema.py", "def resolve_group(g):\n    return g\n")
    w("helpers.py", "def group_helpers(g, gid, i, ctx):\n    return [], i\n")
    w("ui.py", "def group_ui_blocks(g, gid):\n    return []\n")
    w("decide.py", "# voters фичи (pyscript runtime)\n")
    w("runtime.py", "# tick/triggers/@service (pyscript runtime)\n")
    w("README.md", "# feature %s\nКонтракт: schema+helpers+ui+decide в __init__.FEATURE\n" % id)
    w("__init__.py",
      'from features.%s import schema, helpers, ui  # noqa: F401\n'
      'FEATURE = {"id": "%s", "resolve": schema.resolve_group,\n'
      '           "helpers": helpers.group_helpers, "ui": ui.group_ui_blocks}\n' % (id, id))
    print("created feature:", d)
    print("добавь features/%s/runtime.py в ORDER build/build_pyscript.py (если есть runtime)" % id)

GROUP_TPL = '''  - id: {gid}
    name: "{name}"
    lights: []
    flag: input_boolean.feature_{gid}
    features:
      schedule: {{ on: sunset, off: "23:00" }}
      # motion: {{ sensor: binary_sensor..., mode: trigger }}
      # party: {{ role: keep_on }}
'''

def new_group(gid):
    print("Вставь в features.groups манифеста:")
    print(GROUP_TPL.format(gid=gid, name=gid.replace("_", " ").capitalize()))
    print("затем: ./shp helpers --apply && ./shp dashboards")