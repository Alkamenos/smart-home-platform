#!/usr/bin/env python3
"""Загрузка манифеста инстанса: instances/<id>/manifest.yaml -> fallback manifests/<id>.yaml."""
import os
import yaml

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def manifest_path(instance):
    candidates = [
        os.path.join(REPO_ROOT, "instances", instance, "manifest.yaml"),
        os.path.join(REPO_ROOT, "manifests", instance + ".yaml"),
    ]
    for c in candidates:
        if os.path.exists(c):
            return c
    raise SystemExit("Манифест не найден для инстанса: " + instance)

def load_manifest(instance="leonid_house", path=None):
    with open(path or manifest_path(instance), encoding="utf-8") as fh:
        return yaml.safe_load(fh)

def features_root(m):
    return m.get("features", m) or {}

def deploy_active_manifest(instance="leonid_house", path=None):
    import shutil
    src = path or manifest_path(instance)
    dst_dir = os.path.join(os.environ.get("HA_CONFIG", "/config"), "manifests")
    os.makedirs(dst_dir, exist_ok=True)
    dst = os.path.join(dst_dir, "active.yaml")
    shutil.copyfile(src, dst)
    return dst


def lighting_groups(m):
    f = features_root(m)
    return f.get("groups") or (f.get("lighting") or {}).get("groups") or []