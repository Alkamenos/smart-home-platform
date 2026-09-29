"""
Утилиты для работы с индексами в JSON file-based хранилище.

Обеспечивает быстрый поиск по индексам и их управление.
"""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
from uuid import UUID

logger = logging.getLogger(__name__)


class IndexManager:
    """Менеджер для управления индексами в JSON хранилище."""

    def __init__(self, data_dir: Path | str = "data") -> None:
        """
        Инициализация менеджера индексов.

        Args:
            data_dir: Директория для хранения данных и индексов
        """
        self.data_dir = Path(data_dir)
        self.sources_indices_file = self.data_dir / ".sources_indices.json"
        self.devices_indices_file = self.data_dir / ".devices_indices.json"

    # === Индексы для Sources ===

    def load_sources_indices(self) -> Dict[str, Any]:
        """
        Загрузить индексы sources.

        Returns:
            Словарь с индексами sources
        """
        if not self.sources_indices_file.exists():
            return self._create_default_sources_indices()

        try:
            with open(self.sources_indices_file, "r") as f:
                return json.load(f)
        except (json.JSONDecodeError, FileNotFoundError):
            return self._create_default_sources_indices()

    def save_sources_indices(self, indices: Dict[str, Any]) -> None:
        """
        Сохранить индексы sources.

        Args:
            indices: Индексы для сохранения
        """
        indices["last_updated"] = datetime.utcnow().isoformat()
        with open(self.sources_indices_file, "w") as f:
            json.dump(indices, f, indent=2, default=str)

    def _create_default_sources_indices(self) -> Dict[str, Any]:
        """Создать индексы sources по умолчанию."""
        return {
            "by_name": {},
            "by_status": {
                "connected": [],
                "disconnected": [],
                "error": []
            },
            "last_updated": datetime.utcnow().isoformat()
        }

    def get_sources_by_name(self, name: str) -> List[str]:
        """
        Получить ID источников по имени.

        Args:
            name: Имя источника

        Returns:
            Список ID источников
        """
        indices = self.load_sources_indices()
        return indices.get("by_name", {}).get(name, [])

    def get_sources_by_status(self, status: str) -> List[str]:
        """
        Получить ID источников по статусу.

        Args:
            status: Статус (connected, disconnected, error)

        Returns:
            Список ID источников
        """
        indices = self.load_sources_indices()
        return indices.get("by_status", {}).get(status, [])

    def add_source_to_indices(self, source_id: str, name: str, status: str) -> None:
        """
        Добавить источник в индексы.

        Args:
            source_id: ID источника
            name: Имя источника
            status: Статус источника
        """
        indices = self.load_sources_indices()

        # Добавляем в индекс по имени
        if name:
            if name not in indices["by_name"]:
                indices["by_name"][name] = []
            if source_id not in indices["by_name"][name]:
                indices["by_name"][name].append(source_id)

        # Добавляем в индекс по статусу
        if status in indices["by_status"]:
            if source_id not in indices["by_status"][status]:
                indices["by_status"][status].append(source_id)

        self.save_sources_indices(indices)

    def remove_source_from_indices(self, source_id: str, name: Optional[str] = None, status: Optional[str] = None) -> None:
        """
        Удалить источник из индексов.

        Args:
            source_id: ID источника
            name: Имя источника (опционально)
            status: Статус источника (опционально)
        """
        indices = self.load_sources_indices()

        # Удаляем из индекса по имени
        if name and name in indices["by_name"]:
            if source_id in indices["by_name"][name]:
                indices["by_name"][name].remove(source_id)
            if not indices["by_name"][name]:
                del indices["by_name"][name]

        # Удаляем из индекса по статусу
        if status and status in indices["by_status"]:
            if source_id in indices["by_status"][status]:
                indices["by_status"][status].remove(source_id)

        self.save_sources_indices(indices)

    def update_source_in_indices(
        self,
        source_id: str,
        old_name: Optional[str] = None,
        new_name: Optional[str] = None,
        old_status: Optional[str] = None,
        new_status: Optional[str] = None
    ) -> None:
        """
        Обновить источник в индексах.

        Args:
            source_id: ID источника
            old_name: Старое имя
            new_name: Новое имя
            old_status: Старый статус
            new_status: Новый статус
        """
        indices = self.load_sources_indices()

        # Обновляем индекс по имени
        if old_name and old_name in indices["by_name"]:
            if source_id in indices["by_name"][old_name]:
                indices["by_name"][old_name].remove(source_id)
            if not indices["by_name"][old_name]:
                del indices["by_name"][old_name]

        if new_name:
            if new_name not in indices["by_name"]:
                indices["by_name"][new_name] = []
            if source_id not in indices["by_name"][new_name]:
                indices["by_name"][new_name].append(source_id)

        # Обновляем индекс по статусу
        if old_status and old_status in indices["by_status"]:
            if source_id in indices["by_status"][old_status]:
                indices["by_status"][old_status].remove(source_id)

        if new_status and new_status in indices["by_status"]:
            if source_id not in indices["by_status"][new_status]:
                indices["by_status"][new_status].append(source_id)

        self.save_sources_indices(indices)

    # === Индексы для Devices ===

    def load_devices_indices(self) -> Dict[str, Any]:
        """
        Загрузить индексы devices.

        Returns:
            Словарь с индексами devices
        """
        if not self.devices_indices_file.exists():
            return self._create_default_devices_indices()

        try:
            with open(self.devices_indices_file, "r") as f:
                return json.load(f)
        except (json.JSONDecodeError, FileNotFoundError):
            return self._create_default_devices_indices()

    def save_devices_indices(self, indices: Dict[str, Any]) -> None:
        """
        Сохранить индексы devices.

        Args:
            indices: Индексы для сохранения
        """
        indices["last_updated"] = datetime.utcnow().isoformat()
        with open(self.devices_indices_file, "w") as f:
            json.dump(indices, f, indent=2, default=str)

    def _create_default_devices_indices(self) -> Dict[str, Any]:
        """Создать индексы devices по умолчанию."""
        return {
            "by_source_id": {},
            "by_device_type": {},
            "by_ha_entity_id": {},
            "by_status": {
                "available": [],
                "unavailable": [],
                "removed_from_ha": []
            },
            "last_updated": datetime.utcnow().isoformat()
        }

    def get_devices_by_source_id(self, source_id: str) -> List[str]:
        """
        Получить ID устройств по source_id.

        Args:
            source_id: ID источника

        Returns:
            Список ID устройств
        """
        indices = self.load_devices_indices()
        return indices.get("by_source_id", {}).get(source_id, [])

    def get_devices_by_type(self, device_type: str) -> List[str]:
        """
        Получить ID устройств по типу.

        Args:
            device_type: Тип устройства

        Returns:
            Список ID устройств
        """
        indices = self.load_devices_indices()
        return indices.get("by_device_type", {}).get(device_type, [])

    def get_device_by_ha_entity_id(self, ha_entity_id: str) -> Optional[str]:
        """
        Получить ID устройства по ha_entity_id.

        Args:
            ha_entity_id: Entity ID в Home Assistant

        Returns:
            ID устройства или None
        """
        indices = self.load_devices_indices()
        return indices.get("by_ha_entity_id", {}).get(ha_entity_id)

    def get_devices_by_status(self, status: str) -> List[str]:
        """
        Получить ID устройств по статусу.

        Args:
            status: Статус (available, unavailable, removed_from_ha)

        Returns:
            Список ID устройств
        """
        indices = self.load_devices_indices()
        return indices.get("by_status", {}).get(status, [])

    def add_device_to_indices(
        self,
        device_id: str,
        source_id: str,
        device_type: str,
        ha_entity_id: str,
        status: str
    ) -> None:
        """
        Добавить устройство в индексы.

        Args:
            device_id: ID устройства
            source_id: ID источника
            device_type: Тип устройства
            ha_entity_id: Entity ID в HA
            status: Статус устройства
        """
        indices = self.load_devices_indices()

        # Индекс по source_id
        if source_id:
            if source_id not in indices["by_source_id"]:
                indices["by_source_id"][source_id] = []
            if device_id not in indices["by_source_id"][source_id]:
                indices["by_source_id"][source_id].append(device_id)

        # Индекс по device_type
        if device_type:
            if device_type not in indices["by_device_type"]:
                indices["by_device_type"][device_type] = []
            if device_id not in indices["by_device_type"][device_type]:
                indices["by_device_type"][device_type].append(device_id)

        # Индекс по ha_entity_id
        if ha_entity_id:
            indices["by_ha_entity_id"][ha_entity_id] = device_id

        # Индекс по статусу
        if status in indices["by_status"]:
            if device_id not in indices["by_status"][status]:
                indices["by_status"][status].append(device_id)

        self.save_devices_indices(indices)

    def remove_device_from_indices(
        self,
        device_id: str,
        source_id: Optional[str] = None,
        device_type: Optional[str] = None,
        ha_entity_id: Optional[str] = None,
        status: Optional[str] = None
    ) -> None:
        """
        Удалить устройство из индексов.

        Args:
            device_id: ID устройства
            source_id: ID источника (опционально)
            device_type: Тип устройства (опционально)
            ha_entity_id: Entity ID в HA (опционально)
            status: Статус устройства (опционально)
        """
        indices = self.load_devices_indices()

        # Удаляем из индекса по source_id
        if source_id and source_id in indices["by_source_id"]:
            if device_id in indices["by_source_id"][source_id]:
                indices["by_source_id"][source_id].remove(device_id)
            if not indices["by_source_id"][source_id]:
                del indices["by_source_id"][source_id]

        # Удаляем из индекса по device_type
        if device_type and device_type in indices["by_device_type"]:
            if device_id in indices["by_device_type"][device_type]:
                indices["by_device_type"][device_type].remove(device_id)
            if not indices["by_device_type"][device_type]:
                del indices["by_device_type"][device_type]

        # Удаляем из индекса по ha_entity_id
        if ha_entity_id and indices["by_ha_entity_id"].get(ha_entity_id) == device_id:
            del indices["by_ha_entity_id"][ha_entity_id]

        # Удаляем из индекса по статусу
        if status and status in indices["by_status"]:
            if device_id in indices["by_status"][status]:
                indices["by_status"][status].remove(device_id)

        self.save_devices_indices(indices)

    def update_device_in_indices(
        self,
        device_id: str,
        old_source_id: Optional[str] = None,
        new_source_id: Optional[str] = None,
        old_device_type: Optional[str] = None,
        new_device_type: Optional[str] = None,
        old_ha_entity_id: Optional[str] = None,
        new_ha_entity_id: Optional[str] = None,
        old_status: Optional[str] = None,
        new_status: Optional[str] = None
    ) -> None:
        """
        Обновить устройство в индексах.

        Args:
            device_id: ID устройства
            old_source_id: Старый ID источника
            new_source_id: Новый ID источника
            old_device_type: Старый тип
            new_device_type: Новый тип
            old_ha_entity_id: Старый Entity ID
            new_ha_entity_id: Новый Entity ID
            old_status: Старый статус
            new_status: Новый статус
        """
        indices = self.load_devices_indices()

        # Обновляем по source_id
        if old_source_id and old_source_id in indices["by_source_id"]:
            if device_id in indices["by_source_id"][old_source_id]:
                indices["by_source_id"][old_source_id].remove(device_id)
            if not indices["by_source_id"][old_source_id]:
                del indices["by_source_id"][old_source_id]

        if new_source_id:
            if new_source_id not in indices["by_source_id"]:
                indices["by_source_id"][new_source_id] = []
            if device_id not in indices["by_source_id"][new_source_id]:
                indices["by_source_id"][new_source_id].append(device_id)

        # Обновляем по device_type
        if old_device_type and old_device_type in indices["by_device_type"]:
            if device_id in indices["by_device_type"][old_device_type]:
                indices["by_device_type"][old_device_type].remove(device_id)
            if not indices["by_device_type"][old_device_type]:
                del indices["by_device_type"][old_device_type]

        if new_device_type:
            if new_device_type not in indices["by_device_type"]:
                indices["by_device_type"][new_device_type] = []
            if device_id not in indices["by_device_type"][new_device_type]:
                indices["by_device_type"][new_device_type].append(device_id)

        # Обновляем по ha_entity_id
        if old_ha_entity_id and indices["by_ha_entity_id"].get(old_ha_entity_id) == device_id:
            del indices["by_ha_entity_id"][old_ha_entity_id]

        if new_ha_entity_id:
            indices["by_ha_entity_id"][new_ha_entity_id] = device_id

        # Обновляем по статусу
        if old_status and old_status in indices["by_status"]:
            if device_id in indices["by_status"][old_status]:
                indices["by_status"][old_status].remove(device_id)

        if new_status and new_status in indices["by_status"]:
            if device_id not in indices["by_status"][new_status]:
                indices["by_status"][new_status].append(device_id)

        self.save_devices_indices(indices)
