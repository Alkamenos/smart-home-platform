import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from pyscript_mocks import build_ns, exec_files

ns = build_ns()
exec_files(ns, ["features/climate/fsm.py", "features/climate/runtime.py"])


def test_send_off_switch():
    ns["service"].calls.clear()
    ns["_clim_send_off"]("switch.heater")
    d, s, kw = ns["service"].calls[-1]
    assert (d, s) == ("switch", "turn_off") and kw["entity_id"] == "switch.heater"


def test_send_off_climate():
    ns["service"].calls.clear()
    ns["_clim_send_off"]("climate.ac")
    d, s, kw = ns["service"].calls[-1]
    assert (d, s) == ("climate", "set_hvac_mode") and kw["hvac_mode"] == "off"


def test_send_on_switch():
    ns["service"].calls.clear()
    ns["_clim_send_on"]("switch.heater", "heat", 22)
    d, s, kw = ns["service"].calls[-1]
    assert (d, s) == ("switch", "turn_on")


def test_send_on_climate():
    ns["service"].calls.clear()
    ns["_clim_send_on"]("climate.ac", "cool", 24)
    d, s, kw = ns["service"].calls[-1]
    assert (d, s) == ("climate", "set_temperature")
    assert kw["temperature"] == 24 and kw["hvac_mode"] == "cool"
