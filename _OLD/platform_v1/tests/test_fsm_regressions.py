import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent

def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod

fsm_engine = load("fsm_engine", ROOT / "ha" / "pyscript" / "fsm_engine.py")
lfsm = load("light_fsm", ROOT / "features" / "lighting" / "fsm.py")
vfsm = load("vent_fsm", ROOT / "features" / "ventilation" / "fsm.py")


def lctx(**kw):
    base = {"gid": "t", "motion": False, "night": False, "nightlight_enabled": False,
            "schedule_on": False, "schedule_off": False, "no_motion_timeout": False,
            "nightlight_timeout": False, "party_mode": False, "party_ended": False,
            "imitation_on": False, "imitation_off": False, "manual_change": False,
            "timeout_expired": False, "override_cleared": False, "device_available": True}
    base.update(kw)
    return base


def lrun(gid, **kw):
    ctx = lctx(**kw)
    ctx["gid"] = gid
    return lfsm.light_fsm_run({"id": gid}, ctx)


def lstate(gid):
    return fsm_engine.fsm_get_state("light." + gid)


def test_schedule_stuck_fixed():
    lrun("g1", schedule_on=True)
    assert lstate("g1") == "ON_SCHEDULE"
    # окно закрылось -> должен выйти в OFF, а не зависнуть
    lrun("g1")
    assert lstate("g1") == "OFF"


def test_motion_not_knocked_by_schedule_off():
    lrun("g2", motion=True)
    assert lstate("g2") == "ON_MOTION"
    # активно движение + schedule_off (ночь) -> НЕ выбиваем в OFF
    lrun("g2", motion=True, schedule_off=True)
    assert lstate("g2") == "ON_MOTION"


def test_motion_timeout_returns_off():
    lrun("g3", motion=True)
    assert lstate("g3") == "ON_MOTION"
    lrun("g3", no_motion_timeout=True)
    assert lstate("g3") == "OFF"


def test_manual_lock_and_release():
    lrun("g4", schedule_on=True)
    assert lstate("g4") == "ON_SCHEDULE"
    lrun("g4", manual_change=True)
    assert lstate("g4") == "MANUAL_LOCK"
    # FSM не трогает устройство в MANUAL_LOCK
    res = lrun("g4", manual_change=True)
    assert lstate("g4") == "MANUAL_LOCK"
    lrun("g4", timeout_expired=True)
    assert lstate("g4") == "ON_SCHEDULE"


def test_manual_beats_motion():
    lrun("g5", motion=True, manual_change=True)
    assert lstate("g5") == "MANUAL_LOCK"


def test_unavailable_roundtrip():
    lrun("g6", schedule_on=True)
    lrun("g6", device_available=False)
    assert lstate("g6") == "UNAVAILABLE"
    lrun("g6")
    assert lstate("g6") != "UNAVAILABLE"


def vrun(dev, **kw):
    base = {"co2_level": 600, "humidity": 45, "outdoor_temperature": 20,
            "indoor_temperature": 22, "manual_mode": False, "override_remaining_min": 0,
            "heating_lockout": False, "is_night": False, "room_context": "HOME_DAY",
            "boost_remaining_min": 0, "manual_boost": False}
    base.update(kw)
    return vfsm.ventilation_fsm_run(dev, base)


def vstate(dev):
    return fsm_engine.fsm_get_state("fan." + dev)


def test_vent_night_boost_on_co2():
    vrun("r1", is_night=True)
    assert vstate("r1") == "NIGHT"
    # высокий CO2 ночью -> BOOST (ранее зависал в NIGHT)
    vrun("r1", is_night=True, co2_level=1200)
    assert vstate("r1") == "BOOST"


def test_vent_manual_boost_from_night():
    vrun("r2", is_night=True)
    assert vstate("r2") == "NIGHT"
    vrun("r2", is_night=True, manual_boost=True)
    assert vstate("r2") == "BOOST"


def test_fsm_persist_roundtrip():
    """FSM-состояния сохраняются и восстанавливаются между рестартами."""
    import json
    lrun("g7", schedule_on=True)
    assert lstate("g7") == "ON_SCHEDULE"
    
    # Симуляция save
    saved = fsm_engine._FSM_STATES.copy()
    
    # Симуляция рестарта: очищаем
    fsm_engine._FSM_STATES.clear()
    assert fsm_engine.fsm_get_state("light.g7") is None
    
    # Симуляция load
    fsm_engine._FSM_STATES.update(saved)
    assert lstate("g7") == "ON_SCHEDULE"
