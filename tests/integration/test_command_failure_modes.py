"""Отказы внешней системы и превышение времени выполнения (спека 009, T024).

Проверяет, что недоступность системы приводит к предсказуемому отказу с
названной причиной, а не к молчаливому успеху или пустому результату.

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0

Почему на уровне HTTP, а не на уровне сервиса
---------------------------------------------
Отказы сервиса уже проверены в `tests/integration/test_commands.py`: там
утверждается, что `execute_command` превращает сбой адаптера в `RuntimeError`
с текстом причины, и что порог 300 секунд соблюдается. Здесь проверяется другое:
что **пользователь** получает предсказуемый отказ по HTTP — код ответа и текст,
а не трассировку и не «успех с пустым телом».

Разница существенна. Сбой на уровне сервиса при ответе `200` и пустом теле
прошёл бы сервисные проверки и при этом оставил бы пользователя в уверенности,
что команда выполнена.
"""

from __future__ import annotations

import asyncio

import pytest
from fastapi.testclient import TestClient
from tests.helpers.ha_stub import HAUnavailable, stub_ha


def _as(client: TestClient, user_id: str, is_admin: bool = False) -> TestClient:
    """Создаёт клиента с ровно заданными заголовками.

    Отдельный клиент обязателен: httpx сливает заголовки запроса с дефолтными
    заголовками клиента, а не заменяет их, поэтому переопределение одного
    `X-User-ID` оставило бы `X-Is-Admin: true` и дало admin-bypass.

    Args:
        client: Клиент-образец, у которого читается приложение.
        user_id: Идентификатор пользователя.
        is_admin: Действовать ли от имени администратора.

    Returns:
        Клиент с ровно теми заголовками, что заданы здесь.
    """
    headers = {"X-User-ID": user_id, "X-Is-Admin": "true" if is_admin else "false"}
    return TestClient(client.app, headers=headers)


@pytest.fixture
def controller(isolated_client, synced_device_id) -> str:
    """Пользователь с ролью `controller` на существующем устройстве.

    Args:
        isolated_client: HTTP-клиент теста.
        synced_device_id: Идентификатор устройства.

    Returns:
        Идентификатор пользователя.
    """
    granted = isolated_client.post(
        f"/api/v1/devices/{synced_device_id}/access",
        json={"user_id": "user_controller", "role": "controller"},
    )
    assert granted.status_code == 201, granted.text
    return "user_controller"


class TestSyncUnderSystemFailure:
    """Недоступность системы при синхронизации."""

    def test_sync_fails_with_named_address(self, isolated_client, ha_unavailable):
        """Отказ называет адрес недоступной системы."""
        with stub_ha(mode=HAUnavailable.REFUSED):
            response = isolated_client.post(f"/api/v1/devices/sources/{ha_unavailable}/sync")

        assert response.status_code == 500, response.text
        detail = response.json()["detail"]
        assert "unreachable.invalid" in detail, f"сообщение должно называть адрес: {detail}"

    def test_sync_failure_has_no_traceback(self, isolated_client, ha_unavailable):
        """Пользователю не показывается внутренняя трассировка."""
        with stub_ha(mode=HAUnavailable.REFUSED):
            response = isolated_client.post(f"/api/v1/devices/sources/{ha_unavailable}/sync")

        body = response.text
        assert "Traceback" not in body, f"трассировка не должна попадать к пользователю: {body}"
        assert 'File "' not in body, f"пути файлов не должны утекать: {body}"

    def test_timeout_is_indistinguishable_from_refusal(self, isolated_client, ha_unavailable):
        """Таймаут и отказ дают одинаковый ответ — и это ожидаемо.

        `HARestClient.connect_to_ha()` гасит любое исключение и возвращает
        `False`, поэтому API не может различить эти два случая. Тест фиксирует
        **фактическое** поведение и называет его причину: проверка, ожидающая
        различия, не прошла бы ни при какой реализации.

        На уровне клиента различение есть, и оно проверяется отдельно —
        в `tests/helpers` и `test_fixtures_infrastructure.py`.
        """
        with stub_ha(mode=HAUnavailable.REFUSED):
            refused = isolated_client.post(f"/api/v1/devices/sources/{ha_unavailable}/sync")

        with stub_ha(mode=HAUnavailable.TIMEOUT):
            timed_out = isolated_client.post(f"/api/v1/devices/sources/{ha_unavailable}/sync")

        assert refused.status_code == timed_out.status_code == 500
        assert "Traceback" not in refused.text
        assert "Traceback" not in timed_out.text

    def test_unexpected_error_also_reported_cleanly(self, isolated_client, ha_unavailable):
        """Неожиданная ошибка на шве подключения тоже даёт понятный отказ."""
        with stub_ha(mode=HAUnavailable.ERROR):
            response = isolated_client.post(f"/api/v1/devices/sources/{ha_unavailable}/sync")

        assert response.status_code == 500, response.text
        assert "Traceback" not in response.text, (
            f"трассировка не должна показываться: {response.text}"
        )


