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
from webui.routes.dashboard import DASHBOARD_PATH, dashboard, publish


class FakeAdapter:
    """Адаптер-двойник: помнит, что ему велели сделать с панелью."""

    def __init__(
        self, existing: bool = False, can_create: bool = True, can_save: bool = True
    ) -> None:
        """Собрать адаптер.

        Args:
            existing: Есть ли уже панель платформы.
            can_create: Удаётся ли создать панель.
            can_save: Принимает ли дом конфигурацию.
        """
        self.existing = existing
        self.can_create = can_create
        self.can_save = can_save
        self.created = False
        self.saved: dict[str, Any] | None = None

    async def find_dashboard(self, url_path: str) -> dict[str, Any] | None:
        """Найти панель.

        Args:
            url_path: Путь панели.

        Returns:
            Описание панели либо ``None``.
        """
        del url_path
        return {"id": "p1"} if self.existing else None

    async def create_dashboard(self, url_path: str, title: str, icon: str = "") -> bool:
        """Создать панель.

        Args:
            url_path: Путь панели.
            title: Название.
            icon: Значок.

        Returns:
            Удалось ли.
        """
        del url_path, title, icon
        self.created = True
        self.existing = self.can_create
        return self.can_create

    async def save_dashboard_config(self, url_path: str, config: dict[str, Any]) -> bool:
        """Записать конфигурацию.

        Args:
            url_path: Путь панели.
            config: Конфигурация.

        Returns:
            Принял ли дом.
        """
        del url_path
        if self.can_save:
            self.saved = config
        return self.can_save


class _Container:
    """Контейнер в объёме, который нужен маршруту."""

    def __init__(self, manifest: Any, adapter: Any = None) -> None:
        """Собрать контейнер.

        Args:
            manifest: Манифест дома.
            adapter: Адаптер дома.
        """
        self.manifest = manifest
        self.adapter = adapter


class _Request:
    """Запрос в объёме, который нужен маршруту."""

    def __init__(self, manifest: Any, adapter: Any = None) -> None:
        """Собрать запрос.

        Args:
            manifest: Манифест дома.
            adapter: Адаптер дома.
        """
        container = _Container(manifest, adapter)
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


@pytest.mark.asyncio
async def test_first_publish_creates_the_panel() -> None:
    """Первая публикация создаёт панель платформы.

    Returns:
        Ничего.
    """
    manifest = load_manifest("instances/leonids_house/manifest.yaml")
    adapter = FakeAdapter(existing=False)

    payload = _payload(await publish(_Request(manifest, adapter)))

    assert payload["published"] is True, payload
    assert adapter.created, "панель не создана"
    assert adapter.saved is not None, "конфигурация не записана"
    assert payload["url_path"] == DASHBOARD_PATH, "путь панели чужой: могли задеть панели владельца"
    assert "создана" in payload["detail"]


@pytest.mark.asyncio
async def test_repeated_publish_updates_the_same_panel() -> None:
    """Повторная публикация обновляет свою же панель, а не плодит новые.

    Returns:
        Ничего.
    """
    manifest = load_manifest("instances/leonids_house/manifest.yaml")
    adapter = FakeAdapter(existing=True)

    payload = _payload(await publish(_Request(manifest, adapter)))

    assert payload["published"] is True
    assert not adapter.created, "повторная публикация создала ещё одну панель"
    assert "обновлена" in payload["detail"]


@pytest.mark.asyncio
async def test_refused_creation_is_named() -> None:
    """Отказ дома называется причиной, а не молчанием.

    Returns:
        Ничего.
    """
    manifest = load_manifest("instances/leonids_house/manifest.yaml")
    adapter = FakeAdapter(existing=False, can_create=False)

    response = await publish(_Request(manifest, adapter))
    payload = _payload(response)

    assert response.status_code == 502
    assert payload["published"] is False
    assert adapter.saved is None, "писать конфигурацию в несуществующую панель нельзя"
    assert "права" in payload["detail"]


def test_dashboard_path_satisfies_home_assistant() -> None:
    """Путь панели обязан содержать дефис — требование Home Assistant.

    Проверено живым отказом: «Url path needs to contain a hyphen (-)». Без дефиса
    панель не создать, и публикация молча упиралась бы в 502.

    Returns:
        Ничего.
    """
    assert "-" in DASHBOARD_PATH, f"Home Assistant отвергнет путь {DASHBOARD_PATH!r}"
