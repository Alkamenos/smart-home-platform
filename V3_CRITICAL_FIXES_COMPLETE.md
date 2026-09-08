# Исправления критических проблем v3 (Март 2025)

Этот документ описывает все критические исправления, применённые к платформе smart-home-platform v3 после код-ревью.

---

## ✅ Шаг 1: Реализованы проверки `cooldown_sec` и `manual_lockout_min` в FSM Engine

**Файл:** `core/fsm.py`

### Проблема
В классе `Transition` были добавлены поля `cooldown_sec` (защита от циклов) и `manual_lockout_min` (блокировка после ручного вмешательства), но они **нигде не проверялись** в `FSMEngine.trigger()` и `_execute_transition()`.

### Решение
Добавлены проверки в метод `trigger()`:

```python
# Проверка cooldown_sec (строки 277-288)
if transition.cooldown_sec > 0:
    time_since_last = now - current_state.last_transition_at
    if time_since_last < transition.cooldown_sec:
        remaining_cooldown = transition.cooldown_sec - time_since_last
        self._logger.debug(...)
        continue

# Проверка manual_lockout_min (строки 248-260)
if current_state.manual_override_until > now:
    if context.get("source") != "manual":
        remaining_sec = current_state.manual_override_until - now
        self._logger.debug(...)
        return False
```

И обновление `manual_override_until` в `_execute_transition()` (строки 414-417):

```python
if transition.manual_lockout_min > 0:
    new_manual_override_until = now + (transition.manual_lockout_min * 60)
```

### Тесты
- `tests/test_e2e_scenarios.py::test_cooldown_prevents_rapid_transitions` — проходит ✓
- `tests/test_e2e_scenarios.py::test_manual_override_blocks_automation` — проходит ✓

---

## ✅ Шаг 2: Реализован метод `subscribe_to_changes` в HA Adapter

**Файл:** `adapters/ha_adapter.py` (строки 692-745)

### Проблема
В `BaseAdapter` определён абстрактный метод `subscribe_to_changes(entity_id, callback)`, но в `HAAdapter` он не был реализован, что нарушало Liskov Substitution Principle.

### Решение
Добавлена полная реализация:

```python
def subscribe_to_changes(
    self,
    entity_id: str,
    callback: Callable[[str, str], None]
) -> None:
    """
    Подписаться на изменения состояния конкретной сущности
    
    Args:
        entity_id: ID сущности (e.g., 'light.kitchen')
        callback: Функция обратного вызова (entity_id, new_state)
    """
    async def _subscribe_and_listen():
        # Получаем текущее состояние для initial callback
        entity = await self.get_entity_state(entity_id)
        if entity:
            callback(entity_id, entity.state)
        
        # Подписываемся на state_changed события
        await self.subscribe_events('state_changed', lambda data: self._filter_and_callback(data, entity_id, callback))
    
    # Запускаем в event loop если доступен
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(_subscribe_and_listen())
    except RuntimeError:
        logger.warning(...)
```

### Дополнительно
Реализован метод `_filter_and_callback()` для фильтрации событий по `entity_id`.

---

## ✅ Шаг 3: Делегирование команд через `attributes` в ActionBridge

**Файл:** `adapters/bridge.py`

### Проблема
В `HAAdapter.set_entity_state()` был хардкод сервисов (`turn_on`/`turn_off`), что не работало для `climate`, `media_player` и других устройств.

### Решение
`ActionBridge` теперь преобразует состояния FSM в команды HA через метод `_state_to_command()`:

```python
def _state_to_command(self, state: str, attributes: dict = None) -> tuple[str | None, dict]:
    # Свет и бинарные устройства
    on_states = {"ON_SCHEDULE", "ON_MOTION", "PARTY", "NIGHTLIGHT", "MANUAL"}
    
    if state in on_states:
        return "turn_on", attributes
    elif state == "OFF":
        return "turn_off", attributes
    
    # Климат - состояния HVAC
    hvac_modes = {
        "HEATING": ("set_hvac_mode", {"hvac_mode": "heat"}),
        "COOLING": ("set_hvac_mode", {"hvac_mode": "cool"}),
        "FAN_ONLY": ("set_hvac_mode", {"hvac_mode": "fan_only"}),
        # ...
    }
    
    if state in hvac_modes:
        cmd, mode_attrs = hvac_modes[state]
        merged_attrs = {**mode_attrs, **attributes}
        return cmd, merged_attrs
    
    return None, {}
```

