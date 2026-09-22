# Спецификация Фазы 1: Расширение модели данных

## 1. Цель

Расширить текущую модель манифеста для поддержки:
- Отслеживания происхождения устройств (origin)
- Внешних идентификаторов для идемпотентности (external_ids)
- Информации о синхронизации (sync_info)
- Возможностей устройств (capabilities)

---

## 2. Текущее состояние

### 2.1. Current: `src/core/models/manifest.py`

```python
class DeviceConfig(BaseModel):
    id: str
    type: str
    name: str = ""
    behaviors: list[BehaviorConfig] = Field(default_factory=list)


class RoomConfig(BaseModel):
    id: str
    name: str
    sensors: dict[str, str] = Field(default_factory=dict)
    devices: list[DeviceConfig] = Field(default_factory=list)


class Manifest(BaseModel):
    instance: InstanceConfig
    version: int = 1
    rooms: list[RoomConfig] = Field(default_factory=list)
    automation_rules: AutomationRules = Field(default_factory=AutomationRules)
    dashboard: Dashboard = Field(default_factory=Dashboard)
```

**Проблемы**:
- ❌ Нет поля `origin` для отслеживания источника устройства
- ❌ Нет поля `external_ids` для идемпотентности
- ❌ Нет поля `sync_info` для отслеживания статуса импорта
- ❌ Нет поля `capabilities` для описания возможностей
- ❌ Нет отдельной секции `areas` (комнаты определяются только в rooms)

---

## 3. Целевая модель

### 3.1. Расширенный `DeviceConfig`

```python
class DeviceConfig(BaseModel):
    # Basic fields (existing)
    id: str
    type: str
    name: str = ""
    behaviors: list[BehaviorConfig] = Field(default_factory=list)
    
    # NEW: Origin tracking
    origin: Literal["home_assistant", "manual", "imported"] = "manual"
    
    # NEW: External identifiers for idempotency
    external_ids: dict[str, str] = Field(default_factory=dict)
    # Example: {"homeAssistantDeviceId": "a1b2c3", "homeAssistantAreaId": "living_room"}
    
    # NEW: Source connection reference
    source_connection_id: str | None = None
    
    # NEW: Device metadata from HA
    manufacturer: str | None = None
    model: str | None = None
    software_version: str | None = None
    
    # NEW: Capabilities (replaces simple type)
    capabilities: list[CapabilityConfig] = Field(default_factory=list)
    
    # NEW: AI metadata
    ai_metadata: dict[str, Any] = Field(default_factory=dict)
    # Example: {"description": "Main light", "aliases": ["люстра", "свет"]}
    
    # NEW: Sync information
    sync_info: dict[str, Any] = Field(default_factory=dict)
    # Example: {"last_imported_at": "2026-01-15T10:30:00Z", "status": "ok"}
```

---

### 3.2. Новый `CapabilityConfig`

```python
class CapabilityConfig(BaseModel):
    """Device capability configuration."""

    id: str
    type: Literal[
        "light",
        "switch",
        "climate",
        "cover",
        "lock",
        "fan",
        "sensor",
        "binary_sensor",
        "media_player",
        "vacuum",
        "button",
        "scene",
        "generic",
    ]
    entity_ids: list[str] = Field(default_factory=list)
    home_assistant_domain: str | None = None
    device_class: str | None = None

    # Supported features
    supports: dict[str, bool | str | int | float] = Field(default_factory=dict)
    # Example: {"onOff": true, "brightness": true, "colorTemperature": false}

    # Additional metadata
    metadata: dict[str, Any] = Field(default_factory=dict)
```

---

### 3.3. Новый `AreaConfig` (опционально)

```python
class AreaConfig(BaseModel):
    """Area/room configuration with external IDs."""
    
    id: str
    name: str
    aliases: list[str] = Field(default_factory=list)
    
    # NEW: Origin tracking
    origin: Literal["home_assistant", "manual"] = "manual"
    
    # NEW: External identifiers
    external_ids: dict[str, str] = Field(default_factory=dict)
    # Example: {"homeAssistantAreaId": "living_room"}
    
    # NEW: Sync information
    sync_info: dict[str, Any] = Field(default_factory=dict)
```

