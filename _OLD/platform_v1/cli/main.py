#!/usr/bin/env python3
"""shp — CLI платформы. Слайс 1: делегирование существующим tools (поведение не меняется)."""
import argparse
import os
import subprocess
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

from core import manifest as CM

PY = sys.executable or "python3"

def run(cmd):
    print(">", " ".join(cmd))
    return subprocess.call(cmd, cwd=REPO_ROOT)

def mpath(args):
    return (args.manifest or getattr(args, "manifest_pos", None)
            or CM.manifest_path(args.instance))

def cmd_validate(args):
    # 1. Валидация FSM графов (если есть определения)
    try:
        from cli import fsm_validate
        import yaml
        import glob
        
        # Собираем все FSM определения из фич
        fsm_defs = {}
        features_dir = os.path.join(REPO_ROOT, "features")
        for feature in os.listdir(features_dir):
            fsm_path = os.path.join(features_dir, feature, "fsm.py")
            if os.path.exists(fsm_path):
                # Пытаемся импортировать и получить определения
                try:
                    import importlib.util
                    spec = importlib.util.spec_from_file_location("%s_fsm" % feature, fsm_path)
                    mod = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(mod)
                    
                    # Ищем определения автоматов в модуле
                    for name in dir(mod):
                        if name.endswith("_FSM_DEFAULT") or name.endswith("_FSM_NIGHTLIGHT") or \
                           name.endswith("_FSM_MOTION") or name.endswith("_FSM_IMITATION"):
                            fsm_defs["%s.%s" % (feature, name)] = getattr(mod, name)
                except Exception as e:
                    print("  WARN: не удалось загрузить FSM для %s: %s" % (feature, e))
        
        if fsm_defs:
            results = fsm_validate.validate_multiple_fsm(fsm_defs)
            all_valid = True
            for name, result in results.items():
                if not result.is_valid():
                    all_valid = False
                    print("  ERROR: FSM %s: %d ошибок" % (name, len(result.errors)))
                    for err in result.errors:
                        print("    - %s" % err)
            
            if not all_valid:
                print("❌ Валидация FSM не пройдена!")
                return 1
            else:
                print("✅ Валидация FSM пройдена (%d автоматов)" % len(fsm_defs))
    except ImportError:
        print("  INFO: fsm_validate не найден, пропускаем валидацию FSM")
    except Exception as e:
        print("  WARN: ошибка при валидации FSM: %s" % e)
    
    # 2. Стандартная валидация манифеста
    m = CM.load_manifest(args.instance, mpath(args))
    f = CM.features_root(m)
    groups = CM.lighting_groups(m)
    print("instance: %s" % args.instance)
    print("features: %s" % ", ".join(sorted(f.keys())))
    print("light groups: %d" % len(groups))
    for g in groups:
        gid = str(g.get("id"))
        if not g.get("lights"):
            print("  WARN: группа %s без lights" % gid)
        feats = g.get("features") or {}
        print("  - %s: %s" % (gid, ", ".join(sorted(feats.keys())) or "legacy"))
    return 0

def cmd_build(args):
    rc = run([PY, "build/build_pyscript.py"])
    if rc != 0:
        return rc
    return run([PY, "-m", "py_compile", "/config/pyscript/manifest_loader.py"])

def cmd_deploy(args):
    rc = cmd_validate(args)
    if rc != 0:
        return rc
    rc = cmd_build(args)
    if rc != 0:
        return rc
    dst = CM.deploy_active_manifest(args.instance, args.manifest)
    print("manifest ->", dst)
    print("Готово. Нужен полный рестарт HA (не pyscript.reload).")
    return 0

def cmd_helpers(args):
    cmd = [PY, "tools/gen_helpers.py", "--manifest", mpath(args)]
    if args.apply:
        cmd.append("--apply")
    if args.confirm:
        cmd.append("--confirm")
    return run(cmd)

def cmd_dashboards(args):
    targets = ["home", "settings", "admin"] if args.target == "all" else [args.target]
    for t in targets:
        rc = run([PY, "tools/gen_dashboard_%s.py" % t, "--manifest", mpath(args)])
        if rc != 0:
            return rc
    return 0

def cmd_cleanup(args):
    cmd = [PY, "tools/cleanup_helpers.py", "--manifest", mpath(args)]
    if args.confirm:
        cmd.append("--confirm")
    return run(cmd)

