"""
Слой персистентности для устройств и управления доступом.

Обеспечивает сохранение и загрузку информации об устройствах и записях доступа
из файловой системы.
"""

import json
import logging
from pathlib import Path
from uuid import UUID

from src.core.models.device import Device
from src.core.models.device_access import DeviceAccess
from src.core.models.device_config import DeviceConfig
from src.core.models.device_sync_event import DeviceSyncEvent


logger = logging.getLogger(__name__)


class DevicePersistence:
    """Управляет сохранением и загрузкой устройств."""

    def __init__(self, data_dir: Path | str = "data") -> None:
        """Инициализация персистентности.

        Args:
            data_dir: Директория для сохранения данных
        """
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.devices_file = self.data_dir / "devices.json"
        self.configs_file = self.data_dir / "device_configs.json"

    async def save_device(self, device: Device) -> None:
        """Сохраняет устройство в файл.

        Args:
            device: Устройство для сохранения
        """
        try:
            devices_data = await self._load_devices_data()
            devices_data[str(device.id)] = device.model_dump(mode="json")

            with open(self.devices_file, "w") as f:
                json.dump(devices_data, f, indent=2, default=str)

            logger.info(f"Устройство {device.id} ({device.name}) сохранено")

        except Exception as e:
            logger.error(f"Ошибка сохранения устройства: {e}")
            raise

    async def save_devices(self, devices: list[Device]) -> None:
        """Сохраняет список устройств.

        Args:
            devices: Список устройств для сохранения
        """
        try:
            devices_data = {}

            for device in devices:
                devices_data[str(device.id)] = device.model_dump(mode="json")

            with open(self.devices_file, "w") as f:
                json.dump(devices_data, f, indent=2, default=str)

            logger.info(f"Сохранено {len(devices)} устройств")

        except Exception as e:
            logger.error(f"Ошибка сохранения устройств: {e}")
            raise

    async def load_device(self, device_id: UUID) -> Device | None:
        """Загружает устройство по ID.

        Args:
            device_id: Идентификатор устройства

        Returns:
            Device если найдено, None иначе
        """
        try:
            devices_data = await self._load_devices_data()
            device_data = devices_data.get(str(device_id))

            if not device_data:
                return None

            return Device(**device_data)

        except Exception as e:
            logger.error(f"Ошибка загрузки устройства {device_id}: {e}")
            return None

    async def load_all_devices(self) -> list[Device]:
        """Загружает все устройства.

        Returns:
            Список всех устройств
        """
        try:
            devices_data = await self._load_devices_data()
            devices = []

            for device_data in devices_data.values():
                try:
                    device = Device(**device_data)
                    devices.append(device)
                except Exception as e:
                    logger.warning(f"Ошибка загрузки устройства: {e}")
                    continue

            logger.info(f"Загружено {len(devices)} устройств")
            return devices

        except Exception as e:
            logger.error(f"Ошибка загрузки устройств: {e}")
            return []

    async def load_devices_by_source(self, source_id: UUID) -> list[Device]:
        """Загружает все устройства из определенного источника.

        Args:
            source_id: Идентификатор источника

        Returns:
            Список устройств от этого источника
        """
        try:
            all_devices = await self.load_all_devices()
            return [d for d in all_devices if d.source_id == source_id]

        except Exception as e:
            logger.error(f"Ошибка загрузки устройств источника {source_id}: {e}")
            return []

    async def delete_device(self, device_id: UUID) -> bool:
        """Удаляет устройство.

        Args:
            device_id: Идентификатор устройства для удаления

        Returns:
            True если удалено успешно
        """
        try:
            devices_data = await self._load_devices_data()

            if str(device_id) in devices_data:
                del devices_data[str(device_id)]

                with open(self.devices_file, "w") as f:
                    json.dump(devices_data, f, indent=2, default=str)

                logger.info(f"Устройство {device_id} удалено")
                return True

            return False

        except Exception as e:
            logger.error(f"Ошибка удаления устройства: {e}")
            return False

    async def delete_devices_by_source(self, source_id: UUID) -> int:
        """Удаляет все устройства определенного источника.

        Args:
            source_id: Идентификатор источника

        Returns:
            Количество удаленных устройств
        """
        try:
            devices_data = await self._load_devices_data()
            count = 0

            for device_id, device_data in list(devices_data.items()):
                if device_data.get("source_id") == str(source_id):
                    del devices_data[device_id]
                    count += 1

            if count > 0:
                with open(self.devices_file, "w") as f:
                    json.dump(devices_data, f, indent=2, default=str)

                logger.info(f"Удалено {count} устройств источника {source_id}")

            return count

        except Exception as e:
            logger.error(f"Ошибка удаления устройств источника {source_id}: {e}")
            return 0

    async def _load_devices_data(self) -> dict:
        """Загружает данные о всех устройствах из файла.

        Returns:
            Словарь с данными устройств
        """
        if not self.devices_file.exists():
            return {}

        try:
            with open(self.devices_file) as f:
                return json.load(f)
        except json.JSONDecodeError:
            logger.warning(f"Файл {self.devices_file} повреждён, начинаю с пустого")
            return {}

    async def save_device_config(self, config: DeviceConfig) -> None:
        """Сохраняет конфигурацию устройства.

        Args:
            config: Конфигурация для сохранения
        """
        try:
            configs_data = await self._load_configs_data()
            configs_data[str(config.id)] = config.model_dump(mode="json")

            with open(self.configs_file, "w") as f:
                json.dump(configs_data, f, indent=2, default=str)

            logger.info(f"Конфигурация {config.id} устройства {config.device_id} сохранена")

        except Exception as e:
            logger.error(f"Ошибка сохранения конфигурации устройства: {e}")
            raise

    async def load_device_config(self, device_id: UUID) -> DeviceConfig | None:
        """Загружает конфигурацию устройства по ID устройства.

        Args:
            device_id: Идентификатор устройства

        Returns:
            DeviceConfig если найдена, None иначе
        """
        try:
            configs_data = await self._load_configs_data()

            # Ищем конфигурацию по device_id
            for config_data in configs_data.values():
                if config_data.get("device_id") == str(device_id):
                    return DeviceConfig(**config_data)

            return None

        except Exception as e:
            logger.error(f"Ошибка загрузки конфигурации устройства {device_id}: {e}")
            return None

    async def _load_configs_data(self) -> dict:
        """Загружает данные всех конфигураций из файла.

        Returns:
            Словарь с данными конфигураций
        """
        if not self.configs_file.exists():
            return {}

        try:
            with open(self.configs_file) as f:
                return json.load(f)
        except json.JSONDecodeError:
            logger.warning(f"Файл {self.configs_file} повреждён, начинаю с пустого")
            return {}


