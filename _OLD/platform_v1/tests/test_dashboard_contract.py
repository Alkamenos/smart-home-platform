import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from pyscript_mocks import build_ns, exec_files


def sensor_for(entity):
    return "sensor." + entity.replace(".", "_") + "_fsm_state"


def test_lighting_sensors_published():
    ns = build_ns()
    exec_files(ns, ["features/lighting/state.py", "features/lighting/schema.py", "features/lighting/control.py",
                    "features/lighting/decide.py", "features/lighting/fsm.py",
                    "features/lighting/runtime.py"])
    cfg = ns["_lg_cfg"]() or {}
    groups = cfg.get("groups", []) or []
    assert groups
    for g in groups:
        ns["light_fsm_run"](g, ns["_lg_build_fsm_ctx"](g, ns["_lg_decide_ctx"](g, cfg)) or {})
        assert sensor_for("light." + str(g.get("id"))) in ns["state"].data


def test_climate_sensors_published():
    ns = build_ns()
    exec_files(ns, ["features/climate/fsm.py", "features/climate/runtime.py"])
    zones = (ns["_REGISTRY"].feature("climate") or {}).get("zones", []) or []
    assert zones
    ctx = {"current_temperature": 21.0, "target_temperature": 22.0, "manual_mode": False,
           "override_remaining_min": 0, "override_expired": False, "sensor_error": False,
           "heating_lockout": False, "room_context": "HOME_DAY", "temp_hysteresis": 0.5}
    for z in zones:
        ns["climate_fsm_run"](str(z.get("id")), dict(ctx))
        assert sensor_for("climate." + str(z.get("id"))) in ns["state"].data


def test_vent_sensors_published():
    ns = build_ns()
    exec_files(ns, ["features/ventilation/fsm.py"])
    devs = [d for d in ((ns["_REGISTRY"].feature("ventilation") or {}).get("devices", []) or []) if d.get("entity")]
    assert devs
    ctx = {"co2_level": 600, "humidity": 45, "outdoor_temperature": 20, "indoor_temperature": 22,
           "manual_mode": False, "override_remaining_min": 0, "heating_lockout": False,
           "is_night": False, "room_context": "HOME_DAY", "boost_remaining_min": 0, "manual_boost": False}
    for d in devs:
        ns["ventilation_fsm_run"](d["entity"].replace("fan.", ""), dict(ctx))
        assert sensor_for(d["entity"]) in ns["state"].data
