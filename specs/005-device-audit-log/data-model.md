# Data Model: История операций с устройствами (ТР-010)

**Date**: 2026-09-29 | **Spec**: [spec.md](./spec.md) | **Research**: [research.md](./research.md)

## Сущность: DeviceSyncEvent (запись операции устройства)

Файл: `src/core/models/device_sync_event.py` — Pydantic `BaseModel` (по образцу `device_access.py`)

| Поле | Тип | Обяз. | Описание | Источник требований |
|------|-----|-------|----------|---------------------|
| `id` | `UUID` | default_factory=uuid4 | Идентификатор записи | ТР-010 |
| `device_id` | `UUID` | да | Устройство, над которым выполнена операция | ТР-010 (entity_id) |
| `action` | `Literal["config_changed", "command_executed", "access_granted", "access_revoked", "access_updated"]` | да | Тип операции | FR-001 |
| `user_id` | `str` | да (default `"system"`) | Инициатор; системные операции — `"system"` | ТР-010, FR-003/004/005/010 |
| `timestamp` | `datetime` | default_factory=utcnow | Время операции (UTC) | ТР-010 |
| `before` | `dict[str, Any] \| None` | default None | Состояние до: config-поля (config_changed), роль (access_*); для команд — None | FR-001 + clarify Q1 |
| `after` | `dict[str, Any] \| None` | default None | Состояние после (по аналогии) | FR-001 + clarify Q1 |
| `data` | `dict[str, Any] \| None` | default None | Релевантные данные: содержимое команды, роль, granted_by | FR-004/005 |

**Сериализация**: `model_dump(mode="json")` (как у `DeviceAccess`) — datetime → ISO-строка, UUID → str.

**Валидация**: `action` — только значения Literal (Pydantic); `user_id` непустая строка.

## Хранилище: DeviceSyncEventPersistence

Файл: `src/core/persistence/devices.py` (рядом с `DeviceAccessPersistence`), регистрация в `PersistenceManager.__init__` → `self.device_sync_events`.

- Файл данных: `data/device_sync_events.json` — карта `{str(id): record}` (паттерн `device_access.json`)
- Append-only: новые записи добавляются; обновление/удаление не предусмотрено (исторический лог)

### Интерфейс

```python
class DeviceSyncEventPersistence:
    def __init__(self, data_dir: Path | str = "data") -> None: ...
    async def append_event(self, event: DeviceSyncEvent) -> None
    async def list_events(
        self,
        device_id: UUID,
        action: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[DeviceSyncEvent]
```

### Правила чтения (FR-007, R5)

- Сортировка: по `timestamp` (по убыванию — новые первыми)
- Фильтр `action` — точное совпадение; неизвестное значение → пустой список
- Пагинация: slice `[offset : offset + limit]` после фильтрации
- Файл отсутствует / JSON повреждён → `[]` + loguru warning (не исключение)

## Точки записи (R2, синхронно в рамках операции — clarify Q2)

| Операция | Хендлер | action | before | after | data | user_id |
|----------|---------|--------|--------|-------|------|---------|
| Изменение конфигурации | `update_device_config` (devices.py) | `config_changed` | копия config-полей ДО изменений | config-поля ПОСЛЕ | — | идентификация запроса |
| Отправка команды | `execute_device_command` (devices.py) | `command_executed` | None | None | `{command: <effective_name>, parameters: ...}` | идентификация запроса |
| Выдача права | `grant_access` (access_control.py) | `access_granted` | None (права не было) | `{role: <роль>}` | `{granted_to: <user>, granted_by: <admin>}` | идентификация запроса |
| Обновление права | `grant_access` (access_control.py) | `access_updated` | `{role: <прежняя>}` | `{role: <новая>}` | `{granted_to: <user>}` | идентификация запроса |
| Отзыв права | `revoke_access` (access_control.py) | `access_revoked` | `{role: <отозванная>}` | None | `{granted_to: <user>}` | идентификация запроса |

**Поведение при ошибке (FR-009)**: `try/except` вокруг записи → loguru `error`, операция завершается штатно. `app.state.persistence is None` → loguru `warning`, пропуск.

## Отношения

- `DeviceSyncEvent.device_id` → устройство (по идентификатору; FK не навязывается — JSON-хранилище)
- `DeviceSyncEvent` НЕ связан с `DeviceAccessChangedEvent` (event bus) — независимые артефакты: событие в bus остаётся, запись истории добавляется
- `DeviceAccessPersistence` / `DevicePersistence` — не изменяются

## Состояния и переходы

Append-only лог — переходов состояния нет. Lifecycle записи: создание → только чтение.
