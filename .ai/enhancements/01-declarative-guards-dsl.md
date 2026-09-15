# Declarative Guards DSL

**Приоритет:** HIGH
**Оценка:** 1-2 дня
**Категория:** Quick Wins

## Цель

Позволить пользователям создавать сложные условия (guards) для FSM transitions без написания Python кода.

## Проблема

Сейчас для создания guard conditions требуется:
1. Написать Python функцию
2. Зарегистрировать её в `FSMEngine` через `register_guard()`
3. Использовать имя функции в YAML манифесте

Это создаёт высокий порог входа для пользователей, которые хотят автоматизацию, но не хотят писать код.

## Предлагаемое решение

Декларативный DSL для guards прямо в YAML:

```yaml
transitions:
  - trigger: motion_detected
    guards:
      - type: time
        between: "23:00-07:00"
      - type: state
        entity: "binary_sensor.alarm"
        is: "off"
      - type: numeric
        entity: "sensor.lux"
        operator: "<"
        value: 50
```

## Типы Guards

| Тип | Назначение | Пример |
|-----|-----------|--------|
| `time` | Проверка времени суток | `between: "23:00-07:00"` |
| `state` | Проверка состояния сущности | `entity: "binary_sensor.alarm"`, `is: "off"` |
| `numeric` | Числовое сравнение сенсора | `entity: "sensor.temp"`, `operator: ">"`, `value: 25` |
| `schedule` | Расписание (дни + время) | `days: [mon-fri]`, `between: "09:00-18:00"` |
| `and` / `or` | Композитные условия | вложенные `conditions` |

## План реализации

1. Создать `core/guards/` с базовыми типами (time, state, numeric, schedule)
2. Guard Factory для создания guards из YAML
3. Pydantic модели для валидации (`core/models/guards.py`)
4. Интеграция с `FSMEngine` и `fsm_factory.py`
5. Тесты для всех типов

## Файлы

- `core/guards/base.py` — абстрактный класс `BaseGuard`
- `core/guards/time_guard.py`, `state_guard.py`, `numeric_guard.py`, `schedule_guard.py`
- `core/guards/composite_guard.py` — AND/OR
- `core/guards/factory.py` — создание из YAML
- `core/models/guards.py` — Pydantic модели
- `tests/test_declarative_guards.py`

## Критерии успеха

- [ ] Все базовые типы реализованы
- [ ] Factory создаёт guards из YAML
- [ ] Pydantic валидация работает
- [ ] Покрытие тестами >= 90%
- [ ] Backward compatibility: старые Python guards продолжают работать

## Риски

1. **Производительность** — декларативные guards медленнее. **Mitigation:** кэширование.
2. **Сложные условия** — не всё выразимо в DSL. **Mitigation:** оставить Python для сложных случаев.
