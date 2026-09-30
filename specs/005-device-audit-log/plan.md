# Implementation Plan: История операций с устройствами (ТР-010)

**Branch**: `005-device-audit-log` | **Date**: 2026-09-29 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/005-device-audit-log/spec.md`

## Summary

Реализовать модель `DeviceSyncEvent` (время, инициатор, устройство, тип действия, до/после) и её персистентность, писать записи при операциях конфигурации (webui API), команд (webui API) и прав доступа (webui grant/revoke), отдавать реальную историю через существующий `GET /api/v1/devices/{id}/events` (сейчас заглушка `[]`), с фильтром по типу и пагинацией. Запись синхронная в рамках операции, ошибка записи не фейлит операцию (clarify Q2/Q3).

## Technical Context

**Language/Version**: Python 3.14, strict type hints обязательны (Constitution)

**Primary Dependencies**: FastAPI, Pydantic v2, pytest (+pytest-asyncio), loguru, ruff/mypy

**Storage**: JSON-файлы в `data/` — паттерн `DeviceAccessPersistence` (`device_sync_events.json`), интеграция через `PersistenceManager` (решение R1 в [research.md](./research.md))

**Testing**: pytest (unit в `tests/unit/`, contract в `tests/contract/`, integration в `tests/integration/`), TDD Red-Green-Refactor

**Target Platform**: Linux server / macOS (Docker + standalone)

**Project Type**: web-service (FastAPI webui + core-слой)

**Performance Goals**: запись истории не замедляет операцию заметно (SC-005: ≤10% времени ответа)

**Constraints**: ошибка записи истории не блокирует операцию (FR-009); core не импортирует adapters (ADR-001); функции ≤50 строк; type hints + Google docstrings

**Scale/Scope**: единственный домашний инстанс; операции — редкие (config/command/access, без state changes — FR-011); история растёт неограниченно, читается с пагинацией (limit/offset, по умолчанию ≤100)

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Gate | Статус | Комментарий |
|------|--------|-------------|
| I. Event-Driven FSM фундамент | ✅ | История — персистентный side-effect операций; существующий `DeviceAccessChangedEvent` в event bus не трогаем |
| II. TDD/SDD (NON-NEGOTIABLE) | ✅ | Spec 005 создан до кода; тесты пишутся до/вместе с реализацией каждого модуля |
| IV. Многоуровневая архитектура | ✅ | Модель → `core/models`, persistence → `core/persistence`, запись/чтение → `webui` (webui импортирует core — разрешённое направление) |
| ADR-001 Core ≠ Adapters | ✅ | Новых зависимостей core→adapters нет |
| ADR-002 Манифест — единственный источник | ✅ | Манифест не изменяется |
| Манифест / hardcoded values | ✅ | Лимит истории (100) — параметр endpoint, не хардкод в логике |
| Type hints + docstrings (100%) | ✅ | Все новые публичные функции |
| Функции ≤50 строк | ✅ | Запись истории — отдельные helper-функции (`_record_sync_event`) |
| Coverage ≥80% новых файлов | ✅ | Unit-тесты модели и persistence + contract/integration |
| Логирование через loguru | ✅ | Ошибки записи — через loguru (FR-009) |

**Gate результат**: PASS, нарушений нет → Phase 0 research выполнен.

**Post-design re-check (после Phase 1)**: PASS — design не создаёт новых зависимостей core→adapters, модель/persistence в core, контракты REST — существующий endpoint.

## Project Structure

### Documentation (this feature)

```text
specs/005-device-audit-log/
├── plan.md              # Этот файл (/speckit-plan)
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output
├── quickstart.md        # Phase 1 output
├── contracts/           # Phase 1 output
│   └── device-events-api.md
├── checklists/
│   └── requirements.md
└── tasks.md             # Phase 2 output (/speckit-tasks)
```

### Source Code (repository root)

```text
src/
├── core/
│   ├── models/
│   │   └── device_sync_event.py     # НОВОЕ: модель DeviceSyncEvent
│   └── persistence/
│       ├── devices.py               # ИЗМЕНЕНИЕ: + DeviceSyncEventPersistence
│       └── manager.py               # ИЗМЕНЕНИЕ: + self.device_sync_events
├── services/
│   └── device_service.py            # НЕ ИЗМЕНЯЕТСЯ (решение R2)
└── webui/
    ├── routes/devices/
    │   ├── deps.py                  # ИЗМЕНЕНИЕ: helper доступа к записи истории
    │   ├── devices.py               # ИЗМЕНЕНИЕ: запись в config/command + чтение в /events
    │   └── access_control.py        # ИЗМЕНЕНИЕ: запись в grant/revoke
    └── app.py                       # НЕ ИЗМЕНЯЕТСЯ (persistence уже в app.state)

tests/
├── unit/
│   ├── test_device_sync_event.py    # НОВОЕ: модель
│   └── test_device_sync_persistence.py  # НОВОЕ: персистентность
├── contract/
│   └── test_device_events_api.py    # НОВОЕ: GET /events, фильтр, пагинация, отказы
└── integration/
    └── test_device_audit_log.py     # НОВОЕ: полный цикл + перезапуск (SC-001..SC-003)
```

**Structure Decision**: существующая структура web-приложения (`src/core` + `src/webui` + `src/services`); новых директорий и опций не вводится. Модель и persistence — в ядре (по образцу `device_access.py` / `DeviceAccessPersistence`), точки записи — в webui-слое (решение R2), чтение — существующий endpoint.
