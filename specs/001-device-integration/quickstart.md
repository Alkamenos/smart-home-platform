# Quickstart: Валидация интеграции устройств из Home Assistant

**Версия**: 1.0 | **Дата**: 2026-09-29 | **Статус**: Руководство валидации

## Обзор

Этот документ содержит пошаговые сценарии для валидации функции интеграции устройств из Home Assistant. Используйте его для проверки корректности реализации.

---

## Сценарий 1: Базовая интеграция и загрузка устройств

**Цель**: Проверить возможность подключения к HA и загрузки устройств

**Предусловия**:
- Home Assistant работает и доступен по адресу `http://192.168.1.100:8123`
- Имеется long-lived access token для HA (создан в HA Settings → Developers Tools)
- Платформа запущена и доступна

**Шаги**:

### Шаг 1.1: Добавить источник Home Assistant

```bash
curl -X POST http://localhost:8000/api/v1/devices/sources \
  -H "Authorization: Bearer {your-token}" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Home Assistant Test",
    "url": "http://192.168.1.100:8123",
    "token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."
  }'
```

**Ожидаемый результат**:
- HTTP 201 Created
- Response содержит `id` источника
- Status = "connecting" (переходит в "connected" в течение 5 сек)

```json
{
  "id": "9f1f5c3d-4e2b-11eb-ae93-0242ac120002",
  "name": "Home Assistant Test",
  "status": "connecting",
  "device_count": 0,
  "created_at": "2026-09-29T10:00:00Z"
}
```

### Шаг 1.2: Проверить статус подключения

```bash
curl http://localhost:8000/api/v1/devices/sources/9f1f5c3d-4e2b-11eb-ae93-0242ac120002 \
  -H "Authorization: Bearer {your-token}"
```

**Ожидаемый результат**:
- Status = "connected"
- last_sync = текущее время (или null если еще не синхронизировано)

### Шаг 1.3: Запустить синхронизацию устройств

```bash
curl -X POST http://localhost:8000/api/v1/devices/sources/9f1f5c3d-4e2b-11eb-ae93-0242ac120002/sync \
  -H "Authorization: Bearer {your-token}" \
  -H "Content-Type: application/json" \
  -d '{"force": false}'
```

**Ожидаемый результат**:
- HTTP 202 Accepted
- Response содержит `sync_id` и статус "started"
- Синхронизация происходит асинхронно

```json
{
  "sync_id": "sync-9f1f5c3d-4e2b-11eb-ae93-0242ac120002",
  "status": "started",
  "source_id": "9f1f5c3d-4e2b-11eb-ae93-0242ac120002",
  "started_at": "2026-09-29T10:00:05Z"
}
```

### Шаг 1.4: Получить список загруженных устройств

Подождать 30 сек, затем:

```bash
curl http://localhost:8000/api/v1/devices \
  -H "Authorization: Bearer {your-token}"
```

**Ожидаемый результат**:
- HTTP 200 OK
- Response содержит список всех загруженных устройств
- Каждое устройство имеет `ha_entity_id`, `name`, `device_type`, `status`
- Количество устройств должно соответствовать количеству сущностей в HA

```json
{
  "total": 47,
  "items": [
    {
      "id": "device-uuid-1",
      "ha_entity_id": "light.kitchen_light",
      "name": "Kitchen Light",
      "device_type": "light",
      "status": "available",
      "created_at": "2026-09-29T10:00:10Z"
    },
    {
      "id": "device-uuid-2",
      "ha_entity_id": "switch.kitchen_outlet",
      "name": "Kitchen Outlet",
      "device_type": "switch",
      "status": "available",
      "created_at": "2026-09-29T10:00:10Z"
    }
  ]
}
```

**Проверки**:
- ✅ Все 47 сущностей из HA загружены (или другое корректное число)
- ✅ У каждого устройства правильный `ha_entity_id` и `device_type`
- ✅ Статус всех доступных устройств = "available"
- ✅ Синхронизация завершена менее чем за 1 минуту

---

## Сценарий 2: Конфигурирование параметров устройства

**Цель**: Проверить возможность редактирования параметров устройства

**Предусловия**:
- Устройства загружены (Сценарий 1 завершен)
- Имеется UUID какого-то устройства (например, device-uuid-1)

**Шаги**:

### Шаг 2.1: Получить текущую конфигурацию устройства

```bash
curl http://localhost:8000/api/v1/devices/device-uuid-1 \
  -H "Authorization: Bearer {your-token}"
```

**Ожидаемый результат**:
- HTTP 200 OK
- Response содержит полную информацию об устройстве
- Поле `config` содержит текущую конфигурацию

```json
{
  "id": "device-uuid-1",
  "ha_entity_id": "light.kitchen_light",
  "name": "Kitchen Light",
  "config": {
    "display_name": "Kitchen Light",
    "description": "",
    "location": "",
    "tags": [],
    "enabled": true
  }
}
```

