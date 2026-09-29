# Implementation Plan: Критические продакшен-фиксы (Phase 9.8)

**Branch**: `003-critical-production-fixes` | **Date**: 2026-09-29 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `/specs/003-critical-production-fixes/spec.md`

## Summary

Закрыть остаток Phase 9.8 по трём пунктам: (1) честный healthcheck контейнера — недостающий модуль, к которому обращается compose (`python -m src.cli.health_check`), плюс верификация фактической сборки/запуска (docker доступен в среде); (2) остаток надёжности WebSocket-восстановления — тесты реконнекта, метрика обрывов, гарантия отсутствия «висящих» задач (сам цикл reconnect уже реализован в `ha_adapter.py`); (3) полная реализация TTL для командных интентов — поля времени жизни, фоновая проверка под `asyncio.Lock`, lifecycle start/stop, тесты (не начата вообще). Подход: минимальные точечные правки существующих модулей с TDD-тестами, без новых слоёв.

## Technical Context

**Language/Version**: Python 3.14 (требование проекта 3.10+)

**Primary Dependencies**: FastAPI/uvicorn (WebUI), aiohttp (метрики/пробы), prometheus_client (метрики), pytest + pytest-asyncio (тесты), Pydantic v2 (модели), loguru (логирование)

**Storage**: N/A — состояние интентов оперативное (`_active_intents` в памяти); ничего не персистируется

**Testing**: pytest (`run_checks.sh`, покрытие цель ≥80%; новые тесты: `tests/test_ha_adapter_reconnect.py`, `tests/test_dispatcher_ttl.py`, `tests/cli/test_health_check.py`)

**Target Platform**: Linux сервер + Docker-контейнер (`deploy/docker/Dockerfile`, `docker-compose.prod.yml`)

**Project Type**: Web-сервис с CLI-компонентами и фоновым event-driven ядром

**Performance Goals**: healthcheck отвечает ≤5 сек (timeout 10с в compose); восстановление связи ≤60 сек после доступности HA; cleanup-цикл — проверка раз в 5 минут (не нагружает CPU)

**Constraints**: graceful shutdown ≤30 сек; backoff не должен ждать окончания при SIGTERM; семантика приоритетной конкуренции интентов не меняется; Core не импортирует Adapters (через Protocol)

**Scale/Scope**: 1 контейнер, 1 процесс; до десятков активных интентов; 3 изменяемых модуля + 3-4 новых тестовых файла

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

**Конституция проекта**: v3.0.0 (Production Readiness) — `.specify/memory/constitution.md`

1. **Event-Driven FSM (Принцип I)** — ✅ force-release интента публикуется через лог/события EventBus (наличие слушателя не обязательно для FR-009:WARNING в логе достаточен по спецификации); reconnect остаётся фоновой задачей адаптера
2. **TDD/SDD (Принцип II)** — ✅ тесты пишутся до/вместе с реализацией (новые файлы тестов в Technical Context), покрытие ≥80% поддерживается общим замером
3. **User Control (Принцип III)** — ✅ оператор управляет через compose/логи/healthcheck; TTL и backoff — автоматические механизмы с дефолтами из enhancement
4. **Multi-layer Architecture (Принцип IV)** — ✅ правки в `core/commands` (ядро), `adapters` (adapters), `cli` (инфраструктура), `main` (composition root); вызовы через Protocols
5. **Manifest as Config (Принцип V)** — ✅ дефолты TTL/backoff задаются константами модулей, ENV только для портов/логирования (как в существующем `main.py`); манифест не меняется
6. **Type Hints & Docstrings** — ✅ обязательны во всех новых/изменённых функциях (Google style)
7. **Логирование через Loguru** — ✅ все новые логи (обрывы, попытки, force-release) — через loguru с trace_id, где применимо

**Потенциальные конфликты**: фоновый cleanup-loop — не событийный паттерн, но это служебный цикл обслуживания в ядре, а не бизнес-логика переходов FSM; альтернатива (событийный таймер на каждое приобретение интента) отклонена как избыточность. Нарушений, требующих Complexity Tracking, нет.

**Решение**: ✅ Проходит гейт. Повторная проверка после Phase 1 — без изменений (дизайн не добавляет новых слоёв).

## Project Structure

### Documentation (this feature)

```text
specs/003-critical-production-fixes/
├── plan.md              # Этот файл (/speckit-plan output)
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output
├── quickstart.md        # Phase 1 output
├── contracts/
│   └── operational-contracts.md  # Phase 1 output (healthcheck, метрики, логи)
├── checklists/
│   └── requirements.md  # из /speckit-specify
└── tasks.md             # Phase 2 output (/speckit-tasks — НЕ создаётся планом)
```

### Source Code (repository root)

```text
src/
├── cli/
│   ├── commands/
│   └── health_check.py            # НОВОЕ: модуль healthcheck контейнера (compose уже ссылается)
├── core/
│   └── commands/
│       └── dispatcher.py          # ИЗМЕНЕНИЕ: CommandIntent +ttl/refresh/is_expired, cleanup-loop, asyncio.Lock, start/stop
├── adapters/
│   └── ha_adapter.py              # ИЗМЕНЕНИЕ (остаток): верификация детекта обрыва, сброс ресурсов при reconnect
├── core/
│   └── container.py               # ИЗМЕНЕНИЕ: lifecycle dispatcher.start() в PlatformContext/stop при shutdown
├── webui/
│   └── routes/__init__.py         # ИЗМЕНЕНИЕ: /health → JSON {"status":"ok"} (FR-002)
└── main.py                        # ИЗМЕНЕНИЕ: dispatcher.stop() в shutdown

deploy/docker/
├── Dockerfile                     # ИЗМЕНЕНИЕ (если верификация выявит): точечные фиксы по итогам сборки
└── docker-compose.prod.yml        # БЕЗ ИЗМЕНЕНИЙ (healthcheck уже задан)

tests/
├── cli/
│   └── test_health_check.py       # НОВОЕ
├── test_ha_adapter_reconnect.py   # НОВОЕ (из enhancement 21)
├── test_dispatcher_ttl.py         # НОВОЕ (из enhancement 22)
└── test_webui.py                  # ИЗМЕНЕНИЕ: обновить тест /health под JSON
```

**Structure Decision**: существующая структура `src/` (single project) сохраняется; новых пакетов не создаётся — только 1 новый модуль `cli/health_check.py` и 3 новых тестовых файла. Точки правок определены верификацией кода 2026-09-29 (см. research.md).

## Complexity Tracking

> Нет нарушений принципов, требующих обоснования (см. Constitution Check).
