# Исследование: Интеграция устройств из Home Assistant

**Дата**: 2026-09-29 | **Функция**: 001-device-integration | **Версия**: 1.0

## Исследовательские вопросы и выводы

### 1. Интеграция с существующим HAAdapter

**Вопрос**: Как организована работа с REST API Home Assistant в текущем проекте?

**Исследование**: Проект уже имеет полнофункциональный `HAAdapter` в `src/adapters/ha_adapter.py` (23.5 KB)

**Выводы**:
- **Текущая поддержка**: HAAdapter поддерживает два режима подключения:
  - **Pyscript mode** (рекомендуемый): Запуск Python скрипта в Home Assistant через сервис `hass.services.async_call`
  - **WebSocket mode**: Прямое соединение через WebSocket API
- **Обработка ошибок**: Реализована exponential backoff при переподключении
- **Трассировка**: Каждое событие имеет уникальный `trace_id` для отладки
- **Режимы развертывания**: Поддерживаются SHADOW (резервный), ACTIVE (полный контроль), DISABLED (fallback)

**Рекомендация**: 
- Использовать существующий HAAdapter как базу
- Расширить его функциональность для загрузки и кэширования полного списка устройств
- Добавить поддержку WebSocket для синхронизации состояния в реальном времени (уже частично реализована)

**Решение**:
- REST API: использовать существующий HAAdapter для GET запросов к `/api/states` (список всех сущностей)
- WebSocket: использовать встроенную поддержку WebSocket для subscribe на события `state_changed`
- Токены: использовать существующий механизм хранения credentials в HAAdapter

---

### 2. Модель данных для конфигурирования устройств

**Вопрос**: Какие Pydantic модели используются для устройств и как их расширить?

**Исследование**: Проект использует Pydantic v2 для всех моделей данных в `src/core/models/`

**Выводы**:
- **Существующие модели**:
  - `Device` - базовая модель сущности
  - `Command` - команда для выполнения
  - `State` - текущее состояние
  - `Behavior` - поведение FSM
  
- **Валидация**: Строгая валидация через Pydantic v2 с миграциями для обратной совместимости
- **Сохранение**: Состояние сохраняется в JSON формате в `data/history.db`
- **Загрузка**: Используется `src/core/persistence/` для работы с хранилищем

**Рекомендация**: 
- Расширить существующие модели новыми полями (description, location, tags)
- Создать новую модель `DeviceConfig` для пользовательских настроек
- Создать `HASource` модель для хранения конфигурации подключения к HA

**Решение**:
```python
# Новые модели в src/core/models/device.py

class HASource(BaseModel):
    """Источник Home Assistant"""
    id: UUID = Field(default_factory=uuid4)
    name: str
    url: HttpUrl
    token: str  # Будет зашифрован в persistence
    status: Literal["connected", "disconnected", "error"] = "disconnected"
    last_sync: datetime | None = None
    error_message: str | None = None
    created_at: datetime = Field(default_factory=datetime.utcnow)

class DeviceConfig(BaseModel):
    """Конфигурация устройства"""
    display_name: str
    description: str = ""
    location: str = ""
    tags: list[str] = []
    user_id: UUID | None = None
    updated_at: datetime = Field(default_factory=datetime.utcnow)

class ExtendedDevice(BaseModel):
    """Расширенная модель устройства"""
    # Существующие поля
    id: UUID
    ha_entity_id: str
    type: str
    
    # Новые поля
    config: DeviceConfig
    status: Literal["available", "unavailable", "removed_from_ha"] = "available"
    source_id: UUID  # Ссылка на HASource
```

---

### 3. EventBus для событий интеграции

**Вопрос**: Как использовать EventBus для событий синхронизации?

**Исследование**: Проект имеет встроенный `EventBus` в `src/core/events/`

**Выводы**:
- **Архитектура**: EventBus - асинхронное распределение событий с поддержкой subscribers
- **Использование**: Все события проходят через EventBus для отделения concerns
- **Трассировка**: Встроена поддержка `trace_id` для отладки цепочки событий
- **Типизация**: События типизированы через Pydantic модели

**Рекомендация**: 
- Создать новый тип события `DeviceSyncEvent` для событий синхронизации
- Использовать EventBus для публикации событий загрузки, изменения конфигурации, синхронизации состояния
- Позволить компонентам подписываться на интересующие события

**Решение**:
```python
# События в src/core/events/device_events.py

class DeviceLoadedEvent(BaseModel):
    """Устройство загружено из HA"""
    device_id: UUID
    ha_entity_id: str
    source_id: UUID
    timestamp: datetime = Field(default_factory=datetime.utcnow)

class DeviceConfigChangedEvent(BaseModel):
    """Конфигурация устройства изменена"""
    device_id: UUID
    changes: dict
    user_id: UUID
    timestamp: datetime = Field(default_factory=datetime.utcnow)

class DeviceStateChangedEvent(BaseModel):
    """Состояние устройства изменилось"""
    device_id: UUID
    old_state: dict
    new_state: dict
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    
# Использование:
# await event_bus.publish(DeviceLoadedEvent(...))
# await event_bus.subscribe(DeviceLoadedEvent, callback)
```

---

### 4. WebSocket интеграция для синхронизации состояния

**Вопрос**: Существуют ли в проекте примеры WebSocket и как их использовать?

**Исследование**: Проект использует WebSocket в HAAdapter и для Web UI

**Выводы**:
- **Библиотека**: Используется `websockets>=12.0`
- **Использование в HAAdapter**: WebSocket mode поддерживается наряду с Pyscript mode
- **Web UI**: FastAPI с WebSocket поддержкой для real-time обновлений UI
- **Асинхронность**: Полная поддержка asyncio для неблокирующего взаимодействия