### Шаг 2.2: Обновить конфигурацию устройства

```bash
curl -X PUT http://localhost:8000/api/v1/devices/device-uuid-1/config \
  -H "Authorization: Bearer {your-token}" \
  -H "Content-Type: application/json" \
  -d '{
    "display_name": "Kitchen Main Light",
    "description": "Primary light for general kitchen lighting",
    "location": "kitchen",
    "tags": ["lights", "automatable", "main"]
  }'
```

**Ожидаемый результат**:
- HTTP 200 OK
- Response содержит обновленную конфигурацию
- Поле `updated_at` обновлено

```json
{
  "id": "device-uuid-1",
  "config": {
    "display_name": "Kitchen Main Light",
    "description": "Primary light for general kitchen lighting",
    "location": "kitchen",
    "tags": ["lights", "automatable", "main"],
    "enabled": true,
    "updated_at": "2026-09-29T10:05:00Z"
  }
}
```

### Шаг 2.3: Проверить сохранение конфигурации

Перезагрузить приложение, затем:

```bash
curl http://localhost:8000/api/v1/devices/device-uuid-1 \
  -H "Authorization: Bearer {your-token}"
```

**Ожидаемый результат**:
- HTTP 200 OK
- Конфигурация сохранилась и осталась после перезагрузки
- `display_name` = "Kitchen Main Light"
- `tags` = ["lights", "automatable", "main"]

**Проверки**:
- ✅ Конфигурация обновилась успешно
- ✅ Все поля (display_name, description, location, tags) сохранились
- ✅ Конфигурация сохранилась после перезагрузки

---

## Сценарий 3: Синхронизация состояния в реальном времени

**Цель**: Проверить WebSocket синхронизацию состояния устройств

**Предусловия**:
- Устройства загружены (Сценарий 1)
- Имеется device-uuid-1 (light)
- WebSocket соединение поддерживается

**Шаги**:

### Шаг 3.1: Открыть WebSocket соединение и подписаться

```bash
# Использовать websocat или другой WebSocket клиент
websocat "ws://localhost:8000/api/v1/ws/devices?token={your-token}"

# Отправить команду подписки
{
  "action": "subscribe",
  "device_ids": ["device-uuid-1"],
  "event_types": ["state_changed"]
}
```

**Ожидаемый результат**:
- WebSocket соединение установлено
- Получен ответ:
```json
{
  "status": "subscribed",
  "subscribed_devices": 1,
  "subscribed_events": ["state_changed"]
}
```

### Шаг 3.2: Изменить состояние устройства в Home Assistant

Используя интерфейс HA или командой:
```bash
# Включить свет в HA
curl -X POST http://192.168.1.100:8123/api/services/light/turn_on \
  -H "Authorization: Bearer {ha-token}" \
  -H "Content-Type: application/json" \
  -d '{"entity_id": "light.kitchen_light", "brightness": 150}'
```

### Шаг 3.3: Проверить получение события состояния

**Ожидаемый результат**:
- В WebSocket соединении получено событие:
```json
{
  "type": "device_state_changed",
  "device_id": "device-uuid-1",
  "old_state": {"state": "off"},
  "new_state": {"state": "on", "brightness": 150},
  "timestamp": "2026-09-29T10:10:00Z"
}
```

- Время задержки между изменением в HA и получением события **<= 5 секунд**

### Шаг 3.4: Проверить обновление в REST API

```bash
curl http://localhost:8000/api/v1/devices/device-uuid-1 \
  -H "Authorization: Bearer {your-token}"
```

**Ожидаемый результат**:
- Поле `state` обновлено: `{"state": "on", "brightness": 150}`
- `last_state_update` = текущее время (или близко к нему)

**Проверки**:
- ✅ WebSocket событие получено
- ✅ Задержка синхронизации <= 5 сек
- ✅ Состояние обновилось в REST API
- ✅ Соединение остается активным

---

## Сценарий 4: Отправка команд на устройство

**Цель**: Проверить возможность отправки команд и выполнение их в HA

**Предусловия**:
- Устройство device-uuid-1 загружено и доступно

**Шаги**:

### Шаг 4.1: Получить список команд для устройства

```bash
curl http://localhost:8000/api/v1/devices/device-uuid-1 \
  -H "Authorization: Bearer {your-token}"
```

**Ожидаемый результат**:
- В response содержится поле `commands`:
```json
{
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
  ]
}
```

### Шаг 4.2: Отправить команду на устройство

```bash
curl -X POST http://localhost:8000/api/v1/devices/device-uuid-1/command \
  -H "Authorization: Bearer {your-token}" \
  -H "Content-Type: application/json" \
  -d '{
    "command": "set_brightness",
    "parameters": {"brightness": 200}
  }'
```

**Ожидаемый результат**:
- HTTP 202 Accepted
- Response содержит command_id

