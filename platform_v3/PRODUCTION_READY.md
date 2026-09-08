# Platform V3.1 - Production Ready Improvements

## Обзор

Этот документ описывает улучшения, реализованные в Platform V3.1 для устранения критических рисков при деплое на боевой сервер Home Assistant.

---

## 🚨 Реализованные исправления

### 1. Защита от "Эха" (Feedback Loop Protection)

**Проблема:** Когда FSM посылает команду `light.turn_on`, HA меняет состояние и генерирует событие `state_changed`. Без защиты FSM мог расценить это как "ручное вмешательство" и перейти в состояние `MANUAL`, заблокировав автомат на час.

**Решение в `ha_adapter.py`:**

```python
class HomeAssistantAdapter:
    def __init__(self, ..., debounce_window_sec: float = 2.0):
        # Debouncer для игнорирования "эха"
        self._sent_commands: Dict[str, float] = {}
        self._debounce_lock = asyncio.Lock()
        
    async def _record_command_sent(self, entity_id: str) -> str:
        """Записать что мы отправили команду"""
        async with self._debounce_lock:
            now = time.time()
            self._sent_commands[entity_id] = now
            context_id = self._generate_context_id()
            return context_id
    
    def _is_echo_event(self, entity_id: str, event_data: dict) -> bool:
        """Проверить является ли событие "эхом" от нашей команды"""
        if entity_id not in self._sent_commands:
            return False
        
        last_command_time = self._sent_commands.get(entity_id, 0)
        event_time = time.time()
        
        # Если событие пришло в течение debounce_window_sec после команды
        if event_time - last_command_time < self.debounce_window_sec:
            return True
        
        return False
```

**Дополнительная защита через context.id:**
```python
async def _listen_events(self):
    if event_type == 'state_changed':
        entity_id = event_data.get('data', {}).get('entity_id', '')
        
        # Игнорируем эхо от наших команд
        if self._is_echo_event(entity_id, event_data):
            continue
        
        # Проверяем context.id для дополнительного распознавания
        context = event_data.get('data', {}).get('context', {})
        context_id = context.get('id', '')
        
        # Если context.id содержит нашу метку "platform_v3:", это точно эхо
        if context_id.startswith('platform_v3:'):
            continue
```

**Тест:** `tests/test_integration.py::TestFeedbackLoop`

---

### 2. Exponential Backoff для WebSocket Reconnect

**Проблема:** При обрыве связи соединение падало в `ConnectionState.ERROR` и не восстанавливалось автоматически.

**Решение в `ha_adapter.py`:**

```python
async def _reconnect(self):
    """Попытка переподключения с Exponential Backoff"""
    self._reconnect_attempts += 1
    
    delay = min(
        self.reconnect_base_delay * (2 ** (self._reconnect_attempts - 1)),
        self.reconnect_max_delay
    )
    
    # 1 попытка: 2 сек, 2 попытка: 4 сек, 3 попытка: 8 сек, ... макс: 60 сек
    await asyncio.sleep(delay)
    
    while not self.is_connected:
        success = await self.connect()
        if success:
            self._reconnect_attempts = 0  # Сброс при успехе
            break
        
        self._reconnect_attempts += 1
        delay = min(...)
        await asyncio.sleep(delay)
```

**Параметры конфигурации:**
- `reconnect_base_delay`: 2.0 секунды (начальная задержка)
- `reconnect_max_delay`: 60.0 секунд (максимальная задержка)

---

### 3. StateSync при старте (State Persistence)

**Проблема:** После перезагрузки HA FSM инициализируется с `initial="OFF"`, даже если физически свет горит.

**Решение в `ha_adapter.py`:**

```python
async def sync_all_states(self) -> Dict[str, HAEntity]:
    """
    Синхронизировать все состояния из HA (StateSync при старте)
    
    Используется при инициализации платформы для приведения FSM
    в соответствие с физическим состоянием устройств.
    """
    logger.info("Starting state synchronization with HA")
    entities = await self.get_all_entities()
    
    result = {}
    for entity in entities:
        result[entity.entity_id] = entity
        self._entities_cache[entity.entity_id] = entity
    
    logger.info(f"State sync complete: {len(result)} entities")
    return result
```

**Использование при старте платформы:**
```python
# В loader.py или init скрипте
adapter = HomeAssistantAdapter(...)
await adapter.connect()

# Синхронизация состояний перед регистрацией FSM
states = await adapter.sync_all_states()

# Для каждого автомата проверяем актуальное состояние
for entity_id, entity in states.items():
    if entity_id in fsm_definitions:
        # "Прогреваем" FSM в актуальное состояние без запуска actions
        fsm.warmup_state(entity_id, entity.state)
```

