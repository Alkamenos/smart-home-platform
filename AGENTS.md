# AGENTS.md – Smart Home FSM Platform

Quick reference for OpenCode agents working in this repository. Every line here answers: "Would an agent miss this without help?"

## Before Starting Any Task

Read these in order (15 minutes):
1. `.ai/00_START_HERE.md` – pipelined workflow with checklist
2. `.ai/04_RULES.md` – hard constraints and requirements
3. `.ai/01_PROJECT_STATE.md` – known issues and current state

## Critical Commands

**Always run before committing:**
```bash
.ai/scripts/run_checks.sh  # Tests, coverage, lint, type check, formatting
```

Exits with code 1 if anything fails. Do not commit until it passes.

**Run single test file:**
```bash
pytest tests/test_<filename>.py -v
```

**Format and fix lint:**
```bash
make format      # ruff format src/ tests/
make lint-fix    # ruff check --fix src/ tests/
```

## Project Structure

```
src/
├── bootstrap.py              # Platform initialization & hot-reload
├── core/
│   ├── fsm/                  # FSM engine (frozen, don't modify without discussion)
│   │   ├── engine.py         # FSMEngine – state machine logic
│   │   ├── factory.py        # FSM creation from manifest
│   │   └── persistence.py    # JSON state storage
│   ├── discovery/            # Device auto-classification from HA
│   ├── models/               # Pydantic schemas (manifest, device, room, etc)
│   ├── scheduling/scheduler.py    # Timer & timeout management
│   ├── registry.py           # Guard/action function registry
│   └── middleware/           # ManualLockoutMiddleware, etc
├── adapters/                 # Do NOT import core/
│   ├── ha_adapter.py         # Home Assistant integration (pyscript/websocket)
│   └── mock_adapter.py       # Testing mock
├── cli/                      # CLI entry point (can import everything)
└── services/                 # External integrations (watcher, metrics, etc)

tests/
├── conftest.py               # Shared fixtures, async setup
├── fixtures/                 # Test data (NEVER modify)
└── test_*.py                 # Unit & integration tests
```

## Architecture Layers (Strict Separation)

```
Core    → NO imports from adapters/services
Adapters → NO imports from services/ or implementation details
CLI     → Can import everything
```

Violation breaks testability and backward compatibility.

## Manifest & FSM Basics

**Manifest:** YAML file in `instances/*/manifest.yaml` – defines devices, behaviors, rooms
**FSM:** Finite state machine template (behavior) in `features/*.yaml`
**Device:** Entity controlled by platform (e.g., `light.kitchen`)
**Behavior:** FSM applied to a device (e.g., `lighting` with priority 10)

Key constraint: Each device + behavior + priority = unique FSM instance.

## Testing Requirements

**Minimum coverage:** 80% for new files, 95% for critical modules (dispatcher, router), 100% for action handlers.

**Test naming:** `test_<what>_should_<behavior>_when_<condition>`
```python
def test_dispatcher_should_reject_low_priority_when_high_priority_active(): ...
```

**Async tests:** Use `@pytest.mark.asyncio`; conftest handles setup/teardown.

**Time-based tests:** Use `freezegun` (imported in conftest):
```python
from freezegun import freeze_time


@freeze_time("2024-01-15 10:30:00")
async def test_timeout_transition(): ...
```

## Pydantic v2 Validation

Manifest uses strict Pydantic v2 schemas. All config changes require:
1. Update model in `src/core/models/manifest.py`
2. Write migration in `src/core/migrations/`
3. Test backward compatibility

## Pre-Commit Hooks

Git hooks run **automatically** on every commit:
- **ruff check** (lint)
- **ruff format** (code formatting)
- **mypy** (type checking on `src/` only)
- `.gitignore` validation

No flag needed—hooks always run. Commit fails if checks fail; fix and retry.

## Common Pitfalls

| Issue | Solution |
|-------|----------|
| Import from adapters in core | Restructure: move to adapter, use registry for injection |
| Missing type hints | Add `: Type` and `-> ReturnType` to all functions |
| Test hangs on async | Mark with `@pytest.mark.asyncio`; check conftest for fixture setup |
| Manifest schema errors | Check `src/core/models/manifest.py` version; write migration if needed |
| State not persisting | Add to `_persistence_required_fields` in FSM factory |
| Coverage < 80% | Add tests; check if code is actually reachable |

## Configuration Files

| File | Purpose | Modify? |
|------|---------|---------|
| `pyproject.toml` | Dependencies, tool config | ✓ Add deps only |
| `Makefile` | Build targets | ✓ Add targets only |
| `.pre-commit-config.yaml` | Git hooks | ✗ Fixed |
| `.ruff.toml` / `[tool.ruff]` | Lint rules | ✗ See rules in `.ai/04_RULES.md` |
| `.github/workflows/ci.yml` | CI/CD | ✗ Contact maintainer |

## Code Style Quick Rules

- **Imports:** `from __future__ import annotations` in every file
- **Constants:** Uppercase with underscores: `MANUAL_SOURCES = {"manual", "user"}`
- **Logging:** Use loguru: `logger.info("msg", extra=value)`; always include `trace_id`
- **Max function length:** 50 lines (excluding docstring)
- **Docstrings:** Google style, mandatory for all public functions
- **Exceptions:** Never bare `except:`; log via loguru

## How Device Hot-Reload Works

1. Manifest file saved → `config_watcher.py` detects change
2. `bootstrap.py` reloads manifest → validates with Pydantic
3. FSMs destroyed & recreated → persisted state preserved
4. Guards/actions re-registered → new functions picked up

No platform restart needed. Useful for rapid iteration.

## Debugging with Trace IDs

Every event has an 8-char `trace_id`:
```
[trace_id: a1b2c3d4] HAAdapter: state_change for binary_sensor.kitchen_motion: off -> on
[trace_id: a1b2c3d4] EventBus: Publishing event: state_change
[trace_id: a1b2c3d4] FSM: Transition idle -> active
[trace_id: a1b2c3d4] HAAdapter: calling service light.turn_on
```

Grep logs by trace_id to follow full event chain.

## Key Dependencies

| Package | Version | Purpose | Config |
|---------|---------|---------|--------|
| pydantic | ≥2.0 | Schema validation | `pyproject.toml` |
| loguru | ≥0.7 | Logging | See `src/core/logger.py` |
| pyyaml | ≥6.0 | Manifest parsing | — |
| pytest-asyncio | ≥0.23 | Async test runner | `pyproject.toml` |
| freezegun | ≥1.4 | Time mocking | — |

## Existing Instruction Files

These cover deeper guidance. Refer as needed:
- `.ai/01_PROJECT_STATE.md` – Known issues, last significant changes
- `.ai/02_ARCHITECTURE.md` – Design decisions, rationale
- `.ai/03_ROADMAP.md` – Task list, phases, technical debt
- `.ai/04_RULES.md` – Detailed rules, style, forbidden files

## Entry Points

| Type | Location | Purpose |
|------|----------|---------|
| CLI | `src/cli/main.py` | Command-line interface |
| Platform init | `src/bootstrap.py` | Startup, config watch, hot-reload |
| Test setup | `tests/conftest.py` | Fixtures, async loop config |
| HA Pyscript | Examples only | Not auto-discovered |

## Questions for New Contributors?

If something is not documented:
1. Check `.ai/` directory
2. Search `README.md` for architecture diagrams
3. Ask via issue tracker (don't guess)

After answer, update relevant `.ai/` file.
