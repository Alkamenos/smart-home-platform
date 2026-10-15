"""Дашборд Home Assistant, собранный из дома (BACKLOG B79).

Платформа знает комнаты, приборы и датчики — этого достаточно, чтобы собрать
готовый дашборд для Home Assistant, а не заводить его руками. Генератор
(`dashboard/lovelace_generator.py`) написан давно, но не вызывался ниоткуда:
секция `dashboard:` манифеста была настройкой в пустоту (аудит 2026-10-16, К-17).

Два действия:

* ``GET /api/v1/system/dashboard`` — готовый дашборд и его текст;
* ``POST /api/v1/system/dashboard/publish`` — создать (или обновить) **свою**
  панель в Home Assistant. Чужие панели владельца платформа не трогает: у неё
  собственный путь ``behavioral``, и правит она только его.

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0
"""

from __future__ import annotations

from typing import Any

import yaml
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse


router = APIRouter(tags=["dashboard"])

#: Путь панели платформы в Home Assistant.
#:
#: Отдельный от панелей владельца намеренно: публикация — это запись в его дом, и
#: она не должна касаться того, что он настроил сам. Дефис обязателен: Home
#: Assistant отвергает путь без дефиса («Url path needs to contain a hyphen»),
#: иначе панель не создать.
DASHBOARD_PATH = "behavioral-platform"


def _container(request: Request) -> Any:
    """Взять контейнер платформы.

    Args:
        request: Входящий HTTP-запрос.

    Returns:
        Контейнер либо ``None``.
    """
    return getattr(request.app.state, "container", None)


def _manifest(request: Request) -> Any:
    """Взять манифест дома.

    Args:
        request: Входящий HTTP-запрос.

    Returns:
        Манифест либо ``None``, если контейнера нет.
    """
    container = _container(request)
    if container is None:
        return None
    try:
        return container.manifest
    except Exception:  # noqa: BLE001 — дашборд не стоит отказа страницы
        return None


def _adapter(request: Request) -> Any:
    """Взять адаптер Home Assistant.

    Args:
        request: Входящий HTTP-запрос.

    Returns:
        Адаптер либо ``None``.
    """
    container = _container(request)
    if container is None:
        return None
    return getattr(container, "adapter", None)


def _title(manifest: Any, config: dict[str, Any]) -> str:
    """Название дашборда: из манифеста, иначе имя дома.

    Пустое название в манифесте — не повод отдать дашборд без имени: в списке
    панелей Home Assistant он должен называться домом, а не пустой строкой.

    Args:
        manifest: Манифест дома.
        config: Собранная конфигурация.

    Returns:
        Название дашборда.
    """
    title = str(config.get("title") or "").strip()
    if title:
        return title
    dashboard = getattr(manifest, "dashboard", None)
    title = str(getattr(dashboard, "title", "") or "").strip()
    if title:
        return title
    return str(getattr(getattr(manifest, "instance", None), "name", "") or "Дом")


def _build(manifest: Any) -> dict[str, Any]:
    """Собрать конфигурацию дашборда из дома.

    Args:
        manifest: Манифест дома.

    Returns:
        Конфигурация Lovelace; пустая, если собрать не удалось.
    """
    from dashboard.lovelace_generator import LovelaceGenerator

    config = LovelaceGenerator().generate(manifest)
    if not isinstance(config, dict):
        return {"title": "Дом", "views": []}
    config["title"] = _title(manifest, config)
    return config


@router.get("/api/v1/system/dashboard")
async def dashboard(request: Request) -> JSONResponse:
    """Дашборд Home Assistant, собранный из манифеста дома.

    Args:
        request: Входящий HTTP-запрос.

    Returns:
        JSON: ``title``, ``views`` (готовые представления), ``counts`` и ``yaml`` —
        тот же дашборд текстом, чтобы вставить в Home Assistant.
    """
    manifest = _manifest(request)
    if manifest is None:
        return JSONResponse({"title": "", "views": [], "counts": {}, "yaml": ""})

    config = _build(manifest)
    views = config.get("views") or []
    counts = {
        "views": len(views),
        "cards": sum(len(view.get("cards") or []) for view in views if isinstance(view, dict)),
    }
    return JSONResponse(
        {
            "title": config["title"],
            "views": views,
            "counts": counts,
            "yaml": yaml.safe_dump(config, allow_unicode=True, sort_keys=False),
        }
    )


@router.post("/api/v1/system/dashboard/publish")
async def publish(request: Request) -> JSONResponse:
    """Создать (или обновить) панель платформы в Home Assistant.

    Запись в дом — действие человека: маршрут ничего не делает сам по себе.
    Панель одна и со своим путём (``behavioral``): повторная публикация обновляет
    её, чужие панели не затрагиваются.

    Args:
        request: Входящий HTTP-запрос.

    Returns:
        JSON с признаком ``published`` и объяснением, если не вышло.
    """
    manifest = _manifest(request)
    adapter = _adapter(request)
    if manifest is None or adapter is None:
        return JSONResponse(
            {"published": False, "detail": "дом недоступен: публиковать некуда"},
            status_code=503,
        )

    config = _build(manifest)
    existing = await adapter.find_dashboard(DASHBOARD_PATH)
    if existing is None and not await adapter.create_dashboard(DASHBOARD_PATH, config["title"]):
        return JSONResponse(
            {
                "published": False,
                "detail": "Home Assistant не создал панель: проверьте права токена",
            },
            status_code=502,
        )

    if not await adapter.save_dashboard_config(DASHBOARD_PATH, config):
        return JSONResponse(
            {"published": False, "detail": "Home Assistant не принял конфигурацию панели"},
            status_code=502,
        )

    return JSONResponse(
        {
            "published": True,
            "url_path": DASHBOARD_PATH,
            "title": config["title"],
            "detail": (
                f"панель «{config['title']}» обновлена в доме"
                if existing is not None
                else f"панель «{config['title']}» создана в доме"
            ),
        }
    )
