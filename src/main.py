#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0

# src/main.py
import asyncio
import logging
import os
import signal
from pathlib import Path

import uvicorn
from loguru import logger

from bootstrap import bootstrap_platform
from webui.app import create_app


# Настройка loguru с цветным выводом для Docker
# Определяем нужно ли раскрашивать логи
SHOULD_COLORIZE = os.getenv("FORCE_COLOR", "true").lower() in ("1", "true", "yes", "on")

# Уровень логирования из переменной окружения
LOG_LEVEL = os.getenv("LOG_LEVEL", "DEBUG")

# Цветной формат для loguru
COLORED_FORMAT = (
    "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | "
    "<level>{level: <8}</level> | "
    "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - "
    "<level>{message}</level>"
)

# Формат без цветов (для файлов)
PLAIN_FORMAT = "{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | {name}:{function}:{line} - {message}"

# Удаляем стандартный обработчик loguru
logger.remove()

# Добавляем обработчик в stderr с цветами
logger.add(
    "stderr",
    level=LOG_LEVEL,
    format=COLORED_FORMAT,
    colorize=SHOULD_COLORIZE,
    backtrace=True,
    diagnose=False,
    enqueue=True,
)

# Опционально: лог в файл (без цветов)
LOG_FILE = os.getenv("LOG_FILE")
if LOG_FILE:
    logger.add(
        LOG_FILE,
        level="DEBUG",
        format=PLAIN_FORMAT,
        colorize=False,
        rotation="10 MB",
        retention="7 days",
        compression="zip",
        backtrace=True,
    )

logger.info(f"Logger initialized (colorize={SHOULD_COLORIZE}, level={LOG_LEVEL})")


# Перехват логов uvicorn через loguru
class LoguruHandler(logging.Handler):
    """Handler для перенаправления standard logging в loguru."""

    def emit(self, record):
        # Получаем уровень loguru
        try:
            level = logger.level(record.levelname).name
        except ValueError:
            level = "INFO"

        # Логируем через loguru
        logger.opt(depth=1, exception=record.exc_info).log(level, record.getMessage())


# Настраиваем перехват логов uvicorn
uvicorn_logger = logging.getLogger("uvicorn")
uvicorn_logger.handlers.clear()
uvicorn_logger.addHandler(LoguruHandler())
uvicorn_logger.setLevel(logging.INFO)

# Также перехватываем логи access
logging.getLogger("uvicorn.access").handlers.clear()
logging.getLogger("uvicorn.access").addHandler(LoguruHandler())
logging.getLogger("uvicorn.access").setLevel(logging.INFO)


async def run_platform():
    # Get project root (parent of src directory)
    project_root = Path(__file__).parent.parent

    manifest_dir = os.environ.get("CONFIG_PATH", project_root / "instances" / "leonids_house")
    manifest_path = Path(manifest_dir) / "manifest.yaml"

    # Convert to absolute path to ensure it works regardless of CWD
    manifest_path = manifest_path.resolve()

    logger.info(f"🚀 Bootstrapping Smart Home Platform from {manifest_path}")
    container = bootstrap_platform(str(manifest_path))
    ctx = container  # Alias for backward compatibility

    # 1. Запуск WebSocket коннекта к HA (в фоне)
    await ctx.adapter.start()

    # 2. Запуск FastAPI для Healthcheck (порт 8125, как в docker-compose)
    # Pass the container instance so discovery routes can use the connected adapter
    logger.info(f"🌐 Creating FastAPI app with manifest: {manifest_path}")
    app = create_app(str(manifest_path), container_instance=container)
    logger.info("✅ FastAPI app created successfully")

    # Принудительно ставим уровень DEBUG для всех логов Uvicorn
    config = uvicorn.Config(app, host="0.0.0.0", port=8125, log_level="debug")
    server = uvicorn.Server(config)
    logger.info("✅ Uvicorn server configured on port 8125 (log_level=debug)")

    # 3. Graceful Shutdown
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, lambda: asyncio.create_task(server.shutdown()))

    logger.info("✅ Platform is ready and listening on port 8125")
    await server.serve()

    # Очистка ресурсов
    await ctx.adapter.stop()
    await ctx.fsm.shutdown()


if __name__ == "__main__":
    asyncio.run(run_platform())
