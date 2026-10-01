# 📌 Enhancements — Индекс

Единый каталог всех 28 предложений по развитию платформы.

**Источник статусов:** `.ai/03_ROADMAP.md` (машиночитаемый roadmap), сверенный с фактическим кодом.

## Легенда статусов

| Статус | Значение |
|--------|----------|
| ✅ **Реализовано** | Фича реализована и покрыта тестами |
| ⚠️ **Реализовано (нет отметки)** | Код и тесты есть, но чек-бокс в roadmap не отмечен |
| 🔄 **В работе** | Частично реализовано |
| 📝 **Планирование** | Описание готово, реализации нет |
| ⬜ **Бэклог** | Отложено на будущее |

## Индекс

| № | Фича | Статус | Приоритет | Категория |
|---|------|--------|-----------|-----------|
| [01](01-declarative-guards-dsl.md) | Declarative Guards DSL | ✅ Реализовано | HIGH | Quick Wins |
| [02](02-fsm-visualization.md) | FSM Visualization (Mermaid/Graphviz) | ✅ Реализовано | MEDIUM | Quick Wins |
| [03](03-interactive-repl.md) | Interactive REPL (`shp shell`) | ✅ Реализовано | LOW | Quick Wins |
| [04](04-scene-manager.md) | Scene Manager / Flow Engine | ✅ Реализовано | HIGH | Core Features |
| [05](05-room-aggregation.md) | Room Aggregation & Policies | ✅ Реализовано | MEDIUM | Core Features |
| [06](06-digital-twin.md) | Digital Twin / Simulator | ✅ Реализовано | MEDIUM | Core Features |
| [07](07-prometheus-metrics.md) | Prometheus / OpenTelemetry Metrics | ✅ Реализовано | HIGH | Observability |
| [08](08-circuit-breaker.md) | Circuit Breaker Pattern | ✅ Реализовано | HIGH | Observability |
| [09](09-secrets-management.md) | Secrets Management | ⚠️ Реализовано¹ | MEDIUM | Observability |
| [10](10-llm-nlp-adapter.md) | LLM / NLP Adapter | ⬜ Бэклог | LOW | Advanced Features |
| [11](11-ddd-refactoring.md) | Domain-Driven Design Refactoring | ✅ Реализовано | MEDIUM | Architecture |
| [12](12-plugin-system.md) | Plugin System | ✅ Реализовано | LOW | Architecture |
| [13](13-dependency-injection.md) | Dependency Injection | ✅ Реализовано | LOW | Architecture |
| [14](14-hot-reloading.md) | Hot-Reloading Guard/Action функций | ⚠️ Реализовано² | LOW | Developer Experience |
| [15](15-production-deployment.md) | Production Deployment Preparation | 🔄 В работе | — | Production |
| [16](16-safe-deployment.md) | Safe Deployment Strategy | ✅ Реализовано | CRITICAL | Production |
| [17](17-enhanced-logging.md) | Enhanced Logging Integration | ✅ Реализовано | HIGH | Production |
| [18](18-automatic-manifest-generator.md) | Automatic Manifest Generator | ✅ Реализовано | HIGH | Production |
| [19](19-dashboard-generator.md) | Dashboard Generator for Platform Management | 🔄 Частично³ | MEDIUM | Production |
| [20](20-docker-entrypoint-fix.md) | Docker Entrypoint & Bootstrap Fix | ✅ Реализовано | CRITICAL | Production Bugfixes |
| [21](21-websocket-reconnect.md) | WebSocket Reconnection Reliability | ✅ Реализовано | CRITICAL | Production Bugfixes |
| [22](22-intent-ttl-dispatcher.md) | Command Intent TTL & Auto-Release | ✅ Реализовано | HIGH | Production Bugfixes |
| [23](23-event-history-persistence.md) | Event History Persistence (Data Lake) | 📝 Планирование | HIGH | AI & Analytics |
| [24](24-predictive-ai-middleware.md) | Predictive AI Middleware | 📝 Планирование | MEDIUM | AI & Advanced |
| [25](25-web-ui.md) | Web UI (редактирование манифеста) | ✅ Реализовано | — | Web UI |
| [26](26-extend-web-ui.md) | Расширенный Web UI (real-time визуализация FSM) | ✅ Реализовано (сверка 2026-10-01: real-time закрыт в specs/007 — публикация переходов, живой канал с проверкой прав, подсветка состояния; до этого был завышен) | specs/007 | Web UI |
| [27](27-device-discovery-wizard.md) | Device Discovery Wizard | ✅ Реализовано | — | Web UI |
| [28](28-add-devices.md) | Добавление устройств из HA в манифест | ✅ Реализовано | — | CLI / Web UI |

### Сноски

1. Код (`src/core/secrets.py`) и тесты (`tests/test_secrets.py`) существуют, но чек-бокс в roadmap не отмечен.
2. `services/config_watcher.py` поддерживает hot-reload Python-модулей с guard/action функциями; roadmap (Phase 11) не отмечен.
3. `src/dashboard/lovelace_generator.py` и `src/dashboard/dashboard.py` реализованы и протестированы; CLI-команда `generate-dashboard` из описания не реализована.

## Связанные документы

- [.ai/03_ROADMAP.md](../03_ROADMAP.md) — статусы задач по фазам
- [.ai/01_PROJECT_STATE.md](../01_PROJECT_STATE.md) — текущее состояние проекта
- [specs/](../../specs/) — рабочие спецификации (Spec Kit)

---

**Последнее обновление:** 2026-10-01