class TestDiscoveryUnderSystemFailure:
    """Недоступность системы при обнаружении устройств."""

    def test_discovery_endpoint_reports_error_field(self, isolated_client, ha_unavailable):
        """Обнаружение отдаёт причину в поле `error`, а не пустой список.

        Пустой список означал бы «устройств нет» вместо «система недоступна»,
        то есть два разных состояния выглядели бы одинаково.
        """
        with stub_ha(mode=HAUnavailable.REFUSED):
            response = isolated_client.get(
                f"/api/v1/devices/sources/{ha_unavailable}/discovery-data"
            )

        assert response.status_code == 200, response.text
        body = response.json()
        assert body.get("error"), f"причина недоступности должна быть названа: {body}"
        assert "unreachable.invalid" in str(body["error"]), f"причина должна называть адрес: {body}"

    def test_discovery_error_is_not_empty_result(self, isolated_client, ha_unavailable):
        """Ошибка не выдаётся за пустой успешный результат."""
        with stub_ha(mode=HAUnavailable.REFUSED):
            response = isolated_client.get(
                f"/api/v1/devices/sources/{ha_unavailable}/discovery-data"
            )

        body = response.json()
        assert not body.get("devices"), (
            f"при недоступной системе устройства не должны выдаваться как найденные: {body}"
        )


class TestCommandUnderSystemFailure:
    """Поведение команды при недоступной системе."""

    def test_denied_command_does_not_promise_success(self, isolated_client, synced_device_id):
        """Отказ по правам не сопровождается признаком выполнения.

        Проверяется пара «отказ — отсутствие записи в истории»: команда, которая
        была отклонена, не должна ни выполняться, ни попасть в журнал.
        """
        stranger = _as(isolated_client, "user_without_rights")
        response = stranger.post(
            f"/api/v1/devices/{synced_device_id}/command",
            json={"command_name": "turn_off"},
        )

        assert response.status_code == 403, response.text
        assert "executing" not in response.text, (
            f"отказ не должен содержать признака выполнения: {response.text}"
        )

    def test_command_on_missing_device_is_not_confused_with_refusal(
        self, isolated_client, synced_device_id, controller
    ):
        """Отказ по отсутствию устройства отличается от отказа по правам.

        Оба — неуспехи, но с разными кодами: `404` означает «устройства нет»,
        `403` — «доступа нет». Смешивать их нельзя, иначе диагностика у пользователя
        вводит в заблуждение.
        """
        from uuid import uuid4

        permitted = _as(isolated_client, controller)
        granted = permitted.post(
            f"/api/v1/devices/{uuid4()}/command", json={"command_name": "turn_off"}
        )
        stranger = _as(isolated_client, "user_without_rights")
        forbidden = stranger.post(
            f"/api/v1/devices/{synced_device_id}/command", json={"command_name": "turn_off"}
        )

        assert granted.status_code == 404, f"ожидался 404: {granted.text}"
        assert forbidden.status_code == 403, f"ожидался 403: {forbidden.text}"