```json
{
  "command_id": "cmd-exec-uuid",
  "device_id": "device-uuid-1",
  "command": "set_brightness",
  "status": "pending",
  "parameters": {"brightness": 200},
  "sent_at": "2026-09-29T10:15:00Z"
}
```

### Шаг 4.3: Проверить статус выполнения команды

```bash
curl http://localhost:8000/api/v1/devices/device-uuid-1/command/cmd-exec-uuid \
  -H "Authorization: Bearer {your-token}"
```

**Ожидаемый результат**:
- Статус изменился на "success" (или "failed" если ошибка)
- Время выполнения указано

```json
{
  "command_id": "cmd-exec-uuid",
  "status": "success",
  "executed_at": "2026-09-29T10:15:02Z",
  "duration_ms": 125
}
```

### Шаг 4.4: Проверить эффект команды в HA

Проверить в интерфейсе Home Assistant или через API:

```bash
curl http://192.168.1.100:8123/api/states/light.kitchen_light \
  -H "Authorization: Bearer {ha-token}"
```

**Ожидаемый результат**:
- Состояние света в HA изменилось: яркость = 200
- Команда выполнена успешно

**Проверки**:
- ✅ Команда отправлена (status = success)
- ✅ Команда выполнилась в HA (состояние изменилось)
- ✅ Время выполнения < 1 сек
- ✅ WebSocket событие получено об изменении состояния

---

## Сценарий 5: Обработка ошибок и сбои соединения

**Цель**: Проверить корректную обработку ошибок и восстановление

**Предусловия**:
- Система работает с загруженными устройствами

**Шаги**:

### Шаг 5.1: Проверить восстановление при недоступности HA

Отключить/заблокировать доступ к HA:

```bash
# Например, изменить URL источника на невалидный
curl -X PUT http://localhost:8000/api/v1/devices/sources/source-uuid/config \
  -H "Authorization: Bearer {your-token}" \
  -H "Content-Type: application/json" \
  -d '{"url": "http://invalid-host:8123"}'
```

**Ожидаемый результат**:
- Через 30-60 сек статус источника изменяется на "error"
- Система пытается переподключиться с exponential backoff
- Устройства остаются в статусе "unavailable", но система не падает

```bash
curl http://localhost:8000/api/v1/devices/sources/source-uuid \
  -H "Authorization: Bearer {your-token}"
```

Response:
```json
{
  "id": "source-uuid",
  "status": "error",
  "last_error": "Failed to connect: [Errno -2] Name or service not known"
}
```

### Шаг 5.2: Восстановление соединения

Восстановить доступ к HA и дождаться автоматического переподключения:

```bash
# Через 1-2 минуты статус должен измениться на connected
curl http://localhost:8000/api/v1/devices/sources/source-uuid \
  -H "Authorization: Bearer {your-token}"
```

**Ожидаемый результат**:
- Status = "connected"
- Синхронизация происходит автоматически
- Устройства возвращают статус "available"
- Нет потери данных или корупции

**Проверки**:
- ✅ Ошибка соединения обработана корректно
- ✅ Система автоматически восстанавливает соединение
- ✅ Нет потери данных
- ✅ Пользователи информированы об ошибке

---

## Сценарий 6: История операций и логирование

**Цель**: Проверить корректность логирования и истории операций

**Шаги**:

### Шаг 6.1: Получить историю операций устройства

```bash
curl "http://localhost:8000/api/v1/devices/device-uuid-1/events?days=1&limit=50" \
  -H "Authorization: Bearer {your-token}"
```

**Ожидаемый результат**:
- HTTP 200 OK
- Response содержит список событий:

```json
{
  "total": 15,
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
      "timestamp": "2026-09-29T10:05:00Z"
    },
    {
      "id": "event-uuid-2",
      "event_type": "state_changed",
      "details": {
        "old_state": {"state": "off"},
        "new_state": {"state": "on", "brightness": 200}
      },
      "status": "success",
      "timestamp": "2026-09-29T10:10:00Z"
    }
  ]
}
```

**Проверки**:
- ✅ История содержит все операции
- ✅ Каждое событие имеет тип, детали и timestamp
- ✅ Информация о пользователе сохранена для user-initiated операций
- ✅ Система-инициированные события (state_changed) не имеют user_id

---

## Итоговая проверка

После прохождения всех сценариев убедитесь, что:

- ✅ [Сценарий 1] Загрузка устройств работает
- ✅ [Сценарий 2] Конфигурирование сохраняется
- ✅ [Сценарий 3] WebSocket синхронизация работает (<=5 сек задержка)
- ✅ [Сценарий 4] Команды отправляются и выполняются
- ✅ [Сценарий 5] Ошибки обрабатываются корректно
- ✅ [Сценарий 6] История логируется полностью

Если все проверки пройдены, функция готова к использованию.

---

**Версия**: 1.0 | **Статус**: Руководство завершено | **Дата**: 2026-09-29
