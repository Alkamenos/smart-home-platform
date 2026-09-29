# Модель данных: Интеграция и конфигурирование устройств

**Дата**: 2026-09-29 | **Статус**: Phase 1 Design | **Базис**: [research.md](research.md)

---

## Основные сущности

### 1. HASource (Источник Home Assistant)

Конфигурация подключения к одному экземпляру Home Assistant.

```
HASource
├── id: UUID (primary key)
├── name: str (min 1, max 255) — название источника
├── url: str (valid HTTPS URL) — адрес HA инстанса
├── token: str (encrypted at-rest) — long-lived token HA
├── status: enum [connected, disconnected, error] — статус соединения
├── last_sync: datetime | null — время последней синхронизации
├── last_error: str | null — последняя ошибка (например "401 Unauthorized")
├── created_at: datetime
└── updated_at: datetime
```

**Constraints**:
- `url` must be valid HTTPS URL (http allowed for localhost testing)
- `token` automatically encrypted/decrypted by model (see `core/security/encryption.py`)
- One HASource can contain many Devices (1:N relationship)
- `name` unique within system (no duplicates)

**Validation rules**:
- URL format: regex `https?://[a-zA-Z0-9.-]+(:[0-9]+)?`
- Token length: 30+ characters
- Status transitions: connected → disconnected → error → connected (only)

---

### 2. Device (Устройство)

Физическое или виртуальное устройство в Home Assistant, синхронизированное в платформу.

```
Device
├── id: UUID (primary key платформы)
├── ha_entity_id: str — unique ID в HA (format: domain.entity_name)
├── ha_source_id: UUID (foreign key) — ссылка на HASource
├── device_name: str — название устройства в HA (неизменяемое)
├── device_type: str — тип устройства (light, switch, sensor, etc)
├── model: str | null — модель устройства
├── manufacturer: str | null — производитель
├── state: dict — текущее состояние (json attrs)
├── status: enum [available, unavailable, removed_from_ha]
├── config: DeviceConfig (1:1 relationship)
├── last_state_update: datetime — когда последнее обновление состояния
├── created_at: datetime
└── updated_at: datetime
```

**Constraints**:
- `ha_entity_id` + `ha_source_id` = unique key (устройство идентифицируется ha_entity_id внутри источника)
- `device_name` не редактируется (из HA); редактируется только `config.display_name`
- `status` transitions: available → unavailable → removed_from_ha (not reversible)

**Validation rules**:
- `ha_entity_id` format: `[a-z_]+\.[a-z0-9_]+`
- `device_type` must be known HA domain (light, switch, binary_sensor, etc)
- `state` is arbitrary dict from HA (no fixed schema)

---

### 3. DeviceConfig (Конфигурация устройства)

Пользовательские параметры и метаданные для Device.

```
DeviceConfig
├── id: UUID
├── device_id: UUID (foreign key) — 1:1 relationship
├── display_name: str (min 1, max 255) — пользовательское название
├── description: str (max 1000) | null
├── location: str (max 255) | null — комната/зона (Кухня, Гостиная)
├── tags: List[str] (max 10 tags, each max 50 chars)
├── notes: str (max 2000) | null — пользовательские заметки
├── enabled: bool = true — может ли пользователь использовать устройство
├── custom_settings: dict | null — расширяемые пользовательские параметры
├── created_by: UUID (user_id)
├── updated_by: UUID | null (user_id)
├── created_at: datetime
└── updated_at: datetime
```

**Constraints**:
- `display_name` must be unique within `ha_source_id` (не может быть двух устройств с одним именем в источнике)
- `tags` must be lowercase alphanumeric + dash (regex: `[a-z0-9-]+`)
- Если Device удалено из HA, DeviceConfig остается с `enabled: false`

**Validation rules**:
- display_name regex: `^[a-zA-Zа-яА-Я0-9\s\-.,()]*$`
- description HTML sanitize (remove scripts)
- location autocomplete по существующим значениям

---

### 4. DeviceCommand (Команда устройства)

Действие, которое можно выполнить на Device (управление).

```
DeviceCommand
├── id: UUID
├── device_id: UUID (foreign key) — Device может иметь много команд (1:N)
├── name: str (min 1, max 255) — display name (turn_on → "Включить")
├── ha_service: str (format: domain.service) — HA сервис для вызова
├── description: str | null
├── parameters: Dict[str, Parameter] — параметры команды
├── return_type: str | null — тип возвращаемого значения (if any)
├── execution_timeout: int (1-300 sec, default 30) — timeout выполнения
├── is_safe: bool = true — безопасно ли вызывать автоматически
└── created_at: datetime
```

