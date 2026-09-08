# Platform V3 - Critical Fixes Summary

## Обзор

Этот документ суммирует критические исправления, реализованные в Platform V3 для устранения рисков зависаний и ошибок при деплое на боевой сервер Home Assistant.

---

## ✅ Реализованные исправления (V3.0)

### 1. Защита от Feedback Loop (Echo Detection)

**Файл:** `adapters/ha_adapter.py`

**Проблема:** Когда FSM посылает команду `light.turn_on`, HA меняет состояние и генерирует событие `state_changed`. Без защиты это могло быть расценено как "ручное вмешательство".

**Решение:**
- `_sent_commands` словарь для отслеживания отправленных команд
- `_is_echo_event()` метод для проверки является ли событие эхом
- Проверка `context.id` на наличие метки `platform_v3:`
- Debounce окно 2 секунды по умолчанию

```python
async def _listen_events(self):
    if event_type == 'state_changed':
        entity_id = event_data.get('data', {}).get('entity_id', '')
        
        # Игнорируем эхо от наших команд
        if self._is_echo_event(entity_id, event_data):
            continue
        
        # Проверяем context.id
        context_id = event_data.get('data', {}).get('context', {}).get('id', '')
        if context_id.startswith('platform_v3:'):
            continue  # Это наше событие
```

**Тест:** `tests/test_debounce.py::TestEchoDetection`

---

### 2. Exponential Backoff для WebSocket Reconnect

**Файл:** `adapters/ha_adapter.py`

**Проблема:** При обрыве связи соединение падало в `ConnectionState.ERROR` без авто-восстановления.

**Решение:**
- Базовая задержка: 2 секунды
- Максимальная задержка: 60 секунд
- Экспоненциальное увеличение: `delay = base * 2^(attempts-1)`

```python
async def _reconnect(self):
    self._reconnect_attempts += 1
    
    delay = min(
        self.reconnect_base_delay * (2 ** (self._reconnect_attempts - 1)),
        self.reconnect_max_delay
    )
    
    await asyncio.sleep(delay)
    # Попытка переподключения...
```

---

### 3. StateSync при старте

**Файл:** `adapters/ha_adapter.py`

**Проблема:** После рестарта HA FSM инициализируется с `initial="OFF"`, даже если физически свет горит.

**Решение:**
- Метод `sync_all_states()` для получения всех состояний из HA
- Кэширование состояний в `_entities_cache`
- Возможность "прогрева" FSM перед регистрацией слушателей

```python
async def sync_all_states(self) -> Dict[str, HAEntity]:
    """Синхронизировать все состояния из HA (StateSync при старте)"""
    logger.info("Starting state synchronization with HA")
    entities = await self.get_all_entities()
    # ...
```

---

### 4. EventBus Exception Safety

**Файл:** `core/event_bus.py`

**Проблема:** Исключение в одном хендлере останавливало обработку всех последующих.

**Решение:**
- Обёртка каждого хендлера в `try...except`
- Логирование ошибки без прерывания цикла
- Продолжение обработки остальных подписчиков

```python
def publish(self, event_type: str, data: dict = None) -> None:
    for handler in handlers:
        try:
            handler(data)
        except Exception as e:
            # Логируем, но продолжаем
            self._logger.error(f"Error in handler: {e}")
```

**Тест:** `tests/test_debounce.py::TestEventBusResilience::test_multiple_handlers_one_fails`

---

### 5. Guard Exception Handling

**Файл:** `core/fsm.py`

**Проблема:** Исключение в guard функции крашило весь движок FSM.

**Решение:**
- Обёртка вызова `transition.guard()` в `try...except`
- Пропуск перехода с faulty guard
- Логирование ошибки через Logger

```python
try:
    if not transition.guard(context):
        continue
except Exception as e:
    self._logger.error(f"Guard failed for {entity_id}: {e}")
    continue  # Пропускаем переход
```

**Тест:** `tests/test_integration.py::TestGuardExceptions`

---

## 🆕 Новые тесты (V3.1)

### TestDebounceSpam

