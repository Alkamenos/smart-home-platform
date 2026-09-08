# Smart Home Platform V3 — Спецификация

**Версия**: 3.0.0
**Дата**: 2026-09-08
**Автор**: Leo
**Статус**: Draft

---

## 1. Обзор проекта

### 1.1 Цели
Создать надёжную, тестируемую и легко поддерживаемую платформу умного дома на базе Home Assistant с использованием конечных автоматов (FSM) для принятия решений.

### 1.2 Проблемы предыдущих версий

**V1 (smart-home-platform):**
- Сложная feature-sliced архитектура с множеством артефактов
- FSM реализован через `eval()` для guard условий — небезопасно и медленно
- Отсутствие моков для локального тестирования
- Каждая правка требовала перезапуска HA
- Сложная отладка из-за отсутствия структурированных логов

**V2 (platform_v2):**
- Критический баг: `task.sleep(1)` вместо `time.sleep(1)` — падение главного цикла
- Гонки в `SyncEngine` из-за множественных вызовов `_check_divergence()`
- Сложная логика определения "ручного вмешательства"
- Всё ещё нет полноценного локального тестирования

### 1.3 Ключевые принципы V3

1. **Простота**: Минимум абстракций, понятный код
2. **Тестируемость**: Ядро работает без HA, тестируется моками
3. **Декларативность**: Фичи описываются как данные, а не код
4. **Иммутабельность**: Состояния не мутируются, создаются новые
5. **Observability**: Структурированные логи с контекстом
6. **Event-driven**: Все изменения через шину событий

---

## 2. Архитектура

### 2.1 Общая схема

```
Features Layer (Lighting, Climate, Ventilation)
    ↓
Core Layer (FSM, Event Bus, Registry, Logger)
    ↓
Adapters Layer (MockAdapter, HAAdapter)
```

### 2.2 Структура проекта

```
platform_v3/
├── core/                      # Ядро (НЕ зависит от HA)
│   ├── fsm.py                # Простой FSM движок
│   ├── event_bus.py          # Шина событий (pub/sub)
│   ├── registry.py           # Реестр автоматов
│   ├── logger.py             # Структурированные логи
│   └── types.py              # Общие типы данных
│
├── adapters/                  # Интеграция с внешним миром
│   ├── base.py               # Абстрактный адаптер
│   ├── mock_adapter.py       # Мок для тестирования
│   └── ha_adapter.py         # Реальный HA адаптер
│
├── features/                  # Декларативные описания фич
│   ├── lighting.py           # Автоматы освещения
│   ├── climate.py            # Автоматы климата
│   └── ventilation.py        # Автоматы вентиляции
│
├── tests/                     # Тесты
│   ├── test_fsm.py           # Unit-тесты FSM
│   ├── test_lighting.py      # Scenario-тесты
│   └── test_climate.py       # Scenario-тесты
│
├── cli.py                     # CLI команды
├── run.py                     # Точка входа
├── SPEC_V3.md                # Этот документ
└── README.md                  # Инструкция
```

---

## 3. Компоненты Core Layer

### 3.1 FSM Engine (core/fsm.py)

#### Назначение
Универсальный движок конечных автоматов для управления логикой устройств.

#### Ключевые отличия от V1/V2
- **Нет `eval()`**: Guard условия через функции (type-safe)
- **Иммутабельность**: Состояния не мутируются
- **Event-driven**: Все переходы через Event Bus
- **Простота**: Минимум абстракций (~200 строк кода)

#### Структуры данных

```python
@dataclass(frozen=True)
class Transition:
    """Описание перехода между состояниями"""
    from_state: str | tuple[str, ...]  # Из какого состояния
    to_state: str                      # В какое состояние
    trigger: str                       # Событие, вызывающее переход
    guard: Callable[[dict], bool] = lambda ctx: True  # Условие
    priority: int = 0                  # Приоритет (выше = важнее)
    reason: str = ""                   # Описание

@dataclass(frozen=True)
class FSMDefinition:
    """Описание автомата"""
    entity_id: str                     # ID устройства
    states: tuple[str, ...]            # Все возможные состояния
    initial: str                       # Начальное состояние
    transitions: tuple[Transition, ...]  # Все переходы

@dataclass(frozen=True)
class State:
    """Текущее состояние автомата"""
    entity_id: str
    current: str
    entered_at: float
    entered_by: str
    entered_why: str
    history: tuple[dict, ...]          # Последние 20 переходов
```

