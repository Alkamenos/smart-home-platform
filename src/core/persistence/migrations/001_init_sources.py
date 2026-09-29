"""
Миграция 001: Инициализация таблицы sources.

Создает структуру для хранения источников Home Assistant с индексами
для оптимизации поиска по имени и статусу.
"""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any


logger = logging.getLogger(__name__)


class Migration001InitSources:
    """Миграция для инициализации таблицы sources."""

    name = "001_init_sources"
    description = "Инициализация таблицы sources с индексами по имени и статусу"

    def __init__(self, data_dir: Path | str = "data") -> None:
        """
        Инициализация миграции.

        Args:
            data_dir: Директория для хранения данных
        """
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.sources_file = self.data_dir / "sources.json"
        self.indices_file = self.data_dir / ".sources_indices.json"

    async def up(self) -> None:
        """Применить миграцию (создать таблицу sources с индексами)."""
        try:
            logger.info(f"Применение миграции {self.name}...")

            # Инициализируем файл sources.json если его нет
            if not self.sources_file.exists():
                self._init_sources_file()
                logger.info(f"Создан файл {self.sources_file}")
            else:
                logger.info(f"Файл {self.sources_file} уже существует")

            # Инициализируем индексы
            self._init_indices()
            logger.info("Индексы для sources инициализированы")

            logger.info(f"Миграция {self.name} успешно применена")

        except Exception as e:
            logger.error(f"Ошибка при применении миграции {self.name}: {e}")
            raise

    async def down(self) -> None:
        """Откатить миграцию (удалить таблицу sources)."""
        try:
            logger.info(f"Откат миграции {self.name}...")

            if self.sources_file.exists():
                self.sources_file.unlink()
                logger.info(f"Удален файл {self.sources_file}")

            if self.indices_file.exists():
                self.indices_file.unlink()
                logger.info(f"Удален файл индексов {self.indices_file}")

            logger.info(f"Миграция {self.name} успешно отката")

        except Exception as e:
            logger.error(f"Ошибка при откате миграции {self.name}: {e}")
            raise

    def _init_sources_file(self) -> None:
        """Инициализировать файл sources.json с пустой структурой."""
        sources_structure: dict[str, Any] = {}
        with open(self.sources_file, "w") as f:
            json.dump(sources_structure, f, indent=2)

    def _init_indices(self) -> None:
        """Инициализировать индексные структуры для оптимизации поиска."""
        indices: dict[str, Any] = {
            "by_name": {},  # Индекс: имя -> список ID источников
            "by_status": {  # Индекс: статус -> список ID источников
                "connected": [],
                "disconnected": [],
                "error": [],
            },
            "last_updated": datetime.utcnow().isoformat(),
        }

        with open(self.indices_file, "w") as f:
            json.dump(indices, f, indent=2, default=str)

    def get_indices(self) -> dict[str, Any]:
        """
        Получить текущие индексы sources.

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
                "by_name": {},
                "by_status": {"connected": [], "disconnected": [], "error": []},
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
        """Перестроить все индексы из текущих данных sources."""
        try:
            logger.info("Перестройка индексов sources...")

            if not self.sources_file.exists():
                logger.warning(f"Файл {self.sources_file} не существует")
                return

            with open(self.sources_file) as f:
                sources = json.load(f)

            # Инициализируем новые индексы
            indices: dict[str, Any] = {
                "by_name": {},
                "by_status": {"connected": [], "disconnected": [], "error": []},
            }

            # Заполняем индексы
            for source_id, source_data in sources.items():
                name = source_data.get("name", "")
                status = source_data.get("status", "disconnected")

                # Индекс по имени
                if name:
                    if name not in indices["by_name"]:
                        indices["by_name"][name] = []
                    if source_id not in indices["by_name"][name]:
                        indices["by_name"][name].append(source_id)

                # Индекс по статусу
                if status in indices["by_status"] and source_id not in indices["by_status"][status]:
                    indices["by_status"][status].append(source_id)

            self.update_indices(indices)
            logger.info("Индексы sources успешно перестроены")

        except Exception as e:
            logger.error(f"Ошибка при перестройке индексов sources: {e}")
            raise