**Parameter (вложенная структура)**:
```
Parameter
├── name: str
├── type: str (string, number, boolean, enum, array)
├── required: bool
├── allowed_values: List | null — для enum type
├── default: Any | null
└── description: str | null
```

**Examples**:
```
Light device commands:
- turn_on: light.turn_on (params: brightness, color_temp, effect)
- turn_off: light.turn_off (no params)
- toggle: light.toggle (no params)

Switch device commands:
- turn_on: switch.turn_on
- turn_off: switch.turn_off
```

**Constraints**:
- `name` unique within Device
- `ha_service` must match HA service registry
- `execution_timeout` must be 1-300 seconds

---

### 5. DeviceSyncEvent (События синхронизации)

Логирование всех операций с устройствами для audit trail.

```
DeviceSyncEvent
├── id: UUID
├── device_id: UUID (foreign key)
├── event_type: enum [loaded, config_changed, state_changed, command_sent, command_failed]
├── details: dict — event-specific data (see below)
├── user_id: UUID | null — who triggered (null if system event)
├── timestamp: datetime (UTC)
└── trace_id: str | null — для корреляции с логами
```

**Event-specific details**:

```
event_type: "loaded"
details: {
  "ha_entity_id": "light.kitchen",
  "device_type": "light",
  "state": {...}
}

event_type: "config_changed"
details: {
  "changes": {
    "display_name": ["Кухня", "Кухня свет"],
    "tags": [["old"], ["old", "priority"]]
  }
}

event_type: "state_changed"
details: {
  "old_state": {"state": "off"},
  "new_state": {"state": "on", "brightness": 255},
  "source": "ha"  # or "user"
}

event_type: "command_sent"
details: {
  "command_id": "uuid-xxx",
  "command_name": "turn_on",
  "parameters": {"brightness": 100},
  "service_call": "light.turn_on"
}

event_type: "command_failed"
details: {
  "command_id": "uuid-xxx",
  "error": "Service not found",
  "http_status": 404
}
```

**Constraints**:
- Events are immutable (no updates, only inserts)
- Retention: keep for 1 year (configurable)
- Query optimization: index on `device_id` + `timestamp`

---

## Отношения между сущностями

```
HASource (1)
    ↓
    → (1:N) → Device
                  ↓
                  → (1:1) → DeviceConfig
                  ↓
                  → (1:N) → DeviceCommand
                  ↓
                  → (1:N) → DeviceSyncEvent

DeviceAccess (для управления доступом, Phase 2):
    ↓
    → (N:1) → Device
    → (N:1) → User
    → property: role (viewer, controller, admin)
```

---

## Состояния и переходы

### Device Status State Machine
```
[available] ←→ [unavailable]
    ↓
[removed_from_ha]  (необратимо, сохраняется в истории)
```

- `available`: устройство доступно в HA и отвечает
- `unavailable`: не получали обновлений > 60 сек
- `removed_from_ha`: устройство удалено из HA источника (остается в системе для истории)

### HASource Status State Machine
```
[connected] ←→ [disconnected] ←→ [error]
                    ↓               ↓
                 (retry)         (retry)
```

- `connected`: WebSocket активен или REST API доступен
- `disconnected`: потеря соединения (retrying)
- `error`: ошибка аутентификации или авторизации (требует действия администратора)

---

## Сериализация для API

### JSON Schema для DeviceConfig
```json
{
  "id": "uuid-xxx",
  "display_name": "Кухня свет",
  "description": "Основное освещение кухни",
  "location": "Кухня",
  "tags": ["main", "kitchen"],
  "enabled": true
}
```

### JSON Schema для DeviceCommand
```json
{
  "id": "uuid-yyy",
  "name": "Включить",
  "ha_service": "light.turn_on",
  "parameters": {
    "brightness": {
      "type": "number",
      "required": false,
      "default": 255
    },
    "effect": {
      "type": "enum",
      "required": false,
      "allowed_values": ["none", "colorloop", "random"]
    }
  }
}
```

---

## Валидация

### На уровне Pydantic моделей

Все сущности используют Pydantic v2 для валидации:
- Type checking при создании/обновлении
- Custom validators для бизнес-логики
- Автоматическое преобразование типов где возможно

### На уровне приложения

- Уникальность constraints проверяются в слое персистентности
- Иностранные ключи проверяются перед вставкой
- Состояния проверяются перед переходами

---

## Следующие шаги

Эта модель данных используется для:
1. **Phase 1**: Создание contracts/ (REST API spec)
2. **Phase 1**: Создание quickstart.md (валидация сценарий)
3. **Phase 2**: tasks.md (реализация models и слоев персистентности)

