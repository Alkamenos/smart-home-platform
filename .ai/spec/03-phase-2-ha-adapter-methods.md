# Фаза 2: HA Adapter - Методы получения данных

**Статус:** Draft  
**Приоритет:** High  
**Связанные спецификации:** 
- [01-device-import-overview.md](01-device-import-overview.md)
- [02-phase-1-extend-manifest-model.md](02-phase-1-extend-manifest-model.md)

---

## Цель

Добавить в `HAAdapter` методы для получения структурных данных из Home Assistant:
- Areas (зоны/комнаты)
- Devices (устройства)
- Entities (сущности)

Это основа для последующего импорта устройств в манифест.

---

## Архитектурные решения

### 2.1. Интерфейс HomeAssistantGateway

Создаем протокол для абстракции взаимодействия с HA API:

```python
from typing import Protocol, runtime_checkable
from dataclasses import dataclass
from datetime import datetime


@runtime_checkable
class HomeAssistantGateway(Protocol):
    """Interface for HA data retrieval."""

    async def get_areas(self) -> list[AreaInfo]:
        """Get all areas/zones from HA."""
        ...

    async def get_devices(self, area_id: str | None = None) -> list[DeviceInfo]:
        """Get devices, optionally filtered by area."""
        ...

    async def get_entities(self, device_id: str | None = None) -> list[EntityInfo]:
        """Get entities, optionally filtered by device."""
        ...

    async def get_entity_state(self, entity_id: str) -> EntityState:
        """Get current state of a specific entity."""
        ...
```

### 2.2. Модели данных

```python
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

@dataclass
class AreaInfo:
    """HA Area information."""
    id: str
    name: str
    floor_id: str | None = None
    labels: list[str] = field(default_factory=list)

@dataclass
class DeviceInfo:
    """HA Device information."""
    id: str
    name: str
    model: str | None = None
    manufacturer: str | None = None
    sw_version: str | None = None
    hw_version: str | None = None
    serial_number: str | None = None
    identifiers: list[tuple[str, str]] = field(default_factory=list)  # [(domain, id)]
    connections: list[tuple[str, str]] = field(default_factory=list)  # [(type, value)]
    area_id: str | None = None
    labels: list[str] = field(default_factory=list)
    created_at: datetime | None = None

@dataclass
class EntityInfo:
    """HA Entity information."""
    entity_id: str
    name: str | None = None
    platform: str  # e.g., 'light', 'switch'
    domain: str  # e.g., 'light', 'binary_sensor'
    device_id: str | None = None
    area_id: str | None = None
    labels: list[str] = field(default_factory=list)
    disabled_by: str | None = None  # 'user', 'integration', etc.
    hidden_by: str | None = None  # 'user', 'integration', etc.
    capabilities: dict[str, Any] = field(default_factory=dict)
    device_class: str | None = None
    unit_of_measurement: str | None = None
    state: str | None = None
    attributes: dict[str, Any] = field(default_factory=dict)

@dataclass
class EntityState:
    """Current state of an entity."""
    entity_id: str
    state: str
    attributes: dict[str, Any]
    last_changed: datetime
    last_updated: context: dict[str, Any]
```

### 2.3. Реализация через WebSocket API

HA предоставляет следующие WebSocket endpoints:

| Endpoint | Описание |
|----------|----------|
| `config/area/list` | Получить список областей |
| `config/device_registry/list` | Получить устройства |
| `config/entity_registry/list` | Получить сущности |
| `get_states` | Получить состояния всех сущностей |

Пример вызова:
```python
result = await ws_client.call_service(
    domain="config", service="device_registry/list", return_response=True
)
```

---

## План реализации

### Шаг 1: Создать модели данных
- Файл: `src/adapters/ha_models.py`
- Модели: `AreaInfo`, `DeviceInfo`, `EntityInfo`, `EntityState`

### Шаг 2: Добавить методы в SimpleHAWebSocketClient
- Файл: `src/adapters/ha_adapter.py`
- Методы:
  - `async def get_areas(self) -> list[dict]`
  - `async def get_devices(self) -> list[dict]`
  - `async def get_entities(self) -> list[dict]`
  - `async def get_entity_states(self) -> list[dict]`

### Шаг 3: Добавить методы в HAAdapter
- Обернуть низкоуровневые вызовы в типизированные методы
- Добавить кэширование результатов (опционально)
- Добавить логирование и обработку ошибок

### Шаг 4: Написать тесты
- Моки для WebSocket ответов
- Тесты на парсинг данных
- Тесты на обработку ошибок

---

## Пример использования

```python
from src.adapters.ha_adapter import HAAdapter

adapter = HAAdapter(
    mode="websocket", ws_url="ws://localhost:8123/api/websocket", token="YOUR_TOKEN"
)

await adapter.start()

# Получить все области
areas = await adapter.get_areas()
print(f"Found {len(areas)} areas")

# Получить устройства в области
devices = await adapter.get_devices(area_id="bedroom")
for device in devices:
    print(f"Device: {device.name} ({device.id})")

# Получить сущности устройства
entities = await adapter.get_entities(device_id=device.id)
for entity in entities:
    print(f"  Entity: {entity.entity_id} - {entity.state}")
```

---

## Критерии приемки

- [ ] Все 4 метода реализованы в `HAAdapter`
- [ ] Модели данных созданы и типизированы
- [ ] Тесты покрывают основные сценарии
- [ ] Обработка ошибок (таймауты, отключения)
- [ ] Логирование на всех уровнях
- [ ] Документация методов

---

## Риски и зависимости

### Риски
1. **Изменения в HA API** - WebSocket API может измениться в будущих версиях HA
   - Митигация: Абстракция через интерфейс + тесты на реальных данных
   
2. **Производительность** - Получение всех сущностей может быть медленным
   - Митигация: Кэширование, пагинация (если поддерживается)

3. **Разрешения токена** - Токен должен иметь доступ к registry
   - Митигация: Валидация токена при подключении

### Зависимости
- ✅ Фаза 1 завершена (модели расширены)
- ⏳ WebSocket клиент уже существует
- ⏳ Требуется для Фазы 3 (импорт устройств)

---

## Следующие шаги

После завершения Фазы 2:
1. Перейти к Фазе 3: Сервис импорта устройств
2. Реализовать маппинг HA → Smart Home Platform
3. Добавить CLI команду `import-devices`
