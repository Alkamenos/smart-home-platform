# Схема манифеста платформы умного дома

Этот документ описывает формат файла `manifest.yaml` который используется для конфигурации платформы умного дома.

## Структура манифеста

```yaml
version: 1                    # Версия формата (обязательно)

instance:                     # Мета-информация об инстансе (обязательно)
  id: leonids_house           # Уникальный ID (обязательно)
  name: "Leonid's House"      # Человекочитаемое имя (обязательно)
  owner: Leo                  # Владелец (опционально)
  created_at: "2026-09-08"    # Дата создания (опционально)

devices:                      # Устройства (обязательно)
  lighting:                   # Освещение
    - id: light.kitchen       # Entity ID устройства (обязательно)
      name: "Свет на кухне"   # Имя (обязательно)
      room: kitchen           # Комната, должна быть в zones (обязательно)
      motion_sensor: binary_sensor.kitchen_motion  # Датчик движения (опционально)
      schedule: "07:00-23:00" # Расписание в формате HH:MM-HH:MM (опционально)
      motion_timeout_sec: 300 # Таймаут отключения после движения (опционально)

  climate:                    # Климат
    - id: climate.kitchen
      name: "Климат кухни"
      room: kitchen
      sensor: sensor.kitchen_temperature  # Датчик температуры (обязательно)
      target: 22.0            # Целевая температура (опционально, по умолчанию 22.0)
      hysteresis: 0.5         # Гистерезис (опционально, по умолчанию 0.5)
      modes: ["heat", "cool", "auto"]  # Режимы работы (опционально)

  ventilation:                # Вентиляция
    - id: fan.bathroom
      name: "Вентиляция ванной"
      room: bathroom
      humidity_sensor: sensor.bathroom_humidity  # Датчик влажности (опционально)
      humidity_threshold: 65  # Порог включения (опционально, по умолчанию 65)
      timeout_sec: 1800       # Максимальное время работы (опционально)

zones:                        # Зоны/комнаты (обязательно)
  - id: kitchen               # ID комнаты (обязательно)
    name: "Кухня"             # Название (обязательно)
    floor: 1                  # Этаж (опционально)

automation_rules:             # Правила автоматизации (опционально)
  lighting:
    manual_lockout_min: 60    # Блокировка автоматики после ручного управления (мин)
    schedule_enabled: true    # Включить расписание
    motion_enabled: true      # Включить датчики движения

  climate:
    manual_lockout_min: 30
    safety_lockout_enabled: true
    away_mode_enabled: true

  ventilation:
    manual_lockout_min: 15
    humidity_based: true

dashboard:                    # Настройки дашборда (опционально)
  title: "Leonid's House"     # Заголовок
  show_motion_sensors: true   # Показывать датчики движения
  show_climate: true          # Показывать климат
  show_history: true          # Показывать историю
  history_days: 7             # Дней истории
```

## Требования к полям

### version
- **Тип:** integer
- **Обязательно:** да
- **Описание:** Версия формата манифеста для обратной совместимости

### instance.id
- **Тип:** string
- **Обязательно:** да
- **Формат:** lowercase с подчёркиваниями
- **Пример:** `leonids_house`, `my_smart_home`

### devices.*.id
- **Тип:** string
- **Обязательно:** да
- **Формат:** `domain.entity_name` (Home Assistant entity_id)
- **Пример:** `light.kitchen`, `climate.living_room`
- **Требования:** 
  - Только lowercase буквы, цифры и подчёркивания
  - Обязательно наличие точки

### devices.lighting[].schedule
- **Тип:** string
- **Формат:** `HH:MM-HH:MM`
- **Пример:** `07:00-23:00`, `06:30-23:30`

### devices.climate[].target
- **Тип:** float
- **Диапазон:** 10.0 - 35.0 °C
- **По умолчанию:** 22.0

### devices.climate[].hysteresis
- **Тип:** float
- **Диапазон:** 0.1 - 5.0 °C
- **По умолчанию:** 0.5

### devices.ventilation[].humidity_threshold
- **Тип:** float
- **Диапазон:** 0 - 100 %
- **По умолчанию:** 65

## Проверка целостности

Валидатор проверяет:

1. **Обязательные поля** — все required поля присутствуют
2. **Типы данных** — значения соответствуют ожидаемым типам
3. **Форматы** — entity_id, расписания в правильном формате
4. **Ссылочная целостность** — все комнаты из устройств существуют в zones
5. **Уникальность ID** — нет дубликатов entity_id
6. **Диапазоны значений** — температуры, влажность в допустимых пределах

## Примеры ошибок

### Ошибка: несуществующая комната
```yaml
devices:
  lighting:
    - id: light.kitchen
      room: nonexistent_room  # ❌ Ошибка: комнаты нет в zones
```

### Ошибка: дубликат ID
```yaml
devices:
  lighting:
    - id: light.kitchen
      ...
    - id: light.kitchen  # ❌ Ошибка: дубликат
```

### Ошибка: неверный формат entity_id
```yaml
devices:
  lighting:
    - id: INVALID_ID  # ❌ Ошибка: нет точки
```

### Ошибка: температура вне диапазона
```yaml
devices:
  climate:
    - id: climate.kitchen
      target: 50.0  # ❌ Ошибка: вне диапазона 10-35
```

## Использование

### Валидация через CLI
```bash
python cli.py manifest validate
python cli.py manifest validate --strict  # warnings тоже ошибки
```

### Валидация в коде
```python
from core.manifest_validator import ManifestValidator
import yaml

with open('instances/leonids_house/manifest.yaml') as f:
    manifest = yaml.safe_load(f)

validator = ManifestValidator()
errors = validator.validate(manifest)

if errors:
    for e in errors:
        print(f"{e.field}: {e.message}")
else:
    print("Манифест валиден!")
```

### Генерация автоматов
```python
from core.manifest_generator import ManifestAutomationGenerator

generator = ManifestAutomationGenerator(manifest, logger)
result = generator.generate_all()

# result.lighting_definitions — FSM для освещения
# result.lighting_mappings — маппинги сенсоров
# result.climate_definitions — FSM для климата
# result.ventilation_definitions — FSM для вентиляции
# result.automation_rules — правила автоматизации
```

## Обратная совместимость

Версия формата `1` гарантирует:
- Старые манифесты читаются новыми версиями платформы
- Новые поля добавляются как опциональные
- Изменение обязательных полей увеличивает мажорную версию