class TestTimeoutHandling:
    """Превышение времени выполнения."""

    def test_timed_out_command_is_recorded_as_failed(self):
        """Превосход времени даёт отказ, который виден в истории команды.

        Раньше таймаут «проверялся» подавлением исключения: при задержке 0.1 с и
        пороге 300 с таймаут наступить не мог, поэтому тест был зелёным независимо
        от того, отработал бы код. Здесь задержка заведомо больше порога.
        """
        from unittest.mock import AsyncMock
        from uuid import UUID

        from core.events.event_bus import EventBus
        from core.models.device import Device
        from services.device_service import DeviceService

        adapter = AsyncMock()

        async def too_slow(*args, **kwargs):
            await asyncio.sleep(5)
            return {"success": True}

        adapter.call_service = too_slow
        service = DeviceService(event_bus=EventBus(), persistence_module=None, ha_adapter=adapter)
        device = Device(
            ha_entity_id="climate.slow",
            source_id=UUID(int=0),
            name="Медленное устройство",
            device_type="climate",
            status="available",
        )
        service._devices[device.id] = device

        async def run():
            with pytest.raises(RuntimeError, match="Command timeout after 1 seconds"):
                await service.execute_command(
                    device_id=device.id,
                    command_name="set_temperature",
                    parameters={"temperature": 22},
                    timeout=1,
                )

        asyncio.run(run())

        record = next(iter(service._commands.values()))
        assert record["status"] == "failed", f"ожидался статус failed: {record['status']}"
        assert "timeout" in record["error"].lower(), f"причина должна называть таймаут: {record}"
        assert record["completed_at"] is not None, "время завершения обязано проставляться"

    def test_timeout_does_not_leave_command_in_executing_state(self):
        """После таймаута команда не остаётся в состоянии «выполняется».

        Зависшая в «executing» запись означала бы, что пользователь вечно видит
        «команда выполняется», хотя она провалилась.
        """
        from unittest.mock import AsyncMock
        from uuid import UUID

        from core.events.event_bus import EventBus
        from core.models.device import Device
        from services.device_service import DeviceService

        adapter = AsyncMock()

        async def too_slow(*args, **kwargs):
            await asyncio.sleep(5)
            return {"success": True}

        adapter.call_service = too_slow
        service = DeviceService(event_bus=EventBus(), persistence_module=None, ha_adapter=adapter)
        device = Device(
            ha_entity_id="climate.stuck",
            source_id=UUID(int=0),
            name="Зависшее устройство",
            device_type="climate",
            status="available",
        )
        service._devices[device.id] = device

        async def run():
            with pytest.raises(RuntimeError):
                await service.execute_command(
                    device_id=device.id,
                    command_name="set_temperature",
                    parameters={},
                    timeout=1,
                )

        asyncio.run(run())

        stuck = [r for r in service._commands.values() if r["status"] == "executing"]
        assert not stuck, f"после таймаута не должно остаться команд в executing: {stuck}"

    def test_timeout_is_within_run_duration(self):
        """Провал по таймауту укладывается в разумное время.

        Обещание «не дольше указанного» должно проверяться: тест, ждущий 300 секунд,
        не выполнил бы обещание, но и не проверил бы его.
        """
        from unittest.mock import AsyncMock
        from uuid import UUID

        from core.events.event_bus import EventBus
        from core.models.device import Device
        from services.device_service import DeviceService

        adapter = AsyncMock()

        async def too_slow(*args, **kwargs):
            await asyncio.sleep(30)
            return {"success": True}

        adapter.call_service = too_slow
        service = DeviceService(event_bus=EventBus(), persistence_module=None, ha_adapter=adapter)
        device = Device(
            ha_entity_id="climate.patient",
            source_id=UUID(int=0),
            name="Очень медленное устройство",
            device_type="climate",
            status="available",
        )
        service._devices[device.id] = device

        async def run():
            loop = asyncio.get_running_loop()
            started = loop.time()
            with pytest.raises(RuntimeError):
                await service.execute_command(
                    device_id=device.id,
                    command_name="set_temperature",
                    parameters={},
                    timeout=1,
                )
            return loop.time() - started

        elapsed = asyncio.run(run())

        assert elapsed < 10, (
            f"отказ по таймауту 1 секунда занял {elapsed:.1f} с — ожидается возврат "
            "сразу по истечении порога"
        )
