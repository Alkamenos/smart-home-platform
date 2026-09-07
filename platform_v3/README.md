# Smart Home Platform V3

Новая версия платформы умного дома на базе конечных автоматов (FSM).

## Особенности V3

- ✅ **Простота**: Минимум абстракций, понятный код (~200 строк ядро)
- ✅ **Тестируемость**: Ядро работает без HA, тестируется моками
- ✅ **Декларативность**: Фичи описываются как данные, а не код
- ✅ **Иммутабельность**: Состояния не мутируются, создаются новые
- ✅ **Event-driven**: Все изменения через шину событий
- ✅ **Нет eval()**: Guard условия через функции (type-safe)

## Структура проекта

```
platform_v3/
├── core/                      # Ядро (НЕ зависит от HA)
│   ├── fsm.py                # Простой FSM движок
│   ├── event_bus.py          # Шина событий (pub/sub)
│   ├── registry.py           # Реестр автоматов
│   └── logger.py             # Структурированные логи
│
├── adapters/                  # Интеграция с внешним миром
│   ├── base.py               # Абстрактный адаптер
│   ├── mock_adapter.py       # Мок для тестирования
│   └── ha_adapter.py         # Реальный HA адаптер (TODO)
│
├── features/                  # Декларативные описания фич
│   ├── lighting.py           # Автоматы освещения
│   └── climate.py            # Автоматы климата
│
└── tests/                     # Тесты
    ├── test_fsm.py           # Unit-тесты FSM
    └── test_lighting.py      # Scenario-тесты
```

## Быстрый старт

### Запуск тестов

```bash
cd platform_v3
python -c "from tests.test_fsm import *; print('Tests passed!')"
```

Или напрямую:

```python
from core.fsm import FSMEngine, FSMDefinition, Transition
from core.event_bus import EventBus
from core.logger import Logger

# Создаём движок
event_bus = EventBus()
logger = Logger(component="app")
fsm = FSMEngine(event_bus, logger)

# Определяем автомат
definition = FSMDefinition(
    entity_id="light.living_room",
    states=("OFF", "ON"),
    initial="OFF",
    transitions=(
        Transition(from_state="OFF", to_state="ON", trigger="turn_on"),
    )
)

# Регистрируем и используем
fsm.register(definition)
fsm.trigger("light.living_room", "turn_on", {})
print(f"State: {fsm.get_state('light.living_room').current}")  # ON
```

## Пример использования

### Освещение

```python
from features.lighting import create_lighting_automations

# Создаём автоматы для комнат
definitions = create_lighting_automations(["living_room", "bedroom"])

# Регистрируем
for definition in definitions:
    fsm.register(definition)

# Используем
fsm.trigger("light.living_room", "schedule_on", {
    "living_room_is_schedule_time": True,
    "living_room_is_night_time": False
})
```

## Архитектура

```
Features Layer (Lighting, Climate, Ventilation)
    ↓
Core Layer (FSM, Event Bus, Registry, Logger)
    ↓
Adapters Layer (MockAdapter, HAAdapter)
```

## План реализации

- [x] Phase 1: Ядро (FSM, Event Bus, Registry, Logger)
- [x] Phase 2: Моки и базовые фичи (Mock Adapter, Lighting, Climate)
- [ ] Phase 3: Интеграция с HA (HA Adapter, Loader скрипт)
- [ ] Phase 4: Деплой и полировка (CLI, Dashboard, Migration)

## Требования

- Python 3.11+
- Home Assistant 2024.1+ (для production)
- PyScript 2024.1+ (для integration)

## Запуск тестов

```bash
cd platform_v3

# Все тесты
python tests/test_fsm.py
python tests/test_lighting.py

# Или через pytest
pytest tests/ -v
```

## Документация

Полная спецификация в файле `v3.md` в корне репозитория.

## Лицензия

MIT
