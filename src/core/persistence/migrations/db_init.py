"""
Инициализационный скрипт для подготовки БД и применения миграций.

Используется при старте приложения для обеспечения наличия всех необходимых
структур данных и индексов.
"""

import asyncio
import logging
from pathlib import Path

from src.core.persistence.migrations.migrations_runner import (
    MigrationsRunner,
    check_migrations_status,
    init_migrations,
)


logger = logging.getLogger(__name__)


async def initialize_database(data_dir: Path | str = "data", apply_migrations: bool = True) -> bool:
    """
    Инициализировать БД и применить все необходимые миграции.

    Args:
        data_dir: Директория для хранения данных
        apply_migrations: Применять ли миграции автоматически

    Returns:
        True если инициализация успешна
    """
    try:
        logger.info("Инициализация БД...")
        data_dir = Path(data_dir)
        data_dir.mkdir(parents=True, exist_ok=True)

        if apply_migrations:
            logger.info("Применение миграций...")
            runner = await init_migrations(data_dir)
            logger.info("Миграции успешно применены")
        else:
            logger.info("Проверка статуса миграций...")
            status = await check_migrations_status(data_dir)
            logger.info(
                f"Статус: {status['applied_count']} applied, {status['pending_count']} pending"
            )

        return True

    except Exception as e:
        logger.error(f"Ошибка при инициализации БД: {e}", exc_info=True)
        return False


async def verify_migrations(data_dir: Path | str = "data") -> bool:
    """
    Проверить, что все миграции применены.

    Args:
        data_dir: Директория для хранения данных

    Returns:
        True если все миграции применены
    """
    try:
        status = await check_migrations_status(data_dir)
        is_complete = status["pending_count"] == 0

        logger.info(
            f"Статус миграций: {status['applied_count']} applied, {status['pending_count']} pending"
        )

        if not is_complete:
            logger.warning("Есть необученные миграции. Необходимо запустить инициализацию БД.")

        return is_complete

    except Exception as e:
        logger.error(f"Ошибка при проверке миграций: {e}", exc_info=True)
        return False


async def reset_database(data_dir: Path | str = "data", confirm: bool = False) -> bool:
    """
    Полностью сбросить БД (откатить все миграции).

    Args:
        data_dir: Директория для хранения данных
        confirm: Подтверждение на выполнение

    Returns:
        True если сброс успешен
    """
    if not confirm:
        logger.warning("Требуется подтверждение для сброса БД")
        return False

    try:
        logger.warning("Сброс БД...")
        runner = MigrationsRunner(data_dir)
        status = await check_migrations_status(data_dir)

        if status["applied_count"] > 0:
            await runner.down(steps=status["applied_count"])
            logger.info("БД успешно сброшена")

        return True

    except Exception as e:
        logger.error(f"Ошибка при сбросе БД: {e}", exc_info=True)
        return False


def print_migration_status(data_dir: Path | str = "data") -> None:
    """
    Вывести статус всех миграций.

    Args:
        data_dir: Директория для хранения данных
    """
    try:
        runner = MigrationsRunner(data_dir)
        status = runner.status()

        print("\n" + "=" * 60)
        print("Статус миграций БД")
        print("=" * 60)
        print(f"Applied:  {status['applied_count']}")
        print(f"Pending:  {status['pending_count']}")
        if status.get("last_migration_time"):
            print(f"Last:     {status['last_migration_time']}")
        print("\nМиграции:")
        print("-" * 60)

        for migration in status["migrations"]:
            status_icon = "[X]" if migration["status"] == "applied" else "[ ]"
            print(f"{status_icon} {migration['name']}: {migration['description']}")
            if migration.get("applied_at"):
                print(f"    Applied: {migration['applied_at']}")

        print("=" * 60 + "\n")

    except Exception as e:
        logger.error(f"Ошибка при выводе статуса: {e}", exc_info=True)


# Для использования в CLI или главном скрипте приложения
if __name__ == "__main__":
    import sys

    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )

    # Получаем команду из аргументов
    command = sys.argv[1] if len(sys.argv) > 1 else "init"
    data_dir = sys.argv[2] if len(sys.argv) > 2 else "data"

    if command == "init":
        success = asyncio.run(initialize_database(data_dir))
        sys.exit(0 if success else 1)

    elif command == "verify":
        success = asyncio.run(verify_migrations(data_dir))
        sys.exit(0 if success else 1)

    elif command == "status":
        print_migration_status(data_dir)
        sys.exit(0)

    elif command == "reset":
        confirm = "--confirm" in sys.argv
        success = asyncio.run(reset_database(data_dir, confirm=confirm))
        sys.exit(0 if success else 1)

    else:
        print(f"Неизвестная команда: {command}")
        print("Доступные команды: init, verify, status, reset")
        sys.exit(1)