#### Пример использования

```python
from core.fsm import FSMEngine, FSMDefinition, Transition

# Создаём движок
fsm = FSMEngine(event_bus, logger)

# Определяем автомат для света
light_def = FSMDefinition(
    entity_id="light.living_room",
    states=("OFF", "ON_SCHEDULE", "ON_MOTION", "MANUAL"),
    initial="OFF",
    transitions=(
        Transition(
            from_state="OFF",
            to_state="ON_SCHEDULE",
            trigger="schedule_on",
            guard=lambda ctx: ctx.get("is_schedule_time", False),
            priority=10,
            reason="Включение по расписанию"
        ),
        Transition(
            from_state="*",  # Из любого состояния
            to_state="MANUAL",
            trigger="manual_change",
            priority=100,  # Самый высокий приоритет
            reason="Ручное вмешательство"
        ),
    )
)

# Регистрируем и используем
fsm.register(light_def)
fsm.trigger("light.living_room", "schedule_on", {"is_schedule_time": True})
```

### 3.2 Event Bus (core/event_bus.py)

Шина событий для связи компонентов через паттерн pub/sub.

```python
class EventBus:
    def subscribe(self, event_type: str, handler: Callable) -> None:
        """Подписаться на события"""

    def publish(self, event_type: str, data: dict) -> None:
        """Опубликовать событие"""
```

**Типы событий:**
- `fsm.transition` - переход автомата
- `device.state_changed` - изменение состояния устройства
- `device.command` - команда устройству
- `platform.started/stopped` - системные события

### 3.3 Registry (core/registry.py)

Реестр всех зарегистрированных автоматов.

```python
class Registry:
    def register_all(self, definitions: list[FSMDefinition]) -> None:
        """Зарегистрировать список автоматов"""

    def get_all_entity_ids(self) -> list[str]:
        """Получить все entity_id"""

    def get_states_snapshot(self) -> dict[str, State]:
        """Получить снимок всех состояний"""
```

### 3.4 Logger (core/logger.py)

Структурированное логирование с контекстом.

```python
class Logger:
    def info(self, message: str, **context) -> None:
        """Информационное сообщение"""
        # Формат: {"timestamp", "level", "component", "entity_id", "message", "context"}

    def error(self, message: str, **context) -> None:
        """Ошибка"""
```

---

## 4. Компоненты Adapters Layer

### 4.1 Base Adapter (adapters/base.py)

```python
class BaseAdapter(ABC):
    @abstractmethod
    def get_state(self, entity_id: str) -> str | None:
        """Получить состояние устройства"""

    @abstractmethod
    def send_command(self, entity_id: str, command: str, attributes: dict = None) -> bool:
        """Отправить команду устройству"""

    @abstractmethod
    def subscribe_to_changes(self, entity_id: str, callback: Callable) -> None:
        """Подписаться на изменения"""
```

### 4.2 Mock Adapter (adapters/mock_adapter.py)

Мок-адаптер для локального тестирования без Home Assistant.

**Возможности:**
- Хранит состояния устройств в памяти
- Позволяет устанавливать состояния вручную
- Логирует все вызовы команд
- Эмулирует задержки и ошибки

```python
class MockAdapter(BaseAdapter):
    def set_state(self, entity_id: str, state: str) -> None:
        """Установить состояние (для тестов)"""

    def get_commands_log(self) -> list[dict]:
        """Получить лог команд (для проверок)"""
```

### 4.3 HA Adapter (adapters/ha_adapter.py)

Реальный адаптер для интеграции с Home Assistant.

