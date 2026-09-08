import types
from pathlib import Path
import yaml

ROOT = Path(__file__).parent.parent


class FakeState:
    def __init__(self):
        self.data = {}
        self.attrs = {}

    def get(self, e, *a):
        return self.data.get(e)

    def set(self, e, v, **attrs):
        self.data[e] = v
        self.attrs[e] = attrs

    def __call__(self, e):
        return self.data.get(e)


class FakeService:
    def __init__(self):
        self.calls = []

    def call(self, domain, svc=None, **kw):
        self.calls.append((domain, svc, kw))

    def __call__(self, fn=None, **kw):
        if callable(fn):
            return fn
        def wrap(f):
            return f
        return wrap


class FakeHass:
    class _States:
        def __init__(self, st):
            self._st = st

        def get(self, e):
            v = self._st.data.get(e)
            if v is None:
                return None
            return types.SimpleNamespace(state=v, attributes=self._st.attrs.get(e, {}))

    def __init__(self, st):
        self.states = self._States(st)


import sys as _sys
if str(ROOT) not in _sys.path:
    _sys.path.insert(0, str(ROOT))
from shplatform.loader.registry import RuntimeRegistry


class FakeRegistry(RuntimeRegistry):
    def __init__(self):
        p = ROOT / "instances" / "leonid_house" / "manifest.yaml"
        with open(p, encoding="utf-8") as f:
            super().__init__(yaml.safe_load(f) or {})

    def features(self):
        return getattr(self, "_features", {}) or {}


def _noop_dec(*a, **kw):
    if len(a) == 1 and callable(a[0]) and not kw:
        return a[0]
    def wrap(f):
        return f
    return wrap


def build_ns():
    import time as _t
    import json as _j
    from datetime import datetime as _dt, timedelta as _td
    st = FakeState()
    return {
        "time": _t,
        "json": _j,
        "datetime": _dt,
        "timedelta": _td,
        "state": st,
        "service": FakeService(),
        "hass": FakeHass(st),
        "task": types.SimpleNamespace(sleep=lambda s: None),
        "log": types.SimpleNamespace(info=lambda *a, **k: None, error=lambda *a, **k: None,
                                     warning=lambda *a, **k: None, debug=lambda *a, **k: None),
        "log_event": lambda *a, **k: None,
        "time_trigger": _noop_dec,
        "state_trigger": _noop_dec,
        "event_trigger": _noop_dec,
        "_REGISTRY": FakeRegistry(),
    }


def exec_files(ns, paths):
    paths = ["ha/pyscript/fsm_engine.py"] + [x for x in paths if "fsm_engine" not in x]
    for rel in paths:
        src = (ROOT / rel).read_text(encoding="utf-8")
        ns["__file__"] = str(ROOT / rel)
        exec(compile(src, rel, "exec"), ns)
    return ns