---

### 3.4. Расширенный `Manifest`

```python
class Manifest(BaseModel):
    instance: InstanceConfig
    version: int = 1
    
    # NEW: Areas as separate section (optional)
    areas: list[AreaConfig] = Field(default_factory=list)
    
    rooms: list[RoomConfig] = Field(default_factory=list)
    automation_rules: AutomationRules = Field(default_factory=AutomationRules)
    dashboard: Dashboard = Field(default_factory=Dashboard)
    
    # NEW: Connections reference (for multi-HA support)
    connections: list[dict[str, Any]] = Field(default_factory=list)
    # Will be defined in Phase 3 (Connection Manager)
```

---

## 4. Правила миграции

### 4.1. Обратная совместимость

Все новые поля должны быть **опциональными** со значениями по умолчанию:
- `origin = "manual"` (для существующих устройств)
- `external_ids = {}` (пустой dict)
- `capabilities = []` (пустой list)
- `sync_info = {}` (пустой dict)

Это обеспечит:
- ✅ Загрузку старых манифестов без ошибок
- ✅ Постепенную миграцию устройств
- ✅ Возможность ручного добавления устройств без заполнения всех полей

---

### 4.2. Миграция существующих устройств

При загрузке старого манифеста:
1. Все устройства получают `origin="manual"` по умолчанию
2. Поле `type` сохраняется для обратной совместимости
3. Если нужно, создаётся простая capability на основе `type`:

```python
# Migration logic example
def migrate_device(old_device: dict) -> DeviceConfig:
    device = DeviceConfig(
        id=old_device["id"],
        type=old_device["type"],
        name=old_device.get("name", ""),
        behaviors=[...],
        origin="manual",  # Default
        external_ids={},
        capabilities=[],
    )
    
    # Create simple capability from type if needed
    if old_device["type"] in ["light", "switch", "climate"]:
        device.capabilities.append(
            CapabilityConfig(
                id=f"cap_{old_device['id']}",
                type=old_device["type"],
                entity_ids=[old_device["id"]],  # Assuming entity_id == device_id
                supports={},
            )
        )
    
    return device
```

---

## 5. Валидация

### 5.1. Обязательные поля

| Поле | Обязательно | Когда |
|------|-------------|-------|
| `id` | ✅ Да | Всегда |
| `type` | ✅ Да | Для обратной совместимости |
| `name` | ❌ Нет | Может быть пустым |
| `origin` | ❌ Нет | Default: `"manual"` |
| `external_ids` | ❌ Нет | Default: `{}` |
| `capabilities` | ❌ Нет | Default: `[]` |

### 5.2. Правила валидации

```python
@field_validator("external_ids")
@classmethod
def validate_external_ids(cls, v: dict[str, str]) -> dict[str, str]:
    """Ensure external IDs are non-empty strings."""
    for key, value in v.items():
        if not isinstance(key, str) or not key.strip():
            raise ValueError(f"External ID key must be non-empty string: {key}")
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"External ID value must be non-empty string: {key}={value}")
    return v


@field_validator("capabilities")
@classmethod
def validate_capabilities_unique(cls, v: list[CapabilityConfig]) -> list[CapabilityConfig]:
    """Ensure capability IDs are unique within a device."""
    seen_ids = set()
    for cap in v:
        if cap.id in seen_ids:
            raise ValueError(f"Duplicate capability ID: {cap.id}")
        seen_ids.add(cap.id)
    return v
```

---

## 6. Примеры YAML

### 6.1. Ручное устройство (старый формат, остаётся рабочим)

```yaml
rooms:
  - id: living_room
    name: Гостиная
    devices:
      - id: light.living_room_main
        type: light
        behaviors:
          - template: lighting
            priority: 10
```

