"""
Менеджер персистентности - объединяет все компоненты для сохранения и загрузки данных.
"""

from pathlib import Path

from src.core.persistence.devices import (
    DeviceAccessPersistence,
    DevicePersistence,
    DeviceSyncEventPersistence,
)
from src.core.persistence.sources import HASourcePersistence


class PersistenceManager:
    """Менеджер для управления всеми слоями персистентности."""

    def __init__(
        self,
        data_dir: Path | str = "data",
        encryptor: object | None = None,
    ) -> None:
        """Инициализация менеджера.

        Args:
            data_dir: Директория для сохранения данных
            encryptor: Шифровальщик для токенов (опционально)
        """
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)

        # Инициализируем компоненты
        # Пытаемся использовать encryptor если он передан или доступен
        try:
            if not encryptor:
                from src.core.security.encryption import TokenEncryptor

                encryptor = TokenEncryptor()
        except ImportError:
            # Если cryptography не установлен, работаем без шифрования
            encryptor = None

        self.sources = HASourcePersistence(data_dir=self.data_dir, encryptor=encryptor)
        self.devices = DevicePersistence(data_dir=self.data_dir)
        self.device_access = DeviceAccessPersistence(data_dir=self.data_dir)
        self.device_sync_events = DeviceSyncEventPersistence(data_dir=self.data_dir)

    async def load_device_config(self, device_id):
        """Загружает конфигурацию устройства."""
        return await self.devices.load_device_config(device_id)

    async def save_device_config(self, config):
        """Сохраняет конфигурацию устройства."""
        return await self.devices.save_device_config(config)

    async def save_device(self, device):
        """Сохраняет устройство."""
        return await self.devices.save_device(device)

    async def load_device(self, device_id):
        """Загружает устройство по ID."""
        return await self.devices.load_device(device_id)

    async def load_all_devices(self):
        """Загружает все устройства."""
        return await self.devices.load_all_devices()

    async def save_devices(self, devices):
        """Сохраняет список устройств (полностью перезаписывает хранилище)."""
        return await self.devices.save_devices(devices)

    async def load_devices_by_source(self, source_id):
        """Загружает устройства источника."""
        return await self.devices.load_devices_by_source(source_id)

    async def delete_device(self, device_id):
        """Удаляет устройство из постоянного хранилища.

        Args:
            device_id: Идентификатор устройства.

        Returns:
            True, если устройство было удалено; False, если его не было.
        """
        return await self.devices.delete_device(device_id)

    async def delete_devices_by_source(self, source_id):
        """Удаляет все устройства источника.

        Args:
            source_id: Идентификатор источника.

        Returns:
            Количество удалённых устройств.
        """
        return await self.devices.delete_devices_by_source(source_id)

    async def delete_accesses_for_device(self, device_id):
        """Удаляет все записи о доступе к устройству.

        Args:
            device_id: Идентификатор устройства.

        Returns:
            Количество удалённых записей.
        """
        return await self.device_access.delete_accesses_for_device(device_id)
