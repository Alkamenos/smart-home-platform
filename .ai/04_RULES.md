# Rules for AI

Эти правила обязательны. Нарушение любого правила требует явного согласования с пользователем.

## Запрещенные файлы

**НЕ ТРОГАТЬ без явного разрешения:**

| Файл/Директория | Причина | Исключение |
|----------------|---------|------------|
| `.gitignore` | Управляется вручную | Никогда |
| `pyproject.toml` | Только добавление зависимостей | По запросу |
| `Makefile` | Только добавление targets | По запросу |
| `docker-compose.*.yml` | Инфраструктура | Никогда |
| `*.lock` | Генерируется автоматически | Никогда |
| `tests/fixtures/` | Тестовые данные | Никогда |
| `core/fsm.py` | Ядро платформы | Только по согласованию |

## Обязательные требования к коду

### Type Hints

**Хорошо:**
```python
def get_mapping_for_sensor(self, sensor_id: str) -> list[tuple[str, str]]:
    """Get FSM mappings for a sensor."""
    return list(self._sensor_to_fsms.get(sensor_id, []))
```

**Плохо:**
```python
def get_mapping_for_sensor(self, sensor_id):
    return self._sensor_to_fsms.get(sensor_id, [])
```

**Правила:**
- Все функции имеют type hints для аргументов и возвращаемого значения
- Использовать `from __future__ import annotations` в каждом файле
- Избегать `Any` — использовать конкретные типы или `TypeVar`

### Docstrings

**Хорошо:**
```python
def route_state_change(
    self,
    entity_id: str,
    new_state: str,
    old_state: str,
    context: Optional[Dict[str, Any]] = None,
) -> None:
    """
    Route a state change event to all registered FSMs.

    Looks up the entity_id in the sensor-to-FSM mapping and triggers
    appropriate events on each matching FSM.

    Args:
        entity_id: The entity entity ID that changed state.
        new_state: The new state value (e.g., "on", "off").
        old_state: The previous state value.
        context: Optional context dictionary to pass to the FSM trigger.
    """
```

**Плохо:**
```python
def route_state_change(self, entity_id, new_state, old_state, context=None):
    # Route the event
    pass
```

**Правила:**
- Все публичные функции (не начинающиеся с `_`) имеют docstring
- Формат: Google style
- Минимум: описание, Args, Returns

### Длина функций

**Максимум:** 50 строк (без учета docstring и комментариев)

**Хорошо:**
```python
async def route_state_change(self, entity_id: str, ...) -> None:
    """Route a state change event."""
    mappings = self._get_mappings(entity_id)
    if not mappings:
        logger.debug(f"No mappings for {entity_id}")
        return
    await self._trigger_all(mappings, entity_id, ...)

def _get_mappings(self, entity_id: str) -> list:
    return self._sensor_to_fsms.get(entity_id, [])
```

**Плохо:** Одна функция на 80 строк с вложенной логикой

### Обработка ошибок

**Хорошо:**
```python
try:
    result = await adapter.call_service(domain, service, entity_id)
except ConnectionError as e:
    logger.error(f"Failed to call service {service}: {e}")
    return False
```

**Плохо:**
```python
try:
    result = await adapter.call_service(domain, service, entity_id)
except:
    pass
```

**Правила:**
- Всегда логировать исключения через `loguru`
- Не использовать bare `except:` — указывать конкретные исключения
- Для ожидаемых ошибок использовать custom exceptions

## Архитектурные ограничения

### Слои архитектуры

```
┌─────────────────┐
│   CLI / Main    │  ← Может импортировать всё
├─────────────────┤
│    Adapters     │  ← НЕ импортирует core
├─────────────────┤
│      Core       │  ← НЕ импортирует adapters
└─────────────────┘
```

**Правила:**
- `core/` НЕ должен импортировать `adapters/`
- `adapters/` НЕ должен импортировать `services/`
- Бизнес-логика только в `core/`

### FSM Engine

**Не изменять без обсуждения:**
- Структуру `FSMDefinition` (frozen dataclass)
- Логику debounce
- Механизм таймаутов
- Схему именования `{device}_{template}_{priority}`

### Манифест

- Все изменения схемы манифеста требуют обновления Pydantic моделей
- Увеличивать `version` в манифесте при breaking changes
- Писать миграции для обратной совместимости

## Тестирование

### Покрытие

| Тип кода | Минимальное покрытие |
|----------|---------------------|
| Новые файлы | 80% |
| Критические модули (dispatcher, router) | 95% |
| Action handlers | 100% |

### Типы тестов

| Тип | Назначение | Пример |
|-----|-----------|--------|
| Unit | Изолированные, моки всех зависимостей | `test_dispatcher.py` |
| Integration | Взаимодействие модулей | `test_event_router.py` |
| E2E | Полные сценарии | `test_composition_scenario.py` |

### Именование тестов

**Формат:** `test_<что>_should_<поведение>_when_<условие>`

**Хорошо:**
```python
def test_dispatcher_should_reject_low_priority_when_high_priority_active(): ...


def test_event_router_should_route_motion_detected_when_state_is_on(): ...
```

**Плохо:**
```python
def test_dispatcher(): ...


def test_router_1(): ...
```

## Коммиты

### Формат сообщения

```
<type>(<scope>): <description>

[optional body]

[optional footer]
```

**Types:** `feat`, `fix`, `refactor`, `test`, `docs`, `chore`
**Scope:** `core`, `adapters`, `manifest`, `cli`, `tests`, `docs`

**Хорошо:**
```
feat(core): Add EventRouter for sensor-to-FSM mapping

- Build sensor-to-FSM mapping from manifest
- Route motion_detected/motion_cleared events
- Add comprehensive unit tests

Closes #42
```

**Плохо:**
```
fix bug
update code
```

### Размер коммита

- Один коммит = одна логическая задача
- Не смешивать рефакторинг и новые фичи
- Максимум 500 строк изменений (без тестов)

## Стиль кода

### Импорты

**Хорошо:**
```python
from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from loguru import logger
from pydantic import BaseModel, Field

from .command_dispatcher import CommandIntent
from .fsm import FSMDefinition, FSMEngine
```

**Плохо:**
```python
import asyncio, uuid
from typing import *
from core.command_dispatcher import *
```

### Константы

**Хорошо:**
```python
MANUAL_SOURCES = {"manual", "user", "home_assistant", "voice"}
DEFAULT_PRIORITY = 10
```

**Плохо:**
```python
if source in {"manual", "user", "home_assistant", "voice"}:  # magic values
    ...
```

### Логирование

**Использовать:** `loguru`
**Уровни:** `debug`, `info`, `warning`, `error`
**Всегда:** включать `trace_id` для корреляции

**Хорошо:**
```python
logger.bind(trace_id=trace_id).info(f"Routing event: sensor={entity_id}")
```

**Плохо:**
```python
print(f"Routing event: {entity_id}")
```
