# REST API контракты: Интеграция устройств из Home Assistant

**Версия**: 1.0 | **Дата**: 2026-09-29 | **Статус**: Спецификация

## Обзор API

Все endpoints используют JSON для запросов и ответов. Аутентификация по токену JWT в заголовке `Authorization: Bearer {token}`.

### Базовый URL
```
/api/v1/devices
```

---

## Sources (Источники HA)

### POST /api/v1/devices/sources
**Создать новый источник Home Assistant**

**Права доступа**: admin

**Request**:
```json
{
  "name": "Home Assistant Pro",
  "url": "http://192.168.1.100:8123",
  "token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."
}
```

**Response (201)**:
```json
{
  "id": "uuid-1234",
  "name": "Home Assistant Pro",
  "url": "http://192.168.1.100:8123",
  "status": "connecting",
  "device_count": 0,
  "created_at": "2026-09-29T10:00:00Z",
  "updated_at": "2026-09-29T10:00:00Z"
}
```

**Ошибки**:
- 400: Invalid URL or token format
- 401: Unauthorized
- 409: Source with same name already exists

---

### GET /api/v1/devices/sources
**Получить список всех источников**

**Права доступа**: admin, user (видит только свои)

**Query параметры**:
- `status`: filter by status (connected, disconnected, error)
- `limit`: пагинация (default: 20, max: 100)
- `offset`: пагинация

**Response (200)**:
```json
{
  "total": 2,
  "items": [
    {
      "id": "uuid-1234",
      "name": "Home Assistant Pro",
      "url": "http://192.168.1.100:8123",
      "status": "connected",
      "device_count": 47,
      "last_sync": "2026-09-29T10:05:00Z",
      "created_at": "2026-09-29T10:00:00Z"
    }
  ]
}
```

---

### GET /api/v1/devices/sources/{id}
**Получить детальную информацию о источнике**

**Параметры**:
- `id`: UUID источника

**Response (200)**:
```json
{
  "id": "uuid-1234",
  "name": "Home Assistant Pro",
  "url": "http://192.168.1.100:8123",
  "status": "connected",
  "device_count": 47,
  "last_sync": "2026-09-29T10:05:00Z",
  "last_error": null,
  "created_at": "2026-09-29T10:00:00Z",
  "updated_at": "2026-09-29T10:00:00Z"
}
```

**Ошибки**:
- 404: Source not found
- 401: Unauthorized

---

### POST /api/v1/devices/sources/{id}/sync
**Запустить синхронизацию устройств из источника**

**Параметры**:
- `id`: UUID источника

**Request** (опциональный):
```json
{
  "force": true  // Переиндексировать все устройства
}
```

**Response (202)** - Асинхронная операция:
```json
{
  "sync_id": "sync-uuid-5678",
  "status": "started",
  "source_id": "uuid-1234",
  "started_at": "2026-09-29T10:10:00Z",
  "estimated_completion": "2026-09-29T10:11:00Z"
}
```

**Ошибки**:
- 404: Source not found
- 409: Sync already in progress for this source
- 503: Cannot connect to HA instance

---

### DELETE /api/v1/devices/sources/{id}
**Удалить источник и все связанные устройства**

**Параметры**:
- `id`: UUID источника

**Response (204)**: No content

**Ошибки**:
- 404: Source not found
- 409: Cannot delete source with active operations

---

## Devices (Устройства)

### GET /api/v1/devices
**Получить список устройств**

**Права доступа**: user (видит только доступные)

**Query параметры**:
- `source_id`: filter by source
- `device_type`: filter by type (light, switch, binary_sensor, etc.)
- `status`: filter by status (available, unavailable, removed_from_ha)
- `tags`: filter by tags (comma-separated)
- `location`: filter by location
- `limit`: пагинация (default: 20, max: 100)
- `offset`: пагинация
- `sort`: sort field (name, type, created_at) + direction (asc/desc)

**Response (200)**:
```json
{
  "total": 47,
  "items": [
    {
      "id": "device-uuid-1",
      "ha_entity_id": "light.kitchen_light",
      "name": "Kitchen Light",
      "device_type": "light",
      "model": "Philips Hue A19",
      "manufacturer": "Philips",
      "status": "available",
      "state": {
        "state": "on",
        "brightness": 200,
        "color_temp": 3500
      },
      "config": {
        "display_name": "Kitchen Light",
        "description": "Main light in kitchen",
        "location": "kitchen",
        "tags": ["lights", "automatable"],
        "enabled": true
      },
      "last_state_update": "2026-09-29T10:05:00Z",
      "created_at": "2026-09-29T10:00:00Z"
    }
  ]
}
```

---

### GET /api/v1/devices/{id}
**Получить подробную информацию об устройстве**

**Параметры**:
- `id`: UUID устройства

**Response (200)**:
```json
{
  "id": "device-uuid-1",
  "ha_entity_id": "light.kitchen_light",
  "name": "Kitchen Light",
  "device_type": "light",
  "model": "Philips Hue A19",
  "manufacturer": "Philips",
  "status": "available",
  "state": {
    "state": "on",
    "brightness": 200,
    "color_temp": 3500,
    "updated_at": "2026-09-29T10:05:00Z"
  },
  "config": {
    "id": "config-uuid-1",
    "display_name": "Kitchen Light",
    "description": "Main light in kitchen",
    "location": "kitchen",
    "tags": ["lights", "automatable"],
    "notes": "Installed in September 2026",
    "enabled": true,
    "created_by": "user-uuid-1",
    "updated_by": "user-uuid-2",
    "updated_at": "2026-09-29T10:03:00Z"
  },
  "commands": [
    {
      "id": "cmd-uuid-1",
      "name": "turn_on",
      "ha_service": "light.turn_on",
      "description": "Turn light on",
      "parameters": {},
      "is_safe": true
    },
    {
      "id": "cmd-uuid-2",
      "name": "set_brightness",
      "ha_service": "light.turn_on",
      "description": "Set light brightness",
      "parameters": {
        "brightness": {
          "type": "integer",
          "min": 0,
          "max": 255,
          "required": true
        }
      },
      "is_safe": true
    }
  ],
  "created_at": "2026-09-29T10:00:00Z",
  "updated_at": "2026-09-29T10:00:00Z"
}
```

