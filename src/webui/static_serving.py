"""Раздача собранного фронтенда тем же процессом (спека 017, R-02).

Фронтенд собирается в статику (``frontend/out``) и раздаётся с того же origin,
что API: CORS не нужен, модель доступа в локальной сети не меняется, а контейнер
остаётся один. Монтирование добавляется в конец регистрации маршрутов — поэтому
API и служебные пути (``/health``, ``/metrics``, ``/ready``) имеют приоритет.

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0
"""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles


#: Переменная, включающая раздачу нового интерфейса.
SERVE_FRONTEND_ENV = "WEBUI_SERVE_FRONTEND"

#: Значения переменной, означающие «включено».
_TRUTHY = {"1", "true", "yes", "on"}


def default_frontend_dir() -> Path:
    """Каталог собранного фронтенда в дереве репозитория.

    Returns:
        Путь ``frontend/out`` от корня репозитория.
    """
    return Path(__file__).resolve().parents[2] / "frontend" / "out"


def should_serve_frontend() -> bool:
    """Раздавать ли новый интерфейс.

    После удаления старого серверного интерфейса раздача статики — обычное
    поведение: включена, если сборка есть. Переменная
    ``WEBUI_SERVE_FRONTEND`` позволяет явно выключить раздачу (например, чтобы
    отдать только API).

    Returns:
        True, если раздачу следует включить.
    """
    value = os.environ.get(SERVE_FRONTEND_ENV)
    if value is None:
        return True
    return value.strip().lower() in _TRUTHY


def mount_frontend(app: FastAPI, static_dir: Path | None = None) -> bool:
    """Смонтировать статику фронтенда на ``/``, если она собрана.

    Args:
        app: Приложение FastAPI.
        static_dir: Каталог сборки; по умолчанию ``frontend/out``.

    Returns:
        True, если раздача добавлена (каталог существует).
    """
    directory = static_dir if static_dir is not None else default_frontend_dir()
    if not directory.is_dir():
        return False
    app.mount("/", StaticFiles(directory=str(directory), html=True), name="spa")
    return True
