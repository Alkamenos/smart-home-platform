"""
REST клиент для подключения к Home Assistant API.

Обеспечивает HTTP подключение к экземпляру Home Assistant и получение информации об устройствах.
"""

import logging
from typing import Any, Optional

import aiohttp
from pydantic import HttpUrl

logger = logging.getLogger(__name__)


class HARestClient:
    """Клиент для работы с REST API Home Assistant."""

    def __init__(self, base_url: HttpUrl | str, token: str) -> None:
        """Инициализация клиента.

        Args:
            base_url: URL экземпляра Home Assistant (e.g., 'http://192.168.1.100:8123')
            token: Long-lived access token для аутентификации
        """
        self.base_url = str(base_url).rstrip("/")
        self.token = token
        self.session: Optional[aiohttp.ClientSession] = None
        self._connected = False

    async def __aenter__(self) -> "HARestClient":
        """Контекст менеджер для автоматического управления сессией."""
        self.session = aiohttp.ClientSession()
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Закрытие сессии при выходе из контекста."""
        if self.session:
            await self.session.close()
            self.session = None
            self._connected = False

    async def connect_to_ha(self) -> bool:
        """Подключается к Home Assistant и проверяет токен.

        Returns:
            True если подключение успешно, False иначе
        """
        try:
            if not self.session:
                self.session = aiohttp.ClientSession()

            headers = {
                "Authorization": f"Bearer {self.token}",
                "Content-Type": "application/json",
            }

            async with self.session.get(
                f"{self.base_url}/api/",
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                if resp.status == 200:
                    self._connected = True
                    logger.info(f"Успешно подключился к Home Assistant: {self.base_url}")
                    return True
                else:
                    logger.error(f"Ошибка подключения к HA (статус {resp.status})")
                    self._connected = False
                    return False
        except Exception as e:
            logger.error(f"Ошибка при подключении к Home Assistant: {e}")
            self._connected = False
            return False

    async def fetch_devices(self) -> list[dict[str, Any]]:
        """Получает список всех состояний (включая устройства и сущности) из Home Assistant.

        Returns:
            Список состояний устройств/сущностей из HA

        Raises:
            ConnectionError: Если не подключен к HA
            aiohttp.ClientError: При ошибке HTTP запроса
        """
        if not self._connected:
            raise ConnectionError("Not connected to Home Assistant. Call connect_to_ha() first.")

        try:
            headers = {
                "Authorization": f"Bearer {self.token}",
                "Content-Type": "application/json",
            }

            async with self.session.get(
                f"{self.base_url}/api/states",
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=30),
            ) as resp:
                if resp.status == 200:
                    states = await resp.json()
                    logger.info(f"Получено {len(states)} состояний из Home Assistant")
                    return states
                else:
                    logger.error(f"Ошибка получения состояний (статус {resp.status})")
                    return []
        except Exception as e:
            logger.error(f"Ошибка при получении состояний из HA: {e}")
            raise

    async def fetch_areas(self) -> list[dict[str, Any]]:
        """Получает список всех областей (комнат) из Home Assistant.

        Returns:
            Список областей из реестра HA

        Raises:
            ConnectionError: Если не подключен к HA
            aiohttp.ClientError: При ошибке HTTP запроса
        """
        if not self._connected:
            raise ConnectionError("Not connected to Home Assistant. Call connect_to_ha() first.")

        try:
            headers = {
                "Authorization": f"Bearer {self.token}",
                "Content-Type": "application/json",
            }

            async with self.session.get(
                f"{self.base_url}/api/config/area_registry",
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                if resp.status == 200:
                    areas = await resp.json()
                    logger.info(f"Получено {len(areas)} областей из Home Assistant")
                    return areas
                elif resp.status == 404:
                    logger.warning("Endpoint /api/config/area_registry не найден (может быть, старая версия HA)")
                    return []
                else:
                    logger.error(f"Ошибка получения областей (статус {resp.status})")
                    return []
        except Exception as e:
            logger.error(f"Ошибка при получении областей из HA: {e}")
            return []

    async def fetch_device_registry(self) -> list[dict[str, Any]]:
        """Получает реестр устройств из Home Assistant с детальной информацией.

        Реестр содержит информацию об устройствах включая ссылки на области (комнаты).

        Returns:
            Список устройств из реестра HA

        Raises:
            ConnectionError: Если не подключен к HA
        """
        if not self._connected:
            raise ConnectionError("Not connected to Home Assistant. Call connect_to_ha() first.")

        try:
            headers = {
                "Authorization": f"Bearer {self.token}",
                "Content-Type": "application/json",
            }

            async with self.session.get(
                f"{self.base_url}/api/config/device_registry",
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                if resp.status == 200:
                    devices = await resp.json()
                    logger.info(f"Получено {len(devices)} устройств из реестра Home Assistant")
                    return devices
                elif resp.status == 404:
                    logger.warning("Endpoint /api/config/device_registry не найден (может быть, старая версия HA)")
                    return []
                else:
                    logger.error(f"Ошибка получения реестра устройств (статус {resp.status})")
                    return []
        except Exception as e:
            logger.error(f"Ошибка при получении реестра устройств из HA: {e}")
            return []

    async def call_service(self, domain: str, service: str, service_data: dict[str, Any]) -> bool:
        """Вызывает сервис в Home Assistant.

        Args:
            domain: Домен сервиса (e.g., 'light', 'switch')
            service: Имя сервиса (e.g., 'turn_on', 'turn_off')
            service_data: Данные для сервиса (e.g., {'entity_id': 'light.kitchen'})

        Returns:
            True если сервис вызван успешно

        Raises:
            ConnectionError: Если не подключен к HA
        """
        if not self._connected:
            raise ConnectionError("Not connected to Home Assistant. Call connect_to_ha() first.")

        try:
            headers = {
                "Authorization": f"Bearer {self.token}",
                "Content-Type": "application/json",
            }

            async with self.session.post(
                f"{self.base_url}/api/services/{domain}/{service}",
                headers=headers,
                json=service_data,
                timeout=aiohttp.ClientTimeout(total=30),
            ) as resp:
                if resp.status == 200:
                    logger.info(f"Сервис {domain}.{service} вызван успешно")
                    return True
                else:
                    logger.error(f"Ошибка вызова сервиса (статус {resp.status})")
                    return False
        except Exception as e:
            logger.error(f"Ошибка при вызове сервиса {domain}.{service}: {e}")
            raise

    def is_connected(self) -> bool:
        """Проверяет статус подключения.

        Returns:
            True если подключен к HA
        """
        return self._connected
