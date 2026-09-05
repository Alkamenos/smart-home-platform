import sys
import time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from pyscript_mocks import build_ns, exec_files

ns = build_ns()
exec_files(ns, ["ha/pyscript/fsm_engine.py"])

DEF = {"states": ["A", "B", "C"], "initial": "A",
       "transitions": [
           {"from": "A", "to": "B", "trigger": "go"},
           {"from": "B", "to": "C", "trigger": "go"},
           {"from": "C", "to": "A", "trigger": "back"},
           {"from": "*", "to": "C", "trigger": "manual_change"},
       ],
       "debounce_sec": 0.2}


def test_debounce_blocks_rapid_transitions():
    ns["fsm_register"]("x1", DEF)
    assert ns["fsm_trigger"]("x1", "go") is True
    assert ns["fsm_get_state"]("x1") == "B"
    assert ns["fsm_trigger"]("x1", "go") is False  # кулдаун
    assert ns["fsm_get_state"]("x1") == "B"
    time.sleep(0.25)
    assert ns["fsm_trigger"]("x1", "go") is True
    assert ns["fsm_get_state"]("x1") == "C"


def test_debounce_exempt_manual():
    ns["fsm_register"]("x2", DEF)
    ns["fsm_trigger"]("x2", "go")          # A->B
    assert ns["fsm_trigger"]("x2", "manual_change") is True  # exempt
    assert ns["fsm_get_state"]("x2") == "C"


def test_no_debounce_by_default():
    d = dict(DEF); d.pop("debounce_sec")
    ns["fsm_register"]("x3", d)
    ns["fsm_trigger"]("x3", "go")
    assert ns["fsm_trigger"]("x3", "go") is True
    assert ns["fsm_get_state"]("x3") == "C"
