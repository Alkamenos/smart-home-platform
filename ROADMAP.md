# 🗺 Smart Home Platform Roadmap

*Автоматически сгенерировано из `.ai/03_ROADMAP.md`. Не редактировать вручную.*

## Release History

- **v3.0.0** (2024-09-14) - FSM Engine v3, EventRouter, Behavior Composition, Middleware System
- **v2.x** - Previous stable release

```mermaid
gantt
    title Development Timeline
    dateFormat YYYY-MM-DD

    section Phase 1- Foundation
    Phase 1- Foundation :done, p1, 2026-09-05, 2026-09-10

    section Phase 2- Reliability
    Phase 2- Reliability :done, p2, 2026-09-12, 2026-09-17

    section Phase 3- Core Platform
    Phase 3- Core Platform :done, p3, 2026-09-19, 2026-09-24

    section Phase 4- Production Readiness
    Phase 4- Production Readiness :active, p4, 2026-09-26, 2026-10-01

    section Phase 5- Advanced Features
    Phase 5- Advanced Features :p5, 2026-10-03, 2026-10-08

    section Phase 6- Platform Maturity
    Phase 6- Platform Maturity :p6, 2026-10-10, 2026-10-15

```

## 📌 Status Legend

- ✅ Completed
- [ ] In Progress
- [ ] Planned
- ~~Cancelled~~

## ✅ Phase 1: Foundation

**Status:** COMPLETED: 2026-09-05

- ✅ Basic FSM engine with states and transitions
- ✅ EventBus for async event distribution
- ✅ Scheduler for timeout management
- ✅ Registry for guard/action functions
- ✅ YAML loader for FSM definitions

## ✅ Phase 2: Reliability

**Status:** COMPLETED: 2026-09-08

- ✅ State persistence (JSON storage)
- ✅ Control tracker for manual/automated sources
- ✅ Debounce protection
- ✅ Cooldown and manual lockout in transitions
- ✅ Watchdog service for health monitoring

## ✅ Phase 3: Core Platform

**Status:** COMPLETED: 2026-09-13

- ✅ Pydantic v2 manifest validation (commit: 701c7ab)
- ✅ CommandDispatcher with priority resolution (commit: 8cee5aa)
- ✅ EventRouter for sensor-to-FSM mapping (commit: a3126c4)
- ✅ Middleware system (ManualLockoutMiddleware) (commit: edccfd3)
- ✅ Composition pattern with behaviors (commit: 869ac4d)
- ✅ E2E composition tests (commit: c3007a6)
- ✅ CLI with validate/doctor/health commands (commit: 955f2f0)
- ✅ State persistence with graceful shutdown
- ✅ Docker integration tests

## 🔄 Phase 4: Production Readiness

**Status:** IN PROGRESS

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

## 📋 Phase 5: Advanced Features

**Status:** PLANNED - Target: v3.1.0

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

## 🔮 Phase 6: Platform Maturity

**Status:** FUTURE - Target: v3.2.0+

- [ ] Plugin system for custom behaviors
- [ ] Multi-instance support (multiple houses)
- [ ] Voice assistant integration (Alexa, Google)
- [ ] Machine learning for behavior optimization

## 📌 Technical Debt


### High Priority
- File: `core/event_router.py:67`
- Fix: Add public method `engine.get_entities_by_device()`
- File: `core/action_handlers.py`
- Fix: Extract to helper function `extract_device_id(context)`

### Medium Priority
- File: `adapters/ha_adapter.py`
- Fix: Add tests with mocked connection failures
- File: `cli.py`
- Fix: Add end-to-end CLI tests

### Low Priority
- File: `tools/dashboard_generator.py`
- Fix: Refactor to Jinja2 templates

## 📌 Cancelled Ideas


### GraphQL API
- **Reason:** Too complex for current scale. REST/WebSocket is sufficient.
- **Date cancelled:** 2026-09-10

### Multi-tenant support
- **Reason:** Premature optimization. Focus on single-house reliability first.
- **Date cancelled:** 2026-09-12

### Visual FSM editor
- **Reason:** YAML with composition pattern is more maintainable than visual editing.
- **Date cancelled:** 2026-09-13

## 📅 Upcoming Releases

### v3.1.0 - Advanced Features (Q4 2024)

Focus on usability and observability:

- Device-level sensor configuration
- Web-based manifest editor
- Prometheus metrics integration
- Hot-reload capability

### v3.2.0 - Platform Maturity (Q1 2025)

Focus on extensibility and intelligence:

- Plugin architecture for custom behaviors
- Multi-instance support
- ML-based behavior optimization
- Enhanced debugging tools

### Future Considerations

- Voice assistant integrations
- Mobile application
- Cloud sync capabilities
- Advanced scheduling features