**Особенности:**
- REST API для чтения состояний
- WebSocket для подписок на изменения
- Hot-reload (без перезапуска HA)
- Структурированные логи в HA

---

## 5. Компоненты Features Layer

### 5.1 Декларативное описание фич

Фичи описываются как данные (список `FSMDefinition`), а не как код.

#### Пример: Освещение (features/lighting.py)

```python
def create_lighting_automations(rooms: list[str]) -> list[FSMDefinition]:
    """Создаёт автоматы для всех комнат"""
    definitions = []

    for room in rooms:
        entity_id = f"light.{room}"

        definition = FSMDefinition(
            entity_id=entity_id,
            states=("OFF", "ON_SCHEDULE", "ON_MOTION", "PARTY", "NIGHTLIGHT", "MANUAL"),
            initial="OFF",
            transitions=(
                # Включение по расписанию
                Transition(
                    from_state="OFF",
                    to_state="ON_SCHEDULE",
                    trigger="schedule_on",
                    guard=lambda ctx, r=room: (
                        ctx.get(f"{r}_is_schedule_time", False) and
                        not ctx.get(f"{r}_is_night_time", False)
                    ),
                    priority=10,
                    reason="Включение по расписанию"
                ),

                # Включение по движению
                Transition(
                    from_state=("OFF", "ON_SCHEDULE"),
                    to_state="ON_MOTION",
                    trigger="motion_detected",
                    guard=lambda ctx, r=room: (
                        ctx.get(f"{r}_motion_sensor", False) and
                        ctx.get(f"{r}_motion_enabled", True)
                    ),
                    priority=20,
                    reason="Обнаружено движение"
                ),

                # Ручное вмешательство (самый высокий приоритет)
                Transition(
                    from_state="*",
                    to_state="MANUAL",
                    trigger="manual_change",
                    priority=100,
                    reason="Ручное вмешательство"
                ),

                # Возврат из MANUAL после таймаута
                Transition(
                    from_state="MANUAL",
                    to_state="OFF",
                    trigger="timeout",
                    guard=lambda ctx, r=room: (
                        ctx.get(f"{r}_minutes_since_manual", 0) >= 60
                    ),
                    priority=50,
                    reason="Автоматическое восстановление"
                ),
            )
        )

        definitions.append(definition)

    return definitions
```

### 5.2 Пример: Климат (features/climate.py)

```python
def create_climate_automations(zones: list[str]) -> list[FSMDefinition]:
    """Создаёт автоматы для климатических зон"""
    definitions = []

    for zone in zones:
        entity_id = f"climate.{zone}"

        definition = FSMDefinition(
            entity_id=entity_id,
            states=("IDLE", "HEATING", "COOLING", "SAFETY_LOCKOUT", "AWAY"),
            initial="IDLE",
            transitions=(
                Transition(
                    from_state="IDLE",
                    to_state="HEATING",
                    trigger="temp_low",
                    guard=lambda ctx, z=zone: (
                        ctx.get(f"{z}_temp_current", 0) < ctx.get(f"{z}_temp_target", 0) - 0.5 and
                        ctx.get(f"{z}_mode", "auto") == "heat"
                    ),
                    priority=30,
                    reason="Температура ниже целевой"
                ),

                Transition(
                    from_state="*",
                    to_state="SAFETY_LOCKOUT",
                    trigger="safety_alarm",
                    priority=200,  # Самый высокий приоритет
                    reason="Сработала система безопасности"
                ),
            )
        )

        definitions.append(definition)

    return definitions
```

---

## 6. Тестирование

### 6.1 Стратегия тестирования

```
Unit Tests (90% coverage)
    ↓
Scenario Tests (интеграция компонентов)
    ↓
Integration Tests (с Mock Adapter)
```

### 6.2 Unit-тесты FSM