### 6.2. Устройство из Home Assistant (новый формат)

```yaml
rooms:
  - id: living_room
    name: Гостиная
    devices:
      - id: device_ha_a1b2c3
        type: light
        name: Люстра
        origin: home_assistant
        source_connection_id: ha_main
        external_ids:
          homeAssistantDeviceId: a1b2c3
          homeAssistantAreaId: living_room
        manufacturer: IKEA
        model: LED1624G9
        software_version: "1.0"
        capabilities:
          - id: cap_light_main
            type: light
            entity_ids:
              - light.living_room_main
            home_assistant_domain: light
            supports:
              onOff: true
              brightness: true
              colorTemperature: true
              color: false
            metadata:
              friendly_name: "Люстра"
        ai_metadata:
          description: "Основной свет в гостиной"
          aliases: ["люстра", "свет", "лампа"]
          visibility: primary
          controllability: controllable
        sync_info:
          last_imported_at: "2026-01-15T10:30:00Z"
          status: ok
        behaviors:
          - template: lighting
            priority: 10
            params: {}
```

### 6.3. Комната с area (новый формат)

```yaml
areas:
  - id: living_room
    name: Гостиная
    origin: home_assistant
    external_ids:
      homeAssistantAreaId: living_room
    sync_info:
      last_imported_at: "2026-01-15T10:30:00Z"
      status: ok

rooms:
  - id: living_room
    name: Гостиная
    sensors:
      motion: binary_sensor.living_room_motion
      temperature: sensor.living_room_temperature
    devices:
      - id: device_ha_a1b2c3
        type: light
        # ... (как выше)
```

---

## 7. Изменения в Web UI моделях

### 7.1. Обновить `src/webui/models.py`

Синхронизировать модели с `src/core/models/manifest.py`:

```python
class CapabilityConfig(BaseModel):
    """Capability configuration matching core model."""

    id: str
    type: str
    entity_ids: list[str] = []
    home_assistant_domain: str | None = None
    device_class: str | None = None
    supports: dict[str, Any] = {}
    metadata: dict[str, Any] = {}


class DeviceConfig(BaseModel):
    """Device configuration matching core model."""

    id: str
    type: str
    name: str = ""
    behaviors: list[BehaviorConfig] = []
    origin: str = "manual"
    external_ids: dict[str, str] = {}
    source_connection_id: str | None = None
    manufacturer: str | None = None
    model: str | None = None
    software_version: str | None = None
    capabilities: list[CapabilityConfig] = []
    ai_metadata: dict[str, Any] = {}
    sync_info: dict[str, Any] = {}


class RoomConfig(BaseModel):
    """Room configuration matching core model."""

    id: str
    name: str
    sensors: dict[str, str] = {}
    devices: list[DeviceConfig] = []


class AreaConfig(BaseModel):
    """Area configuration (NEW)."""

    id: str
    name: str
    aliases: list[str] = []
    origin: str = "manual"
    external_ids: dict[str, str] = {}
    sync_info: dict[str, Any] = {}


class ManifestModel(BaseModel):
    """Main manifest model matching core model."""

    instance: InstanceConfig
    version: int = 1
    areas: list[AreaConfig] = []
    rooms: list[RoomConfig] = []
    automation_rules: AutomationRules = {}
    dashboard: DashboardConfig = {}
    connections: list[dict[str, Any]] = []

    model_config = {"extra": "allow"}
```

---

## 8. Тесты

### 8.1. Unit тесты для моделей

