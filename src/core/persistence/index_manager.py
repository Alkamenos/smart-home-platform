"""
Индексирование устройств в базе данных для быстрого поиска.

Поддерживает индексирование по:
- source_id - быстрый поиск устройств от источника
- device_type - быстрый поиск устройств по типу (light, switch, etc.)
- ha_entity_id - поиск по HA ID
- status - поиск по статусу (available, unavailable, removed_from_ha)

Все операции thread-safe.
"""

from __future__ import annotations

import logging
import threading
from collections import defaultdict
from uuid import UUID

from src.core.models.device import Device


logger = logging.getLogger(__name__)


class IndexManager:
    """
    Индексирование устройств для быстрого поиска.

    Поддерживает множественные индексы для оптимизации различных типов запросов:
    - source_id -> {device_ids}
    - device_type -> {device_ids}
    - ha_entity_id -> device_id
    - status -> {device_ids}

    Пример использования:
        index = IndexManager()
        index.add_device(device)
        devices = index.find_by_source(source_id)
        devices = index.find_by_type("light")
        device = index.find_by_ha_entity_id("light.kitchen")
    """

    def __init__(self):
        """Инициализация индекс-менеджера."""
        self._lock = threading.RLock()

        # Индексы
        self._by_source_id: defaultdict[UUID, set[UUID]] = defaultdict(set)
        self._by_device_type: defaultdict[str, set[UUID]] = defaultdict(set)
        self._by_ha_entity_id: dict[str, UUID] = {}
        self._by_status: defaultdict[str, set[UUID]] = defaultdict(set)

        # Быстрый доступ к устройству по ID (кэш)
        self._devices: dict[UUID, Device] = {}

        # Метрики
        self.index_operations = 0
        self.index_errors = 0

    def add_device(self, device: Device) -> None:
        """
        Добавить устройство в индексы.

        Args:
            device: Устройство для индексирования
        """
        with self._lock:
            try:
                self._devices[device.id] = device

                # Индекс по source_id
                self._by_source_id[device.source_id].add(device.id)

                # Индекс по device_type
                self._by_device_type[device.device_type].add(device.id)

                # Индекс по ha_entity_id
                self._by_ha_entity_id[device.ha_entity_id] = device.id

                # Индекс по status
                self._by_status[device.status].add(device.id)

                self.index_operations += 1
                logger.debug(f"Устройство индексировано: {device.id} ({device.ha_entity_id})")

            except Exception as e:
                self.index_errors += 1
                logger.error(f"Ошибка индексирования устройства {device.id}: {e}")

    def remove_device(self, device_id: UUID) -> bool:
        """
        Удалить устройство из индексов.

        Args:
            device_id: ID устройства для удаления

        Returns:
            True если удалено, False если не найдено
        """
        with self._lock:
            try:
                if device_id not in self._devices:
                    return False

                device = self._devices[device_id]

                # Удалить из всех индексов
                self._by_source_id[device.source_id].discard(device_id)
                self._by_device_type[device.device_type].discard(device_id)
                self._by_status[device.status].discard(device_id)

                # Удалить ha_entity_id индекс
                if device.ha_entity_id in self._by_ha_entity_id:
                    del self._by_ha_entity_id[device.ha_entity_id]

                # Удалить кэш
                del self._devices[device_id]

                self.index_operations += 1
                logger.debug(f"Устройство удалено из индексов: {device_id}")
                return True

            except Exception as e:
                self.index_errors += 1
                logger.error(f"Ошибка удаления из индексов {device_id}: {e}")
                return False

    def update_device(self, device: Device) -> None:
        """
        Обновить устройство в индексах (переиндексирование).

        Args:
            device: Обновленное устройство
        """
        with self._lock:
            try:
                # Старые значения ключей недоступны: вызывающий код обычно мутирует
                # тот же объект, который лежит в self._devices, поэтому old_device is device.
                # Поэтому удаляем устройство из ВСЕХ бакетов по его id, а не только из
                # бакетов, вычисленных по текущим полям.
                for index in (self._by_source_id, self._by_device_type, self._by_status):
                    for key in list(index.keys()):
                        index[key].discard(device.id)
                        if not index[key]:
                            del index[key]

                for entity_id in [
                    key for key, value in self._by_ha_entity_id.items() if value == device.id
                ]:
                    del self._by_ha_entity_id[entity_id]

                # Добавить в новые индексы
                self.add_device(device)
                logger.debug(f"Устройство переиндексировано: {device.id}")

            except Exception as e:
                self.index_errors += 1
                logger.error(f"Ошибка переиндексирования {device.id}: {e}")

    def find_by_source(self, source_id: UUID) -> list[Device]:
        """
        Найти все устройства от источника.

        Args:
            source_id: ID источника

        Returns:
            Список устройств
        """
        with self._lock:
            device_ids = self._by_source_id.get(source_id, set())
            return [self._devices[did] for did in device_ids if did in self._devices]

    def find_by_type(self, device_type: str) -> list[Device]:
        """
        Найти все устройства по типу.

        Args:
            device_type: Тип устройства (light, switch, binary_sensor, etc.)

        Returns:
            Список устройств
        """
        with self._lock:
            device_ids = self._by_device_type.get(device_type, set())
            return [self._devices[did] for did in device_ids if did in self._devices]

    def find_by_ha_entity_id(self, ha_entity_id: str) -> Device | None:
        """
        Найти устройство по HA entity ID.

        Args:
            ha_entity_id: HA entity ID (e.g., 'light.kitchen_light')

        Returns:
            Устройство или None если не найдено
        """
        with self._lock:
            device_id = self._by_ha_entity_id.get(ha_entity_id)
            if device_id and device_id in self._devices:
                return self._devices[device_id]
            return None

    def find_by_status(self, status: str) -> list[Device]:
        """
        Найти все устройства по статусу.

        Args:
            status: Статус (available, unavailable, removed_from_ha)

        Returns:
            Список устройств
        """
        with self._lock:
            device_ids = self._by_status.get(status, set())
            return [self._devices[did] for did in device_ids if did in self._devices]

    def find_by_source_and_type(self, source_id: UUID, device_type: str) -> list[Device]:
        """
        Найти устройства по источнику и типу.

        Args:
            source_id: ID источника
            device_type: Тип устройства

        Returns:
            Список устройств
        """
        with self._lock:
            source_devices = self._by_source_id.get(source_id, set())
            type_devices = self._by_device_type.get(device_type, set())
            common_ids = source_devices & type_devices
            return [self._devices[did] for did in common_ids if did in self._devices]

    def get_device(self, device_id: UUID) -> Device | None:
        """
        Получить устройство по ID.

        Args:
            device_id: ID устройства

        Returns:
            Устройство или None если не найдено
        """
        with self._lock:
            return self._devices.get(device_id)

    def clear(self) -> None:
        """Очистить все индексы."""
        with self._lock:
            self._by_source_id.clear()
            self._by_device_type.clear()
            self._by_ha_entity_id.clear()
            self._by_status.clear()
            self._devices.clear()
            logger.info("Все индексы очищены")

    def rebuild_from_devices(self, devices: list[Device]) -> None:
        """
        Пересоздать индексы из списка устройств.

        Args:
            devices: Список устройств для индексирования
        """
        with self._lock:
            self.clear()
            for device in devices:
                self.add_device(device)
            logger.info(f"Индексы пересозданы из {len(devices)} устройств")

    def get_stats(self) -> dict[str, any]:
        """
        Получить статистику индексов.

        Returns:
            Словарь со статистикой
        """
        with self._lock:
            return {
                "total_devices": len(self._devices),
                "unique_sources": len(self._by_source_id),
                "unique_types": len(self._by_device_type),
                "unique_statuses": len(self._by_status),
                "index_operations": self.index_operations,
                "index_errors": self.index_errors,
                "device_types": {k: len(v) for k, v in self._by_device_type.items()},
                "statuses": {k: len(v) for k, v in self._by_status.items()},
            }

    def get_all_devices(self) -> list[Device]:
        """
        Получить все устройства.

        Returns:
            Список всех устройств
        """
        with self._lock:
            return list(self._devices.values())

    def get_device_count(self) -> int:
        """Получить количество устройств в индексе."""
        with self._lock:
            return len(self._devices)
