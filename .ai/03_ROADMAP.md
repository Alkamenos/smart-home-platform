# Roadmap (Machine-Readable)

## Status Legend
- [x] Completed
- [ ] In Progress
- [ ] Planned
- [x] Cancelled

## Phase 1: Foundation [COMPLETED: 2026-09-05]
- [x] Basic FSM engine with states and transitions
- [x] EventBus for async event distribution
- [x] Scheduler for timeout management
- [x] Registry for guard/action functions
- [x] YAML loader for FSM definitions

## Phase 2: Reliability [COMPLETED: 2026-09-08]
- [x] State persistence (JSON storage)
- [x] Control tracker for manual/automated sources
- [x] Debounce protection
- [x] Cooldown and manual lockout in transitions
- [x] Watchdog service for health monitoring

## Phase 3: Core Platform [COMPLETED: 2026-09-13]
- [x] Pydantic v2 manifest validation (commit: 701c7ab)
- [x] CommandDispatcher with priority resolution (commit: 8cee5aa)
- [x] EventRouter for sensor-to-FSM mapping (commit: a3126c4)
- [x] Middleware system (ManualLockoutMiddleware) (commit: edccfd3)
- [x] Composition pattern with behaviors (commit: 869ac4d)
- [x] E2E composition tests (commit: c3007a6)
- [x] CLI with validate/doctor/health commands (commit: 955f2f0)
- [x] State persistence with graceful shutdown
- [x] Docker integration tests

## Phase 4: Production Readiness [IN PROGRESS]
- [ ] **CRITICAL** Consolidate project structure (remove code duplication)
  - Issue: Code exists in both `core/` and `src/smart_home/core/`
  - Action: Migrate fully to `src` layout, remove flat structure
  - Impact: All imports, pyproject.toml, cli.py
- [ ] **CRITICAL** Fix manifest bug: add `motion_sensor` to night_light params
  - File: `instances/leonids_house/manifest.yaml`
  - Issue: `01_PROJECT_STATE.md` → Known Issues #1
- [ ] Clean up legacy tests
  - Remove: `tests/test_legacy_*.py`
  - Add: middleware tests, CLI tests, WebSocket reconnect tests
- [ ] Add pre-commit hooks
  - pytest, mypy, ruff, black
- [ ] Write MIGRATION_V2_TO_V3.md
- [ ] Update README.md with new architecture diagrams
- [ ] Add code coverage badge

## Phase 5: Advanced Features [PLANNED]
- [ ] Device-level sensors (avoid duplication in behavior params)
  - Add `sensors:` field to device in manifest
  - EventRouter reads from device level first, then behavior level
- [ ] Web UI for manifest editing
  - FastAPI + HTMX
  - Form validation using Pydantic models
- [ ] Prometheus metrics export
  - `/metrics` endpoint
  - FSM state changes, command latency, error rates
- [ ] Hot-reload without restart
  - File watcher for manifest changes
  - Graceful FSM migration (unregister old, register new)

## Phase 6: Platform Maturity [FUTURE]
- [ ] Plugin system for custom behaviors
- [ ] Multi-instance support (multiple houses)
- [ ] Voice assistant integration (Alexa, Google)
- [ ] Machine learning for behavior optimization

## Technical Debt

### High Priority
1. EventRouter tight coupling with `engine._definitions`
   - File: `core/event_router.py:67`
   - Fix: Add public method `engine.get_entities_by_device()`
2. Duplicated entity_id extraction in action handlers
   - File: `core/action_handlers.py`
   - Fix: Extract to helper function `extract_device_id(context)`

### Medium Priority
3. No WebSocket reconnect tests
   - File: `adapters/ha_adapter.py`
   - Fix: Add tests with mocked connection failures
4. CLI commands lack integration tests
   - File: `cli.py`
   - Fix: Add end-to-end CLI tests

### Low Priority
5. Dashboard generator could use templates
   - File: `tools/dashboard_generator.py`
   - Fix: Refactor to Jinja2 templates

## Cancelled Ideas

### GraphQL API
- **Reason:** Too complex for current scale. REST/WebSocket is sufficient.
- **Date cancelled:** 2026-09-10

### Multi-tenant support
- **Reason:** Premature optimization. Focus on single-house reliability first.
- **Date cancelled:** 2026-09-12

### Visual FSM editor
- **Reason:** YAML with composition pattern is more maintainable than visual editing.
- **Date cancelled:** 2026-09-13
