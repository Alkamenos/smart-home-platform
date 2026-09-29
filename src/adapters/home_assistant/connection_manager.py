"""
Менеджер соединения с обработкой ошибок и переподключением.

Обеспечивает надежное соединение с Home Assistant с автоматическим переподключением.
"""

import asyncio
import logging

import aiohttp


logger = logging.getLogger(__name__)


class ConnectionManager:
    """Управляет соединением с exponential backoff переподключением."""

    def __init__(
        self,
        base_url: str,
        token: str,
        max_retries: int = 5,
        initial_retry_delay: float = 1.0,
        max_retry_delay: float = 300.0,
    ) -> None:
        """Инициализация менеджера соединения.

        Args:
            base_url: URL Home Assistant
            token: API токен
            max_retries: Максимальное количество попыток переподключения
            initial_retry_delay: Начальная задержка переподключения в секундах
            max_retry_delay: Максимальная задержка переподключения в секундах
        """
        self.base_url = base_url
        self.token = token
        self.max_retries = max_retries
        self.initial_retry_delay = initial_retry_delay
        self.max_retry_delay = max_retry_delay
        self._connected = False
        self._retry_count = 0
        self._session: aiohttp.ClientSession | None = None

    async def connect(self) -> bool:
        """Подключается с логикой переподключения.

        Returns:
            True если успешно подключен
        """
        while self._retry_count < self.max_retries:
            try:
                self._session = aiohttp.ClientSession()

                # Попытка подключиться к API Home Assistant
                headers = {
                    "Authorization": f"Bearer {self.token}",
                    "Content-Type": "application/json",
                }

                async with self._session.get(
                    f"{self.base_url}/api/",
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as resp:
                    if resp.status == 200:
                        self._connected = True
                        self._retry_count = 0
                        logger.info(f"Успешно подключился к {self.base_url}")
                        return True

                # Если статус не 200, ошибка подключения
                raise ConnectionError(f"HTTP {resp.status}")

            except Exception as e:
                self._retry_count += 1
                await self._session.close() if self._session else None

                if self._retry_count >= self.max_retries:
                    logger.error(f"Максимальное количество попыток превышено: {e}")
                    return False

                delay = self._calculate_backoff_delay()
                logger.warning(
                    f"Ошибка подключения ({self._retry_count}/{self.max_retries}): {e}. "
                    f"Переподключение через {delay:.1f} сек..."
                )
                await asyncio.sleep(delay)

        return False

    async def disconnect(self) -> None:
        """Отключается от сервера."""
        self._connected = False
        if self._session:
            await self._session.close()
            logger.info("Отключено от Home Assistant")

    def _calculate_backoff_delay(self) -> float:
        """Вычисляет задержку с exponential backoff.

        Returns:
            Задержка в секундах
        """
        # exponential backoff: 1, 2, 4, 8, 16, но не более max_retry_delay
        delay = self.initial_retry_delay * (2 ** (self._retry_count - 1))
        return min(delay, self.max_retry_delay)

    def is_connected(self) -> bool:
        """Проверяет статус соединения.

        Returns:
            True если подключен
        """
        return self._connected

    def get_retry_count(self) -> int:
        """Возвращает количество попыток переподключения.

        Returns:
            Текущее количество попыток
        """
        return self._retry_count
