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

# ============================================================
# Интерактивное добавление группы света
# ============================================================
TRANSLIT = {"а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e",
            "ж": "zh", "з": "z", "и": "i", "й": "i", "к": "k", "л": "l", "м": "m",
            "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u",
            "ф": "f", "х": "h", "ц": "ts", "ч": "ch", "ш": "sh", "щ": "sch",
            "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu", "я": "ya", " ": "_"}

def _slug(name):
    s = "".join([TRANSLIT.get(ch, ch if ch.isalnum() else "_") for ch in name.lower()])
    while "__" in s:
        s = s.replace("__", "_")
    return s.strip("_") or "group"

def _ask(prompt, default=None):
    suffix = " [%s]" % default if default else ""
    v = input(prompt + suffix + ": ").strip()
    return v or (default or "")

def _yn(prompt, default=False):
    d = "Y/n" if default else "y/N"
    v = input("%s (%s): " % (prompt, d)).strip().lower()
    if not v:
        return default
    return v in ("y", "yes", "д", "да", "1", "true", "+")

def _pick(prompt, options, multi=False, allow_custom=False):
    print(prompt + ":")
    for i, o in enumerate(options, 1):
        print("  %d. %s" % (i, o))
    if allow_custom:
        print("  0. другое (ввести)")
    while True:
        v = input("Выбор" + (" (через запятую)" if multi else "") + ": ").strip()
        if allow_custom and v == "0":
            return [input("Значение: ").strip()] if multi else input("Значение: ").strip()
        try:
            idxs = [int(x) for x in v.replace(" ", "").split(",") if x]
        except ValueError:
            continue
        if not idxs or any([i < 1 or i > len(options) for i in idxs]):
            continue
        sel = [options[i - 1] for i in idxs]
        return sel if multi else sel[0]

def _discover(prefixes, exclude, keywords=None):
    try:
        from core import ha
        states = ha.list_all_states()
    except Exception:
        print("⚠ HA недоступен — сущности введёте вручную")
        return []
    out = []
    for s in states:
        eid = s.get("entity_id", "")
        if not any([eid.startswith(p) for p in prefixes]):
            continue
        if eid in exclude or (keywords and not any([k in eid for k in keywords])):
            continue
        out.append(eid)
    return sorted(out)

def add_light(instance="leonid_house"):
    import io
    from core import manifest as CM
    try:
        from ruamel.yaml import YAML
    except ImportError:
        raise SystemExit("Нужен ruamel.yaml: pip install ruamel.yaml")
    path = CM.manifest_path(instance)
    yaml = YAML()
    yaml.preserve_quotes = True
    yaml.indent(mapping=2, sequence=4, offset=2)
    with open(path, encoding="utf-8") as fh:
        data = yaml.load(fh)
    feats_root = data.get("features", data)
    groups = feats_root.get("groups")
    if groups is None:
        groups = []
        feats_root["groups"] = groups
    used_ids = set([str(g.get("id")) for g in groups])
    used_lights = set()
    for g in groups:
        for e in (g.get("lights") or []):
            used_lights.add(e)

    print("=== Добавление группы света ===")
    rooms = ["gostinnaia", "spalnia", "kabinet", "sanuzel", "gostevaia_spalnia", "outdoor"]
    room = _pick("Комната", rooms, allow_custom=True)
    name = _ask("Название группы", "Новая лампа")
    gid = _ask("ID (латиница, snake_case)", _slug(name))
    while gid in used_ids:
        print("ID '%s' уже занят" % gid)
        gid = _ask("ID", gid + "_2")

    lights = _pick("Свободные устройства (свет/реле)",
                   _discover(("light.", "switch."), used_lights) or ["ввести вручную"],
                   multi=True, allow_custom=True)

    feats = {}
    if _yn("Расписание (вкл/выкл)?", True):
        on = _pick("Включение", ["sunset", "time", "нет"])
        off = _pick("Выключение", ["время", "sunrise", "нет"])
        sch = {}
        if on == "sunset":
            sch["on"] = "sunset"
        elif on == "time":
            sch["on"] = _ask("Время включения", "18:00")
        if off == "время":
            sch["off"] = _ask("Время выключения", "23:00")
        elif off == "sunrise":
            sch["off"] = "sunrise"
        if sch:
            feats["schedule"] = sch
    if _yn("Сумерки (включение по темноте)?", True):
        feats["dusk"] = {"require_dark": _yn("Ждать темноты (require_dark)?", True)}
    if _yn("Датчик движения?", False):
        sensors = _discover(("binary_sensor.",), set(), ("occupancy", "presence", "motion"))
        sensor = _pick("Датчик", sensors or ["ввести вручную"], allow_custom=True)
        feats["motion"] = {"sensor": sensor, "mode": _pick("Режим", ["trigger", "keepalive"])}
    if _yn("Ночник?", False):
        feats["nightlight"] = {"brightness": 40, "color": [255, 150, 60], "off_min": 3}
    if _yn("Роль в вечеринке?", False):
        feats["party"] = {"role": _pick("Роль", ["keep_on", "on", "off", "keep"])}
    if _yn("Следовать цветовой температуре (ct)?", True):
        feats["ct"] = {"follow": True}
    if _yn("Участие в имитации присутствия?", False):
        feats["imitation"] = {"participate": True}

    g = {"id": gid, "name": name, "room": room, "lights": lights,
         "flag": "input_boolean.feature_" + gid}
    if _yn("tolerate_unavailable (гирлянды/сезонное)?", False):
        g["tolerate_unavailable"] = True
    g["features"] = feats

    buf = io.StringIO()
    yaml.dump({gid: g}, buf)
    print("\nБудет добавлено:\n" + buf.getvalue())
    if not _yn("Записать в манифест?", True):
        raise SystemExit("Отменено")
    groups.append(g)
    with open(path, "w", encoding="utf-8") as fh:
        yaml.dump(data, fh)
    print("Записано: " + path)
    print("Дальше:\n  ./shp helpers --apply\n  ./shp deploy\n  ./shp dashboards\n  полный рестарт HA")