```python
# tests/test_fsm.py
import pytest
from core.fsm import FSMEngine, FSMDefinition, Transition

@pytest.fixture
def fsm():
    return FSMEngine(EventBus(Logger()), Logger())

def test_fsm_simple_transition(fsm):
    """Тест простого перехода"""
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

    result = fsm.trigger("test.entity", "turn_on", {})
    assert result is True
    assert fsm.get_state("test.entity").current == "ON"

def test_fsm_guard_condition(fsm):
    """Тест guard условия"""
    definition = FSMDefinition(
        entity_id="test.entity",
        states=("OFF", "ON"),
        initial="OFF",
        transitions=(
            Transition(
                from_state="OFF",
                to_state="ON",
                trigger="turn_on",
                guard=lambda ctx: ctx.get("allowed", False)
            ),
        )
    )

    fsm.register(definition)

    # Guard возвращает False — переход не происходит
    result = fsm.trigger("test.entity", "turn_on", {"allowed": False})
    assert result is False
    assert fsm.get_state("test.entity").current == "OFF"

    # Guard возвращает True — переход происходит
    result = fsm.trigger("test.entity", "turn_on", {"allowed": True})
    assert result is True
    assert fsm.get_state("test.entity").current == "ON"

def test_fsm_priority(fsm):
    """Тест приоритетов переходов"""
    definition = FSMDefinition(
        entity_id="test.entity",
        states=("OFF", "ON", "EMERGENCY"),
        initial="OFF",
        transitions=(
            Transition(from_state="OFF", to_state="ON", trigger="activate", priority=10),
            Transition(from_state="OFF", to_state="EMERGENCY", trigger="activate", priority=100),
        )
    )

    fsm.register(definition)

    # Должен выбрать переход с приоритетом 100
    fsm.trigger("test.entity", "activate", {})
    assert fsm.get_state("test.entity").current == "EMERGENCY"
```

### 6.3 Scenario-тесты

```python
# tests/test_lighting.py
import pytest
from features.lighting import create_lighting_automations

@pytest.fixture
def lighting_system():
    fsm = FSMEngine(EventBus(Logger()), Logger())
    definitions = create_lighting_automations(["living_room"])
    for definition in definitions:
        fsm.register(definition)
    return fsm

def test_lighting_schedule_on(lighting_system):
    """Тест включения по расписанию"""
    context = {
        "living_room_is_schedule_time": True,
        "living_room_is_night_time": False
    }

    lighting_system.trigger("light.living_room", "schedule_on", context)

    state = lighting_system.get_state("light.living_room")
    assert state.current == "ON_SCHEDULE"
    assert state.entered_by == "schedule_on"

def test_lighting_motion_overrides_schedule(lighting_system):
    """Тест: движение переопределяет расписание"""
    context = {"living_room_is_schedule_time": True}
    lighting_system.trigger("light.living_room", "schedule_on", context)

    context = {"living_room_motion_sensor": True, "living_room_motion_enabled": True}
    lighting_system.trigger("light.living_room", "motion_detected", context)

    state = lighting_system.get_state("light.living_room")
    assert state.current == "ON_MOTION"

def test_lighting_manual_highest_priority(lighting_system):
    """Тест: ручное вмешательство имеет наивысший приоритет"""
    lighting_system.trigger("light.living_room", "schedule_on", {})
    lighting_system.trigger("light.living_room", "motion_detected", {})
    lighting_system.trigger("light.living_room", "manual_change", {})

    state = lighting_system.get_state("light.living_room")
    assert state.current == "MANUAL"
```

### 6.4 Запуск тестов

```bash
# Запустить все тесты
pytest tests/ -v

# Запустить с coverage
pytest tests/ --cov=core --cov=features --cov-report=html

# Запустить только unit-тесты
pytest tests/test_fsm.py tests/test_event_bus.py -v

# Запустить scenario-тесты
pytest tests/test_lighting.py tests/test_climate.py -v
```

---

## 7. CLI и запуск

### 7.1 CLI команды (cli.py)

