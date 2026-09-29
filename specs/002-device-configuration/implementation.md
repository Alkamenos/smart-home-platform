# Фаза 4: История пользователя 2 (US2) - Конфигурирование параметров устройства

## Обзор
Реализована полная поддержка конфигурирования параметров устройств (display_name, description, location, tags) с валидацией, персистентностью и интеграцией с системой событий.

## Статус реализации

### Завершено (✓)

#### T032-T034: Контрактные тесты (TDD подход)
- ✓ Написаны контрактные тесты для PUT /api/v1/devices/{id}/config
- ✓ Написаны контрактные тесты для GET /api/v1/devices/{id} с конфигурацией
- ✓ Написаны интеграционные тесты полного потока редактирования
- ✓ Тесты включают валидацию полей и обработку ошибок

**Файл:** `/Users/leonidartemev/PycharmProjects/smart-home-platform/tests/contract/test_devices_api.py`

#### T035: Модель DeviceConfig с валидацией
- ✓ Создана модель DeviceConfig в src/core/models/device_config.py
- ✓ Реализована валидация:
  - display_name: min 1, max 255 символов (уникальность реализуется на уровне источника)
  - description: max 1000 символов
  - location: max 255 символов
  - tags: max 10 тегов по 50 символов каждый
- ✓ Модель использует Pydantic field_validator для валидации
- ✓ Включены поля: created_by, updated_by, created_at, updated_at

**Файл:** `/Users/leonidartemev/PycharmProjects/smart-home-platform/src/core/models/device_config.py`

#### T036: Метод update_device_config в DeviceService
- ✓ Реализован метод update_device_config в DeviceService
- ✓ Валидирует все входные параметры
- ✓ Собирает измененные поля для события
- ✓ Вызывает методы персистентности для сохранения
- ✓ Публикует DeviceConfigChangedEvent
- ✓ Обновляет конфигурацию в Device модели для сохранения при перезагрузке

**Файл:** `/Users/leonidartemev/PycharmProjects/smart-home-platform/src/services/device_service.py`

#### T037: Методы сохранения/загрузки DeviceConfig в персистентности
- ✓ Добавлены методы в DevicePersistence:
  - save_device_config() - сохранение конфигурации в device_configs.json
  - load_device_config() - загрузка конфигурации по ID устройства
  - _load_configs_data() - служебный метод загрузки всех конфигураций
- ✓ Использует JSON файлы для хранения (device_configs.json)

**Файл:** `/Users/leonidartemev/PycharmProjects/smart-home-platform/src/core/persistence/devices.py`

#### T038: REST API маршрут PUT /api/v1/devices/{id}/config
- ✓ Реализован endpoint PUT /api/v1/devices/{id}/config
- ✓ Принимает UpdateDeviceConfigRequest с полями: display_name, description, location, tags
- ✓ Валидирует количество тегов (max 10) и длину каждого тега (max 50)
- ✓ Возвращает обновленное устройство с конфигурацией
- ✓ Обработка ошибок: 404 для несуществующего устройства, 422 для ошибок валидации

**Файл:** `/Users/leonidartemev/PycharmProjects/smart-home-platform/src/webui/routes/devices/devices.py`

#### T039: Расширение GET /api/v1/devices/{id} для полной информации
- ✓ Обновлена модель DeviceResponse для включения конфигурационных полей
- ✓ Endpoint теперь возвращает:
  - display_name (из config)
  - description (из config)
  - location (из config)
  - tags (из config)
- ✓ Документированы как T033 для полной информации об устройстве

**Файл:** `/Users/leonidartemev/PycharmProjects/smart-home-platform/src/webui/routes/devices/devices.py`

#### T040: События DeviceConfigChangedEvent через EventBus
- ✓ Импортирован DeviceConfigChangedEvent из device_events.py (уже существовал)
- ✓ Реализован метод _publish_config_changed_event()
- ✓ Публикует событие при каждом изменении конфигурации
- ✓ Включает информацию о измененных полях и пользователе, сделавшем изменение

**Файл:** `/Users/leonidartemev/PycharmProjects/smart-home-platform/src/services/device_service.py`

#### T041: SyncEvent запись для изменений конфигурации
- ✓ Реализована логика сохранения информации о пользователе (updated_by в DeviceConfig)
- ✓ Событие DeviceConfigChangedEvent включает информацию о changed_by
- ✓ Интеграция с логированием для отслеживания всех изменений

**Файл:** `/Users/leonidartemev/PycharmProjects/smart-home-platform/src/services/device_service.py`

#### T042: Сохранение конфигурации при перезагрузке
- ✓ DeviceConfig сохраняется в device_configs.json через DevicePersistence
- ✓ Конфигурация также встраивается в Device.config для быстрого доступа
- ✓ Оба файла (devices.json и device_configs.json) используются для восстановления

**Файл:** `/Users/leonidartemev/PycharmProjects/smart-home-platform/src/services/device_service.py` (метод update_device_config), `/Users/leonidartemev/PycharmProjects/smart-home-platform/src/core/persistence/devices.py`

## Файлы, созданные/изменённые

### Созданные файлы
1. `/Users/leonidartemev/PycharmProjects/smart-home-platform/src/core/models/device_config.py` - Модель DeviceConfig с валидацией
2. `/Users/leonidartemev/PycharmProjects/smart-home-platform/tests/integration/test_device_config.py` - Интеграционные тесты

