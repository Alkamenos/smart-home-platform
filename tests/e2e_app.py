"""Фабрика FastAPI-приложения для Playwright E2E-тестов.

Нужна потому, что uvicorn запускается с ``--factory`` и вызывает функцию без
аргументов, а ``create_app()`` требует путь к манифесту. Путь передаётся через
переменную окружения ``E2E_MANIFEST_PATH``, которую выставляет фикстура
``start_webui_server`` — так E2E-тесты работают на временной копии манифеста и
не переписывают ``instances/leonids_house/manifest.yaml``.

Запуск: ``uvicorn tests.e2e_app:create_e2e_app --factory``
"""

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import os

from fastapi import FastAPI
from src.webui.app import create_app


def create_e2e_app() -> FastAPI:
    """Создаёт приложение Web UI на манифесте из ``E2E_MANIFEST_PATH``.

    Returns:
        Сконфигурированное FastAPI-приложение.
    """
    manifest_path = os.environ.get("E2E_MANIFEST_PATH")
    return create_app(manifest_path=manifest_path)