```python
import click
from core.platform import Platform

@click.group()
def cli():
    """Smart Home Platform V3 CLI"""
    pass

@cli.command()
@click.option("--adapter", type=click.Choice(["mock", "ha"]), default="mock")
def run(adapter: str):
    """Запустить платформу"""
    platform = Platform(adapter_type=adapter)
    platform.start()

@cli.command()
def test():
    """Запустить тесты"""
    import subprocess
    subprocess.run(["pytest", "tests/", "-v"])

@cli.command()
@click.argument("entity_id")
def debug(entity_id: str):
    """Показать состояние автомата"""
    platform = Platform(adapter_type="mock")
    platform.load()

    state = platform.fsm.get_state(entity_id)
    if state:
        print(f"Entity: {state.entity_id}")
        print(f"State: {state.current}")
        print(f"Entered at: {state.entered_at}")
        print(f"Entered by: {state.entered_by}")
        print(f"Why: {state.entered_why}")
        print("\nHistory:")
        for h in state.history[:5]:
            print(f"  {h['from']} -> {h['to']} ({h['trigger']})")
    else:
        print(f"Entity {entity_id} not found")

@cli.command()
def list_entities():
    """Показать все зарегистрированные автоматы"""
    platform = Platform(adapter_type="mock")
    platform.load()

    for entity_id in platform.registry.get_all_entity_ids():
        state = platform.fsm.get_state(entity_id)
        print(f"{entity_id}: {state.current}")

if __name__ == "__main__":
    cli()
```

### 7.2 Запуск

```bash
# Запуск с моком (для разработки)
python cli.py run --adapter mock

# Запуск с реальным HA (для production)
python cli.py run --adapter ha

# Запуск тестов
python cli.py test

# Отладка автомата
python cli.py debug light.living_room

# Список всех автоматов
python cli.py list_entities
```

---

## 8. Интеграция с Home Assistant

### 8.1 Структура файлов в HA

```
/config/
├── pyscript/
│   ├── platform_v3_loader.py    # Загрузчик (генерируется автоматически)
│   └── platform_v3/             # Скопированные файлы ядра
│       ├── core/
│       ├── adapters/
│       └── features/
│
├── configuration.yaml           # Конфигурация HA
└── automations.yaml             # Автоматизации HA
```

### 8.2 Loader скрипт (pyscript/platform_v3_loader.py)

```python
# Генерируется автоматически при деплое
from platform_v3.core.platform import Platform

# Инициализация
platform = Platform(adapter_type="ha")
platform.start()

# Подписка на события HA
@state_trigger("sensor.living_room_motion")
def on_motion(value):
    if value == "on":
        platform.handle_event("light.living_room", "motion_detected", {
            "living_room_motion_sensor": True
        })

@state_trigger("input_boolean.party_mode")
def on_party_mode(value):
    trigger = "party_mode_on" if value == "on" else "party_mode_off"
    for entity_id in platform.registry.get_all_entity_ids():
        if entity_id.startswith("light."):
            platform.handle_event(entity_id, trigger, {})
```

### 8.3 Сервисы для отладки

```yaml
# services.yaml
fsm_debug:
  name: FSM Debug
  description: Показать состояние автомата
  fields:
    entity_id:
      name: Entity ID
      description: ID автомата
      example: light.living_room

fsm_reset:
  name: FSM Reset
  description: Сбросить автомат в начальное состояние
  fields:
    entity_id:
      name: Entity ID
      description: ID автомата
      example: light.living_room
```

---

## 9. План реализации

### Phase 1: Ядро (2-3 дня)
- [ ] FSM Engine с полным набором тестов
- [ ] Event Bus
- [ ] Registry
- [ ] Logger
- [ ] Unit-тесты (coverage > 90%)

### Phase 2: Моки и базовые фичи (2-3 дня)
- [ ] Mock Adapter
- [ ] Lighting feature
- [ ] Climate feature
- [ ] Scenario-тесты
- [ ] CLI: run, test, debug

### Phase 3: Интеграция с HA (3-4 дня)
- [ ] HA Adapter (REST + WebSocket)
- [ ] Loader скрипт для PyScript
- [ ] Сервисы для отладки
- [ ] Интеграционные тесты
- [ ] Документация