```python
# tests/test_manifest_models_extended.py


def test_device_config_backward_compatibility():
    """Old format should still work."""
    device = DeviceConfig(id="light.living_room", type="light", behaviors=[])
    assert device.origin == "manual"
    assert device.external_ids == {}
    assert device.capabilities == []


def test_device_config_with_external_ids():
    """New format with external IDs."""
    device = DeviceConfig(
        id="device_ha_a1b2c3",
        type="light",
        origin="home_assistant",
        external_ids={"homeAssistantDeviceId": "a1b2c3"},
        capabilities=[...],
    )
    assert device.origin == "home_assistant"
    assert device.external_ids["homeAssistantDeviceId"] == "a1b2c3"


def test_manifest_load_old_format():
    """Loading old manifest should work."""
    old_yaml = """
    instance:
      id: test_house
      name: Test House
    rooms:
      - id: living_room
        name: Living Room
        devices:
          - id: light.main
            type: light
    """
    manifest = Manifest.model_validate(yaml.safe_load(old_yaml))
    assert len(manifest.rooms) == 1
    assert manifest.rooms[0].devices[0].origin == "manual"
```

### 8.2. Integration тесты

```python
# tests/test_manifest_migration.py


def test_migrate_old_manifest_to_new_format():
    """Test migration of old manifest to new format."""
    # Load old manifest
    old_manifest = load_manifest("tests/fixtures/old_manifest.yaml")

    # Verify defaults applied
    for device in old_manifest.devices:
        assert device.origin == "manual"
        assert device.external_ids == {}

    # Save and reload
    temp_path = save_manifest(old_manifest)
    reloaded = load_manifest(temp_path)

    # Verify data preserved
    assert len(reloaded.rooms) == len(old_manifest.rooms)
    assert len(reloaded.devices) == len(old_manifest.devices)
```

---

## 9. Чеклист реализации

### 9.1. Core models (`src/core/models/manifest.py`)

- [ ] Добавить `CapabilityConfig` класс
- [ ] Расширить `DeviceConfig` новыми полями:
  - [ ] `origin: str = "manual"`
  - [ ] `external_ids: dict[str, str] = {}`
  - [ ] `source_connection_id: str | None = None`
  - [ ] `manufacturer: str | None = None`
  - [ ] `model: str | None = None`
  - [ ] `software_version: str | None = None`
  - [ ] `capabilities: list[CapabilityConfig] = []`
  - [ ] `ai_metadata: dict[str, Any] = {}`
  - [ ] `sync_info: dict[str, Any] = {}`
- [ ] Добавить `AreaConfig` класс (опционально)
- [ ] Расширить `Manifest` полем `areas`
- [ ] Добавить валидаторы для новых полей
- [ ] Написать unit-тесты

### 9.2. Web UI models (`src/webui/models.py`)

- [ ] Добавить `CapabilityConfig` класс
- [ ] Расширить `DeviceConfig` аналогично core модели
- [ ] Добавить `AreaConfig` класс
- [ ] Расширить `ManifestModel` полем `areas`
- [ ] Проверить сериализацию/десериализацию

### 9.3. Тесты

- [ ] Написать тесты на обратную совместимость
- [ ] Написать тесты на валидацию внешних ID
- [ ] Написать тесты на уникальность capability ID
- [ ] Написать integration тесты загрузки старых манифестов

### 9.4. Документация

- [ ] Обновить README с примерами нового формата
- [ ] Добавить миграционный гайд для пользователей
- [ ] Обновить примеры в `/examples/`

---

## 10. Риски

| Риск | Вероятность | Влияние | Митигация |
|------|-------------|---------|-----------|
| Ломается обратная совместимость | Низкая | Высокое | Тщательное тестирование старых манифестов |
 | Пользователи запутаются в новых полях | Средняя | Среднее | Хорошая документация, дефолтные значения |
| Сложность миграции существующих данных | Низкая | Низкое | Автоматическая миграция при загрузке |

---

## 11. Критерии приёмки

- [ ] Старые манифесты загружаются без ошибок
- [ ] Новые поля имеют корректные значения по умолчанию
- [ ] Валидация работает для всех новых полей
- [ ] Web UI отображает новые поля корректно
- [ ] Все тесты проходят (старые + новые)
- [ ] Документация обновлена

---

*Версия: 1.0*
*Статус: Готов к реализации*
*Приоритет: Высокий (база для остальных фаз)*