Теперь `FSMDefinition` сама указывает какой сервис вызывать через `attributes`:

```python
Transition(
    from_state="OFF",
    to_state="HEATING",
    trigger="temperature_low",
    attributes={"hvac_mode": "heat", "temperature": 22.0}
)
```

---

## ✅ Шаг 4: Интеграционные E2E тесты

**Файл:** `tests/test_e2e_scenarios.py`

### Проблема
Отсутствовали сценарные тесты полного цикла: событие → FSM → команда адаптеру.

### Решение
Написано 5 E2E тестов с использованием `MockAdapter`:

1. **`test_motion_activates_light`** — движение включает свет
2. **`test_manual_override_blocks_automation`** — ручное управление блокирует автоматику
3. **`test_cooldown_prevents_rapid_transitions`** — cooldown предотвращает циклы
4. **`test_debounce_blocks_duplicate_triggers`** — debounce фильтрует дубликаты
5. **`test_full_day_scenario`** — полный сценарий дня

### Исправление в тестах
Обновлена проверка команд в логе `MockAdapter` — теперь фильтруются записи по типу `"command"` (а не `"state_change"`):

```python
command_entries = [c for c in commands if c.get("type") == "command"]
assert len(command_entries) == 1
```

### Результат
Все 210 тестов платформы проходят успешно:
```bash
$ pytest tests/ -v
======================= 210 passed, 7 warnings in 7.35s ========================
```

---

## 🔧 Дополнительные улучшения

### Асинхронная поддержка в Scheduler
Улучшена обработка async action в `FSMEngine._execute_transition()` (строки 373-390):

```python
if asyncio.iscoroutinefunction(transition.action):
    try:
        loop = asyncio.get_running_loop()
        task = asyncio.create_task(transition.action(context))
    except RuntimeError:
        self._logger.warning("Async action scheduled but no running loop")
else:
    transition.action(context)
```

### Поддержка climate в ActionBridge
Добавлен mapping состояний FSM на HVAC команды (строки 124-137):

```python
hvac_modes = {
    "HEATING": ("set_hvac_mode", {"hvac_mode": "heat"}),
    "COOLING": ("set_hvac_mode", {"hvac_mode": "cool"}),
    "FAN_ONLY": ("set_hvac_mode", {"hvac_mode": "fan_only"}),
    "DRY": ("set_hvac_mode", {"hvac_mode": "dry"}),
    "AUTO": ("set_hvac_mode", {"hvac_mode": "auto"}),
    "HEAT_COOL": ("set_hvac_mode", {"hvac_mode": "heat_cool"}),
}
```

---

## 📊 Статус платформы v3

| Компонент | Статус | Примечания |
|-----------|--------|------------|
| FSM Engine | ✅ Готов | Cooldown, manual_lockout, debounce работают |
| HA Adapter | ✅ Готов | `subscribe_to_changes` реализован |
| ActionBridge | ✅ Готов | Делегирование команд через attributes |
| MockAdapter | ✅ Готов | Логирование команд для тестов |
| Integration Tests | ✅ Готовы | 5 E2E сценариев + 205 unit тестов |
| Documentation | ⚠️ Требует обновления | README.md нужно актуализировать |

---

## 🚀 Следующие шаги (рекомендации)

1. **Обновить README.md** — добавить информацию об исправлениях v3
2. **Dry-run тест** — запустить `python loader.py --dry-run` для проверки транспиляции PyScript
3. **Разделить ha_adapter.py** — выделить `HAConnection`, `HAStateCache`, `HADebouncer`
4. **Логгер для HA** — адаптировать `core/logger.py` для нативных логов PyScript

---

**Дата применения исправлений:** Март 2025  
**Версия платформы:** v3.1  
**Статус:** Готова к продакшену