---

### PUT /api/v1/devices/{id}/config
**Обновить конфигурацию устройства**

**Параметры**:
- `id`: UUID устройства

**Request**:
```json
{
  "display_name": "Kitchen Main Light",
  "description": "Primary light in kitchen for general lighting",
  "location": "kitchen",
  "tags": ["lights", "automatable", "main"],
  "notes": "Updated notes"
}
```

**Response (200)**:
```json
{
  "id": "device-uuid-1",
  "config": {
    "display_name": "Kitchen Main Light",
    "description": "Primary light in kitchen for general lighting",
    "location": "kitchen",
    "tags": ["lights", "automatable", "main"],
    "notes": "Updated notes",
    "enabled": true,
    "updated_by": "current-user-uuid",
    "updated_at": "2026-09-29T10:10:00Z"
  }
}
```

**Ошибки**:
- 404: Device not found
- 400: Invalid configuration
- 409: Another user is editing this device

---

### POST /api/v1/devices/{id}/command
**Отправить команду на устройство**

**Параметры**:
- `id`: UUID устройства

**Request**:
```json
{
  "command": "set_brightness",
  "parameters": {
    "brightness": 150
  }
}
```

**Response (202)** - Асинхронная операция:
```json
{
  "command_id": "cmd-exec-uuid",
  "device_id": "device-uuid-1",
  "command": "set_brightness",
  "status": "pending",
  "parameters": {"brightness": 150},
  "sent_at": "2026-09-29T10:10:00Z"
}
```

**Polling результата**:
```
GET /api/v1/devices/{id}/command/{command_id}

Response (200):
{
  "command_id": "cmd-exec-uuid",
  "status": "success",
  "executed_at": "2026-09-29T10:10:02Z",
  "duration_ms": 125
}
```

**Ошибки**:
- 404: Device or command not found
- 400: Invalid command or parameters
- 503: Device is unavailable
- 403: User doesn't have permission to control this device

---

### GET /api/v1/devices/{id}/events
**Получить историю операций с устройством**

**Параметры**:
- `id`: UUID устройства

**Query параметры**:
- `event_type`: filter by type (device_loaded, config_changed, state_changed, command_sent)
- `days`: последние N дней (default: 7, max: 90)
- `limit`: пагинация (default: 50, max: 500)
- `offset`: пагинация

**Response (200)**:
```json
{
  "total": 125,
  "items": [
    {
      "id": "event-uuid-1",
      "event_type": "config_changed",
      "details": {
        "changed_fields": ["display_name"],
        "old_value": {"display_name": "Kitchen Light"},
        "new_value": {"display_name": "Kitchen Main Light"}
      },
      "user_id": "user-uuid-1",
      "status": "success",
      "timestamp": "2026-09-29T10:10:00Z"
    },
    {
      "id": "event-uuid-2",
      "event_type": "state_changed",
      "details": {
        "old_state": {"state": "off"},
        "new_state": {"state": "on", "brightness": 200}
      },
      "status": "success",
      "timestamp": "2026-09-29T10:05:00Z"
    }
  ]
}
```

---

## WebSocket API (Синхронизация состояния)

**URL**: `ws://host:port/api/v1/ws/devices`

**Аутентификация**: Query параметр или заголовок: `?token=eyJhbGc...`

### Подписка на события

**Send**:
```json
{
  "action": "subscribe",
  "device_ids": ["device-uuid-1", "device-uuid-2"],
  "event_types": ["state_changed", "config_changed"]
}
```

**Response**:
```json
{
  "status": "subscribed",
  "subscribed_devices": 2,
  "subscribed_events": ["state_changed", "config_changed"]
}
```

### Получение событий

**Receive** (автоматически):
```json
{
  "type": "device_state_changed",
  "device_id": "device-uuid-1",
  "old_state": {"state": "off"},
  "new_state": {"state": "on", "brightness": 200},
  "timestamp": "2026-09-29T10:05:00Z"
}
```

```json
{
  "type": "device_config_changed",
  "device_id": "device-uuid-1",
  "changes": {"display_name": "Kitchen Main Light"},
  "timestamp": "2026-09-29T10:10:00Z"
}
```

---

## HTTP Status коды

| Код | Статус | Описание |
|-----|--------|---------|
| 200 | OK | Успешный запрос |
| 201 | Created | Ресурс создан |
| 202 | Accepted | Асинхронная операция принята |
| 204 | No Content | Успешно удалено/обновлено |
| 400 | Bad Request | Ошибка в параметрах |
| 401 | Unauthorized | Отсутствует/невалидный токен |
| 403 | Forbidden | Недостаточно прав доступа |
| 404 | Not Found | Ресурс не найден |
| 409 | Conflict | Конфликт (дублирование, состояние) |
| 503 | Service Unavailable | HA не доступна или операция в процессе |

---

**Версия**: 1.0 | **Статус**: Спецификация завершена | **Дата**: 2026-09-29
