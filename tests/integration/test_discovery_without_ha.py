"""Мастер обнаружения устройств без Home Assistant: `/discovery/*` не падает (Known Issue #45).

`Container.adapter` возвращает `MockAdapter`, если переменная `HA_TOKEN` не
задана. Раньше у `MockAdapter` не было свойства `is_connected`, которое
`DeviceDiscoveryService.scan_devices` читает напрямую, поэтому все
`/discovery/*` отвечали 500 с текстом `AttributeError`. Пользователь мастера
должен получать внятное «Home Assistant недоступен» (503), а не «внутренняя
ошибка сервера» и уж тем более не «подключено, но устройств нет».

Проверяем обе стороны: заглушка не притворяется подключённой, а обход
объявляет недоступность осмысленно — и при этом сценарий с работающим
Home Assistant не сломан.

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0
"""

from __future__ import annotations

import os
import shutil
import tempfile
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient


HEADERS = {"X-User-ID": "admin_user", "X-Is-Admin": "true"}


@pytest.fixture
def workdir() -> Iterator[Path]:
    """Временная копия манифеста в отдельном каталоге данных.

    Yields:
        Путь к каталогу с манифестом.
    """
    project_root = Path(__file__).resolve().parent.parent.parent
    work_dir = Path(tempfile.mkdtemp(prefix="discovery_no_ha_"))
    shutil.copy(
        project_root / "instances" / "leonids_house" / "manifest.yaml", work_dir / "manifest.yaml"
    )
    previous_cwd = os.getcwd()
    os.chdir(work_dir)
    try:
        yield work_dir
    finally:
        os.chdir(previous_cwd)
        shutil.rmtree(work_dir, ignore_errors=True)


