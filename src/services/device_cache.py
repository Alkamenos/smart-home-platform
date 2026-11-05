"""Device cache and metrics for the device service (spec 018, T058).

Extracted from DeviceService: cache invalidation, index lookups and Prometheus
helpers are infrastructure concerns, separate from device business rules.
"""

# mypy: disable-error-code="attr-defined"

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from core.models.device import Device


logger = logging.getLogger("services.device_service")


class DeviceCacheMixin:
    """Maintain the device cache, index and related metrics."""

    def get_cache_stats(self) -> dict[str, Any]:
        """
        Получить статистику кэша.

        Returns:
            Словарь со статистикой кэша
        """
        return self._cache.get_stats()

    def get_index_stats(self) -> dict[str, Any]:
        """
        Получить статистику индекса.

        Returns:
            Словарь со статистикой индекса
        """
        return self._index.get_stats()

    def clear_cache(self) -> None:
        """Очистить весь кэш."""
        self._cache.clear()
        logger.info("Кэш устройств очищен")

    def invalidate_device_cache(self, device_id: UUID) -> bool:
        """
        Инвалидировать кэш для конкретного устройства.

        Args:
            device_id: ID устройства

        Returns:
            True если элемент был удален из кэша
        """
        device = self._devices.get(device_id)
        result = self._cache.invalidate(f"device:{device_id}")

        if device:
            self._cache.invalidate(f"source:{device.source_id}")

        return result

    def invalidate_source_cache(self, source_id: UUID) -> int:
        """
        Инвалидировать кэш для всех устройств источника.

        Args:
            source_id: ID источника

        Returns:
            Количество инвалидированных элементов
        """
        count = self._cache.invalidate_by_prefix(f"source:{source_id}")
        logger.info(f"Кэш источника инвалидирован: {source_id} ({count} элементов)")
        return count

    def rebuild_index(self) -> None:
        """Пересоздать индекс из всех устройств в памяти."""
        devices = list(self._devices.values())
        self._index.rebuild_from_devices(devices)
        logger.info(f"Индекс пересоздан: {len(devices)} устройств")

    def add_devices_to_cache_and_index(self, devices: list[Device]) -> None:
        """
        Добавить устройства в кэш и индекс.

        Args:
            devices: Список устройств для добавления
        """
        for device in devices:
            self._devices[device.id] = device
            self._index.add_device(device)

        logger.info(f"Добавлено {len(devices)} устройств в кэш и индекс")

    def find_devices_by_type(self, device_type: str) -> list[Device]:
        """
        Найти все устройства по типу с использованием индекса.

        Args:
            device_type: Тип устройства (light, switch, binary_sensor, etc.)

        Returns:
            Список устройств
        """
        return self._index.find_by_type(device_type)

    def find_device_by_ha_entity_id(self, ha_entity_id: str) -> Device | None:
        """
        Найти устройство по HA entity ID.

        Args:
            ha_entity_id: HA entity ID (e.g., 'light.kitchen_light')

        Returns:
            Устройство или None если не найдено
        """
        device = self._index.find_by_ha_entity_id(ha_entity_id)
        if device:
            # Добавить в кэш
            self._cache.set(f"device:{device.id}", device)
        return device

    # ============ Prometheus Metrics Helper Methods ============
    def _update_device_availability_metrics(self) -> None:
        """Обновляет метрики доступности устройств по источникам и типам.

        Анализирует состояние всех устройств и обновляет gauge метрики
        для отслеживания количества доступных/недоступных устройств.
        """
        try:
            # Группируем устройства по (source_id, device_type)
            device_counts: dict[tuple[str, str], tuple[int, int]] = {}

            for device in self._devices.values():
                source_id_str = str(device.source_id)
                device_type = device.device_type or "unknown"
                key = (source_id_str, device_type)

                if key not in device_counts:
                    device_counts[key] = (0, 0)

                available, unavailable = device_counts[key]

                if device.status == "available":
                    available += 1
                else:
                    unavailable += 1

                device_counts[key] = (available, unavailable)

            # Обновляем метрики для каждой комбинации source_id и device_type
            for (source_id_str, device_type), (available, unavailable) in device_counts.items():
                self._metrics.set_devices_available(source_id_str, device_type, available)
                self._metrics.set_devices_unavailable(source_id_str, device_type, unavailable)

            logger.debug(f"Обновлены метрики доступности устройств: {device_counts}")

        except Exception as e:
            logger.error(f"Ошибка при обновлении метрик доступности: {e}")

    def update_sources_connected_count(self, count: int) -> None:
        """Обновляет метрику количества подключенных источников.

        Args:
            count: Количество подключенных источников
        """
        try:
            self._metrics.set_sources_connected_count(count)
            logger.debug(f"Обновлена метрика подключенных источников: {count}")
        except Exception as e:
            logger.error(f"Ошибка при обновлении метрики источников: {e}")

    def update_cache_metrics(self, cache_size_bytes: int) -> None:
        """Обновляет метрики кэша.

        Args:
            cache_size_bytes: Размер кэша в байтах
        """
        try:
            self._metrics.set_cache_size(cache_size_bytes)
            logger.debug(f"Обновлена метрика размера кэша: {cache_size_bytes} bytes")
        except Exception as e:
            logger.error(f"Ошибка при обновлении метрик кэша: {e}")

    def record_cache_hit(self, cache_type: str = "device") -> None:
        """Записывает попадание в кэш.

        Args:
            cache_type: Тип кэша (например, "device", "config")
        """
        try:
            self._metrics.record_cache_hit(cache_type)
        except Exception as e:
            logger.error(f"Ошибка при записи cache hit: {e}")

    def record_cache_miss(self, cache_type: str = "device") -> None:
        """Записывает промах кэша.

        Args:
            cache_type: Тип кэша (например, "device", "config")
        """
        try:
            self._metrics.record_cache_miss(cache_type)
        except Exception as e:
            logger.error(f"Ошибка при записи cache miss: {e}")
