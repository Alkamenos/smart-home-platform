#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0

# src/main.py
import asyncio
import os
import signal
from pathlib import Path

import uvicorn
from loguru import logger

from bootstrap import bootstrap_platform
from webui.app import create_app


async def run_platform():
    # Get project root (parent of src directory)
    project_root = Path(__file__).parent.parent

    manifest_dir = os.environ.get("CONFIG_PATH", project_root / "instances" / "leonids_house")
    manifest_path = Path(manifest_dir) / "manifest.yaml"

    # Convert to absolute path to ensure it works regardless of CWD
    manifest_path = manifest_path.resolve()

    logger.info(f"🚀 Bootstrapping Smart Home Platform from {manifest_path}")
    ctx = bootstrap_platform(str(manifest_path))

    # 1. Запуск WebSocket коннекта к HA (в фоне)
    await ctx.adapter.start()

    # 2. Запуск FastAPI для Healthcheck (порт 8125, как в docker-compose)
    app = create_app(str(manifest_path))
    config = uvicorn.Config(app, host="0.0.0.0", port=8125, log_level="warning")
    server = uvicorn.Server(config)
    try:
        logger.info(f"🌐 Creating FastAPI app with manifest: {manifest_path}")
        app = create_app(manifest_path)
        logger.info("✅ FastAPI app created successfully")
        config = uvicorn.Config(app, host="0.0.0.0", port=8125, log_level="info")
        server = uvicorn.Server(config)
        logger.info("✅ Uvicorn server configured on port 8125")
    except Exception as e:
        logger.error(f"❌ Failed to create FastAPI app: {e}")
        import traceback

        traceback.print_exc()
        raise

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