class DeviceAccessPersistence:
    """Управляет сохранением и загрузкой записей доступа к устройствам."""

    def __init__(self, data_dir: Path | str = "data") -> None:
        """Инициализация персистентности доступа.

        Args:
            data_dir: Директория для сохранения данных
        """
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.access_file = self.data_dir / "device_access.json"

    async def save_access(self, access: DeviceAccess) -> None:
        """Сохраняет запись доступа.

        Args:
            access: Запись доступа для сохранения
        """
        try:
            access_data = await self._load_access_data()
            access_data[str(access.id)] = access.model_dump(mode="json")

            with open(self.access_file, "w") as f:
                json.dump(access_data, f, indent=2, default=str)

            logger.info(
                f"Запись доступа {access.id} (user {access.user_id} -> device {access.device_id}) сохранена"
            )

        except Exception as e:
            logger.error(f"Ошибка сохранения записи доступа: {e}")
            raise

    async def save_accesses(self, accesses: list[DeviceAccess]) -> None:
        """Сохраняет список записей доступа.

        Args:
            accesses: Список записей доступа для сохранения
        """
        try:
            access_data = {}

            for access in accesses:
                access_data[str(access.id)] = access.model_dump(mode="json")

            with open(self.access_file, "w") as f:
                json.dump(access_data, f, indent=2, default=str)

            logger.info(f"Сохранено {len(accesses)} записей доступа")

        except Exception as e:
            logger.error(f"Ошибка сохранения записей доступа: {e}")
            raise

    async def load_access(self, access_id: UUID) -> DeviceAccess | None:
        """Загружает запись доступа по ID.

        Args:
            access_id: Идентификатор записи доступа

        Returns:
            DeviceAccess если найдена, None иначе
        """
        try:
            access_data = await self._load_access_data()
            data = access_data.get(str(access_id))

            if not data:
                return None

            return DeviceAccess(**data)

        except Exception as e:
            logger.error(f"Ошибка загрузки записи доступа {access_id}: {e}")
            return None

    async def load_all_accesses(self) -> list[DeviceAccess]:
        """Загружает все записи доступа.

        Returns:
            Список всех записей доступа
        """
        try:
            access_data = await self._load_access_data()
            accesses = []

            for data in access_data.values():
                try:
                    access = DeviceAccess(**data)
                    accesses.append(access)
                except Exception as e:
                    logger.warning(f"Ошибка загрузки записи доступа: {e}")
                    continue

            logger.info(f"Загружено {len(accesses)} записей доступа")
            return accesses

        except Exception as e:
            logger.error(f"Ошибка загрузки записей доступа: {e}")
            return []

    async def load_accesses_for_device(self, device_id: UUID) -> list[DeviceAccess]:
        """Загружает все записи доступа для определенного устройства.

        Args:
            device_id: Идентификатор устройства

        Returns:
            Список записей доступа для этого устройства
        """
        try:
            all_accesses = await self.load_all_accesses()
            return [a for a in all_accesses if a.device_id == device_id]

        except Exception as e:
            logger.error(f"Ошибка загрузки доступа для устройства {device_id}: {e}")
            return []

    async def load_access_for_user_device(
        self, device_id: UUID, user_id: str
    ) -> DeviceAccess | None:
        """Загружает запись доступа пользователя к устройству.

        Args:
            device_id: Идентификатор устройства
            user_id: Идентификатор пользователя

        Returns:
            DeviceAccess если найдена, None иначе
        """
        try:
            device_accesses = await self.load_accesses_for_device(device_id)
            for access in device_accesses:
                if access.user_id == user_id:
                    return access
            return None

        except Exception as e:
            logger.error(f"Ошибка загрузки доступа user {user_id} -> device {device_id}: {e}")
            return None

    async def load_accesses_for_user(self, user_id: str) -> list[DeviceAccess]:
        """Загружает все записи доступа для пользователя.

        Args:
            user_id: Идентификатор пользователя

        Returns:
            Список всех устройств, к которым пользователь имеет доступ
        """
        try:
            all_accesses = await self.load_all_accesses()
            return [a for a in all_accesses if a.user_id == user_id]

        except Exception as e:
            logger.error(f"Ошибка загрузки доступа пользователя {user_id}: {e}")
            return []

    async def delete_access(self, access_id: UUID) -> bool:
        """Удаляет запись доступа.

        Args:
            access_id: Идентификатор записи доступа для удаления

        Returns:
            True если удалено успешно
        """
        try:
            access_data = await self._load_access_data()

            if str(access_id) in access_data:
                del access_data[str(access_id)]

                with open(self.access_file, "w") as f:
                    json.dump(access_data, f, indent=2, default=str)

                logger.info(f"Запись доступа {access_id} удалена")
                return True

            return False

        except Exception as e:
            logger.error(f"Ошибка удаления записи доступа: {e}")
            return False

    async def delete_accesses_for_device(self, device_id: UUID) -> int:
        """Удаляет все записи доступа для устройства.

        Args:
            device_id: Идентификатор устройства

        Returns:
            Количество удаленных записей доступа
        """
        try:
            access_data = await self._load_access_data()
            count = 0

            for access_id, data in list(access_data.items()):
                if data.get("device_id") == str(device_id):
                    del access_data[access_id]
                    count += 1

            if count > 0:
                with open(self.access_file, "w") as f:
                    json.dump(access_data, f, indent=2, default=str)

                logger.info(f"Удалено {count} записей доступа для устройства {device_id}")

            return count

        except Exception as e:
            logger.error(f"Ошибка удаления доступа для устройства {device_id}: {e}")
            return 0

    async def delete_access_for_user_device(self, device_id: UUID, user_id: str) -> bool:
        """Удаляет запись доступа пользователя к устройству.

        Args:
            device_id: Идентификатор устройства
            user_id: Идентификатор пользователя

        Returns:
            True если удалено успешно
        """
        try:
            access = await self.load_access_for_user_device(device_id, user_id)

            if access:
                return await self.delete_access(access.id)

            return False

        except Exception as e:
            logger.error(f"Ошибка удаления доступа user {user_id} -> device {device_id}: {e}")
            return False

    async def _load_access_data(self) -> dict:
        """Загружает данные о всех записях доступа из файла.

        Returns:
            Словарь с данными записей доступа
        """
        if not self.access_file.exists():
            return {}

        try:
            with open(self.access_file) as f:
                return json.load(f)
        except json.JSONDecodeError:
            logger.warning(f"Файл {self.access_file} повреждён, начинаю с пустого")
            return {}


