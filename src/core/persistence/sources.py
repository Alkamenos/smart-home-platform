"""
Слой персистентности для источников Home Assistant.

Обеспечивает сохранение и загрузку конфигурации источников HA из файловой системы.
"""

import json
import logging
from pathlib import Path
from uuid import UUID

from src.core.models.ha_source import HASource
from src.core.security.encryption import TokenEncryptor


logger = logging.getLogger(__name__)


class HASourcePersistence:
    """Управляет сохранением и загрузкой источников Home Assistant."""

    def __init__(
        self, data_dir: Path | str = "data", encryptor: TokenEncryptor | None = None
    ) -> None:
        """Инициализация персистентности.

        Args:
            data_dir: Директория для сохранения данных
            encryptor: Шифровальщик для токенов (опционально)
        """
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.sources_file = self.data_dir / "sources.json"
        self.encryptor = encryptor

    async def save_source(self, source: HASource) -> None:
        """Сохраняет источник в файл.

        Args:
            source: Источник для сохранения
        """
        try:
            # Получаем существующие источники
            sources_data = await self._load_sources_data()

            # Создаем копию для сохранения
            source_dict = source.model_dump(mode="json")

            # Шифруем токен
            if self.encryptor:
                source_dict["token"] = self.encryptor.encrypt(source.token)

            sources_data[str(source.id)] = source_dict

            # Сохраняем в файл
            with open(self.sources_file, "w") as f:
                json.dump(sources_data, f, indent=2, default=str)

            logger.info(f"Источник {source.id} сохранен в {self.sources_file}")

        except Exception as e:
            logger.error(f"Ошибка сохранения источника: {e}")
            raise

    async def load_source(self, source_id: UUID) -> HASource | None:
        """Загружает источник по ID.

        Args:
            source_id: Идентификатор источника

        Returns:
            HASource если найден, None иначе
        """
        try:
            sources_data = await self._load_sources_data()
            source_data = sources_data.get(str(source_id))

            if not source_data:
                return None

            # Дешифруем токен
            if self.encryptor:
                try:
                    source_data["token"] = self.encryptor.decrypt(source_data["token"])
                except ValueError:
                    # Если не зашифрован, используем как есть
                    pass

            return HASource(**source_data)

        except Exception as e:
            logger.error(f"Ошибка загрузки источника {source_id}: {e}")
            return None

    async def load_all_sources(self) -> list[HASource]:
        """Загружает все источники.

        Returns:
            Список всех источников
        """
        try:
            sources_data = await self._load_sources_data()
            sources = []

            for source_data in sources_data.values():
                try:
                    # Дешифруем токен
                    if self.encryptor:
                        try:
                            source_data = source_data.copy()
                            source_data["token"] = self.encryptor.decrypt(source_data["token"])
                        except ValueError:
                            pass

                    source = HASource(**source_data)
                    sources.append(source)
                except Exception as e:
                    logger.warning(f"Ошибка загрузки источника: {e}")
                    continue

            logger.info(f"Загружено {len(sources)} источников")
            return sources

        except Exception as e:
            logger.error(f"Ошибка загрузки источников: {e}")
            return []

    async def delete_source(self, source_id: UUID) -> bool:
        """Удаляет источник.

        Args:
            source_id: Идентификатор источника для удаления

        Returns:
            True если удален успешно
        """
        try:
            sources_data = await self._load_sources_data()

            if str(source_id) in sources_data:
                del sources_data[str(source_id)]

                with open(self.sources_file, "w") as f:
                    json.dump(sources_data, f, indent=2, default=str)

                logger.info(f"Источник {source_id} удален")
                return True

            return False

        except Exception as e:
            logger.error(f"Ошибка удаления источника: {e}")
            return False

    async def _load_sources_data(self) -> dict:
        """Загружает данные о всех источниках из файла.

        Returns:
            Словарь с данными источников
        """
        if not self.sources_file.exists():
            return {}

        try:
            with open(self.sources_file) as f:
                return json.load(f)
        except json.JSONDecodeError:
            logger.warning(f"Файл {self.sources_file} повреждён, начинаю с пустого")
            return {}
