#!/usr/bin/env python3
"""Манифест -> provisioning JSON троек helpers освещения (формат docs/ENTITY_PROVISIONING.md)."""
import argparse, json
import yaml

parser = argparse.ArgumentParser()
parser.add_argument("--start-id", type=int, default=1)
parser.add_argument("--groups", type=str, default=None, help="список id через запятую (иначе все)")
parser.add_argument("--manifest", default="manifests/leonid_house.yaml")
args = parser.parse_args()

m = yaml.safe_load(open(args.manifest))
f = m.get("features", m)
groups = (f.get("lighting", {}) or {}).get("groups", [])
want = [s.strip() for s in args.groups.split(",")] if args.groups else None

def icon(gid):
    if "garland" in gid or "xmas" in gid:
        return "mdi:string-lights"
    if "flood" in gid:
        return "mdi:lightbulb-spot"
    return "mdi:lightbulb"

out, i = [], args.start_id
for g in groups:
    gid = str(g.get("id"))
    if want and gid not in want:
        continue
    out.append({"id": i, "type": "input_boolean/create", "name": "vlight_%s" % gid, "icon": icon(gid)}); i += 1
    out.append({"id": i, "type": "input_select/create", "name": "light_%s_on" % gid,
                "options": ["Не включать", "Закат", "Время"], "initial": "Закат", "icon": "mdi:form-select"}); i += 1
    out.append({"id": i, "type": "input_datetime/create", "name": "light_%s_on_time" % gid,
                "has_date": False, "has_time": True, "icon": "mdi:clock-outline"}); i += 1

print(json.dumps(out, ensure_ascii=False, indent=2))
