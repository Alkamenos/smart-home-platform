# Примеры использования Smart Home Platform v3

## 🚀 Kitchen Demo

Минимальный рабочий пример платформы, демонстрирующий полный цикл работы:

```bash
python examples/kitchen_demo.py
```

### Что демонстрирует demo:

1. **Инициализация** — создание EventBus, Logger, FSMEngine, MockAdapter
2. **Регистрация автомата** — свет на кухне с 6 состояниями
3. **Движение обнаружено** — переход `OFF → ON_MOTION`, свет включается
4. **Таймаут 5 минут** — переход `ON_MOTION → OFF`, свет выключается
5. **Ручное вмешательство** — переход в `MANUAL` режим
6. **История переходов** — показывает последние изменения состояния
7. **Команды в адаптер** — логирует вызовы `turn_on` / `turn_off`

### Ожидаемый вывод:

```
============================================================
  KITCHEN DEMO - Smart Home Platform v3
============================================================

[00:00] 🚀 START
         Платформа запущена. Свет на кухне выключен.
         FSM состояние: OFF
[00:05] 🏃 MOTION
         Датчик движения сработал
[00:05] 💡 LIGHT_ON
         Свет включён! Переход: OFF → ON_MOTION
[05:05] ⏰ TIMEOUT
         Прошло 5 минут без движения
[05:05] ⬛ LIGHT_OFF
         Свет выключен. Переход: ON_MOTION → OFF
[05:10] ✋ MANUAL
         Пользователь включил свет вручную
...
```

## 🧪 Запуск тестов

Все тесты запускаются через pytest:

```bash
# Все тесты
pytest tests/ -v

# Только интеграционные тесты
pytest tests/test_integration.py -v

# Только тесты освещения
pytest tests/test_lighting.py -v
```

## 📋 Интеграционные тесты

Файл `tests/test_integration.py` содержит end-to-end тесты:

- `test_motion_turns_on_light_via_dispatcher` — HA событие → FSM → Action
- `test_motion_timeout_turns_off_light` — таймаут → FSM → Action  
- `test_manual_override_stops_automation` — MANUAL блокирует автоматы
- `test_full_lifecycle` — полный цикл: OFF → ON_MOTION → OFF → MANUAL

## 🔍 Отладка

Для отладки используйте CLI:

```bash
# Показать статус всех автоматов
python cli.py status

# Показать детали конкретного автомата
python cli.py debug light.kitchen --state

# Вывод в JSON формате
python cli.py status --json
```
