#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0

# src/main.py
import asyncio
import os
import signal

import uvicorn
from loguru import logger

from bootstrap import bootstrap_platform
from webui.app import create_app


async def run_platform():
    manifest_dir = os.environ.get("CONFIG_PATH", "instances/leonids_house")
    manifest_path = os.path.join(manifest_dir, "manifest.yaml")

    logger.info(f"🚀 Bootstrapping Smart Home Platform from {manifest_path}")
    ctx = bootstrap_platform(manifest_path)

    # 1. Запуск WebSocket коннекта к HA (в фоне)
    await ctx.adapter.start()

    # 2. Запуск FastAPI для Healthcheck (порт 8125, как в docker-compose)
    app = create_app(manifest_path)
    config = uvicorn.Config(app, host="0.0.0.0", port=8125, log_level="warning")
    server = uvicorn.Server(config)

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