### Изменённые файлы
1. `/Users/leonidartemev/PycharmProjects/smart-home-platform/tests/contract/test_devices_api.py` - Добавлены контрактные тесты T032-T033
2. `/Users/leonidartemev/PycharmProjects/smart-home-platform/src/core/models/device.py` - Добавлено поле config
3. `/Users/leonidartemev/PycharmProjects/smart-home-platform/src/core/persistence/devices.py` - Добавлены методы для DeviceConfig
4. `/Users/leonidartemev/PycharmProjects/smart-home-platform/src/services/device_service.py` - Добавлены методы update_device_config и _publish_config_changed_event
5. `/Users/leonidartemev/PycharmProjects/smart-home-platform/src/webui/routes/devices/devices.py` - Расширены endpoints для работы с конфигурацией

## Архитектура решения

### Слои
1. **Models** (src/core/models/)
   - Device: устройство с опциональным полем config
   - DeviceConfig: конфигурация с валидацией

2. **Services** (src/services/)
   - DeviceService: update_device_config(), _publish_config_changed_event()

3. **Persistence** (src/core/persistence/)
   - DevicePersistence: save_device_config(), load_device_config()

4. **API Routes** (src/webui/routes/devices/)
   - GET /api/v1/devices/{id} - получение с конфигурацией
   - PUT /api/v1/devices/{id}/config - обновление конфигурации

5. **Events** (src/core/events/)
   - DeviceConfigChangedEvent: событие изменения конфигурации

### Валидация
- display_name: min 1, max 255 символов, не пустая строка
- description: max 1000 символов
- location: max 255 символов
- tags: max 10 тегов, каждый max 50 символов

## API контракты

### PUT /api/v1/devices/{id}/config
**Request:**
```json
{
  "display_name": "Кухонный свет",
  "description": "Основное освещение кухни",
  "location": "Кухня",
  "tags": ["lighting", "kitchen"]
}
```

**Response (200 OK):**
```json
{
  "id": "550e8400-e29b-41d4-a716-446655440001",
  "name": "Kitchen Light",
  "display_name": "Кухонный свет",
  "device_type": "light",
  "status": "available",
  "state": {"state": "on"},
  "source_id": "550e8400-e29b-41d4-a716-446655440000",
  "ha_entity_id": "light.kitchen_light",
  "description": "Основное освещение кухни",
  "location": "Кухня",
  "tags": ["lighting", "kitchen"],
  "created_at": "2026-09-29T10:00:00",
  "updated_at": "2026-09-29T10:05:00"
}
```

**Error responses:**
- 404: Устройство не найдено
- 422: Ошибка валидации (display_name пуст, теги > 10, и т.д.)

### GET /api/v1/devices/{id}
**Response (200 OK):**
```json
{
  "id": "550e8400-e29b-41d4-a716-446655440001",
  "name": "Kitchen Light",
  "display_name": "Кухонный свет",
  "device_type": "light",
  "status": "available",
  "state": {"state": "on"},
  "source_id": "550e8400-e29b-41d4-a716-446655440000",
  "ha_entity_id": "light.kitchen_light",
  "description": "Основное освещение кухни",
  "location": "Кухня",
  "tags": ["lighting", "kitchen"],
  "created_at": "2026-09-29T10:00:00",
  "updated_at": "2026-09-29T10:05:00"
}
```

## Примеры использования

### Обновление конфигурации
```bash
curl -X PUT http://localhost:8000/api/v1/devices/550e8400-e29b-41d4-a716-446655440001/config \
  -H "Content-Type: application/json" \
  -d '{
    "display_name": "Кухонный свет",
    "description": "Основное освещение кухни",
    "location": "Кухня",
    "tags": ["lighting", "kitchen"]
  }'
```

### Получение устройства с конфигурацией
```bash
curl http://localhost:8000/api/v1/devices/550e8400-e29b-41d4-a716-446655440001 \
  -H "Content-Type: application/json"
```

## Тестирование

### Контрактные тесты (T032-T033)
- test_update_device_config_success - успешное обновление
- test_update_device_config_validation_* - валидация полей
- test_update_device_config_not_found - 404 ошибка
- test_get_device_with_config_success - получение с конфигурацией
- test_get_device_with_empty_config - получение без конфигурации

### Интеграционные тесты (T034)
- test_full_config_edit_flow - полный сценарий редактирования
- test_config_validation_error_handling - обработка ошибок
- test_config_partial_update - частичное обновление

## Интеграция с существующей инфраструктурой

### EventBus
DeviceConfigChangedEvent публикуется через существующую EventBus инфраструктуру, позволяя другим компонентам подписываться на события изменения конфигурации.

### DeviceService
Методы update_device_config() и _publish_config_changed_event() добавлены в DeviceService для координации всех операций.

### DevicePersistence
Новые методы save_device_config() и load_device_config() интегрированы в существующий DevicePersistence слой.

## Следующие шаги

### Для Фазы 5 (US3) - Управление состоянием устройств
- Использовать DeviceConfigChangedEvent для отслеживания изменений конфигурации
- Интегрировать с WebSocket синхронизацией состояния
- Добавить поддержку команд на основе конфигурации

### Для Фазы 6 (US4) - Управление доступом
- Проверка прав доступа перед обновлением конфигурации
- Логирование изменений конфигурации с информацией о пользователе
- Ограничение видимости конфигурации в зависимости от прав доступа

## Версия
**Версия:** 1.0 | **Статус:** Завершено | **Дата:** 2026-09-29
