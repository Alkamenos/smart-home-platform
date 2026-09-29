# Модель данных: Интеграция устройств из Home Assistant

**Дата**: 2026-09-29 | **Функция**: 001-device-integration | **Версия**: 1.0

## Обзор моделей данных

Функция использует следующие основные сущности для управления устройствами из Home Assistant:

---

## Сущность 1: HASource (Источник Home Assistant)

**Назначение**: Конфигурация подключения к экземпляру Home Assistant

**Поля**:

| Поле | Тип | Обязательное | Описание |
|------|-----|-------------|---------|
| `id` | UUID | ✅ | Уникальный идентификатор источника |
| `name` | str | ✅ | Отображаемое название источника (e.g., "Home Assistant Pro") |
| `url` | str | ✅ | URL для подключения к HA (e.g., "http://192.168.1.100:8123") |
| `token` | str | ✅ | Long-lived access token (шифруется при сохранении) |
| `status` | enum | ✅ | Статус соединения: `connected`, `disconnected`, `error` |
| `last_sync` | datetime | ❌ | Время последней успешной синхронизации |
| `last_error` | str | ❌ | Сообщение об ошибке последней попытки подключения |
| `device_count` | int | ❌ | Количество загруженных устройств из этого источника |
| `created_at` | datetime | ✅ | Время создания записи |
| `updated_at` | datetime | ✅ | Время последнего обновления |

**Валидация**:
- `name`: min_length=1, max_length=255
- `url`: должен быть валидный HTTP/HTTPS URL
- `token`: min_length=10 (токены HA обычно длинные)
- Уникальность: пара (url, name) должна быть уникальной

**Отношения**:
- 1 HASource → N Device (один источник содержит много устройств)
- 1 HASource → N SyncLog (история синхронизаций)

---

## Сущность 2: Device (Устройство)

**Назначение**: Представляет физическое или виртуальное устройство в Home Assistant

**Поля**:

| Поле | Тип | Обязательное | Описание |
|------|-----|-------------|---------|
| `id` | UUID | ✅ | Уникальный идентификатор устройства в платформе |
| `ha_entity_id` | str | ✅ | Идентификатор сущности в HA (e.g., "light.kitchen_light") |
| `source_id` | UUID | ✅ | Ссылка на HASource, из которого загружено устройство |
| `name` | str | ✅ | Исходное название устройства из HA |
| `device_type` | str | ✅ | Тип устройства (e.g., "light", "switch", "binary_sensor", "climate") |
| `model` | str | ❌ | Модель устройства (e.g., "Philips Hue A19") |
| `manufacturer` | str | ❌ | Производитель устройства (e.g., "Philips") |
| `state` | dict | ✅ | Текущее состояние (значение и атрибуты из HA) |
| `attributes` | dict | ❌ | Дополнительные атрибуты (brightness, color_temp, etc.) |
| `status` | enum | ✅ | Статус доступности: `available`, `unavailable`, `removed_from_ha` |
| `config` | DeviceConfig | ✅ | Конфигурация пользователя для устройства |
| `last_state_update` | datetime | ✅ | Время последнего обновления состояния |
| `created_at` | datetime | ✅ | Время добавления в платформу |
| `updated_at` | datetime | ✅ | Время последнего обновления записи |

**Валидация**:
- `ha_entity_id`: должен соответствовать формату `domain.object_id` (e.g., `light.kitchen`)
- `device_type`: должен быть из одобренного списка типов
- Уникальность: пара (source_id, ha_entity_id) должна быть уникальной
- `state`: должен содержать поле `state` или `value`

**Отношения**:
- N Device ← 1 HASource (много устройств от одного источника)
- 1 Device → 1 DeviceConfig (одна конфигурация на устройство)
- 1 Device → N DeviceCommand (устройство поддерживает несколько команд)
- 1 Device → N SyncEvent (логирование операций)

---

## Сущность 3: DeviceConfig (Конфигурация устройства)

**Назначение**: Пользовательские параметры конфигурации для устройства

**Поля**:

