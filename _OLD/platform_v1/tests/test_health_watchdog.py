import sys
import time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from pyscript_mocks import build_ns, exec_files

FILES = ["features/lighting/state.py", "features/lighting/control.py",
         "features/lighting/decide.py", "features/lighting/schema.py",
         "features/lighting/fsm.py", "features/lighting/runtime.py",
         "features/health/runtime.py"]
ns = build_ns()
exec_files(ns, FILES)


def groups():
    return (ns["_lg_cfg"]() or {}).get("groups", []) or []


def test_divergence_detected():
    g = [x for x in groups() if x.get("lights")][0]
    gid = str(g.get("id"))
    for e in g["lights"]:
        ns["state"].data[e] = "off"
    ns["light_fsm_run"](g, ns["_lg_build_fsm_ctx"](g, ns["_lg_decide_ctx"](g, ns["_lg_cfg"]())))
    assert ns["fsm_get_state"]("light." + gid) == "OFF"
    ns["state"].data[g["lights"][0]] = "on"  # устройство включено вопреки FSM
    ns["_SH_DIVERGE_SINCE"][gid] = time.monotonic() - 600
    probs = ns["_sh_fsm_divergence"]({})
    assert any(p["entity"] == "light." + gid for p in probs)


def test_divergence_cleared():
    g = [x for x in groups() if x.get("lights")][0]
    gid = str(g.get("id"))
    for e in g["lights"]:
        ns["state"].data[e] = "off"
    probs = ns["_sh_fsm_divergence"]({})
    assert not any(p["entity"] == "light." + gid for p in probs)


def test_stuck_detected():
    g = [x for x in groups() if x.get("motion_sensor") and x.get("lights")][0]
    gid = str(g.get("id")); ms = g["motion_sensor"]
    for e in g["lights"]:
        ns["state"].data[e] = "off"
    ns["light_fsm_run"](g, ns["_lg_build_fsm_ctx"](g, ns["_lg_decide_ctx"](g, ns["_lg_cfg"]())))
    ns["state"].data[ms] = "on"
    ns["_SH_STUCK_SINCE"][gid] = time.monotonic() - 700
    probs = ns["_sh_fsm_stuck"]({})
    assert any(p["entity"] == ms for p in probs)
