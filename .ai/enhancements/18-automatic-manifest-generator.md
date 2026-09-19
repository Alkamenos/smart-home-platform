# Automatic Manifest Generator from Real Devices

**Приоритет:** HIGH
**Оценка:** 1-2 дня
**Категория:** Production Deployment

## Цель

Автоматизировать создание манифеста платформы путём сканирования реальных устройств Home Assistant, минимизируя ручную работу и снижая вероятность ошибок конфигурации.

## Проблема

Текущий процесс создания манифеста:
1. Пользователь должен вручную перечислить все устройства
2. Нужно знать правильные entity_id для каждого устройства
3. Требуется группировка по комнатам вручную
4. Легко ошибиться в типах устройств и их назначении
5. При добавлении новых устройств нужно обновлять манифест вручную

Для дома со 100+ устройствами это занимает часы и чревато ошибками.

## Предлагаемое решение

### 1. CLI Команда для генерации

```bash
smart-home generate-manifest \
  --url http://homeassistant:8123 \
  --token <LONG_LIVED_TOKEN> \
  --output instances/my_home/manifest.yaml \
  --interactive
```

### 2. Автоматическая классификация

Система автоматически определяет:
- **Типы устройств** по domain (light, switch, sensor, binary_sensor)
- **Комнаты** через HA Areas (если настроены) или по именам устройств
- **Главное устройство** в комнате (основной свет, термостат)
- **Сенсоры движения** по паттернам именования (`binary_sensor.*motion*`)
- **Сенсоры освещённости** (`sensor.*lux*`, `sensor.*illuminance*`)

### 3. Интерактивный Review

Перед сохранением пользователь может:
- Просмотреть сгенерированный манифест в CLI или Web UI
- Отредактировать классификацию комнат
- Исключить ненужные устройства
- Добавить недостающие связи вручную
- Указать параметры для FSM (таймауты, пороги)

### 4. Incremental Updates

При повторном запуске:
- Система сравнивает с существующим манифестом
- Показывает только изменения (новые/удалённые устройства)
- Предлагает применить инкрементальные обновления
- Сохраняет пользовательские настройки

## План реализации

1. **HA API Client**
   - Создать `services/ha_api_client.py`
   - Методы: `get_entities()`, `get_areas()`, `get_entity_state()`
   - Аутентификация через long-lived token
   - Кэширование ответов

2. **Manifest Generator Engine**
   - `core/manifest_generator.py` — основная логика
   - Классификаторы по типам устройств
   - Детектор комнат через Areas
   - Генератор YAML структуры

3. **CLI Command**
   - `cli/commands/generate_manifest.py`
   - Флаги: --url, --token, --output, --interactive, --dry-run
   - Интерактивный режим через questionary/inquirer

4. **Web UI Integration**
   - Страница `/tools/manifest-generator`
   - Визуальный редактор сгенерированного манифеста
   - Drag-and-drop для перемещения между комнатами
   - Предпросмотр перед сохранением

5. **Validation & Testing**
   - Валидация через Pydantic модели
   - Тесты с моком HA API
   - E2E тест на реальном HA instance

## Файлы

- `services/ha_api_client.py` — клиент для HA REST API
- `core/manifest_generator.py` — движок генерации манифеста
- `core/classifiers/device_classifier.py` — классификация устройств
- `core/classifiers/room_detector.py` — определение комнат
- `cli/commands/generate_manifest.py` — CLI команда
- `webui/routes/manifest_generator.py` — Web UI routes
- `webui/templates/manifest_generator.html` — шаблон страницы
- `webui/static/js/manifest_editor.js` — интерактивный редактор
- `tests/test_ha_api_client.py` — тесты API клиента
- `tests/test_manifest_generator.py` — тесты генератора
- `tests/test_device_classifier.py` — тесты классификаторов
- `docs/user-guide/manifest-generation.md` — документация

## Критерии успеха

- [ ] Генерация работает с реальным HA API
- [ ] Автоматическая классификация точна >90%
- [ ] Интерактивный режим удобен для пользователя
- [ ] Web UI предоставляет визуальный редактор
- [ ] Инкрементальные обновления сохраняют настройки
- [ ] Покрытие тестами >85%
- [ ] Генерация для 100 устройств < 10 секунд

## User Stories

### US-1: Быстрая генерация манифеста
**Как** новый пользователь
**Хочу** сгенерировать манифест одной командой
**Чтобы** начать использовать платформу без ручной настройки

**Acceptance Criteria:**
- Команда `smart-home generate-manifest --url <URL> --token <TOKEN>`
- Манифест создаётся за < 10 секунд для 100 устройств
- Все устройства классифицированы по комнатам
- Файл сохранён в `instances/<name>/manifest.yaml`

### US-2: Интерактивная проверка
**Как** осторожный пользователь
**Хочу** просмотреть и отредактировать манифест перед сохранением
**Чтобы** убедиться в корректности классификации