| Тест | Описание | Статус |
|------|----------|--------|
| `test_motion_sensor_spam_100_events` | 100 событий движения подряд | ✅ PASS |
| `test_rapid_on_off_cycles` | 50 циклов вкл/выкл | ✅ PASS |
| `test_guard_exception_during_spam` | Спам + падающий guard | ✅ PASS |

### TestEchoDetection

| Тест | Описание | Статус |
|------|----------|--------|
| `test_fsm_command_sequence_stable` | Команды FSM не вызывают manual override | ✅ PASS |
| `test_multiple_triggers_same_state` | Дублирующиеся триггеры игнорируются | ✅ PASS |

### TestEventBusResilience

| Тест | Описание | Статус |
|------|----------|--------|
| `test_multiple_handlers_one_fails` | Один faulty хендлер не ломает других | ✅ PASS |
| `test_async_handler_in_sync_context` | Async хендлер в sync контексте | ✅ PASS |

---

## 📊 Результаты тестов

**Всего тестов:** 53  
**Пройдено:** 53 ✅  
**Предупреждения:** 2 (некритичные, связаны с asyncio в синхронном контексте)

```bash
cd platform_v3
python -m pytest tests/ -p no:libtmux -v

# Результат:
# ======================== 53 passed, 2 warnings in 3.32s =========================
```

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

## ⚠️ Оставшиеся рекомендации (не реализованы, но важны)

### 1. Точечные подписки на entity_id

**Проблема:** Подписка `@state_changed("*")` будет получать события от ВСЕХ устройств, включая те, которые шлют обновления несколько раз в секунду (Shelly EM, Zigbee linkquality).

**Рекомендация:** 
```python
# В loader.py или init скрипте
registry = Registry()
registry.register_all(fsm_definitions)

# Подписываемся ТОЛЬКО на нужные entity_id
for entity_id in registry.get_all_entity_ids():
    ha_adapter.subscribe_to_state_changes(entity_id)
```

### 2. Лимит input_text (255 символов)

**Проблема:** Если хранить сложный `context` FSM в `input_text`, он обрежется на 255 символах.

**Рекомендация:**
- Для простых стейтов использовать `input_select`
- Сложный контекст хранить в памяти (с потерей при рестарте) или в локальном `.json` файле

### 3. Watchdog сервис

**Рекомендация:** Создать сервис `pyscript.fsm_watchdog`, который раз в минуту логирует состояния всех автоматов:

```python
@service
def fsm_watchdog():
    states = fsm_engine.get_all_states()
    logger.warning(json.dumps({
        entity_id: state.current 
        for entity_id, state in states.items()
    }))
```

---

## ✅ Чек-лист Production Ready

| Требование | Статус | Файл |
|------------|--------|------|
| Feedback Loop Protection | ✅ | `adapters/ha_adapter.py` |
| Exponential Backoff Reconnect | ✅ | `adapters/ha_adapter.py` |
| StateSync при старте | ✅ | `adapters/ha_adapter.py` |
| Guard Exception Handling | ✅ | `core/fsm.py` |
| EventBus Exception Safety | ✅ | `core/event_bus.py` |
| Debounce Tests (спам 100 событий) | ✅ | `tests/test_debounce.py` |
| Echo Detection Tests | ✅ | `tests/test_debounce.py` |
| Все тесты проходят (53/53) | ✅ | - |

---

## 🧪 Запуск тестов

```bash
cd platform_v3

# Все тесты
python -m pytest tests/ -p no:libtmux -v

# Только debounce тесты
python -m pytest tests/test_debounce.py -v

# Конкретный тест
python -m pytest tests/test_debounce.py::TestDebounceSpam::test_motion_sensor_spam_100_events -v
```

---

## 📈 Сравнение версий

| Версия | Тестов | Проблемы |
|--------|--------|----------|
| V1 | ~10 | Зависания при спаме, нет защиты от эха |
| V2 | ~20 | Частичная защита, нет exponential backoff |
| V3 | 53 | ✅ Все критические риски устранены |

