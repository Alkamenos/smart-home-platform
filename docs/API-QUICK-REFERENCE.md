# Справочник API - Быстрый поиск

**Файл полной документации:** `docs/device-integration-api.md`

## Краткое описание endpoints

### Endpoints источников (Sources)

| Метод | Endpoint | Описание |
|-------|----------|---------|
| POST | `/api/v1/devices/sources` | Создать новый источник HA |
| GET | `/api/v1/devices/sources/{source_id}` | Получить источник |
| POST | `/api/v1/devices/sources/{source_id}/sync` | Запустить синхронизацию |

### Endpoints устройств (Devices)

| Метод | Endpoint | Описание |
|-------|----------|---------|
| GET | `/api/v1/devices` | Получить список всех устройств (опционально фильтр `?source_id=...`) |
| GET | `/api/v1/devices/{device_id}` | Получить информацию об устройстве |
| PUT | `/api/v1/devices/{device_id}/config` | Обновить конфигурацию |
| POST | `/api/v1/devices/{device_id}/command` | Отправить команду |

---

## Основные модели данных

- **HASource** - Источник подключения к Home Assistant
- **Device** - Устройство из HA
- **DeviceConfig** - Конфигурация устройства
- **DeviceCommand** - Команда для отправки
- **DeviceAccess** - Управление доступом

---

## Примеры curl

### Создать источник
```bash
curl -X POST http://localhost:8000/api/v1/devices/sources \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Home Assistant",
    "url": "http://192.168.1.100:8123",
    "token": "eyJ..."
  }'
```

### Синхронизировать устройства
```bash
curl -X POST http://localhost:8000/api/v1/devices/sources/{source_id}/sync
```

### Получить все устройства
```bash
curl http://localhost:8000/api/v1/devices
```

### Включить свет
```bash
curl -X POST http://localhost:8000/api/v1/devices/{device_id}/command \
  -H "Content-Type: application/json" \
  -d '{
    "service": "light.turn_on",
    "data": {"brightness": 200}
  }'
```

### Обновить конфигурацию
```bash
curl -X PUT http://localhost:8000/api/v1/devices/{device_id}/config \
  -H "Content-Type: application/json" \
  -d '{
    "display_name": "Новое название",
    "location": "Kitchen",
    "tags": ["lighting"]
  }'
```

---

## Коды ошибок

| Код | Причина |
|-----|---------|
| 400 | Неверные данные |
| 404 | Ресурс не найден |
| 422 | Некорректная схема |
| 500 | Ошибка сервера |
| 503 | Сервис недоступен |

---

## Статусы

**Источник:** `connected`, `disconnected`, `error`

**Устройство:** `available`, `unavailable`, `removed_from_ha`

**Команда:** `pending`, `executing`, `success`, `failed`

---

Полная документация с примерами, описаниями всех параметров и best practices находится в `docs/device-integration-api.md`
