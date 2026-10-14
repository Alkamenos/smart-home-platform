# Rules for AI

Эти правила обязательны. Нарушение любого правила требует явного согласования с пользователем.

## Боевой манифест и эталон синхронизируются всегда (правило владельца, 2026-10-14)

**Правило:** после **каждой** правки боевого манифеста — в том числе через
веб-интерфейс (раздел «Настройка → Манифест», редактор ролей локаций) — эталон в
git приводится к боевому: `make sync-prod-manifest`.

**Почему:** боевой манифест лежит в томе и в git не хранится
(`deploy/docker/config` под `.gitignore`), а эталон
`instances/leonids_house_prod/manifest.yaml` — источник засева пустого тома при
развёртывании. Без синхронизации при развёртывании поднимается **старая**
конфигурация, а правки из интерфейса в git не попадают и теряются при
пересоздании (BACKLOG B46).

**Как проверить:** `cmp deploy/docker/config/manifest.yaml instances/leonids_house_prod/manifest.yaml`
— молчание означает совпадение. Скрипт `make sync-prod-manifest` сам скажет,
совпадают ли файлы, и покажет изменения для коммита.

## Поля манифеста обязаны быть описаны в модели веб-слоя (правило, 2026-10-14)

**Правило:** любое поле манифеста, которое читает платформа, должно быть описано
в модели веб-слоя (`src/webui/models.py`) — или разрешено через `extra: allow`.
Иначе правка манифеста через интерфейс молча вычеркнет это поле.

**Почему:** 2026-10-14 за ночь пять отказов автоматики (свет, шторы, вентиляция)
имели одну причину — редактор манифеста затирал **вложенные** поля правил
(`lighting.quiet_*`, `climate.setpoint_entity`, `ventilation.enable_entity` и др.)
значениями по умолчанию.

**Как проверить:** для каждого домена правил есть round-trip тест
(`tests/unit/webui/test_manifest_rules_roundtrip.py`); новый домен — новый тест.
Перед правкой боевого манифеста и после неё — `make sync-prod-manifest`.

## Логику — в документацию (правило владельца, 2026-10-09)

**Правило:** каждое изменение логики поведения сопровождается записью логики в
документацию **до коммита**. Код без описания логики и описание без кода —
незавершённая задача.

Что именно записывать:

| Что изменилось | Куда писать |
|----------------|-------------|
| Поведение автоматики (когда включается/выключает, что блокирует) | `.ai/01_PROJECT_STATE.md` → «Последние значимые изменения» |
| Архитектурное решение, правило домовладения | `.ai/02_ARCHITECTURE.md` |
| Отложенные задачи, выясненные по ходу | `.ai/03_ROADMAP.md` |
| Изменённые ограничения/процедуры | `.ai/04_RULES.md` (этот файл) |

Формулировка — **с точки зрения логики, а не кода**: не «добавлен модуль X»,
а «свет не включается, пока включён модификатор „мы спим“; при его
отсутствии решает солнце». Обязательно: при каких условиях срабатывает, чему
противоречит (требование владельца), что проверено живьём.

**Почему правило появилось:** 2026-10-09 за вечер выяснилось три дефекта,
которых не было ни в одной документации (цикл расписания не срабатывал без
точки отсчёта, дебаунс съедал события расписания, локаут отменял ночное
выключение). Все три были видны в логах и в коде, но отсутствовали в
документации — их пришлось восстанавливать по кускам.

## Подробные логи для утреннего анализа (правило владельца, 2026-10-09)

**Требование:** утром по логам должно быть восстановимо, что произошло ночью и
почему — поведение сравнивается с ожидаемой логикой **без перезапуска, без
вопросов к коду и без «наверное, сработало»**.

Каждое решение автоматики обязано оставить в журнале след:

1. **Событие и фактическое время** — движение, расписание, изменение сущности
   HA (с именем источника).
2. **Решение и причину** — включил / не включил / заблокировал, с указанием
   условия: «темно по sun.sun», «локкаут ручного действия», «мы спим»,
   «нет перехода», «свет считается выключенным».
3. **Команду и её судьбу** — intent создана → принята/отклонена → вызов сервиса
   HA → результат (устройство не ответило — тоже писать).

**Плохо:** «обработано событие» без причины; молчальный отказ (свет не
включился, а в журнале пусто); ожидаемое событие, о котором не сказано ни слова.

**Хорошо:** `Transition 'OFF' -> 'OFF' triggered by quiet_hours_started`,
`Blocked automated command ...: manual lockout active (last manual control at ...)`,
`Суточный цикл света: {'quiet_hours_started': '23:00'}`.

**Правило для кода:** если ветка логики может молча не сработать — это дефект
той же задачи, лог добавляется вместе с логикой, а не потом.

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

### `asyncio.CancelledError` не наследует `Exception`

**Правило:** ловить `CancelledError` нужно явно и только там, где отмена ожидаема.

**Почему.** `except Exception` не ловит отмену задачи. Места, где это привело к
дефекту в этом проекте:

- `listen_task.result()` на **отменённой** задаче бросает `CancelledError`. Обработчик
  `except Exception` его пропускал, исключение уходило в обработчик отмены самого цикла
  переподключения, и переподключения не происходило никогда — платформа молча слепла,
  хотя `/health` отвечал 200 (Known Issue #70).
- `contextlib.suppress(asyncio.CancelledError)` вокруг `await task` подавляет первую
  отмену; следующее ожидание снова её выбрасывает, и вызывающий код уходит в ветку
  отмены. Подавление здесь не равносильно «продолжить работу».

**Как проверять.** Для каждого `.result()`, `.cancel()` и `await` отменяемой задачи
спросить: отмена здесь — ожидаемый исход или признак остановки? В первом случае она
переводится в обычный результат (`_listen_task_reason()` в `src/adapters/ha_adapter.py`),
во втором — propagруется, но записывается в журнал на уровне, который виден.

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
