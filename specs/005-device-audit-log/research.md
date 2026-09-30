# Research: История операций с устройствами (ТР-010)

**Date**: 2026-09-29 | **Plan**: [plan.md](./plan.md)

## Неизвестные Technical Context → решения

### R1. Хранилище истории: JSON (паттерн device-домена) vs SQLite (EventStore)

**Decision**: JSON-файл `data/device_sync_events.json` через новый `DeviceSyncEventPersistence`, интегрированный в `PersistenceManager` — по точному образцу `DeviceAccessPersistence`.

**Rationale**:
- Вся device-персистентность уже в JSON (`devices.json`, `device_access.json`) — консистентность домена
- `PersistenceManager` уже создаётся в `create_app` и лежит в `app.state.persistence` — точка интеграции готова
- Объём операций невелик: пишутся только config/command/access (FR-011 исключает state changes) — JSON не перерастёт формат при домашнем инстансе
- Пагинация (limit/offset) — чтение + slice; редкие чтения не оправдывают SQLite

**Alternatives considered**:
- *Расширить существующий `EventStore` (SQLite, `data/history.db`)*: append-only и нативная пагинация — за; но таблицы `events`/`fsm_transitions` принадлежат домену сенсоров/FSM, нет полей user_id/actor/action payload; смешение доменов в одном модуле; дублирование точек записи. Отвергнуто.
- *Логировать только через loguru без модели*: не даёт API-истории (FR-006), не переживает структурированное чтение. Отвергнуто.

### R2. Где выполнять запись: webui-слой vs device-сервис

**Decision**: записи выполняются в webui-слое, там же где происходят сами операции:
- **config** → хендлер `update_device_config` (`routes/devices/devices.py`), после успешного обновления; before — копия `config` перед изменением
- **command** → хендлер `execute_device_command` (`routes/devices/devices.py`), перед формированием ответа; before/after — пустые (clarify Q1)
- **access** → хендлеры grant/revoke в `routes/devices/access_control.py`; роль до/после в before/after (clarify Q1)

**Rationale**:
- clarify Q3: фиксируются только операции веб-API — все три точки находятся в webui-роутах
- `device_service.py` не изменяется (домен US4 уже закрыт; revoke_access сейчас не принимает инициатора — расширение сигнатуры не нужно)
- Идентификатор инициатора доступен в каждом хендлере из той же идентификации, что и проверка доступа (`X-User-ID` / `request.state`)
- Синхронная запись до ответа (clarify Q2) — естественно внутри хендлера

**Alternatives considered**:
- *Писать в `DeviceService.grant_access/revoke_access`*: нужно менять сигнатуру `revoke_access(access_id, revoked_by)` — модификация домена без нужды; config/command в сервисе вообще не проходят (`update_device_config` пишет напрямую в `_devices_store`). Отвергнуто.
- *Event bus подписчик*: запись асинхронная относительно операции (race для acceptance-тестов SC-001), избыточно для трёх точек. Отвергнуто.

### R3. Точка интеграции доступа к persistence из webui

**Decision**: helper в `routes/devices/deps.py` — `get_sync_history(request) -> DeviceSyncEventPersistence | None`, читает `request.app.state.persistence.device_sync_events`; при отсутствии persistence — `None` и вызывающий код пропускает запись с loguru-warning (FR-009).

**Rationale**:
- Паттерн уже применён в US4 (`get_device_service` в том же `deps.py`)
- `app.state.persistence` может быть `None` (fallback в `create_app` при ошибке инициализации) — guard обязателен
- Чтение в `GET /events`: тот же helper; `persistence is None` → пустой список (не 500)

**Alternatives considered**:
- FastAPI `Depends` с 503 при отсутствии: история — не критичный ресурс, отказ в 503 противоречит FR-009 (лучше пустой список/пропуск). Отвергнуто.

### R4. Схема модели `DeviceSyncEvent`

**Decision**: Pydantic `BaseModel` в `src/core/models/device_sync_event.py` (по образцу `device_access.py`):

| Поле | Тип | Смысл |
|------|-----|-------|
| `id` | `UUID` (default_factory=uuid4) | Идентификатор записи |
| `device_id` | `UUID` | Устройство |
| `action` | `Literal["config_changed", "command_executed", "access_granted", "access_revoked", "access_updated"]` | Тип операции |
| `user_id` | `str` | Инициатор (для системных — `"system"`, FR-010) |
| `timestamp` | `datetime` (default_factory=utcnow) | Время операции |
| `before` | `dict[str, Any] \| None` | Состояние до (clarify Q1: пусто для команд) |
| `after` | `dict[str, Any] \| None` | Состояние после |
| `data` | `dict[str, Any] \| None` | Релевантные данные (роль, содержимое команды и т.п.) |

**Rationale**: `action` покрывает все три операции спеки; before/after optional — фиксируется только изменяемое состояние; `data` — расширяемый контейнер без ломки схемы. Сериализация `model_dump(mode="json")` — как у `DeviceAccess`.

**Alternatives considered**: переиспользовать `DeviceAccessChangedEvent` (dataclass в event bus) — он не full-доменен (нет before/after для конфигурации/команд, dataclass не сериализуется в JSON напрямую), его роль — событие в bus, не запись истории. Отвергнуто.

### R5. Формат отдачи истории (совместимость с существующим контрактом)

**Decision**: существующий `DeviceEventResponse` (id, device_id, event_type, timestamp, data) сохраняется; маппинг: `event_type` ← `action`, `data` ← `{"user_id": ..., "before": ..., "after": ..., **data}`. Query-параметры `event_type`/`limit`/`offset` работают по `action`/пагинации. Фильтр по неизвестному типу → пустой список.

**Rationale**: контракт `GET /api/v1/devices/{id}/events` уже опубликован в `specs/001/contracts/rest-api.md`; контракт-тесты и фронтенд не ломаются; замена заглушки `[]` на реальные данные — единственное поведенческое изменение (SC-004).

### R6. Стратегия тестов (TDD)

**Decision**:
1. **Unit** (`tests/unit/test_device_sync_event.py`): модель — сериализация, defaults, валидация action
2. **Unit** (`tests/unit/test_device_sync_persistence.py`): запись, чтение списка, фильтр по action, пагинация, повреждённый JSON → `[]` с warning, отсутствие файла → `[]`
3. **Contract** (`tests/contract/test_device_events_api.py`): 200 с записями после config-операции (SC-001), фильтр, пагинация, 404 неизвестное устройство, 403 без роли, пустой список для устройства без операций
4. **Integration** (`tests/integration/test_device_audit_log.py`): config + access + command → три записи с инициаторами (SC-001/002/004); «рестарт» — пересоздание `PersistenceManager` на том же `data_dir` → записи читаются (SC-003); ошибка записи не фейлит операцию (FR-009)

**Red phase**: тесты пишутся первыми, падают (ImportError на модель) → Green.

### R7. Лимит ответа и рост истории

**Decision**: дефолтный `limit=100`, максимум не ограничиваем жёстко (как сейчас); хранение — бессрочно (assumption спеки). Очистка/ретеншн — вне scope, отдельная задача при реальном росте.

## Открытые вопросы

Нет — все NEEDS CLARIFICATION из Technical Context закрыты (R1–R7).
