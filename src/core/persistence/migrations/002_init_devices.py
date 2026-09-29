"""
Миграция 002: Инициализация таблицы devices.

Создает структуру для хранения устройств с индексами для оптимизации
поиска по source_id, device_type и ha_entity_id.
"""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any


logger = logging.getLogger(__name__)


class Migration002InitDevices:
    """Миграция для инициализации таблицы devices."""

    name = "002_init_devices"
    description = (
        "Инициализация таблицы devices с индексами по source_id, device_type, ha_entity_id"
    )

    def __init__(self, data_dir: Path | str = "data") -> None:
        """
        Инициализация миграции.

        Args:
            data_dir: Директория для хранения данных
        """
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.devices_file = self.data_dir / "devices.json"
        self.indices_file = self.data_dir / ".devices_indices.json"

    async def up(self) -> None:
        """Применить миграцию (создать таблицу devices с индексами)."""
        try:
            logger.info(f"Применение миграции {self.name}...")

            # Инициализируем файл devices.json если его нет
            if not self.devices_file.exists():
                self._init_devices_file()
                logger.info(f"Создан файл {self.devices_file}")
            else:
                logger.info(f"Файл {self.devices_file} уже существует")

            # Инициализируем индексы
            self._init_indices()
            logger.info("Индексы для devices инициализированы")

            logger.info(f"Миграция {self.name} успешно применена")

        except Exception as e:
            logger.error(f"Ошибка при применении миграции {self.name}: {e}")
            raise

    async def down(self) -> None:
        """Откатить миграцию (удалить таблицу devices)."""
        try:
            logger.info(f"Откат миграции {self.name}...")

            if self.devices_file.exists():
                self.devices_file.unlink()
                logger.info(f"Удален файл {self.devices_file}")

            if self.indices_file.exists():
                self.indices_file.unlink()
                logger.info(f"Удален файл индексов {self.indices_file}")

            logger.info(f"Миграция {self.name} успешно отката")

        except Exception as e:
            logger.error(f"Ошибка при откате миграции {self.name}: {e}")
            raise

    def _init_devices_file(self) -> None:
        """Инициализировать файл devices.json с пустой структурой."""
        devices_structure: dict[str, Any] = {}
        with open(self.devices_file, "w") as f:
            json.dump(devices_structure, f, indent=2)

    def _init_indices(self) -> None:
        """Инициализировать индексные структуры для оптимизации поиска."""
        indices: dict[str, Any] = {
            "by_source_id": {},  # Индекс: source_id -> список ID устройств
            "by_device_type": {},  # Индекс: device_type -> список ID устройств
            "by_ha_entity_id": {},  # Индекс: ha_entity_id -> ID устройства
            "by_status": {  # Индекс: статус -> список ID устройств
                "available": [],
                "unavailable": [],
                "removed_from_ha": [],
            },
            "last_updated": datetime.utcnow().isoformat(),
        }

        with open(self.indices_file, "w") as f:
            json.dump(indices, f, indent=2, default=str)

    def get_indices(self) -> dict[str, Any]:
        """
        Получить текущие индексы devices.

        Returns:
            Словарь с индексными структурами
        """
        if not self.indices_file.exists():
            self._init_indices()

        try:
            with open(self.indices_file) as f:
                return json.load(f)
        except (json.JSONDecodeError, FileNotFoundError):
            return {
                "by_source_id": {},
                "by_device_type": {},
                "by_ha_entity_id": {},
                "by_status": {"available": [], "unavailable": [], "removed_from_ha": []},
                "last_updated": datetime.utcnow().isoformat(),
            }

    def update_indices(self, indices: dict[str, Any]) -> None:
        """
        Обновить индексные структуры.

        Args:
            indices: Новые индексы
        """
        indices["last_updated"] = datetime.utcnow().isoformat()
        with open(self.indices_file, "w") as f:
            json.dump(indices, f, indent=2, default=str)

    async def rebuild_indices(self) -> None:
        """Перестроить все индексы из текущих данных devices."""
        try:
            logger.info("Перестройка индексов devices...")

            if not self.devices_file.exists():
                logger.warning(f"Файл {self.devices_file} не существует")
                return

            with open(self.devices_file) as f:
                devices = json.load(f)

            # Инициализируем новые индексы
            indices: dict[str, Any] = {
                "by_source_id": {},
                "by_device_type": {},
                "by_ha_entity_id": {},
                "by_status": {"available": [], "unavailable": [], "removed_from_ha": []},
            }

            # Заполняем индексы
            for device_id, device_data in devices.items():
                source_id = device_data.get("source_id", "")
                device_type = device_data.get("device_type", "")
                ha_entity_id = device_data.get("ha_entity_id", "")
                status = device_data.get("status", "available")

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
                if status in indices["by_status"] and device_id not in indices["by_status"][status]:
                    indices["by_status"][status].append(device_id)

            self.update_indices(indices)
            logger.info("Индексы devices успешно перестроены")

        except Exception as e:
            logger.error(f"Ошибка при перестройке индексов devices: {e}")
            raise
