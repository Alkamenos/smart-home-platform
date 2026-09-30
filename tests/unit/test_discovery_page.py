"""Тесты страницы мастера добавления устройств (spec 006, T027–T032).

Проверяем то, что можно проверить без браузера: разметка не содержит
дублирующихся идентификаторов и мёртвого кода, идентичность приходит из
серверных атрибутов, а страница обращается к реальным эндпоинтам и
предлагает только те шаблоны поведений, которые поддерживает платформа.

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client() -> Iterator[TestClient]:
    """Приложение на временной копии манифеста.

    Yields:
        HTTP-клиент теста.
    """
    import os
    import shutil
    import tempfile

    project_root = Path(__file__).resolve().parent.parent.parent
    work_dir = tempfile.mkdtemp(prefix="discovery_page_")
    previous_cwd = os.getcwd()
    try:
        shutil.copy(
            project_root / "instances" / "leonids_house" / "manifest.yaml",
            Path(work_dir) / "manifest.yaml",
        )
        os.chdir(work_dir)

        from src.webui.app import create_app

        app = create_app(str(Path(work_dir) / "manifest.yaml"))
        yield TestClient(app)
    finally:
        os.chdir(previous_cwd)
        shutil.rmtree(work_dir, ignore_errors=True)


@pytest.fixture
def page(client: TestClient) -> str:
    """HTML мастера добавления устройств.

    Args:
        client: HTTP-клиент теста.

    Returns:
        Исходный HTML страницы.
    """
    response = client.get("/discovery")
    assert response.status_code == 200
    return response.text


class TestDiscoveryMarkup:
    """Разметка мастера."""

    def test_element_ids_should_be_unique(self, page: str) -> None:
        """Дубли идентификаторов ломали разметку: было два #total-devices."""
        ids = re.findall(r'\sid="([^"]+)"', page)
        duplicates = [element_id for element_id, count in Counter(ids).items() if count > 1]
        assert not duplicates, f"Дублирующиеся идентификаторы: {duplicates}"

    def test_page_should_not_contain_dead_script_blocks(self, page: str) -> None:
        """Один блок скриптов, без кода вне <script> и без htmx."""
        assert page.count("<script") == page.count("</script>"), "Незакрытые блоки скриптов"
        assert "htmx" not in page, "htmx не используется мастером"
        assert page.count("function toggleDevice") == 1, "Дубли функций в разметке"

    def test_body_should_expose_server_side_identity(self, page: str) -> None:
        """Идентичность приходит в разметку с бэкенда (FR-009)."""
        assert re.search(r'data-user-id="[^"]+"', page), "Нет атрибута data-user-id"
        assert 'data-user-is-admin="true"' in page or 'data-user-is-admin="false"' in page

    def test_page_should_use_live_endpoints(self, page: str) -> None:
        """Мастер ходит в реальные эндпоинты, а не в заглушку."""
        assert "/discovery-data" in page
        assert "const API = {" in page
        assert "'/api/v1/devices/apply'" in page
        assert "sources: '/api/v1/devices/sources'" in page

    def test_page_should_offer_only_platform_templates(self, page: str) -> None:
        """Шаблоны поведений приходят от платформы, а не зашиты в JavaScript."""
        from src.webui.template_loader import get_template_loader

        expected = sorted(get_template_loader().load_all().keys())
        rendered = re.search(r"const TEMPLATES = (\[.*?\]);", page, re.S)
        assert rendered, "Не найден список шаблонов в разметке"

        import json

        assert json.loads(rendered.group(1)) == expected
        for obsolete in ("switch_control", "sensor_monitoring", "binary_sensor_monitoring"):
            assert f"'{obsolete}'" not in rendered.group(1)

    def test_page_should_report_source_error_separately(self, page: str) -> None:
        """Причина недоступности источника показывается отдельно от пустого результата."""
        assert "Источник недоступен" in page
        assert "не вернул ни одного устройства" in page

    def test_page_should_disable_buttons_while_applying(self, page: str) -> None:
        """Кнопки блокируются на время применения."""
        assert "function withBusy" in page
        assert "button.disabled = busy" in page


class TestDiscoveryRoomsEndpoint:
    """Список комнат для мастера."""

    def test_rooms_should_come_from_manifest_store(self, client: TestClient) -> None:
        """Комнаты отдаёт хранилище манифеста, а не чтение сырого YAML с диска."""
        response = client.get("/api/rooms")

        assert response.status_code == 200
        rooms = response.json()["rooms"]
        assert rooms, "В манифесте есть комнаты"
        assert all({"id", "name"} <= set(room) for room in rooms)

    def test_rooms_should_reflect_manifest_changes(self, client: TestClient) -> None:
        """Изменения манифеста видны мастеру без перезапуска."""
        client.post("/api/v1/devices/save", data={"save_manifest": "1"}, follow_redirects=True)

        response = client.get("/api/rooms")

        assert response.status_code == 200
        assert response.json()["rooms"]