### Phase 4: Деплой и полировка (2 дня)
- [x] CLI: deploy
- [x] Hot-reload
- [x] Dashboard для мониторинга
- [x] Миграция данных из v1/v2
- [x] Финальное тестирование

**Итого: 9-12 дней**

---

## 10. Требования к системе

### 10.1 Минимальные требования
- Python 3.11+
- Home Assistant 2024.1+
- PyScript 2024.1+
- 512 MB RAM
- 100 MB свободного места

### 10.2 Рекомендуемые требования
- Python 3.12+
- Home Assistant 2026.1+
- PyScript 2026.1+
- 1 GB RAM
- 500 MB свободного места
- SSD для быстрого чтения логов

---

## 11. Безопасность

### 11.1 Принципы
- Нет `eval()` или `exec()` в production коде
- Все входящие данные валидируются
- Токены HA хранятся в переменных окружения
- Логи не содержат чувствительных данных

### 11.2 Проверка безопасности

```bash
# Проверка на уязвимости
pip-audit

# Проверка типов
mypy core/ adapters/ features/

# Линтинг
ruff check core/ adapters/ features/

# Тесты безопасности
pytest tests/test_security.py -v
```

---

## 12. Мониторинг и отладка

### 12.1 Структурированные логи

```json
{
    "timestamp": "2026-09-08T14:30:00Z",
    "level": "INFO",
    "component": "fsm",
    "entity_id": "light.living_room",
    "event": "transition",
    "from_state": "OFF",
    "to_state": "ON_SCHEDULE",
    "trigger": "schedule_on",
    "why": "Включение по расписанию",
    "duration_ms": 12
}
```

### 12.2 Метрики

- Количество переходов в минуту
- Средняя длительность обработки события
- Количество ошибок
- Количество автоматов

### 12.3 Dashboard

Дашборд для мониторинга в Home Assistant:
- Текущее состояние всех автоматов
- История переходов
- График активности
- Список ошибок
- Кнопки для сброса автоматов

---

## 13. Миграция с V1/V2

### 13.1 Стратегия
1. Запустить V3 параллельно с V1/V2 (shadow mode)
2. Сравнить поведение
3. Отключить V1/V2 после подтверждения корректности V3
4. Удалить код V1/V2

### 13.2 Миграция данных

```python
# Скрипт миграции
def migrate_from_v2():
    # Читаем состояния из V2
    v2_states = load_v2_states()

    # Конвертируем в формат V3
    for entity_id, state in v2_states.items():
        v3_state = convert_state(state)
        fsm.set_state(entity_id, v3_state)

    # Сохраняем
    save_v3_states()
```

---

## 14. Часто задаваемые вопросы

### Q: Почему не использовать существующие FSM библиотеки?
A: Большинство библиотек слишком сложные или не поддерживают нужные нам возможности (Event Bus, иммутабельность, структурированные логи). Наша реализация занимает ~200 строк кода и полностью адаптирована под наши задачи.

### Q: Как обрабатывать ошибки в guard условиях?
A: Если guard вызывает исключение, он возвращает `False`, и переход не происходит. Ошибка логируется для последующего анализа.

### Q: Можно ли добавлять автоматы без перезапуска?
A: Да, через hot-reload. Платформа следит за изменениями файлов фич и автоматически регистрирует новые автоматы.

### Q: Как тестировать сложные сценарии?
A: Используем Mock Adapter для эмуляции устройств и пишем scenario-тесты, которые проверяют полный цикл работы.

---

## 15. Заключение

V3 решает все проблемы предыдущих версий:
- ✅ Простая и понятная архитектура
- ✅ Полное тестовое покрытие
- ✅ Локальное тестирование без HA
- ✅ Структурированные логи для отладки
- ✅ Декларативное описание фич
- ✅ Event-driven архитектура

Это надёжная, поддерживаемая и масштабируемая платформа для умного дома.

---

**Конец документа**
