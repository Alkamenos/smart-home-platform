"""Дашборд Home Assistant, собранный из дома (BACKLOG B79).

Платформа знает комнаты, приборы и датчики — этого достаточно, чтобы собрать
готовый дашборд для Home Assistant, а не заводить его руками. Генератор
(`dashboard/lovelace_generator.py`) написан давно, но не вызывался ниоткуда:
секция `dashboard:` манифеста была настройкой в пустоту (аудит 2026-10-16, К-17).

Здесь он отдаётся наружу: представления по комнатам и готовый YAML, который можно
вставить в Home Assistant. Прямая публикация в дом — следующий шаг: канал для неё
уже проверен (`lovelace/dashboards/create` и `lovelace/config/save`).

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0
"""

from __future__ import annotations

from typing import Any

import yaml
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse


router = APIRouter(tags=["dashboard"])


def _manifest(request: Request) -> Any:
    """Взять манифест дома из контейнера.

    Args:
        request: Входящий HTTP-запрос.

    Returns:
        Манифест либо ``None``, если контейнера нет.
    """
    container = getattr(request.app.state, "container", None)
    if container is None:
        return None
    try:
        return container.manifest
    except Exception:  # noqa: BLE001 — дашборд не стоит отказа страницы
        return None


def _title(manifest: Any) -> str:
    """Название дашборда: из манифеста, иначе имя дома.

    Пустое название в манифесте — не повод отдать дашборд без имени: в списке
    панелей Home Assistant он должен называться домом, а не пустой строкой.

    Args:
        manifest: Манифест дома.

    Returns:
        Название дашборда.
    """
    dashboard = getattr(manifest, "dashboard", None)
    title = str(getattr(dashboard, "title", "") or "").strip()
    if title:
        return title
    return str(getattr(getattr(manifest, "instance", None), "name", "") or "Дом")


@router.get("/api/v1/system/dashboard")
async def dashboard(request: Request) -> JSONResponse:
    """Дашборд Home Assistant, собранный из манифеста дома.

    Args:
        request: Входящий HTTP-запрос.

    Returns:
        JSON: ``title``, ``views`` (готовые представления), ``counts`` и ``yaml`` —
        тот же дашборд текстом, чтобы вставить в Home Assistant.
    """
    from dashboard.lovelace_generator import LovelaceGenerator

    manifest = _manifest(request)
    if manifest is None:
        return JSONResponse({"title": "", "views": [], "counts": {}, "yaml": ""})

    config = LovelaceGenerator().generate(manifest)
    if not isinstance(config, dict):
        return JSONResponse({"title": "Дом", "views": [], "counts": {}, "yaml": ""})

    title = str(config.get("title") or "").strip() or _title(manifest)
    config["title"] = title
    views = config.get("views") or []
    counts = {
        "views": len(views),
        "cards": sum(len(view.get("cards") or []) for view in views if isinstance(view, dict)),
    }
    return JSONResponse(
        {
            "title": title,
            "views": views,
            "counts": counts,
            "yaml": yaml.safe_dump(config, allow_unicode=True, sort_keys=False),
        }
    )