@pytest.fixture
def client_without_ha(workdir: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    """Приложение, собранное в окружении без `HA_TOKEN`.

    `HA_TOKEN` удаляется явно, а не «по среде»: предусловие проверяется, а не
    предполагается — иначе тест молча проверял бы ветку с живым адаптером,
    если окружение окажется с токеном.

    Args:
        workdir: Каталог с манифестом.
        monkeypatch: Подмена переменных окружения.

    Yields:
        HTTP-клиент теста.
    """
    monkeypatch.delenv("HA_TOKEN", raising=False)

    from webui.app import create_app

    app = create_app(str(workdir / "manifest.yaml"))
    yield TestClient(app, headers=HEADERS)


class _WebSocketClientStub:
    """Заглушка клиента обхода Home Assistant."""

    def __init__(self, states: list[dict[str, Any]]) -> None:
        """Запоминает состояния, которые вернёт обход.

        Args:
            states: Состояния сущностей Home Assistant.
        """
        self._states = states

    async def get_states(self) -> list[dict[str, Any]]:
        """Отдаёт сохранённые состояния.

        Returns:
            Список состояний сущностей.
        """
        return self._states


class _ConnectedAdapterStub:
    """Заглушка адаптера с работающим подключением к Home Assistant."""

    def __init__(self, states: list[dict[str, Any]]) -> None:
        """Запоминает состояния и подключение.

        Args:
            states: Состояния сущностей Home Assistant.
        """
        self._ws_client = _WebSocketClientStub(states)

    @property
    def is_connected(self) -> bool:
        """Сообщает, что подключение смоделировано успешным.

        Returns:
            True — подключение есть.
        """
        return True


class TestMockAdapterIsNotConnected:
    """Заглушка не должна притворяться подключённой к Home Assistant."""

    def test_is_connected_should_be_false_without_home_assistant(self) -> None:
        """`MockAdapter` объявляет отсутствие подключения, а не успех."""
        from adapters.mock_adapter import MockAdapter

        assert MockAdapter().is_connected is False

    def test_is_connected_should_stay_false_after_start(self) -> None:
        """Запуск заглушки не превращает её в «подключённую»."""
        import asyncio

        from adapters.mock_adapter import MockAdapter

        adapter = MockAdapter()
        asyncio.run(adapter.start())

        assert adapter.is_connected is False


class TestScanDevicesWithoutHomeAssistant:
    """Обход объявляет недоступность Home Assistant, а не падает."""

    @pytest.mark.asyncio
    async def test_scan_with_mock_adapter_should_raise_runtime_error(self) -> None:
        """С заглушкой обход сообщает о недоступности, а не об атрибуте."""
        from adapters.mock_adapter import MockAdapter
        from core.discovery.discovery_service import DeviceDiscoveryService

        service = DeviceDiscoveryService(MockAdapter())

        with pytest.raises(RuntimeError, match="not connected"):
            await service.scan_devices()

    @pytest.mark.asyncio
    async def test_scan_with_adapter_without_property_should_not_raise_attribute_error(
        self,
    ) -> None:
        """Адаптер без `is_connected` даёт понятную ошибку, а не `AttributeError`."""
        from core.discovery.discovery_service import DeviceDiscoveryService

        class _Bare:
            pass

        service = DeviceDiscoveryService(_Bare())  # type: ignore[arg-type]

        with pytest.raises(RuntimeError, match="not connected"):
            await service.scan_devices()


class TestDiscoveryRoutesWithoutHomeAssistant:
    """Маршруты мастера отвечают внятно, а не 500."""

    def test_scan_should_report_unavailable_not_server_error(
        self, client_without_ha: TestClient
    ) -> None:
        """`/discovery/scan` отвечает 503, а не 500."""
        response = client_without_ha.post("/discovery/scan", data={"page": 1})

        assert response.status_code == 503, response.text
        assert "not connected" in response.json()["detail"]

    def test_stats_should_report_unavailable_not_server_error(
        self, client_without_ha: TestClient
    ) -> None:
        """`/discovery/stats` отвечает 503, а не 500."""
        response = client_without_ha.get("/discovery/stats")

        assert response.status_code == 503, response.text

    def test_bulk_apply_should_report_unavailable_not_server_error(
        self, client_without_ha: TestClient
    ) -> None:
        """`/discovery/apply` отвечает 503, а не 500."""
        response = client_without_ha.post("/discovery/apply", data={"include_all": "true"})

        assert response.status_code == 503, response.text

    def test_discovery_page_should_open(self, client_without_ha: TestClient) -> None:
        """Страница мастера открывается без Home Assistant."""
        response = client_without_ha.get("/discovery")

        assert response.status_code == 200

    def test_routes_should_not_expose_internal_error_text(
        self, client_without_ha: TestClient
    ) -> None:
        """Наружу не утекает текст внутренней ошибки об адаптере."""
        response = client_without_ha.post("/discovery/scan", data={"page": 1})

        assert "AttributeError" not in response.text
        assert "MockAdapter" not in response.text


class TestDiscoveryRoutesWithHomeAssistant:
    """Сценарий с работающим Home Assistant не сломан."""

    def test_scan_should_return_devices_when_connected(self, client_without_ha: TestClient) -> None:
        """С подключённым адаптером обход отдаёт устройства."""
        import webui.routes_discovery as discovery_module

        service = discovery_module._discovery_service
        original = service._ha_adapter  # noqa: SLF001 — подмена адаптера в тесте
        service._ha_adapter = _ConnectedAdapterStub(  # noqa: SLF001
            [
                {"entity_id": "light.hall", "state": "on", "attributes": {"friendly_name": "Hall"}},
                {
                    "entity_id": "automation.system",
                    "state": "on",
                    "attributes": {},
                },
            ]
        )
        try:
            response = client_without_ha.post("/discovery/scan", data={"page": 1})
        finally:
            service._ha_adapter = original  # noqa: SLF001

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["total"] == 1
        assert body["devices"][0]["entity_id"] == "light.hall"

    def test_stats_should_return_counters_when_connected(
        self, client_without_ha: TestClient
    ) -> None:
        """С подключённым адаптером статистика считает устройства."""
        import webui.routes_discovery as discovery_module

        service = discovery_module._discovery_service
        original = service._ha_adapter  # noqa: SLF001 — подмена адаптера в тесте
        service._ha_adapter = _ConnectedAdapterStub(  # noqa: SLF001
            [{"entity_id": "switch.pump", "state": "off", "attributes": {}}]
        )
        try:
            response = client_without_ha.get("/discovery/stats")
        finally:
            service._ha_adapter = original  # noqa: SLF001

        assert response.status_code == 200, response.text
        assert response.json()["total"] == 1