def cmd_explain(args):
    """Разбор группы/устройства: манифест + хелперы + live FSM-статус."""
    import yaml as _y
    with open(mpath(args), encoding="utf-8") as f:
        m = _y.safe_load(f) or {}
    from shplatform.loader.registry import RuntimeRegistry
    reg = RuntimeRegistry(m)
    gid = args.id

    raw = None
    for g in reg.feature("groups") or []:
        if str(g.get("id")) == gid:
            raw = g
    if raw is None:
        print("Группа '%s' не найдена в features.groups" % gid)
        dev = reg.device(gid)
        if dev:
            print("Но есть устройство:")
            print(_y.safe_dump(dev, allow_unicode=True, default_flow_style=False))
        return 1

    print("# === Группа %s (raw из манифеста) ===" % gid)
    print(_y.safe_dump(raw, allow_unicode=True, default_flow_style=False))

    lcfg = reg.feature("lighting") or {}
    defaults = {k: v for k, v in lcfg.items() if k not in ("groups",)}
    if defaults:
        print("# === Defaults lighting-фичи ===")
        print(_y.safe_dump(defaults, allow_unicode=True, default_flow_style=False))

    helpers = ["input_select.light_%s_on" % gid, "input_select.light_%s_off" % gid,
               "input_boolean.feature_%s" % gid]
    print("# === Live-статус (HA) ===")
    try:
        from core import ha
        for h in helpers:
            st = ha.state(h)
            print("  %s = %s" % (h, (st or {}).get("state", "нет в HA")))
        st = ha.state("sensor.light_%s_fsm_state" % gid)
        if st:
            print("  FSM: %s" % st.get("state"))
            for k in ("entered_by", "why"):
                v = (st.get("attributes") or {}).get(k)
                if v:
                    print("    %s: %s" % (k, v))
        else:
            print("  FSM-сенсор отсутствует")
    except Exception as exc:
        print("  (live-часть недоступна: %s)" % exc)
    return 0


def cmd_check(args):
    rc = cmd_validate(args)
    if rc != 0:
        return rc
    from core import ha
    ids = ha.all_entity_ids()
    m = CM.load_manifest(args.instance, args.manifest)
    missing = ["vlight_" + str(g.get("id")) for g in CM.lighting_groups(m)
               if ("input_boolean.vlight_" + str(g.get("id"))) not in ids]
    if missing:
        print("Missing helpers: %s" % ", ".join(missing))
        print("Запусти: ./shp helpers --apply")
        return 1
    print("check OK: helpers на месте")
    return 0

def cmd_add(args):
    from cli import scaffold
    scaffold.add_light(args.instance)
    return 0


def cmd_new(args):
    from cli import scaffold
    {"instance": scaffold.new_instance, "feature": scaffold.new_feature,
     "group": scaffold.new_group}[args.kind](args.id)
    return 0


def main():
    p = argparse.ArgumentParser(prog="shp")
    sub = p.add_subparsers(dest="cmd", required=True)

    def common(sp):
        sp.add_argument("--instance", default="leonid_house")
        sp.add_argument("--manifest", default=None)

    sp = sub.add_parser("validate", help="проверка манифеста"); common(sp)
    sp.add_argument("manifest_pos", nargs="?", default=None)
    sp.set_defaults(fn=cmd_validate)
    sp = sub.add_parser("build", help="склейка + py_compile"); sp.set_defaults(fn=cmd_build)
    sp = sub.add_parser("deploy", help="build + подсказка"); common(sp); sp.set_defaults(fn=cmd_deploy)
    sp = sub.add_parser("helpers", help="gen_helpers"); common(sp)
    sp.add_argument("--apply", action="store_true"); sp.add_argument("--confirm", action="store_true")
    sp.set_defaults(fn=cmd_helpers)
    sp = sub.add_parser("dashboards", help="генераторы дашбордов"); common(sp)
    sp.add_argument("--target", default="all", choices=["home", "settings", "admin", "all"])
    sp.set_defaults(fn=cmd_dashboards)
    sp = sub.add_parser("cleanup", help="чистка дублей helpers"); common(sp)
    sp.add_argument("--confirm", action="store_true"); sp.set_defaults(fn=cmd_cleanup)
    sp = sub.add_parser("check", help="validate + helpers на месте"); common(sp)
    sp.set_defaults(fn=cmd_check)

    sp = sub.add_parser("new", help="scaffold feature/instance/group")
    sp.add_argument("kind", choices=["feature", "instance", "group"])
    sp.add_argument("id")
    sp.set_defaults(fn=cmd_new)

    sp = sub.add_parser("add", help="интерактивное добавление устройств")
    common(sp)
    sp.add_argument("kind", choices=["light"])
    sp.set_defaults(fn=cmd_add)

    sp = sub.add_parser("explain", help="разбор группы по манифесту + live-статус"); common(sp)
    sp.add_argument("id", help="id группы или устройства")
    sp.set_defaults(fn=cmd_explain)
    args = p.parse_args()
    sys.exit(args.fn(args))

if __name__ == "__main__":
    main()


cli = main
