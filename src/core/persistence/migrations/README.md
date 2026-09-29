"""
Документация системы миграций БД.

## Структура миграций

Система миграций обеспечивает управление инициализацией и структурой
данных приложения. Используется JSON file-based хранилище для совместимости.

## Файлы

### Миграции
- `001_init_sources.py` - Инициализация таблицы sources с индексами
- `002_init_devices.py` - Инициализация таблицы devices с индексами

### Управление
- `migrations_runner.py` - Менеджер выполнения миграций
- `index_manager.py` - Утилиты для управления индексами
- `db_init.py` - Инициализационный скрипт для старта приложения

## Структура данных

### Sources (sources.json)
```json
{
  "550e8400-e29b-41d4-a716-446655440000": {
    "id": "550e8400-e29b-41d4-a716-446655440000",
    "name": "Home Assistant Pro",
    "url": "http://192.168.1.100:8123",
    "token": "<encrypted-token>",
    "status": "connected",
    "last_sync": "2026-09-29T10:05:00",
    "last_error": null,
    "device_count": 47,
    "created_at": "2026-09-29T10:00:00",
    "updated_at": "2026-09-29T10:05:00"
  }
}
```

### Devices (devices.json)
```json
{
  "550e8400-e29b-41d4-a716-446655440001": {
    "id": "550e8400-e29b-41d4-a716-446655440001",
    "ha_entity_id": "light.kitchen_light",
    "source_id": "550e8400-e29b-41d4-a716-446655440000",
    "name": "Kitchen Light",
    "device_type": "light",
    "model": "Philips Hue A19",
    "manufacturer": "Philips",
    "state": {"state": "on", "brightness": 200},
    "attributes": {},
    "status": "available",
    "last_state_update": "2026-09-29T10:05:00",
    "created_at": "2026-09-29T10:00:00",
    "updated_at": "2026-09-29T10:05:00"
  }
}
```

## Индексы

### Индексы Sources (.sources_indices.json)
```json
{
  "by_name": {
    "Home Assistant Pro": ["550e8400-e29b-41d4-a716-446655440000"]
  },
  "by_status": {
    "connected": ["550e8400-e29b-41d4-a716-446655440000"],
    "disconnected": [],
    "error": []
  }
}
```

### Индексы Devices (.devices_indices.json)
```json
{
  "by_source_id": {
    "550e8400-e29b-41d4-a716-446655440000": ["550e8400-e29b-41d4-a716-446655440001"]
  },
  "by_device_type": {
    "light": ["550e8400-e29b-41d4-a716-446655440001"]
  },
  "by_ha_entity_id": {
    "light.kitchen_light": "550e8400-e29b-41d4-a716-446655440001"
  },
  "by_status": {
    "available": ["550e8400-e29b-41d4-a716-446655440001"],
    "unavailable": [],
    "removed_from_ha": []
  }
}
```

## Использование

### В коде приложения

```python
from src.core.persistence.migrations.db_init import initialize_database


# При старте приложения
async def startup():
    success = await initialize_database("data")
    if not success:
        raise RuntimeError("Не удалось инициализировать БД")
```

### Из командной строки

```bash
# Инициализировать БД и применить все миграции
python -m src.core.persistence.migrations.db_init init

# Проверить статус миграций
python -m src.core.persistence.migrations.db_init verify

# Показать статус всех миграций
python -m src.core.persistence.migrations.db_init status

# Сбросить БД (с подтверждением)
python -m src.core.persistence.migrations.db_init reset --confirm
```

## API MigrationsRunner

```python
from src.core.persistence.migrations.migrations_runner import MigrationsRunner

runner = MigrationsRunner("data")

# Применить все миграции
await runner.up()

# Откатить последнюю миграцию
await runner.down(steps=1)

# Получить статус
status = runner.status()

# Перестроить индексы
await runner.rebuild_all_indices()
```

## API IndexManager

```python
from src.core.persistence.migrations.index_manager import IndexManager

manager = IndexManager("data")

# Sources
sources_by_name = manager.get_sources_by_name("Home Assistant Pro")
sources_by_status = manager.get_sources_by_status("connected")

manager.add_source_to_indices(source_id, name, status)
manager.remove_source_from_indices(source_id, name, status)
manager.update_source_in_indices(source_id, old_name, new_name, old_status, new_status)

# Devices
devices = manager.get_devices_by_source_id(source_id)
devices = manager.get_devices_by_type("light")
device_id = manager.get_device_by_ha_entity_id("light.kitchen_light")
devices = manager.get_devices_by_status("available")

manager.add_device_to_indices(device_id, source_id, device_type, ha_entity_id, status)
manager.remove_device_from_indices(device_id, source_id, device_type, ha_entity_id, status)
manager.update_device_in_indices(device_id, ...)
```

## Расширение системы миграций

Для добавления новой миграции:

1. Создайте файл `00X_name.py` в папке migrations
2. Создайте класс `Migration00XName` с методами `up()` и `down()`
3. Добавьте миграцию в список `available_migrations` в `MigrationsRunner`

```python
class Migration003SomeFeature:
    name = "003_some_feature"
    description = "Описание миграции"

    async def up(self):
        # Логика инициализации
        pass

    async def down(self):
        # Логика отката
        pass
```

## Изоляция индексов

Индексы хранятся в скрытых файлах (начинающихся с `.`) и не синхронизируются
с основными файлами данных. Если индексы повреждены или неактуальны,
их можно перестроить с помощью `rebuild_all_indices()`.
"""
