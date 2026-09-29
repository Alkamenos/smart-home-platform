# Implementation Plan: Контроль доступа к устройствам (Access Control)

**Branch**: `004-device-access-control` | **Date**: 2026-09-29 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `/specs/004-device-access-control/spec.md`

## Summary

Интеграционный остаток US4 (бэклог specs/001 RU T067–T071): домен доступа почти готов (DeviceService реализует grant/revoke/list/user-devices/check-access с иерархией ролей; модель DeviceAccess и файловая DeviceAccessPersistence готовы), но web-каналы не используют его. Закрыть: (1) регистрация DeviceAccessMiddleware в webui-приложении (401 без X-User-ID, state для device-запросов); (2) реальная фильтрация GET /api/v1/devices по доступу пользователя; (3) разблокировка логики сервиса в grant/revoke/list доступа (заглушки → реальные данные, дубликат grant → обновление роли, отсутствие → 404); (4) проверка check_device_access при WebSocket-подписке И при каждой доставке события (уточнение clarify). Подход: точечные правки существующих модулей + тесты; серверная логика не переписывается.

## Technical Context

**Language/Version**: Python 3.14 (требование проекта 3.10+)

**Primary Dependencies**: FastAPI/starlette (WebUI, BaseHTTPMiddleware, Header-зависимости), Pydantic v2 (модели), pytest + pytest-asyncio (тесты), loguru/std logging (логи — как в существующих маршрутах)

**Storage**: существующая файловая DeviceAccessPersistence (JSON-файл доступов в data-dir домена устройств); специальных хранилищ/миграций нет (уточнение clarify)

**Testing**: pytest (`run_checks.sh`, покрытие ≥80%; новые тесты: контрактные на web-каналы доступа + интеграционные на персистентность/WS-доставку)

**Target Platform**: Linux сервер + Docker-контейнер (тот же деплой, что и вся платформа)

**Project Type**: Web-сервис с event-driven ядром; фича — web-каналы поверх существующего домена

**Performance Goals**: проверка доступа/фильтрация списка — неощутимо (< 1с на запрос, SC-003); операции grant/revoke/list < 2с (SC-004); проверка при доставке события не добавляет заметной задержки каналу

**Constraints**: Core не импортирует Adapters; идентификация из заголовков (X-User-ID/X-Is-Admin) — текущая семантика сохраняется (аутентификация вне scope); тексты/форматы ответов следуют существующим маршрутам; не раскрывать существование устройства (404 одинаков для отсутствующего и чужого)

**Scale/Scope**: до сотен устройств и записей доступа; 4 изменяемых модуля (app.py, devices.py, access_control.py, websocket.py) + файл middleware уже существует; права распределены: все проверки на стороне сервиса с иерархией viewer<controller<admin

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

**Конституция проекта**: v3.0.0 (Production Readiness) — `.specify/memory/constitution.md`

1. **Event-Driven FSM (Принцип I)** — ✅ не затрагивается: FSM/события ядра не меняются; изменения доступа фиксируются записью события синхронизации (история операций), как принято в домене
2. **TDD/SDD (Принцип II)** — ✅ тесты до/вместе с реализацией; покрытие ≥80% поддерживается общим замером run_checks
3. **User Control (Принцип III)** — ✅ суть фичи: пользовательская сегментация прав; администратор управляет доступами через существующие маршруты
4. **Multi-layer Architecture (Принцип IV)** — ✅ правки только в webui-слое (маршруты/middleware/app); сервисные вызовы через готовые методы DeviceService; Core не затрагивается
5. **Manifest as Config (Принцип V)** — ✅ манифест не меняется; иерархия ролей и требуемые уровни — на стороне сервиса (уже существует), новых hardcoded значений в бизнес-логике нет
6. **Type Hints & Docstrings** — ✅ обязательны во всех новых/изменённых функциях
7. **Логирование** — ✅ в стиле существующих маршрутов (warning при отказах доступа, info при назначении/отзыве), без новых систем логирования

**Потенциальные конфликты**: нет новых слоёв и новых компонентов — только интеграция существующих. Один нюанс: проверка доступа при каждой доставке WebSocket-события добавляет вызов сервиса в горячий путь доставки — приемлемо (в памяти/файл, сотни устройств), альтернатива (кэш прав с инвалидацией) отклонена как избыточность для текущего масштаба. Нарушений, требующих Complexity Tracking, нет.

**Решение**: ✅ Проходит гейт. Повторная проверка после Phase 1 — без изменений (дизайн не добавляет новых слоёв).

## Project Structure

### Documentation (this feature)

```text
specs/004-device-access-control/
├── plan.md              # Этот файл (/speckit-plan output)
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output
├── quickstart.md        # Phase 1 output
├── contracts/
│   └── access-control-api.md  # Phase 1 output (HTTP + WS каналы доступа)
├── checklists/
│   └── requirements.md  # из /speckit-specify
└── tasks.md             # Phase 2 output (/speckit-tasks — НЕ создаётся планом)
```

### Source Code (repository root)

```text
src/
├── webui/
│   ├── app.py                              # ИЗМЕНЕНИЕ: регистрация DeviceAccessMiddleware
│   ├── middleware_access_control.py        # (существует) инфраструктурный контроль: 401 без X-User-ID
│   └── routes/devices/
│       ├── devices.py                      # ИЗМЕНЕНИЕ: реальная фильтрация GET /api/v1/devices по доступу
│       ├── access_control.py               # ИЗМЕНЕНИЕ: grant/revoke/list — реальная логика сервиса вместо заглушек
│       └── websocket.py                    # ИЗМЕНЕНИЕ: проверка доступа при подписке и при каждой доставке события
└── services/
    └── device_service.py                   # (существует, не меняется) grant_access/revoke_access/
                                            #   get_device_accesses/get_user_accessible_devices/
                                            #   check_device_access + иерархия ролей
```

**Structure Decision**: фича живёт целиком в webui-слое поверх готового домена; новые файлы — только тесты (`tests/contract/test_access_control.py` расширение / новые кейсы, tests/integration/test_access_control.py — уже существует) и, при необходимости, тест доставки WS-событий. Изменяемых модулей четыре, все — webui.