---

### 4. EventBus с обработкой исключений

**Проблема:** Исключение в одном хендлере событий могло остановить обработку всех последующих.

**Решение уже было в `event_bus.py`:**

```python
def publish(self, event_type: str, data: dict = None) -> None:
    handlers = self._subscribers.get(event_type, [])
    for handler in handlers:
        try:
            handler(data)
        except Exception as e:
            # Логируем ошибку, но не прерываем обработку других хендлеров
            print(f"[EventBus] Error in handler for {event_type}: {e}")
```

**Тест:** `tests/test_integration.py::TestEventBusPriority::test_handler_exception_does_not_stop_others`

---

### 5. Guard Exception Handling

**Проблема:** Исключение в guard функции могло крашить весь движок FSM.

**Решение уже было в `fsm.py`:**

```python
try:
    if not transition.guard(context):
        continue
except Exception as e:
    self._logger.error(
        f"Guard failed for {entity_id}: {e}",
        entity_id=entity_id,
        trigger=trigger,
        error=str(e)
    )
    continue  # Пропускаем переход с faulty guard
```

**Тест:** `tests/test_integration.py::TestGuardExceptions`

---

## 📊 Новые тесты

### Integration Tests (`tests/test_integration.py`)

1. **TestFeedbackLoop**
   - `test_fsm_command_does_not_trigger_manual_override` - FSM команда не вызывает manual override
   - `test_manual_intervention_detected_by_external_orchestrator` - Ручное вмешательство детектируется

2. **TestGuardExceptions**
   - `test_guard_exception_does_not_crash_fsm` - Исключение в guard не крашит FSM
   - `test_multiple_guards_with_one_failing` - Если один guard падает, другие работают

3. **TestEventBusPriority**
   - `test_subscribers_called_in_order` - Подписчики вызываются по порядку
   - `test_handler_exception_does_not_stop_others` - Исключение не останавливает других

4. **TestFullLifecycle**
   - `test_motion_activation_lifecycle` - Полный цикл: датчик -> FSM -> команда
   - `test_state_history_preserved` - История переходов сохраняется

5. **TestSchedulerIntegration**
   - `test_scheduler_cancels_previous_timer` - Новый таймер отменяет старый

---

## ✅ Чек-лист Production Ready

| Требование | Статус | Файл |
|------------|--------|------|
| Feedback Loop Protection | ✅ | `adapters/ha_adapter.py` |
| Exponential Backoff Reconnect | ✅ | `adapters/ha_adapter.py` |
| StateSync при старте | ✅ | `adapters/ha_adapter.py` |
| Guard Exception Handling | ✅ | `core/fsm.py` |
| EventBus Exception Safety | ✅ | `core/event_bus.py` |
| Integration Tests | ✅ | `tests/test_integration.py` |
| Все тесты проходят (46/46) | ✅ | - |

---

## 🔧 Конфигурация HA Adapter

```python
adapter = HomeAssistantAdapter(
    base_url="http://localhost:8123",
    token="YOUR_TOKEN",
    event_bus=event_bus,
    
    # Exponential Backoff параметры
    reconnect_base_delay=2.0,    # Начальная задержка (сек)
    reconnect_max_delay=60.0,    # Максимальная задержка (сек)
    
    # Debouncer параметры
    debounce_window_sec=2.0,     # Окно игнорирования эха (сек)
    
    timeout=10
)
```

---

## 📈 Следующие шаги (рекомендации)

1. **State Persistence в HA** - Сохранение состояний FSM в `input_text` или `pyscript.state` для восстановления после рестарта.

2. **FSM State Sensors** - Публикация сенсоров `sensor.<entity_id>_fsm_state` и `sensor.<entity_id>_fsm_reason` в HA для отображения на дашборде.

3. **Trace ID** - Добавление уникального ID к каждому событию для трассировки всей цепочки Event -> Guard -> Transition -> Command.

4. **Lovelace Dashboard Generator** - Автоматическая генерация YAML для дашборда с карточками всех автоматов.

---

## 🧪 Запуск тестов

```bash
cd platform_v3

# Все тесты
python -m pytest tests/ -p no:libtmux -v

# Только integration тесты
python -m pytest tests/test_integration.py -v

# Конкретный тест
python -m pytest tests/test_integration.py::TestFeedbackLoop -v
```

**Результат:** 46 тестов пройдено, 1 warning (некритичный, связан с asyncio в синхронном контексте).