| Поле | Тип | Обязательное | Описание |
|------|-----|-------------|---------|
| `id` | UUID | ✅ | Уникальный идентификатор |
| `device_id` | UUID | ✅ | Ссылка на Device |
| `display_name` | str | ✅ | Пользовательское название (может отличаться от HA) |
| `description` | str | ❌ | Описание устройства и его назначения |
| `location` | str | ❌ | Расположение (e.g., "kitchen", "bedroom") |
| `tags` | list[str] | ❌ | Пользовательские теги для группировки (e.g., ["lights", "automatable"]) |
| `notes` | str | ❌ | Дополнительные заметки администратора |
| `enabled` | bool | ✅ | Включено ли устройство для использования (default: true) |
| `custom_settings` | dict | ❌ | Дополнительные пользовательские параметры |
| `created_by` | UUID | ❌ | ID пользователя, создавшего конфигурацию |
| `updated_by` | UUID | ❌ | ID пользователя, последним обновившего конфигурацию |
| `created_at` | datetime | ✅ | Время создания конфигурации |
| `updated_at` | datetime | ✅ | Время последнего обновления |

**Валидация**:
- `display_name`: min_length=1, max_length=255
- `display_name`: должна быть уникальной в пределах одного источника
- `tags`: каждый тег min_length=1, max_length=50
- `tags`: макс 10 тегов

**Отношения**:
- 1 DeviceConfig ← 1 Device

---

## Сущность 4: DeviceCommand (Команда устройства)

**Назначение**: Описание команды, которую может выполнить устройство

**Поля**:

| Поле | Тип | Обязательное | Описание |
|------|-----|-------------|---------|
| `id` | UUID | ✅ | Уникальный идентификатор команды |
| `device_id` | UUID | ✅ | Ссылка на Device |
| `name` | str | ✅ | Название команды (e.g., "turn_on", "set_brightness") |
| `ha_service` | str | ✅ | Сервис HA для выполнения (e.g., "light.turn_on") |
| `description` | str | ❌ | Описание что делает команда |
| `parameters` | dict[str, Parameter] | ❌ | Параметры команды с типами и ограничениями |
| `return_type` | str | ❌ | Тип результата (void, boolean, dict) |
| `execution_timeout` | int | ❌ | Таймаут выполнения в секундах (default: 30) |
| `is_safe` | bool | ✅ | Безопасна ли команда (может ли вызвать проблемы) |

**Пример структуры**:
```json
{
  "id": "...",
  "device_id": "...",
  "name": "set_brightness",
  "ha_service": "light.turn_on",
  "description": "Set light brightness to specific level",
  "parameters": {
    "brightness": {
      "type": "integer",
      "min": 0,
      "max": 255,
      "required": true,
      "description": "Brightness level (0-255)"
    }
  },
  "is_safe": true
}
```

**Валидация**:
- `ha_service`: должен соответствовать формату `domain.service`
- `parameters`: каждый параметр должен иметь тип и описание
- Уникальность: пара (device_id, name) должна быть уникальной

**Отношения**:
- N DeviceCommand ← 1 Device

---

## Сущность 5: SyncEvent (События синхронизации)

**Назначение**: Логирование всех операций с устройствами для аудита и отладки

**Поля**:

| Поле | Тип | Обязательное | Описание |
|------|-----|-------------|---------|
| `id` | UUID | ✅ | Уникальный идентификатор события |
| `device_id` | UUID | ✅ | Ссылка на Device |
| `source_id` | UUID | ❌ | Ссылка на HASource (для событий синхронизации источника) |
| `event_type` | enum | ✅ | Тип события: `device_loaded`, `device_removed`, `config_changed`, `state_changed`, `command_sent`, `sync_started`, `sync_completed`, `sync_failed` |
| `details` | dict | ❌ | Подробности события (что именно изменилось) |
| `user_id` | UUID | ❌ | ID пользователя если действие инициировано пользователем |
| `status` | enum | ❌ | Статус события: `pending`, `success`, `failed`, `partial` |
| `error_message` | str | ❌ | Сообщение об ошибке если статус failed |
| `timestamp` | datetime | ✅ | Время события |

