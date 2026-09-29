"""
Примеры использования системы миграций и индексов.

Демонстрирует типичные операции с миграциями и индексами.
"""

import asyncio
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


async def example_migrations():
    """Пример использования миграций."""
    from src.core.persistence.migrations.migrations_runner import MigrationsRunner

    print("\n=== Пример: Миграции ===")

    runner = MigrationsRunner("data")

    # Получить статус
    print("\nТекущий статус миграций:")
    status = runner.status()
    for migration in status["migrations"]:
        print(f"  - {migration['name']}: {migration['status']}")

    # Применить миграции
    print("\nПрименение миграций...")
    try:
        await runner.up()
        print("Миграции успешно применены!")
    except Exception as e:
        print(f"Ошибка: {e}")

    # Новый статус
    print("\nНовый статус миграций:")
    status = runner.status()
    for migration in status["migrations"]:
        print(f"  - {migration['name']}: {migration['status']}")


async def example_index_manager():
    """Пример использования менеджера индексов."""
    from src.core.persistence.migrations.index_manager import IndexManager

    print("\n=== Пример: Управление индексами ===")

    manager = IndexManager("data")

    # Sources
    print("\nРаботаем с индексами Sources:")
    manager.add_source_to_indices(
        "source-1",
        name="Home Assistant 1",
        status="connected"
    )
    manager.add_source_to_indices(
        "source-2",
        name="Home Assistant 2",
        status="disconnected"
    )

    print(f"  Sources by name 'Home Assistant 1': {manager.get_sources_by_name('Home Assistant 1')}")
    print(f"  Sources by status 'connected': {manager.get_sources_by_status('connected')}")

    # Devices
    print("\nРаботаем с индексами Devices:")
    manager.add_device_to_indices(
        device_id="device-1",
        source_id="source-1",
        device_type="light",
        ha_entity_id="light.kitchen",
        status="available"
    )
    manager.add_device_to_indices(
        device_id="device-2",
        source_id="source-1",
        device_type="switch",
        ha_entity_id="switch.living_room",
        status="available"
    )

    print(f"  Devices by source_id 'source-1': {manager.get_devices_by_source_id('source-1')}")
    print(f"  Devices by type 'light': {manager.get_devices_by_type('light')}")
    print(f"  Device by entity_id 'light.kitchen': {manager.get_device_by_ha_entity_id('light.kitchen')}")
    print(f"  Devices by status 'available': {manager.get_devices_by_status('available')}")

    # Обновление
    print("\nОбновление индексов:")
    manager.update_source_in_indices(
        source_id="source-1",
        old_status="connected",
        new_status="error"
    )
    print(f"  Sources by status 'connected' (после update): {manager.get_sources_by_status('connected')}")
    print(f"  Sources by status 'error' (после update): {manager.get_sources_by_status('error')}")

    # Удаление
    print("\nУдаление из индексов:")
    manager.remove_device_from_indices(
        device_id="device-1",
        device_type="light",
        ha_entity_id="light.kitchen",
        status="available"
    )
    print(f"  Devices by type 'light' (после удаления): {manager.get_devices_by_type('light')}")


async def example_db_init():
    """Пример использования инициализации БД."""
    from src.core.persistence.migrations.db_init import (
        initialize_database,
        verify_migrations,
        print_migration_status
    )

    print("\n=== Пример: Инициализация БД ===")

    # Инициализация
    print("\nИнициализация БД...")
    success = await initialize_database("data", apply_migrations=True)
    print(f"Результат: {'успешно' if success else 'ошибка'}")

    # Проверка
    print("\nПроверка миграций...")
    all_applied = await verify_migrations("data")
    print(f"Все миграции применены: {all_applied}")

    # Статус
    print("\nВывод статуса миграций:")
    print_migration_status("data")


async def example_persistence_integration():
    """Пример интеграции с персистентностью."""
    from src.core.persistence.sources import HASourcePersistence
    from src.core.persistence.devices import DevicePersistence
    from src.core.persistence.migrations.index_manager import IndexManager
    from src.core.models.ha_source import HASource
    from src.core.models.device import Device
    from datetime import datetime
    from uuid import uuid4

    print("\n=== Пример: Интеграция персистентности с индексами ===")

    sources_persistence = HASourcePersistence("data")
    devices_persistence = DevicePersistence("data")
    index_manager = IndexManager("data")

    # Создаём и сохраняем источник
    source = HASource(
        id=uuid4(),
        name="Main Home Assistant",
        url="http://192.168.1.100:8123",
        token="eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
        status="connected"
    )

    print(f"\nСохранение источника: {source.name}")
    await sources_persistence.save_source(source)

    # Обновляем индекс
    index_manager.add_source_to_indices(
        str(source.id),
        name=source.name,
        status=source.status
    )
    print(f"  Индекс обновлён")

    # Создаём и сохраняем устройство
    device = Device(
        id=uuid4(),
        ha_entity_id="light.kitchen_light",
        source_id=source.id,
        name="Kitchen Light",
        device_type="light",
        model="Philips Hue",
        manufacturer="Philips",
        status="available"
    )

    print(f"\nСохранение устройства: {device.name}")
    await devices_persistence.save_device(device)

    # Обновляем индекс
    index_manager.add_device_to_indices(
        str(device.id),
        source_id=str(device.source_id),
        device_type=device.device_type,
        ha_entity_id=device.ha_entity_id,
        status=device.status
    )
    print(f"  Индекс обновлён")

    # Быстрый поиск через индексы
    print(f"\nБыстрый поиск через индексы:")
    devices = index_manager.get_devices_by_source_id(str(source.id))
    print(f"  Устройства источника {source.name}: {len(devices)}")

    lights = index_manager.get_devices_by_type("light")
    print(f"  Количество ламп: {len(lights)}")


async def main():
    """Главная функция для запуска примеров."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )

    try:
        # Применяем миграции
        await example_migrations()

        # Примеры с индексами
        await example_index_manager()

        # Инициализация БД
        await example_db_init()

        # Интеграция с персистентностью
        await example_persistence_integration()

        print("\n" + "=" * 60)
        print("Все примеры выполнены успешно!")
        print("=" * 60)

    except Exception as e:
        print(f"\nОшибка: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())