**Acceptance Criteria:**
- Флаг `--interactive` показывает превью в CLI
- Можно исключить устройства из манифеста
- Можно переместить устройство в другую комнату
- Можно добавить параметры FSM (timeout, thresholds)

### US-3: Визуальный редактор в Web UI
**Как** визуальный пользователь
**Хочу** редактировать манифест в браузере
**Чтобы** видеть структуру и связи наглядно

**Acceptance Criteria:**
- Страница `/tools/manifest-generator` доступна
- Отображение устройств по комнатам карточками
- Drag-and-drop для перемещения между комнатами
- Кнопки "Сохранить", "Экспорт", "Отмена"

### US-4: Обновление при изменениях
**Как** существующий пользователь
**Хочу** обновить манифест при добавлении устройств
**Чтобы** не пересоздавать его целиком

**Acceptance Criteria:**
- Повторный запуск показывает только изменения
- Новые устройства добавляются в соответствующие комнаты
- Удалённые устройства помечаются как missing
- Пользовательские настройки сохраняются

## Алгоритм классификации

### Определение типа устройства

```python
DOMAIN_MAPPING = {
    "light": "light",
    "switch": "switch",
    "binary_sensor": "sensor",
    "sensor": "sensor",
    "cover": "cover",
    "climate": "climate",
}

DEVICE_CLASS_MAPPING = {
    "motion": "motion_sensor",
    "door": "contact_sensor",
    "window": "contact_sensor",
    "temperature": "temperature_sensor",
    "humidity": "humidity_sensor",
    "illuminance": "light_sensor",
    "lux": "light_sensor",
}
```

### Определение комнаты

1. **Через HA Areas** (приоритет):
   - Получить area_id для каждого entity
   - Сгруппировать entity по area_id
   - Использовать имя area как название комнаты

2. **По имени устройства** (fallback):
   - Извлечь суффикс/префикс имени (кухня, спальня, гостиная)
   - Сопоставить с известными названиями комнат
   - Сгруппировать по совпадениям

3. **Ручное назначение**:
   - Если автоматика не сработала — предложить пользователю

### Поиск ключевых сенсоров

```python
MOTION_PATTERNS = ["motion", "движение", "pir", "occupancy"]
LIGHT_PATTERNS = ["lux", "illuminance", "освещенность", "light_sensor"]
TEMP_PATTERNS = ["temperature", "temp", "температура"]


def is_motion_sensor(entity_id: str) -> bool:
    return any(pattern in entity_id.lower() for pattern in MOTION_PATTERNS)
```

## Пример вывода CLI

```
$ smart-home generate-manifest --url http://ha:8123 --token <TOKEN> --interactive

🔍 Подключение к Home Assistant... ✓
📊 Найдено устройств: 127
🏠 Обнаружено комнат: 8

┌─────────────────────────────────────────────────────┐
│ Комната: Кухня                                      │
├─────────────────────────────────────────────────────┤
│ 💡 light.kitchen_main (main_light)                  │
│ 💡 light.kitchen_counter                            │
│ 🚪 binary_sensor.kitchen_door (contact_sensor)      │
│ 🏃 binary_sensor.kitchen_motion (motion_sensor)     │
│ 🌡️  sensor.kitchen_temp (temperature_sensor)        │
│ 💧 sensor.kitchen_humidity (humidity_sensor)        │
└─────────────────────────────────────────────────────┘

[?] Действия:
  > Просмотреть все комнаты
    Исключить устройство
    Переместить устройство
    Сохранить манифест
    Отмена

✓ Манифест сохранён в instances/my_home/manifest.yaml
```

## Конфигурация

```yaml
# configuration.yaml
manifest_generator:
  ha_url: http://homeassistant:8123
  token_env: HA_TOKEN  # или直接使用 --token
  auto_detect:
    rooms_from_areas: true
    exclude_domains:
      - camera
      - media_player
    include_only_areas: []  # пустой = все области
  classification:
    motion_patterns: ["motion", "движение", "pir"]
    light_patterns: ["lux", "illuminance"]
    main_light_keywords: ["main", "primary", "основной"]
```

## Риски

1. **Неполные данные Areas** — пользователь не настроил области в HA
   **Mitigation:** Fallback на парсинг имён устройств, интерактивное назначение

2. **Нестандартные имена устройств** — невозможно определить тип
   **Mitigation:** Помечать как "unknown", требовать ручного назначения

3. **Ошибки аутентификации** — неверный токен или URL
   **Mitigation:** Явные сообщения об ошибках, инструкция по созданию токена

4. **Большой объём данных** — тысячи устройств замедляют генерацию
   **Mitigation:** Пагинация API запросов, прогресс-бар, асинхронность

## Метрики успеха

- Точность авто-классификации: >90%
- Время генерации для 100 устройств: < 10 секунд
- Время настройки манифеста пользователем: < 5 минут
- Количество ручных правок после генерации: < 10% устройств
