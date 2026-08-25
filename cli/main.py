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
    rc = cmd_build(args)
    if rc == 0:
        print("Готово. Нужен полный рестарт HA (не pyscript.reload).")
    return rc

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
    sp = sub.add_parser("deploy", help="build + подсказка"); sp.set_defaults(fn=cmd_deploy)
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

    args = p.parse_args()
    sys.exit(args.fn(args))

if __name__ == "__main__":
    main()


cli = main
