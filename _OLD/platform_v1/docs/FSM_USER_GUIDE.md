# Руководство по использованию FSM

## Введение

Система конечных автоматов (FSM) управляет автоматикой умного дома. Каждый автомат имеет:
- **Состояния** - текущий режим работы (например, HEATING, COOLING, OFF)
- **Переходы** - правила изменения состояния (например, "если температура < 20°C, включить нагрев")
- **Приоритеты** - важность перехода (чем выше число, тем важнее)

## Архитектура

### Универсальный движок

Все автоматы используют единый движок из `ha/pyscript/fsm_engine.py`:

```python
# Регистрация автомата
fsm_register("light.yard_floodlights", fsm_definition)

# Триггер перехода
fsm_trigger("light.yard_floodlights", "motion", src="датчик")

# Получение состояния
state = fsm_get_state("light.yard_floodlights")
```

### Структура фич

Каждая фича имеет два файла:

1. **fsm.py** - определение автомата:
   ```python
   CLIMATE_FSM_DEFAULT = {
       "states": ["IDLE", "HEATING", "COOLING", "SAFETY_LOCKOUT"],
       "initial": "IDLE",
       "transitions": [
           {"from": "IDLE", "to": "HEATING", "trigger": "needs_heating", "priority": 10}
       ]
   }
   ```

2. **runtime.py** - интеграция с реальными устройствами:
   ```python
   def _clim_eval_zone(zone):
       ctx = _clim_build_fsm_ctx(zone)
       result = climate_fsm_run(zone_id, ctx)
       if result and result.get("action"):
           _clim_apply_fsm_action(zone, result)
   ```

## Использование

### Мониторинг

Все состояния публикуются в сенсоры:

- `sensor.light_<group>_fsm_state` - освещение
- `sensor.climate_<zone>_fsm_state` - климат
- `sensor.fan_<device>_fsm_state` - вентиляция
- `sensor.cover_<device>_fsm_state` - шторы
- `sensor.room_main_fsm_state` - контекст комнаты

### Отладка

**Через дашборд:**
1. Откройте FSM Dashboard
2. Вкладка "Отладка"
3. Используйте кнопки диагностики

**Через сервисы:**
```yaml
service: pyscript.light_fsm_debug
service: pyscript.covers_fsm_debug
service: pyscript.climate_debug
service: pyscript.vent_debug
```

### Управление

**Сброс блокировок:**
```yaml
service: pyscript.light_override_clear
service: pyscript.covers_override_clear
```

**Ручное вмешательство:**
При ручном изменении состояния устройства автомат переходит в MANUAL_LOCK на 60-120 минут.

## Приоритеты

Стандартные приоритеты переходов:

| Приоритет | Тип перехода |
|-----------|--------------|
| 1000 | Аварийные ситуации |
| 500 | Безопасность |
| 100 | Ручное управление |
| 50 | Специальные режимы (party, sleep) |
| 20 | Расписание |
| 10 | Обычная автоматика |

## Добавление новых автоматов

### 1. Определите автомат в fsm.py

```python
MY_FSM = {
    "states": ["STATE_1", "STATE_2"],
    "initial": "STATE_1",
    "transitions": [
        {"from": "STATE_1", "to": "STATE_2", "trigger": "event", "priority": 10}
    ]
}
```

### 2. Интегрируйте в runtime.py

```python
def my_fsm_run(entity_id, ctx):
    fsm_def = MY_FSM
    _my_fsm_ensure_registered(entity_id, fsm_def)
    # ... логика триггеров
```

### 3. Добавьте в build/build_pyscript.py

```python
ORDER = [
    # ...
    "features/my_feature/fsm.py",
    "features/my_feature/runtime.py",
    # ...
]
```

## Troubleshooting

### Автомат не переходит в нужное состояние

1. Проверьте контекст:
   ```bash
   tail -100 /config/home-assistant.log | grep "fsm\|FSM"
   ```

2. Проверьте триггеры:
   ```bash
   service: pyscript.fsm_debug
   ```

3. Проверьте приоритеты - может быть более важный переход

### Состояние не публикуется в сенсор

1. Проверьте что `fsm_register()` вызывается
2. Проверьте логи:
   ```bash
   grep "_fsm_publish_state" /config/home-assistant.log
   ```

3. Перезапустите HA

### Ручное вмешательство не блокирует автомат

1. Проверьте что `_lg_track_real()` вызывается
2. Проверьте `manual_mode` в контексте
3. Проверьте таймаут override (60-120 мин)

## Примеры

### Освещение: движение ночью

```
Состояние: OFF
Событие: motion (датчик движения)
Условие: night=True, nightlight_enabled=True
Переход: OFF -> NIGHTLIGHT (priority 35)
Действие: включить с минимальной яркостью
```

### Климат: нагрев

```
Состояние: IDLE
Событие: needs_heating (температура < уставки)
Переход: IDLE -> HEATING (priority 10)
Действие: включить конвектор
```

### Вентиляция: высокий CO2

```
Состояние: NORMAL
Событие: high_co2_or_humidity (CO2 > 1000 ppm)
Переход: NORMAL -> BOOST (priority 30)
Действие: усилить вентиляцию
```

## См. также

- [FSM_SPEC.md](FSM_SPEC.md) - спецификация автоматов
- [HANDOFF.md](HANDOFF.md) - текущее состояние системы
- [CHANGELOG.md](CHANGELOG.md) - история изменений
  