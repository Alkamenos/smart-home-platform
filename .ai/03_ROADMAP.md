# Roadmap (Machine-Readable)

## 📌 Как использовать этот файл

**Перед началом задачи:** Найди свою задачу в соответствующей фазе и проверь статус.

**После завершения задачи:** Pre-commit хук автоматически отметит задачу как выполненную `[x]`.
Или обнови вручную: `python3 .ai/scripts/sync_roadmap.py --auto-update`

---

## Status Legend

- `[x]` Completed — задача выполнена, файлы кода существуют
- `[ ]` In Progress — задача в работе
- `[ ]` Planned — запланирована
- `[x]` Cancelled — отменена

> **Примечание:** Pre-commit хук автоматически обновляет статус задач на основе наличия файлов кода.

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

## Phase 4: Production Readiness [COMPLETED: 2026-09-15]
- [x] **CRITICAL** Consolidate project structure (remove code duplication)
  - Issue: Code exists in both `core/` and `../src/core/`
  - Action: Migrate fully to `src` layout, remove flat structure
  - Impact: All imports, pyproject.toml, cli.py
- [x] **CRITICAL** Fix manifest bug: add `motion_sensor` to night_light params
  - File: `instances/leonids_house/manifest.yaml`
  - Issue: `01_PROJECT_STATE.md` → Known Issues #1
- [x] Clean up legacy tests
  - Remove: `tests/test_legacy_*.py`
  - Add: middleware tests, CLI tests, WebSocket reconnect tests
- [x] Add pre-commit hooks
  - pytest, mypy, ruff, black
- [x] Update README.md with new architecture diagrams
- [x] Add code coverage badge

## Phase 5: Room-Based Architecture [COMPLETED: 2026-09-15]
- [x] Refactor Manifest: devices nested inside rooms
- [x] Sensors describe room state, devices are actuators
- [x] Same sensor can be referenced from multiple rooms
- [x] Update EventRouter for room-based routing
- [x] Update LovelaceGenerator for new structure
- [x] Update FSMFactory.create_from_manifest()
- [x] Update all tests
- [x] Remove migration tests (no external users)

## Phase 6: Advanced Features [COMPLETED: 2026-09-18]
- [x] Web UI for manifest editing
  - FastAPI + HTMX
  - Form validation using Pydantic models
  - Files: `src/webui/app.py`, `src/webui/routes.py`, `src/webui/models.py`, `tests/test_webui.py`
  - Implementation date: 2026-09-17
- [x] Prometheus metrics export
  - `/metrics` endpoint
  - FSM state changes, command latency, error rates
  - Files: `core/metrics.py`, `tests/test_metrics.py`
  - Implementation date: 2026-09-16
- [x] Hot-reload without restart
  - File watcher for manifest changes
  - Graceful FSM migration (unregister old, register new)
  - Files: `services/config_watcher.py`, `tests/test_hot_reload.py`
  - Implementation date: 2026-09-17

## Phase 7: Platform Extensions - Quick Wins [IN PROGRESS]
- [x] Declarative Guards DSL
  - Files: `core/guards/`, `core/fsm.py`
  - Detail: `.ai/enhancements/01-declarative-guards-dsl.md`
  - Priority: HIGH
  - Effort: 1-2 days
- [x] FSM Visualization (Mermaid/Graphviz)
  - Files: `core/fsm_visualizer.py`, `cli/commands/export_fsm.py`
  - Detail: `.ai/enhancements/02-fsm-visualization.md`
  - Priority: MEDIUM
  - Effort: 1 day
- [ ] Interactive REPL
  - File: `cli/commands/shell.py`
  - Detail: `.ai/enhancements/03-interactive-repl.md`
  - Priority: LOW
  - Effort: 0.5 days

## Phase 8: Platform Extensions - Core Features [PLANNING]
- [ ] Scene Manager / Flow Engine
  - Files: `core/scene_manager.py`, `core/models/scene.py`
  - Detail: `.ai/enhancements/04-scene-manager.md`
  - Priority: HIGH
  - Effort: 2-3 days
- [ ] Room Aggregation & Policies
  - Files: `core/room_manager.py`, `core/models/room.py`
  - Detail: `.ai/enhancements/05-room-aggregation.md`
  - Priority: MEDIUM
  - Effort: 2 days
- [ ] Digital Twin / Simulator
  - Files: `core/simulator.py`, `cli/commands/simulate.py`
  - Detail: `.ai/enhancements/06-digital-twin.md`
  - Priority: MEDIUM
  - Effort: 2-3 days

## Phase 9: Observability & Reliability [PLANNING]
- [ ] Prometheus / OpenTelemetry Metrics
  - Files: `core/metrics.py`, `services/metrics_server.py`
  - Detail: `.ai/enhancements/07-prometheus-metrics.md`
  - Priority: HIGH
  - Effort: 1-2 days
- [ ] Circuit Breaker Pattern
  - File: `adapters/ha_adapter.py`
  - Detail: `.ai/enhancements/08-circuit-breaker.md`
  - Priority: HIGH
  - Effort: 1 day
- [ ] Secrets Management
  - File: `core/secrets.py`
  - Detail: `.ai/enhancements/09-secrets-management.md`
  - Priority: MEDIUM
  - Effort: 1 day

## Phase 10: Architecture Improvements [FUTURE]
- [ ] Domain-Driven Design Refactoring
  - File: `core/`
  - Detail: `.ai/enhancements/11-ddd-refactoring.md`
  - Priority: MEDIUM
  - Effort: 1-2 days
- [ ] Plugin System
  - File: `core/plugin_loader.py`
  - Detail: `.ai/enhancements/12-plugin-system.md`
  - Priority: LOW
  - Effort: 2-3 days
- [ ] Dependency Injection
  - File: `bootstrap.py`
  - Detail: `.ai/enhancements/13-dependency-injection.md`
  - Priority: LOW
  - Effort: 2-3 days

## Phase 11: Advanced Features [FUTURE]
- [ ] LLM / NLP Adapter
  - Files: `adapters/nlp_adapter.py`, `core/nlp_parser.py`
  - Detail: `.ai/enhancements/10-llm-nlp-adapter.md`
  - Priority: LOW
  - Effort: 3-5 days
- [ ] Hot-Reloading для Guard/Action функций
  - Files: `services/config_watcher.py`, `core/registry.py`
  - Detail: `.ai/enhancements/14-hot-reloading.md`
  - Priority: LOW
  - Effort: 1-2 days

## Phase 12: Platform Maturity [FUTURE]
- [ ] Plugin system for custom behaviors
- [ ] Multi-instance support (multiple houses)
- [ ] Voice assistant integration (Alexa, Google)
- [ ] Machine learning for behavior optimization

## Technical Debt

### High Priority

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