class DeviceSyncEventPersistence:
    """Управляет историей операций с устройствами (ТР-010, spec 005).

    Append-only хранилище записей DeviceSyncEvent в JSON-файле
    ``device_sync_events.json`` (паттерн DeviceAccessPersistence).
    """

    def __init__(self, data_dir: Path | str = "data") -> None:
        """Инициализация персистентности истории операций.

        Args:
            data_dir: Директория для сохранения данных
        """
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.events_file = self.data_dir / "device_sync_events.json"

    async def append_event(self, event: DeviceSyncEvent) -> None:
        """Добавляет запись операции в историю.

        Args:
            event: Запись операции для сохранения

        Raises:
            Exception: При ошибке записи в файл (вызывающий решает,
                блокировать ли основную операцию — FR-009)
        """
        try:
            events_data = await self._load_events_data()
            events_data[str(event.id)] = event.model_dump(mode="json")

            with open(self.events_file, "w") as f:
                json.dump(events_data, f, indent=2, default=str)

            logger.info(
                f"История: записана операция {event.action} "
                f"для устройства {event.device_id} (user {event.user_id})"
            )

        except Exception as e:
            logger.error(f"Ошибка сохранения записи истории: {e}")
            raise

    async def list_events(
        self,
        device_id: UUID,
        action: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[DeviceSyncEvent]:
        """Возвращает историю операций устройства (новые первыми).

        Args:
            device_id: Устройство, операции которого запрашиваются
            action: Фильтр по типу операции (неизвестное значение → [])
            limit: Максимум записей в ответе
            offset: Смещение для пагинации

        Returns:
            Список записей операций; [] при отсутствии или повреждении файла
        """
        events_data = await self._load_events_data()

        events: list[DeviceSyncEvent] = []
        for record in events_data.values():
            try:
                event = DeviceSyncEvent.model_validate(record)
            except Exception as e:
                logger.warning(f"Пропущена некорректная запись истории: {e}")
                continue

            if event.device_id != device_id:
                continue
            if action is not None and event.action != action:
                continue
            events.append(event)

        events.sort(key=lambda e: e.timestamp, reverse=True)
        return events[offset : offset + limit]

    async def _load_events_data(self) -> dict:
        """Загружает данные истории операций из файла.

        Returns:
            Словарь с данными записей операций; {} при отсутствии/повреждении
        """
        if not self.events_file.exists():
            return {}

        try:
            with open(self.events_file) as f:
                return json.load(f)
        except json.JSONDecodeError:
            logger.warning(f"Файл {self.events_file} повреждён, начинаю с пустого")
            return {}
