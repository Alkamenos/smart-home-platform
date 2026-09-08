import sys
import tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from pyscript_mocks import build_ns, exec_files

ns = build_ns()
exec_files(ns, ["ha/pyscript/fsm_engine.py"])
ns["_FSM_PERSIST_PATH"] = tempfile.mktemp(suffix=".json")

DEF = {"states": ["A", "B"], "initial": "A",
       "transitions": [{"from": "A", "to": "B", "trigger": "go"}]}


def test_persist_roundtrip():
    ns["fsm_register"]("p1", DEF)
    ns["fsm_trigger"]("p1", "go")
    assert ns["fsm_get_state"]("p1") == "B"
    ns["fsm_save_states"]()

    # симуляция рестарта: авто-восстановление при первом обращении
    ns["_FSM_STATES"].clear()
    ns["_FSM_RESTORED"].clear()
    assert ns["fsm_get_state"]("p1") == "B"
    assert ns["_FSM_STATES"]["p1"]["entered_by"] == "persist"
