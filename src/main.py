#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0

# src/main.py
import asyncio
import logging
import os
import signal
import sys
from pathlib import Path
from typing import Any

import uvicorn
from loguru import logger
from pydantic import ValidationError

from core.container import Container
from core.logging_setup import configure_library_logging
from services.config_watcher import create_watcher, hot_reload_enabled

# Канонический путь импорта — src.webui.* (совпадает с Makefile и со всеми
# остальными импортами веб-слоя). Импорт через верхнеуровневый `webui` создавал
# второй экземпляр модулей с собственным менеджером WebSocket-соединений, и
# раздача живых обновлений уходила «в никуда» (spec 007, FR-024).
from webui.app import create_app


# Настройка loguru с цветным выводом для Docker
# Определяем нужно ли раскрашивать логи
SHOULD_COLORIZE = os.getenv("FORCE_COLOR", "true").lower() in ("1", "true", "yes", "on")

# Уровень логирования из переменной окружения
LOG_LEVEL = os.getenv(
    "LOG_LEVEL", "INFO"
)  # Дефолт INFO (не DEBUG, чтобы не спамить WebSocket логами)

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

# Отключаем DEBUG логи для WebSocket библиотек (спам бинарными сообщениями)
logging.getLogger("websockets").setLevel(logging.INFO)
logging.getLogger("websockets.client").setLevel(logging.INFO)
logging.getLogger("websockets.server").setLevel(logging.INFO)
logging.getLogger("asyncio").setLevel(logging.INFO)
logging.getLogger("aiohttp").setLevel(logging.INFO)

# Остальные библиотеки настраиваются отдельно
configure_library_logging()

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


# `app` для TestClient-совместимости (tests/contract) собирается лениво, по
# первому обращению.
#
# Раньше здесь стоял вызов `app = create_app()` на уровне модуля. Продакшен
# запускается как `python -m src.main`, то есть **импортирует** модуль, и в этот
# момент поднималось второе приложение со вторым контейнером, вторым реестром и
# вторым снимком манифеста — по пути из образа (`/app/instances/...`), а не из
# тома (`/config/behavioral_platform/...`). Доказано запуском контейнера: при одном
# старте `Registered 10 action handlers` печатается дважды, а
# `Discovery routes initialized` — с двумя разными манифестами.
#
# Два независимых `ManifestStore` означали, что изменение, сделанное одним
# экземпляром, не видно другому: `POST /api/v1/devices/apply` не находил комнату,
# которую `/api/rooms` показывал (Known Issue K7).
#
# Ленивая сборка решает это: `run_platform` остаётся единственным местом,
# собирающим продакшен-приложение, а контрактные тесты продолжают получать
# `main.app` — по одному общему экземпляру.
_APP: Any = None


def __getattr__(name: str) -> Any:
    """Ленивая сборка `app` при первом обращении (PEP 562).

    Args:
        name: Имя атрибута модуля.

    Returns:
        Собранное приложение для `app`.

    Raises:
        AttributeError: Для любого другого имени.
    """
    global _APP
    if name == "app":
        if _APP is None:
            _APP = create_app()
        return _APP
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


async def run_platform():
    # Принудительно поднимаем уровень журналов библиотек ПОСЛЕ всех импортов.
    # Вызов на уровне модуля не работает: websockets импортируется внутри
    # ha_adapter.py и сбрасывает уровень обратно на NOTSET.
    configure_library_logging(force=True)

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
    # Ранняя и понятная проверка манифеста: без него платформа не знает дом, а
    # голый стек pydantic ничего не объясняет тому, кто поднимает платформу
    # впервые (переносимость, BACKLOG B78).
    try:
        _ = container.manifest
    except FileNotFoundError as exc:
        logger.error("{}", exc)
        raise SystemExit(2) from exc
    except ValidationError as exc:
        logger.error(
            "Манифест {} не прошёл проверку — исправьте его и перезапустите:\n{}",
            manifest_path,
            exc,
        )
        raise SystemExit(2) from exc
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
        config = uvicorn.Config(
            app,
            host="0.0.0.0",
            port=8125,
            log_level="debug",
            # Предел ожидания при завершении. Дефолт uvicorn — None, то есть
            # ждать вечно, а WS-ручки держат соединение бесконечным циклом
            # `await websocket.receive_text()`. Без предела Docker выждет
            # stop_grace_period и убьёт процесс SIGKILL, после чего
            # `ctx.shutdown()` не выполнится вовсе.
            timeout_graceful_shutdown=8,
        )
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
