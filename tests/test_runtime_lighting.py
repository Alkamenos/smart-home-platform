import sys
import time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from pyscript_mocks import build_ns, exec_files

LIGHTING = ["features/lighting/state.py", "features/lighting/schema.py", "features/lighting/control.py",
            "features/lighting/decide.py", "features/lighting/fsm.py",
            "features/lighting/runtime.py"]
ns = build_ns()
exec_files(ns, LIGHTING)
cfg = ns["_lg_cfg"]() or {}
G = cfg.get("groups", []) or []


def g0():
    assert G
    return G[0]


def fctx(g):
    return ns["_lg_build_fsm_ctx"](g, ns["_lg_decide_ctx"](g, cfg))


def test_ne_vkl_gate():
    g = g0(); gid = str(g.get("id"))
    ns["state"].data["input_select.light_%s_on" % gid] = "Не включать"
    ns["_DARK"] = True
    assert fctx(g)["schedule_on"] is False


def test_sunset_elev_below_zero():
    g = g0(); gid = str(g.get("id"))
    ns["state"].data["input_select.light_%s_on" % gid] = "Закат"
    ns["state"].data.pop("input_boolean.light_%s_require_dark" % gid, None)
    ns["_DARK"] = False
    ns["state"].data["sun.sun"] = "above_horizon"
    ns["state"].attrs["sun.sun"] = {"elevation": -1.0}
    assert fctx(g)["schedule_on"] is True


def test_sunset_require_dark_blocks():
    g = g0(); gid = str(g.get("id"))
    ns["state"].data["input_select.light_%s_on" % gid] = "Закат"
    ns["state"].data["input_boolean.light_%s_require_dark" % gid] = "on"
    ns["_DARK"] = False
    ns["state"].attrs["sun.sun"] = {"elevation": -1.0}
    assert fctx(g)["schedule_on"] is False


def test_manual_override_ctx():
    g = g0(); gid = str(g.get("id"))
    lights = [e for e in (g.get("lights", []) or []) if e]
    assert lights
    e = lights[0]
    ns["_LG_OVERRIDE"][e] = time.monotonic() + 3600
    f = fctx(g)
    assert f["manual_change"] is True
    ns["_LG_OVERRIDE"][e] = time.monotonic() + 60
    assert fctx(g)["manual_change"] is False
    del ns["_LG_OVERRIDE"][e]
    assert fctx(g)["timeout_expired"] is True
