# Platform V3 — Руководство по использованию

## Обзор

Platform V3 — это современная, надёжная и легко тестируемая платформа для умного дома на базе Home Assistant с использованием конечных автоматов (FSM).

### Ключевые особенности

- ✅ **Простая архитектура** — минимум абстракций, понятный код
- ✅ **Полное тестирование** — все компоненты покрыты тестами
- ✅ **Локальное тестирование** — работает без HA через Mock Adapter
- ✅ **Структурированные логи** — JSON формат для удобной отладки
- ✅ **Декларативные фичи** — автоматы описываются как данные
- ✅ **Event-driven** — все изменения через шину событий

---

## Быстрый старт

### 1. Установка

```bash
cd platform_v3
```

Никаких дополнительных зависимостей не требуется (кроме Python 3.11+).

### 2. Запуск тестов

Проверьте, что всё работает:

```bash
python -m pytest tests/ -p no:libtmux -v
```

Ожидаемый результат: **24 теста пройдены**.

### 3. Использование CLI

#### Показать статус всех автоматов

```bash
python cli.py status
```

#### Показать статус в JSON формате

```bash
python cli.py status --json
```

#### Отладка конкретного автомата

```bash
python cli.py debug light.living_room --state
python cli.py debug light.living_room --history
```

#### Запуск платформы с Mock адаптером

```bash
python cli.py run --mock
```

#### Деплой в Home Assistant (dry-run)

```bash
python loader.py --dry-run
```

#### Полный деплой

```bash
python loader.py --ha-config ~/.homeassistant --ha-url http://localhost:8123 --token YOUR_TOKEN
```

---

## Архитектура

```
platform_v3/
├── core/                      # Ядро (НЕ зависит от HA)
│   ├── fsm.py                # FSM движок
│   ├── event_bus.py          # Шина событий (pub/sub)
│   ├── registry.py           # Реестр автоматов
│   └── logger.py             # Структурированные логи
│
├── adapters/                  # Интеграция с внешним миром
│   ├── base.py               # Абстрактный адаптер
│   ├── mock_adapter.py       # Мок для тестирования
│   └── ha_adapter.py         # Реальный HA адаптер
│
├── features/                  # Декларативные описания фич
│   ├── lighting.py           # Автоматы освещения
│   └── climate.py            # Автоматы климата
│
├── tests/                     # Тесты
│   ├── test_fsm.py           # Unit-тесты FSM
│   └── test_lighting.py      # Scenario-тесты
│
├── cli.py                     # CLI команды
└── loader.py                  # Loader для HA PyScript
```

---

## Core Layer

### FSM Engine

Универсальный движок конечных автоматов.

**Пример использования:**

```python
from core.fsm import FSMEngine, FSMDefinition, Transition
from core.event_bus import EventBus
from core.logger import Logger

# Создаём компоненты
event_bus = EventBus()
logger = Logger()
fsm = FSMEngine(event_bus, logger)

# Определяем автомат
light_def = FSMDefinition(
    entity_id="light.living_room",
    states=("OFF", "ON", "MANUAL"),
    initial="OFF",
    transitions=(
        Transition(
            from_state="OFF",
            to_state="ON",
            trigger="turn_on",
            guard=lambda ctx: ctx.get("allowed", True),
            priority=10,
            reason="Включение света"
        ),
        Transition(
            from_state="*",
            to_state="MANUAL",
            trigger="manual_change",
            priority=100,
            reason="Ручное вмешательство"
        ),
    )
)

# Регистрируем и используем
fsm.register(light_def)
fsm.trigger("light.living_room", "turn_on", {"allowed": True})

state = fsm.get_state("light.living_room")
print(f"Состояние: {state.current}")
```

### Event Bus

Шина событий для связи компонентов (pub/sub).

```python
from core.event_bus import EventBus

event_bus = EventBus()

# Подписка на события
def handler(data):
    print(f"Получено событие: {data}")

event_bus.subscribe("device.state_changed", handler)

# Публикация события
event_bus.publish("device.state_changed", {
    "entity_id": "light.living_room",
    "new_state": "ON"
})
```

### Logger

Структурированное логирование в JSON формате.

```python
from core.logger import Logger

logger = Logger(component="fsm")

logger.info("Transition occurred", 
            entity_id="light.living_room",
            from_state="OFF",
            to_state="ON")

# Вывод:
# {"timestamp": "2026-09-07T18:30:00Z", "level": "INFO", 
#  "component": "fsm", "message": "Transition occurred",
#  "entity_id": "light.living_room", ...}
```

---

## Adapters Layer

### Mock Adapter

Используется для локального тестирования без HA.

```python
from adapters.mock_adapter import MockAdapter

adapter = MockAdapter()

# Устанавливаем состояние вручную (для тестов)
adapter.set_state("light.living_room", "ON")

# Получаем состояние
state = adapter.get_state("light.living_room")

# Проверяем лог команд
commands = adapter.get_commands_log()
```

### HA Adapter

Реальный адаптер для интеграции с Home Assistant.

