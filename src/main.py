#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0

# src/main.py
import asyncio
import logging
import os
import signal
import sys
from pathlib import Path

import uvicorn
from loguru import logger

from core.container import Container
from services.config_watcher import create_watcher, hot_reload_enabled

# Канонический путь импорта — src.webui.* (совпадает с Makefile и со всеми
# остальными импортами веб-слоя). Импорт через верхнеуровневый `webui` создавал
# второй экземпляр модулей с собственным менеджером WebSocket-соединений, и
# раздача живых обновлений уходила «в никуда» (spec 007, FR-024).
from src.webui.app import create_app


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

# Конфигурируем loguru для совместимости с Docker логами
logger.remove()

# Добавляем обработчик в stderr с цветами для Docker
# stderr автоматически попадает в docker logs
logger.add(
    sys.stderr,
    level=LOG_LEVEL,
    format=COLORED_FORMAT,
    colorize=SHOULD_COLORIZE,
    backtrace=True,
    diagnose=False,
    enqueue=False,  # Без очереди для синхронности логов в Docker
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


# Module-level app для TestClient-совместимости (tests/contract):
# create_app() собирает приложение с дефолтным манифестом и сервисами домена.
app = create_app()


async def run_platform():
    # Get project root (parent of src directory)
    project_root = Path(__file__).parent.parent

    manifest_dir = os.environ.get("CONFIG_PATH", project_root / "instances" / "leonids_house")
    manifest_path = Path(manifest_dir) / "manifest.yaml"

    # Convert to absolute path to ensure it works regardless of CWD
    manifest_path = manifest_path.resolve()

    logger.info(f"🚀 Bootstrapping Smart Home Platform from {manifest_path}")
    # Явная сборка контейнера (как bootstrap_platform): нужен доступ к factory/registry
    # для ConfigWatcher — PlatformContext контейнера не содержит
    container = Container(manifest_path=str(manifest_path))
    ctx = container.build()

    # Hot-reload манифеста/фич под env-флагом HOT_RELOAD (default OFF — Known Issue #8)
    config_watcher = None
    if hot_reload_enabled():
        config_watcher = create_watcher(
            factory=container.factory,
            engine=container.fsm,
            registry=container.registry,
            manifest_path=str(manifest_path),
            features_dir=str(project_root / "src" / "features"),
            instances_dir=str(project_root / "instances"),
        )
        config_watcher.start()
        logger.info("🔄 ConfigWatcher started (HOT_RELOAD enabled)")
    else:
        logger.info("Hot-reload disabled (set HOT_RELOAD=1 to enable)")

    try:
        # 1. Запуск WebSocket коннекта к HA (в фоне)
        await ctx.adapter.start()

        # 1a. Оповещение подписчиков о готовности платформы: восстановление
        # сохранённых состояний автоматов и запуск проверки расписаний
        # (FR-007). Событие платформой не публиковалось, поэтому эти
        # подписчики оставались мёртвыми.
        await container.announce_started()

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

        # Очистка ресурсов (идемпотентная цепочка: adapter + FSM + dispatcher TTL-loop)
        await ctx.shutdown()
    finally:
        if config_watcher is not None:
            config_watcher.stop()


if __name__ == "__main__":
    asyncio.run(run_platform())
