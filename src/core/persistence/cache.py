"""
Кэширование списка устройств с поддержкой LRU и TTL.

Обеспечивает быстрый доступ к устройствам с автоматическим инвалидированием
по времени жизни (TTL) и методами управления кэшем.
"""

from __future__ import annotations

import logging
import threading
from collections import OrderedDict
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from uuid import UUID

logger = logging.getLogger(__name__)


class DeviceCache:
    """
    LRU кэш для устройств с поддержкой TTL.

    Характеристики:
    - Максимум 1000 записей (LRU вытеснение)
    - TTL 300 секунд по умолчанию
    - Thread-safe операции с использованием Lock
    - Метрики: cache_hits, cache_misses, cache_size

    Пример использования:
        cache = DeviceCache(max_size=1000, ttl_seconds=300)
        cache.set("device_1", device_obj)
        device = cache.get("device_1")
        cache.invalidate("device_1")
        cache.clear()
    """

    def __init__(self, max_size: int = 1000, ttl_seconds: int = 300):
        """
        Инициализация кэша.

        Args:
            max_size: Максимальное количество элементов в кэше
            ttl_seconds: Время жизни записи в секундах
        """
        self.max_size = max_size
        self.ttl_seconds = ttl_seconds
        self._cache: OrderedDict[str, Dict[str, Any]] = OrderedDict()
        self._lock = threading.RLock()

        # Метрики производительности
        self.cache_hits = 0
        self.cache_misses = 0
        self.invalidations = 0

    def get(self, key: str) -> Optional[Any]:
        """
        Получить значение из кэша.

        Args:
            key: Ключ элемента

        Returns:
            Значение если найдено и не истекло, None иначе
        """
        with self._lock:
            if key not in self._cache:
                self.cache_misses += 1
                logger.debug(f"Кэш-промах: {key}")
                return None

            entry = self._cache[key]

            # Проверить TTL
            expires_at = entry.get("expires_at")
            if expires_at and datetime.now(timezone.utc) > expires_at:
                del self._cache[key]
                self.cache_misses += 1
                self.invalidations += 1
                logger.debug(f"Запись истекла: {key}")
                return None

            # Переместить в конец (LRU)
            self._cache.move_to_end(key)
            self.cache_hits += 1
            logger.debug(f"Кэш-попадание: {key} (всего попаданий: {self.cache_hits})")
            return entry["value"]

    def set(self, key: str, value: Any) -> None:
        """
        Добавить или обновить значение в кэше.

        Args:
            key: Ключ элемента
            value: Значение элемента
        """
        with self._lock:
            # Удалить если уже существует
            if key in self._cache:
                del self._cache[key]

            # Проверить размер - удалить самый старый элемент если нужно
            if len(self._cache) >= self.max_size:
                removed_key, _ = self._cache.popitem(last=False)
                logger.debug(f"LRU вытеснение: {removed_key} (размер кэша: {self.max_size})")

            # Добавить новый элемент с TTL
            expires_at = datetime.now(timezone.utc) + timedelta(seconds=self.ttl_seconds)
            self._cache[key] = {
                "value": value,
                "expires_at": expires_at,
                "created_at": datetime.now(timezone.utc),
            }
            logger.debug(f"Элемент добавлен: {key} (TTL: {self.ttl_seconds}s, всего: {len(self._cache)})")

    def invalidate(self, key: str) -> bool:
        """
        Инвалидировать запись в кэше.

        Args:
            key: Ключ элемента для инвалидации

        Returns:
            True если элемент был удален, False если не существовал
        """
        with self._lock:
            if key in self._cache:
                del self._cache[key]
                self.invalidations += 1
                logger.info(f"Инвалидация кэша: {key} (всего инвалидаций: {self.invalidations})")
                return True
            return False

    def invalidate_by_prefix(self, prefix: str) -> int:
        """
        Инвалидировать все записи по префиксу ключа.

        Args:
            prefix: Префикс для поиска

        Returns:
            Количество удаленных записей
        """
        with self._lock:
            keys_to_remove = [k for k in self._cache.keys() if k.startswith(prefix)]
            for key in keys_to_remove:
                del self._cache[key]
                self.invalidations += 1

            if keys_to_remove:
                logger.info(
                    f"Инвалидация по префиксу '{prefix}': удалено {len(keys_to_remove)} записей"
                )
            return len(keys_to_remove)

    def clear(self) -> None:
        """Очистить весь кэш."""
        with self._lock:
            count = len(self._cache)
            self._cache.clear()
            logger.info(f"Кэш полностью очищен ({count} записей)")

    def get_size(self) -> int:
        """Получить текущий размер кэша."""
        with self._lock:
            return len(self._cache)

    def get_stats(self) -> Dict[str, Any]:
        """
        Получить статистику кэша.

        Returns:
            Словарь со статистикой
        """
        with self._lock:
            total_requests = self.cache_hits + self.cache_misses
            hit_rate = (
                (self.cache_hits / total_requests * 100)
                if total_requests > 0
                else 0
            )

            return {
                "cache_size": len(self._cache),
                "max_size": self.max_size,
                "ttl_seconds": self.ttl_seconds,
                "cache_hits": self.cache_hits,
                "cache_misses": self.cache_misses,
                "cache_invalidations": self.invalidations,
                "hit_rate_percent": round(hit_rate, 2),
                "total_requests": total_requests,
            }

    def cleanup_expired(self) -> int:
        """
        Очистить истекшие записи.

        Returns:
            Количество удаленных записей
        """
        with self._lock:
            current_time = datetime.now(timezone.utc)
            keys_to_remove = [
                k for k, v in self._cache.items()
                if v.get("expires_at") and current_time > v["expires_at"]
            ]

            for key in keys_to_remove:
                del self._cache[key]
                self.invalidations += 1

            if keys_to_remove:
                logger.info(f"Очистка истекших: удалено {len(keys_to_remove)} записей")

            return len(keys_to_remove)

    def extend_ttl(self, key: str, additional_seconds: int = None) -> bool:
        """
        Продлить TTL записи.

        Args:
            key: Ключ элемента
            additional_seconds: Дополнительное время в секундах (по умолчанию = ttl_seconds)

        Returns:
            True если успешно, False если элемента нет
        """
        if additional_seconds is None:
            additional_seconds = self.ttl_seconds

        with self._lock:
            if key not in self._cache:
                return False

            entry = self._cache[key]
            entry["expires_at"] = datetime.now(timezone.utc) + timedelta(
                seconds=additional_seconds
            )
            logger.debug(f"TTL продлен: {key} (+{additional_seconds}s)")
            return True