```python
from adapters.ha_adapter import HAAdapter

adapter = HAAdapter(
    url="http://localhost:8123",
    token="YOUR_LONG_LIVED_TOKEN"
)

# Получаем состояние из HA
state = adapter.get_state("light.living_room")

# Отправляем команду
adapter.send_command("light.living_room", "turn_on", {"brightness": 200})

# Подписываемся на изменения
def on_change(entity_id, old_state, new_state):
    print(f"{entity_id}: {old_state} -> {new_state}")

adapter.subscribe_to_changes("light.living_room", on_change)
```

---

## Features Layer

### Освещение (Lighting)

Автоматы освещения поддерживают состояния:
- `OFF` — выключено
- `ON_SCHEDULE` — включено по расписанию
- `ON_MOTION` — включено по движению
- `PARTY` — режим вечеринки
- `NIGHTLIGHT` — ночник
- `MANUAL` — ручное управление

**Пример создания автоматов:**

```python
from features.lighting import create_lighting_automations

rooms = ["living_room", "bedroom", "kitchen"]
definitions = create_lighting_automations(rooms)

for definition in definitions:
    fsm.register(definition)
```

### Климат (Climate)

Автоматы климата поддерживают состояния:
- `IDLE` — ожидание
- `HEATING` — нагрев
- `COOLING` — охлаждение
- `SAFETY_LOCKOUT` — блокировка безопасности
- `AWAY` — режим отсутствия

**Пример создания автоматов:**

```python
from features.climate import create_climate_automations

zones = ["zone_1", "zone_2"]
definitions = create_climate_automations(zones)

for definition in definitions:
    fsm.register(definition)
```

---

## Тестирование

### Запуск всех тестов

```bash
python -m pytest tests/ -p no:libtmux -v
```

### Запуск конкретных тестов

```bash
# Только FSM тесты
python -m pytest tests/test_fsm.py -v

# Только lighting тесты
python -m pytest tests/test_lighting.py -v

# Один конкретный тест
python -m pytest tests/test_fsm.py::TestFSMTransitions::test_simple_transition -v
```

### Написание собственных тестов

```python
import pytest
from core.fsm import FSMEngine, FSMDefinition, Transition
from core.event_bus import EventBus
from core.logger import Logger

@pytest.fixture
def fsm():
    return FSMEngine(EventBus(), Logger())

def test_my_feature(fsm):
    definition = FSMDefinition(
        entity_id="test.entity",
        states=("OFF", "ON"),
        initial="OFF",
        transitions=(
            Transition(from_state="OFF", to_state="ON", trigger="turn_on"),
        )
    )
    
    fsm.register(definition)
    assert fsm.get_state("test.entity").current == "OFF"
    
    fsm.trigger("test.entity", "turn_on", {})
    assert fsm.get_state("test.entity").current == "ON"
```

---

## Деплой в Home Assistant

### Шаг 1: Подготовка

Убедитесь, что у вас установлен PyScript в Home Assistant.

### Шаг 2: Запуск loader

```bash
python loader.py \
  --ha-config ~/.homeassistant \
  --ha-url http://localhost:8123 \
  --token YOUR_TOKEN
```

### Шаг 3: Проверка

Файлы будут скопированы в:
```
~/.homeassistant/pyscript/platform_v3/
├── core/
├── features/
├── adapters/
└── pyscript.yaml
```

Главный скрипт инициализации:
```
~/.homeassistant/pyscript/platform_v3_init.py
```

### Шаг 4: Перезагрузка PyScript

В Home Assistant перейдите в:
**Developer Tools > Services > pyscript.reload**

Или используйте команду в CLI:
```bash
python loader.py --ha-url http://localhost:8123 --token YOUR_TOKEN
```

---

## Сервисы Home Assistant

После деплоя становятся доступны сервисы:

### fsm.debug

Показать состояние автомата:

```yaml
service: pyscript.fsm_debug
data:
  entity_id: light.living_room
```

### fsm.reset

Сбросить автомат в начальное состояние:

```yaml
service: pyscript.fsm_reset
data:
  entity_id: light.living_room
```

### fsm.trigger

Вызвать триггер вручную:

```yaml
service: pyscript.fsm_trigger
data:
  entity_id: light.living_room
  trigger: manual_change
```

---

## Troubleshooting

### Ошибка: "Module not found"

Убедитесь, что файлы скопированы в правильную директорию и `allow_all_imports: true` указан в `pyscript.yaml`.

### Ошибка: "Permission denied"

Проверьте права доступа к директории HA config.

### Автоматы не регистрируются

Проверьте логи PyScript в Home Assistant (**Settings > System > Logs**).

### Тесты падают

Запустите с флагом `-p no:libtmux` для обхода конфликта плагинов:
```bash
python -m pytest tests/ -p no:libtmux -v
```

---

## Changelog

### v3.0.0 (2026-09-08)

- ✨ Новый FSM движок без `eval()`
- ✨ Event Bus для связи компонентов
- ✨ Mock Adapter для локального тестирования
- ✨ Структурированные логи в JSON
- ✨ CLI для управления платформой
- ✨ Loader для деплоя в HA PyScript
- ✨ Lighting и Climate фичи
- 🐛 Исправлены проблемы V1/V2 (гонки, баги со sleep)

---

**Документация подготовлена в соответствии со спецификацией v3.md**
