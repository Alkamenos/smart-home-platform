# API интеграции Home Assistant

Документация REST API для управления устройствами и интеграцией с Home Assistant в платформе Smart Home Platform.

- **Версия API:** 1.0.0
- **Дата документации:** 2026-09-29
- **Базовый URL:** `http://[host]:[port]/api/v1`

---

## Содержание

1. [Обзор API](#обзор-api)
2. [Авторизация](#авторизация)
3. [Модели данных](#модели-данных)
4. [Endpoints управления источниками](#endpoints-управления-источниками)
5. [Endpoints управления устройствами](#endpoints-управления-устройствами)
6. [Обработка ошибок](#обработка-ошибок)
7. [Rate Limiting и Best Practices](#rate-limiting-и-best-practices)

---

## Обзор API

### Описание

API предназначен для:
- Управления источниками Home Assistant (подключения и синхронизация)
- Получения информации об устройствах
- Обновления конфигурации устройств
- Отправки команд устройствам через Home Assistant

### Версионирование

API использует простое версионирование через URL: `/api/v1/...`

### Content-Type

Все запросы и ответы используют формат JSON:
```
Content-Type: application/json
```

---

## Авторизация

### Текущий статус

На данный момент API работает БЕЗ встроенной авторизации. В production среде рекомендуется добавить:

1. **Bearer Token** - для REST API запросов
2. **API Key** - для интеграций третьих сторон
3. **OAuth2** - для веб-приложений (опционально)

### Пример с авторизацией (для будущей реализации)

```bash
curl -H "Authorization: Bearer YOUR_API_TOKEN" \
  http://localhost:8000/api/v1/devices/sources
```

### Переменные окружения для токенов

```
HA_API_TOKEN=your_token_here
PLATFORM_API_KEY=your_key_here
```

---

## Модели данных

### HASource (Источник Home Assistant)

Модель конфигурации для подключения к Home Assistant инстансу.

**Файл:** `src/core/models/ha_source.py`

```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "name": "Home Assistant Pro",
  "url": "http://192.168.1.100:8123",
  "token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "status": "connected",
  "last_sync": "2026-09-29T10:05:00Z",
  "last_error": null,
  "device_count": 47,
  "created_at": "2026-09-29T10:00:00Z",
  "updated_at": "2026-09-29T10:05:00Z"
}
```

**Поля:**

| Поле | Тип | Описание |
|------|-----|---------|
| `id` | UUID | Уникальный идентификатор источника |
| `name` | string (1-255) | Отображаемое название источника |
| `url` | URL | Адрес для подключения к HA |
| `token` | string (≥10) | Long-lived access token HA (шифруется) |
| `status` | enum | Статус: `connected`, `disconnected`, `error` |
| `last_sync` | datetime (optional) | Время последней синхронизации |
| `last_error` | string (optional) | Сообщение об ошибке |
| `device_count` | integer | Количество загруженных устройств |
| `created_at` | datetime | Время создания |
| `updated_at` | datetime | Время последнего обновления |

**Статусы соединения:**
- `connected` - успешное подключение к HA
- `disconnected` - соединение не установлено
- `error` - ошибка при подключении (см. `last_error`)

---

### Device (Устройство)

Модель устройства, синхронизированного из Home Assistant.

**Файл:** `src/core/models/device.py`

```json
{
  "id": "550e8400-e29b-41d4-a716-446655440001",
  "ha_entity_id": "light.kitchen_light",
  "source_id": "550e8400-e29b-41d4-a716-446655440000",
  "name": "Kitchen Light",
  "device_type": "light",
  "model": "Philips Hue A19",
  "manufacturer": "Philips",
  "state": {
    "state": "on",
    "brightness": 200
  },
  "attributes": {
    "friendly_name": "Kitchen Light",
    "supported_features": 33
  },
  "status": "available",
  "last_state_update": "2026-09-29T10:15:30Z",
  "created_at": "2026-09-29T10:00:00Z",
  "updated_at": "2026-09-29T10:15:30Z"
}
```

**Поля:**

| Поле | Тип | Описание |
|------|-----|---------|
| `id` | UUID | ID устройства в платформе |
| `ha_entity_id` | string | ID сущности в HA (e.g., `light.kitchen_light`) |
| `source_id` | UUID | Ссылка на HASource |
| `name` | string (1-255) | Название устройства из HA |
| `device_type` | string | Тип: `light`, `switch`, `climate`, и т.д. |
| `model` | string (optional) | Модель устройства |
| `manufacturer` | string (optional) | Производитель |
| `state` | object | Текущее состояние (зависит от типа) |
| `attributes` | object | Дополнительные атрибуты из HA |
| `status` | enum | `available`, `unavailable`, `removed_from_ha` |
| `last_state_update` | datetime | Время последнего обновления состояния |
| `created_at` | datetime | Время добавления в платформу |
| `updated_at` | datetime | Время обновления записи |

**Примеры типов устройств:**
- `light` - лампы и осветительные системы
- `switch` - выключатели
- `climate` - кондиционеры и термостаты
- `cover` - жалюзи и шторы
- `sensor` - датчики
- `binary_sensor` - датчики с двумя состояниями
- `lock` - замки

---

### DeviceConfig (Конфигурация устройства)

Модель для обновления конфигурации устройства.

**Файл:** `src/webui/models.py`

```json
{
  "id": "light.kitchen_light",
  "type": "light",
  "name": "Кухонное освещение",
  "behaviors": [
    {
      "template": "lighting",
      "priority": 1,
      "params": {
        "mode": "auto",
        "brightness_level": 100
      }
    }
  ]
}
```

**Поля:**

| Поле | Тип | Описание |
|------|-----|---------|
| `id` | string | ID сущности устройства (HA entity ID) |
| `type` | string | Тип устройства |
| `name` | string | Название устройства в платформе |
| `behaviors` | array | Поведения устройства |

**BehaviorConfig:**

| Поле | Тип | Описание |
|------|-----|---------|
| `template` | string | Шаблон поведения (lighting, climate_control и т.д.) |
| `priority` | integer | Приоритет выполнения |
| `params` | object | Параметры поведения |

---

### DeviceCommand (Команда устройству)

Модель для отправки команды устройству.

```json
{
  "service": "light.turn_on",
  "data": {
    "entity_id": "light.kitchen_light",
    "brightness": 255,
    "transition": 2
  }
}
```

**Поля:**

| Поле | Тип | Описание |
|------|-----|---------|
| `service` | string | Сервис HA (формат: `domain.service`) |
| `data` | object | Данные для сервиса |

**Примеры сервисов:**
- `light.turn_on` / `light.turn_off` - управление светом
- `climate.set_temperature` - установка температуры
- `cover.open_cover` / `cover.close_cover` - управление жалюзи
- `lock.lock` / `lock.unlock` - управление замками

---

### DeviceAccess (Доступ к устройству)

Модель для управления правами доступа к устройствам.

```json
{
  "device_id": "550e8400-e29b-41d4-a716-446655440001",
  "user_id": "user_123",
  "permission_level": "control",
  "read_only": false,
  "granted_at": "2026-09-29T10:00:00Z"
}
```

**Поля:**

| Поле | Тип | Описание |
|------|-----|---------|
| `device_id` | UUID | ID устройства |
| `user_id` | string | ID пользователя |
| `permission_level` | enum | `view`, `control`, `admin` |
| `read_only` | boolean | Если true, только чтение состояния |
| `granted_at` | datetime | Время предоставления доступа |

---

## Endpoints управления источниками

### 1. Создание источника Home Assistant

Создает новый источник для подключения к Home Assistant.

**Endpoint:** `POST /api/v1/devices/sources`

**Статус код:** `201 Created`

**Заголовки запроса:**
```
Content-Type: application/json
```

**Тело запроса:**

```json
{
  "name": "Home Assistant Pro",
  "url": "http://192.168.1.100:8123",
  "token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."
}
```

**Параметры:**

| Параметр | Тип | Обязательный | Описание |
|----------|-----|--------------|---------|
| `name` | string | Да | Название источника (1-255 символов) |
| `url` | URL | Да | Адрес Home Assistant |
| `token` | string | Да | Long-lived access token (мин. 10 символов) |

**Пример curl:**

```bash
curl -X POST http://localhost:8000/api/v1/devices/sources \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Home Assistant Pro",
    "url": "http://192.168.1.100:8123",
    "token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."
  }'
```

**Ответ (201 Created):**

```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "name": "Home Assistant Pro",
  "url": "http://192.168.1.100:8123",
  "status": "disconnected",
  "last_sync": null,
  "last_error": null,
  "created_at": "2026-09-29T10:00:00Z",
  "updated_at": "2026-09-29T10:00:00Z"
}
```

**Коды ошибок:**

| Код | Описание | Решение |
|-----|---------|---------|
| 400 | Валидация не пройдена | Проверьте формат URL и длину токена |
| 500 | Ошибка сервера | Проверьте логи сервера |

---

### 2. Получение информации об источнике

Получает информацию о конкретном источнике.

**Endpoint:** `GET /api/v1/devices/sources/{source_id}`

**Статус код:** `200 OK`

**Параметры пути:**

| Параметр | Тип | Описание |
|----------|-----|---------|
| `source_id` | UUID | ID источника |

**Пример curl:**

```bash
curl http://localhost:8000/api/v1/devices/sources/550e8400-e29b-41d4-a716-446655440000
```

**Ответ (200 OK):**

```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "name": "Home Assistant Pro",
  "url": "http://192.168.1.100:8123",
  "status": "connected",
  "last_sync": "2026-09-29T10:05:00Z",
  "last_error": null,
  "created_at": "2026-09-29T10:00:00Z",
  "updated_at": "2026-09-29T10:05:00Z"
}
```

**Коды ошибок:**

| Код | Описание | Решение |
|-----|---------|---------|
| 404 | Источник не найден | Проверьте ID источника |
| 500 | Ошибка сервера | Проверьте логи сервера |

---

### 3. Запуск синхронизации источника

Запускает процесс синхронизации устройств из Home Assistant.

**Endpoint:** `POST /api/v1/devices/sources/{source_id}/sync`

**Статус код:** `200 OK`

**Параметры пути:**

| Параметр | Тип | Описание |
|----------|-----|---------|
| `source_id` | UUID | ID источника |

**Тело запроса:** Не требуется

**Пример curl:**

```bash
curl -X POST http://localhost:8000/api/v1/devices/sources/550e8400-e29b-41d4-a716-446655440000/sync
```

**Ответ (200 OK):**

```json
{
  "status": "connecting",
  "message": "Синхронизация запущена для источника 550e8400-e29b-41d4-a716-446655440000"
}
```

**Асинхронный процесс:**

Синхронизация работает асинхронно:
1. Сервер подключается к HA
2. Получает список устройств
3. Сохраняет устройства в базу данных
4. Публикует события синхронизации

Рекомендуется проверять статус источника через `GET /api/v1/devices/sources/{source_id}` для отслеживания прогресса.

**Коды ошибок:**

| Код | Описание | Решение |
|-----|---------|---------|
| 404 | Источник не найден | Проверьте ID источника |
| 500 | Ошибка при синхронизации | Проверьте подключение к HA, токен |

---

## Endpoints управления устройствами

### 1. Получение списка всех устройств

Получает список всех синхронизированных устройств, с опциональной фильтрацией.

**Endpoint:** `GET /api/v1/devices`

**Статус код:** `200 OK`

**Query параметры:**

| Параметр | Тип | Обязательный | Описание |
|----------|-----|--------------|---------|
| `source_id` | UUID | Нет | Фильтр по источнику |

**Пример curl:**

```bash
# Все устройства
curl http://localhost:8000/api/v1/devices

# Устройства из конкретного источника
curl "http://localhost:8000/api/v1/devices?source_id=550e8400-e29b-41d4-a716-446655440000"
```

**Ответ (200 OK):**

```json
[
  {
    "id": "550e8400-e29b-41d4-a716-446655440001",
    "name": "Kitchen Light",
    "device_type": "light",
    "status": "available",
    "state": {
      "state": "on",
      "brightness": 200
    },
    "source_id": "550e8400-e29b-41d4-a716-446655440000",
    "ha_entity_id": "light.kitchen_light",
    "created_at": "2026-09-29T10:00:00Z",
    "updated_at": "2026-09-29T10:15:30Z"
  },
  {
    "id": "550e8400-e29b-41d4-a716-446655440002",
    "name": "Bedroom Switch",
    "device_type": "switch",
    "status": "available",
    "state": {
      "state": "off"
    },
    "source_id": "550e8400-e29b-41d4-a716-446655440000",
    "ha_entity_id": "switch.bedroom_switch",
    "created_at": "2026-09-29T10:01:00Z",
    "updated_at": "2026-09-29T10:15:00Z"
  }
]
```

**Коды ошибок:**

| Код | Описание | Решение |
|-----|---------|---------|
| 500 | Ошибка при получении списка | Проверьте логи сервера |

---

### 2. Получение информации об устройстве

Получает подробную информацию о конкретном устройстве.

**Endpoint:** `GET /api/v1/devices/{device_id}`

**Статус код:** `200 OK`

**Параметры пути:**

| Параметр | Тип | Описание |
|----------|-----|---------|
| `device_id` | UUID | ID устройства |

**Пример curl:**

```bash
curl http://localhost:8000/api/v1/devices/550e8400-e29b-41d4-a716-446655440001
```

**Ответ (200 OK):**

```json
{
  "id": "550e8400-e29b-41d4-a716-446655440001",
  "name": "Kitchen Light",
  "device_type": "light",
  "status": "available",
  "state": {
    "state": "on",
    "brightness": 200
  },
  "source_id": "550e8400-e29b-41d4-a716-446655440000",
  "ha_entity_id": "light.kitchen_light",
  "created_at": "2026-09-29T10:00:00Z",
  "updated_at": "2026-09-29T10:15:30Z"
}
```

**Коды ошибок:**

| Код | Описание | Решение |
|-----|---------|---------|
| 404 | Устройство не найдено | Проверьте ID устройства |
| 500 | Ошибка сервера | Проверьте логи сервера |

---

### 3. Обновление конфигурации устройства

Обновляет отображаемые параметры устройства.

**Endpoint:** `PUT /api/v1/devices/{device_id}/config`

**Статус код:** `200 OK`

**Параметры пути:**

| Параметр | Тип | Описание |
|----------|-----|---------|
| `device_id` | UUID | ID устройства |

**Тело запроса:**

```json
{
  "display_name": "Кухонное основное освещение",
  "description": "LED лампа на потолке кухни",
  "location": "Kitchen",
  "tags": ["lighting", "main", "morning"]
}
```

**Параметры:**

| Параметр | Тип | Обязательный | Ограничения | Описание |
|----------|-----|--------------|-------------|---------|
| `display_name` | string | Нет | 1-255 символов | Отображаемое название |
| `description` | string | Нет | макс 1000 символов | Описание устройства |
| `location` | string | Нет | макс 255 символов | Расположение устройства |
| `tags` | array | Нет | макс 10 тегов | Метки для категоризации |

**Пример curl:**

```bash
curl -X PUT http://localhost:8000/api/v1/devices/550e8400-e29b-41d4-a716-446655440001/config \
  -H "Content-Type: application/json" \
  -d '{
    "display_name": "Кухонное основное освещение",
    "description": "LED лампа на потолке кухни",
    "location": "Kitchen",
    "tags": ["lighting", "main"]
  }'
```

**Ответ (200 OK):**

```json
{
  "id": "550e8400-e29b-41d4-a716-446655440001",
  "name": "Кухонное основное освещение",
  "device_type": "light",
  "status": "available",
  "state": {
    "state": "on",
    "brightness": 200
  },
  "source_id": "550e8400-e29b-41d4-a716-446655440000",
  "ha_entity_id": "light.kitchen_light",
  "created_at": "2026-09-29T10:00:00Z",
  "updated_at": "2026-09-29T10:20:00Z"
}
```

**Коды ошибок:**

| Код | Описание | Решение |
|-----|---------|---------|
| 400 | Валидация не пройдена | Проверьте длину строк и количество тегов |
| 404 | Устройство не найдено | Проверьте ID устройства |
| 500 | Ошибка при обновлении | Проверьте логи сервера |

---

### 4. Отправка команды устройству

Отправляет команду устройству через Home Assistant.

**Endpoint:** `POST /api/v1/devices/{device_id}/command`

**Статус код:** `202 Accepted`

**Параметры пути:**

| Параметр | Тип | Описание |
|----------|-----|---------|
| `device_id` | UUID | ID устройства |

**Тело запроса:**

```json
{
  "service": "light.turn_on",
  "data": {
    "entity_id": "light.kitchen_light",
    "brightness": 255,
    "transition": 2
  }
}
```

**Параметры:**

| Параметр | Тип | Обязательный | Описание |
|----------|-----|--------------|---------|
| `service` | string | Да | Сервис HA (формат: `domain.service`) |
| `data` | object | Нет | Данные для сервиса |

**Примеры команд:**

**Включение света:**
```json
{
  "service": "light.turn_on",
  "data": {
    "entity_id": "light.kitchen_light",
    "brightness": 200,
    "transition": 1
  }
}
```

**Выключение света:**
```json
{
  "service": "light.turn_off",
  "data": {
    "entity_id": "light.kitchen_light",
    "transition": 1
  }
}
```

**Установка температуры климат-контроля:**
```json
{
  "service": "climate.set_temperature",
  "data": {
    "entity_id": "climate.living_room",
    "temperature": 21,
    "hvac_mode": "heat"
  }
}
```

**Открытие жалюзи:**
```json
{
  "service": "cover.open_cover",
  "data": {
    "entity_id": "cover.living_room_blinds"
  }
}
```

**Разблокировка двери:**
```json
{
  "service": "lock.unlock",
  "data": {
    "entity_id": "lock.front_door"
  }
}
```

**Пример curl:**

```bash
curl -X POST http://localhost:8000/api/v1/devices/550e8400-e29b-41d4-a716-446655440001/command \
  -H "Content-Type: application/json" \
  -d '{
    "service": "light.turn_on",
    "data": {
      "entity_id": "light.kitchen_light",
      "brightness": 255,
      "transition": 2
    }
  }'
```

**Ответ (202 Accepted):**

```json
{
  "command_id": "cmd_550e8400-e29b-41d4-a716-446655440100",
  "device_id": "550e8400-e29b-41d4-a716-446655440001",
  "service": "light.turn_on",
  "status": "pending"
}
```

**Статусы команды:**
- `pending` - команда в очереди на отправку
- `executing` - команда отправлена в HA
- `success` - команда выполнена успешно
- `failed` - команда не выполнена (см. ошибки HA)

**Коды ошибок:**

| Код | Описание | Решение |
|-----|---------|---------|
| 400 | Некорректная команда | Проверьте синтаксис сервиса и данных |
| 404 | Устройство не найдено | Проверьте ID устройства |
| 500 | Ошибка при отправке | Проверьте подключение к HA |

---

## Обработка ошибок

### Структура ошибки

Все ошибки возвращаются в единообразном формате:

```json
{
  "detail": "Описание ошибки",
  "status_code": 400
}
```

### Общие коды ошибок

| Код HTTP | Описание | Причины |
|----------|---------|---------|
| 400 | Bad Request | Неверный формат данных, валидация не пройдена |
| 404 | Not Found | Ресурс не найден (источник, устройство) |
| 422 | Unprocessable Entity | Данные не соответствуют схеме |
| 500 | Internal Server Error | Ошибка сервера, проблемы с подключением |
| 503 | Service Unavailable | Сервис недоступен, проблемы с HA |

### Специфичные ошибки интеграции

**Ошибка подключения к Home Assistant:**
```json
{
  "detail": "Ошибка при синхронизации: Connection refused (192.168.1.100:8123)",
  "status_code": 500
}
```

**Решение:** Проверьте URL HA и доступность сервера.

**Ошибка аутентификации токена:**
```json
{
  "detail": "Ошибка при синхронизации: Invalid token",
  "status_code": 500
}
```

**Решение:** Проверьте долгосрочный токен в Home Assistant.

**Устройство недоступно:**
```json
{
  "detail": "Устройство 550e8400-e29b-41d4-a716-446655440001 не найдено",
  "status_code": 404
}
```

**Решение:** Выполните синхронизацию источника, проверьте ID.

---

## Rate Limiting и Best Practices

### Текущее состояние

На данный момент Rate Limiting НЕ реализован. Рекомендуется добавить в production:

1. **Per-client rate limit:** 100 запросов в минуту
2. **Global rate limit:** 10,000 запросов в минуту
3. **Burst limit:** 50 запросов в секунду

### Best Practices

#### 1. Синхронизация источников

**Оптимальная частота:** один раз в час

```bash
# Плохо - слишком часто
every 1 minute: sync_source()

# Хорошо - один раз в час
every 60 minutes: sync_source()
```

#### 2. Получение информации об устройствах

**Рекомендуется:** кэшировать результаты на 30 секунд

```python
# Пример кэширования
@cache(ttl=30)
def get_devices():
    return api.get("/api/v1/devices")
```

#### 3. Отправка команд

**Важно:** использовать `202 Accepted` для асинхронных операций

```bash
# Команда отправляется асинхронно
curl -X POST /api/v1/devices/{id}/command \
  -d '{"service": "light.turn_on", ...}'

# Проверить статус команды
curl /api/v1/commands/{command_id}
```

#### 4. Обработка ошибок подключения

**Рекомендуется:** retry логика с экспоненциальной задержкой

```python
import asyncio


async def sync_with_retry(source_id, max_retries=3):
    for attempt in range(max_retries):
        try:
            await sync_source(source_id)
            return True
        except Exception as e:
            if attempt < max_retries - 1:
                await asyncio.sleep(2**attempt)  # 1s, 2s, 4s
            else:
                raise
```

#### 5. Мониторинг и логирование

**Рекомендуется логировать:**
- Успешные синхронизации с кол-вом устройств
- Ошибки подключения и восстановление
- Время выполнения команд
- Недоступные устройства

```python
logger.info(f"Synced {device_count} devices from {source.name}")
logger.error(f"Failed to sync {source.name}: {error}")
logger.warning(f"Device {device_id} unavailable for {duration}s")
```

#### 6. Безопасность токенов

**Критично:**
- Никогда не логировать полные токены
- Использовать переменные окружения
- Ротировать токены регулярно (каждые 90 дней)
- Использовать шифрование при сохранении

```bash
# Плохо
curl -d '{"token": "eyJ...full_token..."}'

# Хорошо
export HA_TOKEN="your_long_token"
curl -d '{"token": "'${HA_TOKEN}'"}'
```

#### 7. Параллельные запросы

**Оптимизируйте сетевые запросы:**

```python
# Плохо - последовательно
for device_id in device_ids:
    send_command(device_id)

# Хорошо - параллельно
await asyncio.gather(*[send_command(device_id) for device_id in device_ids])
```

#### 8. Версионирование API

**Используйте версионированные endpoints:**

```bash
# Всегда указывайте версию
curl http://localhost:8000/api/v1/devices

# Позволяет развивать API без breaking changes
# Старые клиенты продолжают работать на /api/v1
# Новые функции на /api/v2
```

---

## Примеры интеграции

### Пример 1: Полный цикл синхронизации и управления

```bash
#!/bin/bash

HA_HOST="192.168.1.100"
HA_PORT="8123"
HA_TOKEN="eyJ..."
PLATFORM_URL="http://localhost:8000"

# 1. Создаем источник
SOURCE_RESPONSE=$(curl -s -X POST $PLATFORM_URL/api/v1/devices/sources \
  -H "Content-Type: application/json" \
  -d "{
    \"name\": \"Home Assistant\",
    \"url\": \"http://${HA_HOST}:${HA_PORT}\",
    \"token\": \"${HA_TOKEN}\"
  }")

SOURCE_ID=$(echo $SOURCE_RESPONSE | jq -r '.id')
echo "Created source: $SOURCE_ID"

# 2. Запускаем синхронизацию
curl -s -X POST $PLATFORM_URL/api/v1/devices/sources/$SOURCE_ID/sync \
  -H "Content-Type: application/json"

echo "Sync started..."
sleep 5

# 3. Получаем список устройств
DEVICES=$(curl -s $PLATFORM_URL/api/v1/devices?source_id=$SOURCE_ID)
echo "Devices found:"
echo $DEVICES | jq '.[] | {id, name, device_type, status}'

# 4. Включаем первое устройство типа "light"
LIGHT_ID=$(echo $DEVICES | jq -r '.[] | select(.device_type=="light") | .id' | head -1)

if [ ! -z "$LIGHT_ID" ]; then
  curl -s -X POST $PLATFORM_URL/api/v1/devices/$LIGHT_ID/command \
    -H "Content-Type: application/json" \
    -d '{
      "service": "light.turn_on",
      "data": {"brightness": 200}
    }'
  echo "Command sent to device: $LIGHT_ID"
fi
```

### Пример 2: Мониторинг состояния устройств (Python)

```python
import asyncio
import aiohttp
from datetime import datetime


class DeviceMonitor:
    def __init__(self, api_url):
        self.api_url = api_url

    async def get_devices(self, source_id=None):
        async with aiohttp.ClientSession() as session:
            params = {"source_id": source_id} if source_id else {}
            async with session.get(f"{self.api_url}/api/v1/devices", params=params) as resp:
                return await resp.json()

    async def monitor(self, interval=30):
        while True:
            try:
                devices = await self.get_devices()
                available = sum(1 for d in devices if d["status"] == "available")
                unavailable = sum(1 for d in devices if d["status"] == "unavailable")

                print(
                    f"[{datetime.now()}] Devices - Available: {available}, "
                    f"Unavailable: {unavailable}"
                )

                await asyncio.sleep(interval)
            except Exception as e:
                print(f"Error: {e}")
                await asyncio.sleep(5)


# Использование
async def main():
    monitor = DeviceMonitor("http://localhost:8000")
    await monitor.monitor()


asyncio.run(main())
```

---

## Changelog

### Версия 1.0.0 (2026-09-29)

- Начальный релиз API
- Endpoints для управления источниками HA
- Endpoints для управления устройствами
- Поддержка синхронизации и отправки команд
- Обработка ошибок и валидация
- Rate limiting (планируется)
- WebSocket поддержка (планируется)

---

## Контакты и поддержка

**Репозиторий:** https://github.com/your-repo/smart-home-platform

**Email:** support@example.com

**Документация:** `/docs` - Swagger UI

**Issues:** https://github.com/your-repo/smart-home-platform/issues
