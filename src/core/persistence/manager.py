"""
Менеджер персистентности - объединяет все компоненты для сохранения и загрузки данных.
"""

from pathlib import Path

from src.core.persistence.devices import DevicePersistence, DeviceAccessPersistence
from src.core.persistence.sources import HASourcePersistence
from src.core.security.encryption import TokenEncryptor


class PersistenceManager:
    """Менеджер для управления всеми слоями персистентности."""

    def __init__(
        self,
        data_dir: Path | str = "data",
        encryptor: TokenEncryptor | None = None,
    ) -> None:
        """Инициализация менеджера.

        Args:
            data_dir: Директория для сохранения данных
            encryptor: Шифровальщик для токенов (опционально)
        """
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)

        # Инициализируем компоненты
        self.sources = HASourcePersistence(data_dir=self.data_dir, encryptor=encryptor)
        self.devices = DevicePersistence(data_dir=self.data_dir)
        self.device_access = DeviceAccessPersistence(data_dir=self.data_dir)

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