**Рекомендация**: 
- Использовать WebSocket API Home Assistant для подписки на события `state_changed`
- Создать отдельный компонент `HAWebSocketClient` для управления WebSocket соединением
- Реализовать автоматическое переподключение с exponential backoff
- Использовать FastAPI WebSocket для отправки обновлений клиентам

**Решение**:
```python
# src/adapters/home_assistant/websocket_client.py

class HAWebSocketClient:
    """WebSocket клиент для синхронизации состояния с HA"""
    
    def __init__(self, url: str, token: str):
        self.url = url
        self.token = token
        self.websocket = None
        self.event_bus = None  # Инжектируется
        
    async def connect(self):
        """Подключиться к HA WebSocket"""
        # Реализация подключения и handshake
        
    async def subscribe_to_events(self):
        """Подписаться на события изменения состояния"""
        # Отправить subscribe команду
        
    async def listen(self):
        """Слушать события из WebSocket"""
        # При получении события - публиковать в EventBus
```

---

### 5. Безопасность и хранение токенов

**Вопрос**: Как безопасно хранить токены HA в системе?

**Исследование**: Проект использует Pydantic для валидации и хранения в JSON файле

**Выводы**:
- **Текущий подход**: HAAdapter хранит токены в памяти и JSON конфиге
- **Зашифрование**: Не используется на уровне приложения
- **Рекомендация**: Использовать шифрование для чувствительных данных
- **Альтернатива**: Использовать переменные окружения или vault систему

**Рекомендация**: 
- Использовать `cryptography` библиотеку для шифрования токенов
- Хранить encrypted токены в JSON
- При загрузке - дешифровать в памяти
- Никогда не логировать токены

**Решение**:
```python
# src/core/security/encryption.py

from cryptography.fernet import Fernet

class TokenEncryption:
    def __init__(self, key: str | None = None):
        # Использовать ключ из .env или сгенерировать
        self.cipher = Fernet(key or os.getenv("ENCRYPTION_KEY"))
        
    def encrypt(self, token: str) -> str:
        return self.cipher.encrypt(token.encode()).decode()
        
    def decrypt(self, encrypted_token: str) -> str:
        return self.cipher.decrypt(encrypted_token.encode()).decode()

# Использование в HASource:
class HASource(BaseModel):
    token: str  # Будет зашифрован перед сохранением
```

---

### 6. Архитектурные паттерны проекта

**Вопрос**: Какие архитектурные паттерны используются и нужно ли их соблюдать?

**Исследование**: Проект следует микросервисной архитектуре с четким разделением concerns

**Выводы**:
- **Adapter Pattern**: Адаптеры для интеграции с внешними системами (HA)
- **Service Layer**: Business logic в сервис-слое, отделенной от адаптеров
- **Event-driven**: Вся система построена на событиях через EventBus
- **Middleware**: Глобальные правила применяются автоматически (ManualLockoutMiddleware)
- **Plugin System**: Поддержка расширений через behavior composition

**Рекомендация**: 
- Соблюдать существующие паттерны архитектуры
- Новый код для Device Integration должен следовать этим же паттернам
- Создать `DeviceService` в `src/services/` для бизнес-логики
- Использовать `HAAdapter` расширение для работы с REST API

**Решение**: Архитектура функции будет следовать существующим паттернам:
```
HAAdapter (адаптер) 
  ↓
DeviceService (бизнес-логика)
  ↓
EventBus (события)
  ↓
WebUI / CLI (интерфейс)
```

---

## Решения по технологиям

| Компонент | Технология | Альтернативы | Обоснование |
|-----------|-----------|------------|-----------|
| **REST API клиент** | aiohttp (существует) | requests | Асинхронность, совместимость с asyncio |
| **WebSocket синхронизация** | websockets>=12.0 | HAAdapter WebSocket mode | Нативная поддержка, надежность |
| **Хранилище конфигурации** | JSON + persistence | SQLite | Совместимость с текущей архитектурой |
| **Валидация данных** | Pydantic v2 | dataclasses | Уже используется в проекте, strict mode |
| **Шифрование токенов** | cryptography | Переменные окружения | Безопасность, гибкость |
| **Логирование** | Loguru | logging | Уже используется, структурированное логирование |

---

## Архитектурные решения

1. **Структура кода**: Использовать существующую структуру `src/` с новыми модулями
2. **Интеграция HA**: Расширить HAAdapter вместо создания нового адаптера
3. **Синхронизация состояния**: WebSocket подписки через HAAdapter/WebSocket
4. **Хранение данных**: JSON persistence, совместимое с текущей системой
5. **Асинхронность**: Full asyncio stack, совместимо с FastAPI + aiohttp
6. **Тестирование**: pytest + pytest-asyncio, интеграционные и unit тесты

---

## Выводы исследования

✅ **Все необходимые компоненты существуют** - проект уже имеет HAAdapter, EventBus, WebSocket поддержку
✅ **Архитектура готова к интеграции** - можно безопасно добавить новую функцию без переделки
✅ **Технологический стек совместим** - используются те же библиотеки, паттерны, подходы
✅ **Best practices соблюдаются** - проект следует современным паттернам (event-driven, async-first, plugin-based)

**Фаза 0 завершена. Перейти к Фазе 1: Проектирование и контракты.**

---

**Версия**: 1.0 | **Статус**: Завершено | **Автор**: Claude | **Дата**: 2026-09-29