**Примеры деталей**:
```json
{
  "event_type": "config_changed",
  "details": {
    "old_value": {"display_name": "Light 1"},
    "new_value": {"display_name": "Kitchen Light"},
    "changed_fields": ["display_name"]
  }
}

{
  "event_type": "state_changed",
  "details": {
    "old_state": {"state": "off"},
    "new_state": {"state": "on", "brightness": 128}
  }
}
```

**Валидация**:
- `event_type`: только из допустимого списка
- `details`: должны быть валидным JSON

**Отношения**:
- N SyncEvent ← 1 Device
- N SyncEvent ← 1 HASource

---

## Переходы состояния

### Device State Transitions

```
[available] ---(sync, not in HA)---> [removed_from_ha]
[available] ---(connection lost)----> [unavailable]
[unavailable] ---(connection restored)---> [available]
[removed_from_ha] ---(readded to HA)---> [available]
```

**Правила**:
- Устройство считается `available` если оно существует в текущей синхронизации HA
- Устройство становится `unavailable` если последнее обновление состояния старше 60 секунд
- Устройство становится `removed_from_ha` если оно не найдено при синхронизации, но остается в БД

### HASource Connection State Transitions

```
[disconnected] ---(connect attempt)---> [connected]
[connected] ---(connection lost)-------> [disconnected]
[connected] ---(error)-----------------> [error]
[error] ---(retry with backoff)--------> [connected]
```

---

## Отношения между сущностями

```
HASource
├── id: UUID (PK)
└── 1 ↔ N
    └── Device
        ├── id: UUID (PK)
        ├── source_id: UUID (FK)
        ├── 1 ↔ 1
        │   └── DeviceConfig
        │       ├── id: UUID (PK)
        │       └── device_id: UUID (FK)
        ├── 1 ↔ N
        │   └── DeviceCommand
        │       ├── id: UUID (PK)
        │       └── device_id: UUID (FK)
        └── 1 ↔ N
            └── SyncEvent
                ├── id: UUID (PK)
                └── device_id: UUID (FK)

HASource
├── id: UUID (PK)
└── 1 ↔ N
    └── SyncEvent
        ├── id: UUID (PK)
        └── source_id: UUID (FK)
```

---

## Правила валидации

### На уровне сущностей

1. **HASource**:
   - URL должен быть валидный и доступный при сохранении (проверка соединения)
   - Token не должен быть пустым или содержать пробелы
   - Name должна быть уникальной в системе

2. **Device**:
   - ha_entity_id должен быть уникальным для каждого источника
   - device_type должен быть из разрешенного списка
   - Если status=removed_from_ha, то last_state_update >= (now - 24 часов)

3. **DeviceConfig**:
   - display_name не может совпадать с другим устройством в том же источнике
   - Если enabled=false, то config.tags должны содержать "disabled"

4. **DeviceCommand**:
   - ha_service должен соответствовать формату domain.service
   - execution_timeout должен быть > 0 и <= 300 (макс 5 минут)

5. **SyncEvent**:
   - Если event_type=sync_failed, то status должен быть failed и error_message заполнен
   - details должны быть JSON-валидными

### На уровне консистентности данных

1. Удаление HASource должно каскадно удалить все Device этого источника
2. Изменение Device.status в removed_from_ha не должно удалять config и commands
3. Каждая изменение Device или DeviceConfig должно создать SyncEvent
4. Все timestamp поля должны быть UTC и соответствовать логическому порядку

---

## Персистентность

**Механизм**: JSON-based persistence через существующий механизм проекта в `src/core/persistence/`

**Сохранение**:
```python
# Все сущности сохраняются как JSON в data/
data/
├── sources.json         # Все HASource
├── devices.json         # Все Device с embedded DeviceConfig
├── commands.json        # Все DeviceCommand
└── events.json          # Все SyncEvent (архив)
```

**Шифрование**:
- Токены в HASource.token шифруются перед сохранением в JSON
- Другие поля сохраняются в открытом виде

**Восстановление**:
- При загрузке приложения все JSON файлы десериализуются обратно в Pydantic модели
- Дешифрование токенов происходит при загрузке HASource

---

**Версия**: 1.0 | **Статус**: Завершено | **Дата**: 2026-09-29
