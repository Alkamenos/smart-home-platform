"""Дашборд дома отдаётся наружу (BACKLOG B79, аудит К-17).

Генератор дашборда был написан давно, но не вызывался ниоткуда: секция
``dashboard:`` манифеста была настройкой в пустоту. Здесь проверяется, что дашборд
собирается из дома и его можно забрать: представления, счётчики и готовый YAML для
вставки в Home Assistant.
"""

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import json
from typing import Any

import pytest

from core.models.manifest import load_manifest
from webui.routes.dashboard import dashboard


class _Container:
    """Контейнер в объёме, который нужен маршруту."""

    def __init__(self, manifest: Any) -> None:
        """Собрать контейнер.

        Args:
            manifest: Манифест дома.
        """
        self.manifest = manifest


class _Request:
    """Запрос в объёме, который нужен маршруту."""

    def __init__(self, manifest: Any) -> None:
        """Собрать запрос.

        Args:
            manifest: Манифест дома.
        """
        container = _Container(manifest)
        self.app = type("App", (), {"state": type("State", (), {"container": container})()})


def _payload(response: Any) -> dict[str, Any]:
    """Разобрать ответ маршрута.

    Args:
        response: Ответ FastAPI.

    Returns:
        Разобранное тело ответа.
    """
    return json.loads(response.body)


@pytest.mark.asyncio
async def test_dashboard_is_built_from_the_house() -> None:
    """Дашборд собирается из комнат и приборов дома.

    Returns:
        Ничего.
    """
    manifest = load_manifest("instances/leonids_house/manifest.yaml")

    payload = _payload(await dashboard(_Request(manifest)))

    assert payload["views"], "дашборд без представлений: генератор не вызван"
    assert payload["counts"]["views"] >= 1
    assert payload["counts"]["cards"] >= 1
    assert "views:" in payload["yaml"], "нет текста для вставки в Home Assistant"


@pytest.mark.asyncio
async def test_empty_title_becomes_the_house_name() -> None:
    """Пустое название в манифесте заменяется именем дома.

    В списке панелей Home Assistant дашборд должен называться домом, а не пустой
    строкой.

    Returns:
        Ничего.
    """
    manifest = load_manifest("instances/leonids_house/manifest.yaml")
    manifest.dashboard.title = ""

    payload = _payload(await dashboard(_Request(manifest)))

    assert payload["title"].strip(), "дашборд остался без названия"
    assert payload["title"] == manifest.instance.name


@pytest.mark.asyncio
async def test_without_a_manifest_the_route_does_not_fail() -> None:
    """Без манифеста маршрут отдаёт пустой дашборд, а не падает.

    Returns:
        Ничего.
    """
    request = type(
        "R", (), {"app": type("A", (), {"state": type("S", (), {"container": None})()})()}
    )()

    payload = _payload(await dashboard(request))

    assert payload["views"] == []
