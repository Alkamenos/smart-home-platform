# Contract: История операций устройства (ТР-010)

**Date**: 2026-09-29 | **Spec**: [spec.md](../spec.md) | **Data model**: [data-model.md](../data-model.md)

Контракт описывает существующий endpoint `GET /api/v1/devices/{device_id}/events` — поведение **до** (заглушка) и **после** (реальная история). Эндпоинты изменения операций (config/command/grant/revoke) не меняют контракты — они лишь начинают создавать записи истории.

## GET /api/v1/devices/{device_id}/events — история операций устройства

### Изменение поведения

| | До (заглушка) | После (spec 005) |
|---|---|---|
| Ответ 200 | Всегда `[]` (TODO в коде) | Реальные записи операций, новые первыми |
| `event_type` фильтр | Принимался, игнорировался | Фильтрует по типу операции |
| Перезапуск | — | Записи сохраняются (SC-003) |

### Параметры запроса

| Параметр | Тип | Дефолт | Описание |
|----------|-----|--------|----------|
| `event_type` | string, optional | — | Фильтр по типу операции: `config_changed`, `command_executed`, `access_granted`, `access_revoked`, `access_updated`. Неизвестное значение → `[]` |
| `limit` | int | 100 | Максимум записей в ответе |
| `offset` | int | 0 | Смещение (пагинация) |

### Идентификация и доступ

Заголовки идентификации, как у всех device-endpoints (spec 004, `DeviceAccessMiddleware`):
- без идентификации → **401**
- идентифицированный без роли viewer на устройство → **403** (`_require_access_or_403`)
- устройство не существует → **404** (проверка существования раньше доступа)

### Ответ 200

Массив записей (существующая схема `DeviceEventResponse` сохраняется):

```json
[
  {
    "id": "0f9d1b2a-...uuid",
    "device_id": "550e8400-...uuid",
    "event_type": "config_changed",
    "timestamp": "2026-09-29T12:00:00",
    "data": {
      "user_id": "admin_user",
      "before": {"location": "кухня"},
      "after": {"location": "гостиная"}
    }
  }
]
```

**Маппинг модели → контракт** (research R5):

| Поле ответа | Источник |
|-------------|----------|
| `id` | `DeviceSyncEvent.id` (str) |
| `device_id` | `DeviceSyncEvent.device_id` (str) |
| `event_type` | `DeviceSyncEvent.action` |
| `timestamp` | `DeviceSyncEvent.timestamp` (ISO) |
| `data.user_id` | `DeviceSyncEvent.user_id` |
| `data.before` / `data.after` | `DeviceSyncEvent.before` / `.after` (при наличии) |
| `data.*` (прочее) | `DeviceSyncEvent.data` (роль, команда и т.п.) |

### Контрактные кейсы

1. **Записи есть** — после операций над устройством 200 + непустой массив, записи содержат `user_id`, `timestamp`, `before`/`after` (где применимо) — SC-001/002/004, FR-001
2. **Фильтр** — `?event_type=config_changed` возвращает только операции конфигурации — FR-007
3. **Пагинация** — `?limit=1&offset=1` возвращает вторую запись — FR-007
4. **Перезапуск** — записи, созданные до пересоздания приложения, читаются после — SC-003/FR-002
5. **Нет операций** — 200 + `[]`
6. **404** — неизвестный `device_id`
7. **403** — пользователь без роли viewer на устройство
8. **401** — без заголовков идентификации
9. **Фильтр-мусор** — `?event_type=nonexistent` → 200 + `[]`
