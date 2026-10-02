# Specification Quality Checklist: Observability платформы (008-fsm-observability)

**Purpose**: Validate specification completeness and quality before proceeding to planning
**Created**: 2026-10-01
**Feature**: [spec.md](../spec.md)

## Content Quality

- [x] No implementation details (languages, frameworks, APIs)
- [x] Focused on user value and business needs
- [x] Written for non-technical stakeholders
- [x] All mandatory sections completed

## Requirement Completeness

- [x] No [NEEDS CLARIFICATION] markers remain
- [x] Requirements are testable and unambiguous
- [x] Success criteria are measurable
- [x] Success criteria are technology-agnostic (no implementation details)
- [x] All acceptance scenarios are defined
- [x] Edge cases are identified
- [x] Scope is clearly bounded
- [x] Dependencies and assumptions identified

## Feature Readiness

- [x] All functional requirements have clear acceptance criteria
- [x] User scenarios cover primary flows
- [x] Feature meets measurable outcomes defined in Success Criteria
- [x] No implementation details leak into specification

## Notes

### Развилки, закрытые пользователем (2026-10-01)

Три маркера уточнения сняты — все по варианту A (рекомендованному). Решения зафиксированы в разделе «Решения пользователя» спецификации и отражены в требованиях:

| Решение | Что выбрано | На что повлияло в спеке |
|---------|-------------|-------------------------|
| D-1 | Сторож починяется и подключается как полноценная служба | US2 сохраняется полностью (FR-012–FR-019, SC-007–SC-012) |
| D-2 | Показатели отдаются с того же HTTP-сервера платформы, что и панель | FR-002 дополнен требованием единого сервера; отдельный сервер показателей перенесён в «Вне объёма» и удаляется (FR-021) |
| D-3 | Недостижимый модуль интеграции с панелью удаляется как мёртвый код | FR-021 дополнен; оживление вынесено в «Вне объёма» |

### Обоснование отметок

**Про «без деталей реализации»:** в разделе «Контекст проблемы» намеренно приведены пути и номера строк — это наблюдения о текущем состоянии кода (факты проверки), а не предписание способа реализации. Требования (FR-001–FR-026) и критерии успеха (SC-001–SC-016) сформулированы без указания конкретных библиотек, модулей и портов. Соответствует стилю specs/007, который принят в проекте.

### Соответствие объёма приоритетам

- **US1 (P1)** — корень: без инициализации сборщика 18 метрик и 12 существующих мест вызова остаются no-op. Даёт ценность сам по себе (внешний мониторинг, алерты).
- **US2 (P2)** — требует US1 (FR-015 «проблемы MUST попадать в показатели»), самостоятельно проверяется отдельно.
- **US3 (P3)** — независима по коду, но по смыслу фиксирует итог US1/US2 (FR-020).

### Согласованность с предыдущими фичами

- Спека 007 явно вывела наблюдаемость за свой объём («Метрики платформы (`/metrics`), сторожевые проверки состояний и снимки состояний — отдельная фича наблюдаемости»). Настоящая спека закрывает это обязательство.
- Источник данных — события `fsm.transitioned`/`fsm.rejected`, введённые в specs/007; зависимость D-001 зафиксирована.
- Один пункт BACKLOG F3 (`DashboardIntegration` подписан на непубликуемое `fsm.state.changed`) **уже неактуален** — исправлен в specs/007 (`src/dashboard/dashboard.py:44` подписан на `fsm.transitioned`, тест `tests/test_dashboard.py:35-50`). Отражено в разделе «Контекст проблемы».