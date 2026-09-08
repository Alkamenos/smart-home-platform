import sys
from pathlib import Path
import pytest
import yaml

sys.path.insert(0, str(Path(__file__).parent))
from pyscript_mocks import build_ns, exec_files

ROOT = Path(__file__).parent.parent

LIGHT_FILES = ["features/lighting/state.py", "features/lighting/control.py",
               "features/lighting/decide.py", "features/lighting/schema.py",
               "features/lighting/fsm.py", "features/lighting/runtime.py"]

L_BASE = dict(motion=False, night=False, nightlight_enabled=False, schedule_on=False,
              schedule_off=False, no_motion_timeout=False, nightlight_timeout=False,
              party_mode=False, party_ended=False, imitation_on=False, imitation_off=False,
              manual_change=False, timeout_expired=False, override_cleared=False,
              device_available=True)
V_BASE = dict(co2_level=600, humidity=45, outdoor_temperature=20, indoor_temperature=22,
              manual_mode=False, override_remaining_min=0, heating_lockout=False,
              is_night=False, room_context="HOME_DAY", boost_remaining_min=0,
              manual_boost=False)

SCENARIOS = sorted(p for p in (ROOT / "features").glob("*/scenarios/*.yaml"))


@pytest.mark.parametrize("path", SCENARIOS, ids=lambda p: p.parent.parent.name + "/" + p.name)
def test_scenario(path):
    feature = path.parent.parent.name
    spec = yaml.safe_load(path.read_text(encoding="utf-8"))
    ns = build_ns()
    uid = path.stem + "_scen"
    if feature == "lighting":
        exec_files(ns, LIGHT_FILES)
    elif feature == "ventilation":
        exec_files(ns, ["features/ventilation/fsm.py"])
    else:
        pytest.skip("no runner for " + feature)
    base = L_BASE if feature == "lighting" else V_BASE
    for i, step in enumerate(spec.get("steps", [])):
        ctx = dict(base)
        ctx.update(step.get("ctx", {}))
        if feature == "lighting":
            ctx["gid"] = uid
            ns["light_fsm_run"]({"id": uid}, ctx)
            got = ns["fsm_get_state"]("light." + uid)
        else:
            ns["ventilation_fsm_run"](uid, ctx)
            got = ns["fsm_get_state"]("fan." + uid)
        assert got == step["expect"], "step %d (%s): got %s, want %s" % (
            i, spec.get("name", ""), got, step["expect"])
