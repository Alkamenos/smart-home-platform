"""
Менеджер для выполнения миграций БД.

Обеспечивает последовательное выполнение и откат миграций,
отслеживание примененных миграций в истории.
"""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class MigrationsRunner:
    """Менеджер для выполнения миграций БД."""

    def __init__(self, data_dir: Path | str = "data", migrations_package: str = "migrations") -> None:
        """
        Инициализация менеджера миграций.

        Args:
            data_dir: Директория для хранения данных и истории миграций
            migrations_package: Имя пакета с миграциями
        """
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.migrations_history_file = self.data_dir / ".migrations_history.json"
        self.migrations_package = migrations_package

        # Импортируем миграции
        from src.core.persistence.migrations.001_init_sources import Migration001InitSources
        from src.core.persistence.migrations.002_init_devices import Migration002InitDevices

        self.available_migrations = [
            Migration001InitSources(data_dir),
            Migration002InitDevices(data_dir),
        ]

        self._init_history()

    def _init_history(self) -> None:
        """Инициализировать файл истории миграций."""
        if not self.migrations_history_file.exists():
            history: Dict[str, Any] = {
                "applied_migrations": [],
                "last_migration_time": None,
                "migrations": {}
            }
            self._save_history(history)

    def _load_history(self) -> Dict[str, Any]:
        """
        Загрузить историю примененных миграций.

        Returns:
            Словарь с историей
        """
        if not self.migrations_history_file.exists():
            return {
                "applied_migrations": [],
                "last_migration_time": None,
                "migrations": {}
            }

        try:
            with open(self.migrations_history_file, "r") as f:
                return json.load(f)
        except (json.JSONDecodeError, FileNotFoundError):
            return {
                "applied_migrations": [],
                "last_migration_time": None,
                "migrations": {}
            }

    def _save_history(self, history: Dict[str, Any]) -> None:
        """
        Сохранить историю примененных миграций.

        Args:
            history: История для сохранения
        """
        with open(self.migrations_history_file, "w") as f:
            json.dump(history, f, indent=2, default=str)

    async def up(self, target_migration: Optional[str] = None) -> None:
        """
        Применить все неприменённые миграции или до определённой миграции.

        Args:
            target_migration: Имя целевой миграции (опционально)

        Raises:
            ValueError: Если целевая миграция не найдена
        """
        try:
            history = self._load_history()
            applied = set(history.get("applied_migrations", []))

            # Определяем, какие миграции нужно применить
            migrations_to_apply = []
            for migration in self.available_migrations:
                if migration.name not in applied:
                    migrations_to_apply.append(migration)

                    if target_migration and migration.name == target_migration:
                        break

            if not migrations_to_apply:
                logger.info("Нет миграций для применения")
                return

            logger.info(f"Применение {len(migrations_to_apply)} миграции(й)...")

            for migration in migrations_to_apply:
                logger.info(f"Применение миграции {migration.name}...")
                await migration.up()

                history["applied_migrations"].append(migration.name)
                history["last_migration_time"] = datetime.utcnow().isoformat()
                history["migrations"][migration.name] = {
                    "applied_at": datetime.utcnow().isoformat(),
                    "description": migration.description
                }
                self._save_history(history)

                logger.info(f"Миграция {migration.name} успешно применена")

            logger.info(f"Все миграции успешно применены")

        except Exception as e:
            logger.error(f"Ошибка при применении миграций: {e}")
            raise

    async def down(self, steps: int = 1) -> None:
        """
        Откатить последние N миграций.

        Args:
            steps: Количество миграций для отката

        Raises:
            ValueError: Если указано слишком много шагов
        """
        try:
            history = self._load_history()
            applied = history.get("applied_migrations", [])

            if steps > len(applied):
                raise ValueError(f"Не можно откатить {steps} миграций, применено только {len(applied)}")

            migrations_to_revert = applied[-steps:]
            logger.info(f"Откат {len(migrations_to_revert)} миграции(й)...")

            for migration_name in reversed(migrations_to_revert):
                migration = self._get_migration_by_name(migration_name)
                if migration:
                    logger.info(f"Откат миграции {migration_name}...")
                    await migration.down()

                    applied.remove(migration_name)
                    if migration_name in history["migrations"]:
                        del history["migrations"][migration_name]

                    history["applied_migrations"] = applied
                    history["last_migration_time"] = (
                        datetime.utcnow().isoformat() if applied else None
                    )
                    self._save_history(history)

                    logger.info(f"Миграция {migration_name} успешно отката")

            logger.info(f"Откат завершен")

        except Exception as e:
            logger.error(f"Ошибка при откате миграций: {e}")
            raise

    def status(self) -> Dict[str, Any]:
        """
        Получить статус всех миграций.

        Returns:
            Словарь со статусом
        """
        history = self._load_history()
        applied = set(history.get("applied_migrations", []))

        status: Dict[str, Any] = {
            "applied_count": len(applied),
            "pending_count": len(self.available_migrations) - len(applied),
            "last_migration_time": history.get("last_migration_time"),
            "migrations": []
        }

        for migration in self.available_migrations:
            status["migrations"].append({
                "name": migration.name,
                "description": migration.description,
                "status": "applied" if migration.name in applied else "pending",
                "applied_at": history["migrations"].get(migration.name, {}).get("applied_at")
            })

        return status

    def _get_migration_by_name(self, name: str):
        """
        Получить объект миграции по имени.

        Args:
            name: Имя миграции

        Returns:
            Объект миграции или None
        """
        for migration in self.available_migrations:
            if migration.name == name:
                return migration
        return None

    async def rebuild_all_indices(self) -> None:
        """Перестроить все индексы для всех таблиц."""
        try:
            logger.info("Перестройка всех индексов...")

            for migration in self.available_migrations:
                if hasattr(migration, "rebuild_indices"):
                    logger.info(f"Перестройка индексов для {migration.name}...")
                    await migration.rebuild_indices()

            logger.info("Все индексы успешно перестроены")

        except Exception as e:
            logger.error(f"Ошибка при перестройке индексов: {e}")
            raise


async def init_migrations(data_dir: Path | str = "data") -> MigrationsRunner:
    """
    Инициализировать и применить все миграции.

    Args:
        data_dir: Директория для хранения данных

    Returns:
        MigrationsRunner: Инициализированный менеджер миграций
    """
    runner = MigrationsRunner(data_dir)
    await runner.up()
    return runner


async def check_migrations_status(data_dir: Path | str = "data") -> Dict[str, Any]:
    """
    Проверить статус миграций.

    Args:
        data_dir: Директория для хранения данных

    Returns:
        Словарь со статусом миграций
    """
    runner = MigrationsRunner(data_dir)
    return runner.status()
