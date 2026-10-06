"""
Тесты режима тени: команда не должна уходить в Home Assistant (Known Issue #77).

Контекст дефекта. Переменная `SHADOW_MODE` была объявлена в `.env`,
`deploy/README.md` и `deploy/scripts/deploy.sh`, и доходила до контейнера, но её
не читала ни одна строка Python. `DeploymentManager` был реализован целиком и
имел собственные тесты, но не импортировался ни в `main.py`, ни в
`bootstrap.py`. Оператор видел в `.env` `SHADOW_MODE=true` и считал, что
платформа не трогает дом, а она трогала.

Отсюда три требования, которые проверяются здесь:

1. **Безопасность по умолчанию.** Переменная не задана — режим тени. Иначе
   забытая настройка молча включала бы управление реальным домом.
2. **Запрет на выход.** В режиме тени ни одна команда не доходит до Home
   Assistant — ни из автомата, ни из WebUI. Проверяется на обоих путях, потому
   что они идут через адаптер разными способами (позиционными аргументами и
   именованными, как это делает `DeviceService`).
3. **Доказательство, а не обещание.** Тест на «команда не ушла» обязан ловить
   и мутацию, убирающую запрет. Поэтому проверяется не возвращённое значение, а
   сам факт обращения к клиенту Home Assistant: счётчик вызовов у фейкового
   клиента остаётся нулевым.
"""

from __future__ import annotations

import logging
from typing import Any

import pytest

from adapters.ha_adapter import HAAdapter
from core.deployment_manager import DeploymentManager, DeploymentMode


class RecordingWSClient:
    """Фейковый WS-клиент, считающий обращения к Home Assistant.

    Счётчик `service_calls` — единственный наблюдаемый признак того, что команда
    действительно ушла в HA. Проверка «лог содержит DRY RUN» доказала бы только
    то, что код исполнил ветку логирования, а не то, что он остановился.
    """

    def __init__(self, url: str, token: str, session: Any = None) -> None:
        self.url = url
        self.token = token
        self.session = session
        self.connected = False
        self.service_calls: list[tuple[str, str, str, dict[str, Any]]] = []

    async def connect(self) -> None:
        self.connected = True

    async def subscribe(self, handler: Any, filter_dict: Any) -> None:
        return None

    async def close(self) -> None:
        self.connected = False

    async def call_service(
        self,
        domain: str,
        service: str,
        service_data: dict[str, Any] | None = None,
        return_response: bool = True,
    ) -> dict[str, Any]:
        """Подпись повторяет `SimpleHAWebSocketClient.call_service`.

        Имена параметров обязаны совпадать: подмена с другими именами дала бы
        TypeError и тест «команда дошла до HA» прошёл бы на ошибке подмены, а не
        на вызове.
        """
        data = dict(service_data or {})
        entity_id = str(data.pop("entity_id", ""))
        self.service_calls.append((domain, service, entity_id, data))
        return {"context": {"id": "fake"}}

    async def get_states(self) -> list[dict[str, Any]]:
        return []


def make_adapter(deployment: DeploymentManager) -> tuple[HAAdapter, RecordingWSClient]:
    """Собрать адаптер в websocket-режиме с подменённым клиентом."""
    adapter = HAAdapter(
        mode="websocket",
        ws_url="ws://fake/api/websocket",
        token="fake-token",
        deployment=deployment,
    )
    client = RecordingWSClient("ws://fake/api/websocket", "fake-token")
    adapter._ws_client = client  # noqa: SLF001 - подмена транспорта в тесте
    return adapter, client


@pytest.fixture(autouse=True)
def _clear_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Убрать SHADOW_MODE из окружения, чтобы тесты не зависели от машины."""
    monkeypatch.delenv("SHADOW_MODE", raising=False)


class TestDeploymentModeFromEnv:
    """Разбор переменной окружения."""

    def test_true_gives_shadow(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SHADOW_MODE", "true")
        assert DeploymentManager.from_env().get_mode() is DeploymentMode.SHADOW

    def test_false_gives_active(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SHADOW_MODE", "false")
        assert DeploymentManager.from_env().get_mode() is DeploymentMode.ACTIVE

    @pytest.mark.parametrize("value", ["false", "0", "no", "off", "FALSE", "False"])
    def test_false_like_values_give_active(
        self, monkeypatch: pytest.MonkeyPatch, value: str
    ) -> None:
        monkeypatch.setenv("SHADOW_MODE", value)
        assert DeploymentManager.from_env().get_mode() is DeploymentMode.ACTIVE

    @pytest.mark.parametrize("value", ["true", "1", "yes", "on", "TRUE", " shadow "])
    def test_true_like_values_give_shadow(
        self, monkeypatch: pytest.MonkeyPatch, value: str
    ) -> None:
        monkeypatch.setenv("SHADOW_MODE", value)
        assert DeploymentManager.from_env().get_mode() is DeploymentMode.SHADOW

    def test_unset_gives_shadow(self) -> None:
        """Забытая настройка обязана оставить платформу в безопасном режиме."""
        assert DeploymentManager.from_env().get_mode() is DeploymentMode.SHADOW

    @pytest.mark.parametrize("value", ["", "да", "maybe", "shadow"])
    def test_unrecognised_value_gives_shadow(
        self, monkeypatch: pytest.MonkeyPatch, value: str
    ) -> None:
        """Опечатка в настройке не должна включать управление реальным домом."""
        monkeypatch.setenv("SHADOW_MODE", value)
        assert DeploymentManager.from_env().get_mode() is DeploymentMode.SHADOW

    def test_mode_is_reported(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Режим виден наружу — иначе `/health` не может его показать."""
        monkeypatch.setenv("SHADOW_MODE", "true")
        deployment = DeploymentManager.from_env()
        assert deployment.get_state().mode is DeploymentMode.SHADOW
        assert deployment.get_state().to_dict()["mode"] == "shadow"


class TestShadowModeBlocksCommands:
    """В режиме тени команда не уходит в Home Assistant."""

    @pytest.mark.asyncio
    async def test_command_does_not_reach_home_assistant(self) -> None:
        deployment = DeploymentManager.from_env()
        adapter, client = make_adapter(deployment)

        result = await adapter.call_service("light", "turn_on", "light.kitchen", {})

        assert client.service_calls == []
        # Отказ не должен выглядеть как ошибка: автомат продолжает считать свои
        # состояния, иначе в режиме тени нечего было бы наблюдать.
        assert result is True

    @pytest.mark.asyncio
    async def test_manual_command_does_not_reach_home_assistant(self) -> None:
        """Путь WebUI: DeviceService зовёт адаптер именованными аргументами."""
        deployment = DeploymentManager.from_env()
        adapter, client = make_adapter(deployment)

        result = await adapter.call_service(
            domain="light",
            service="turn_off",
            entity_id="light.kitchen",
            data={"brightness": 10},
        )

        assert client.service_calls == []
        assert result is True

    @pytest.mark.asyncio
    async def test_every_command_is_blocked_not_only_first(self) -> None:
        """Запрет не должен истощаться: проверяется серия команд."""
        deployment = DeploymentManager.from_env()
        adapter, client = make_adapter(deployment)

        for _ in range(5):
            await adapter.call_service("light", "turn_on", "light.kitchen", {})

        assert client.service_calls == []

    @pytest.mark.asyncio
    async def test_dry_run_line_is_logged(self, caplog: pytest.LogCaptureFixture) -> None:
        """Обещание «мы бы это сделали» обязано быть видно в логе.

        Уровень — INFO на корневом обработчике не виден (логи адаптера наследуют
        корневой, см. #70), поэтому проверка идёт по WARNING, который виден всегда.
        """
        deployment = DeploymentManager.from_env()
        adapter, _ = make_adapter(deployment)

        with caplog.at_level(logging.DEBUG, logger="adapters.ha_adapter"):
            await adapter.call_service("light", "turn_on", "light.kitchen", {"brightness": 255})

        assert any("DRY RUN" in record.getMessage() for record in caplog.records)
        assert any("light.kitchen" in record.getMessage() for record in caplog.records)

    @pytest.mark.asyncio
    async def test_gate_is_not_bypassed_by_missing_data(self) -> None:
        """Данные команды необязательны; их отсутствие не должно снимать запрет."""
        deployment = DeploymentManager.from_env()
        adapter, client = make_adapter(deployment)

        await adapter.call_service("fan", "turn_on", "fan.bathroom")

        assert client.service_calls == []


class TestActiveModeExecutes:
    """В активном режиме команда доходит до Home Assistant."""

    @pytest.mark.asyncio
    async def test_command_reaches_home_assistant(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SHADOW_MODE", "false")
        deployment = DeploymentManager.from_env()
        adapter, client = make_adapter(deployment)

        result = await adapter.call_service(
            "light", "turn_on", "light.kitchen", {"brightness": 255}
        )

        assert result is True
        assert len(client.service_calls) == 1
        domain, service, entity_id, data = client.service_calls[0]
        assert (domain, service, entity_id) == ("light", "turn_on", "light.kitchen")
        assert data == {"brightness": 255}

    @pytest.mark.asyncio
    async def test_manual_command_reaches_home_assistant(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("SHADOW_MODE", "false")
        deployment = DeploymentManager.from_env()
        adapter, client = make_adapter(deployment)

        await adapter.call_service(
            domain="light", service="turn_off", entity_id="light.bedroom", data={"brightness": 10}
        )

        assert len(client.service_calls) == 1
        assert client.service_calls[0][:3] == ("light", "turn_off", "light.bedroom")

    @pytest.mark.asyncio
    async def test_switching_to_active_at_runtime_takes_effect(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Переключение режима на ходу должно действовать без перезапуска."""
        monkeypatch.setenv("SHADOW_MODE", "true")
        deployment = DeploymentManager.from_env()
        adapter, client = make_adapter(deployment)

        await adapter.call_service("light", "turn_on", "light.kitchen", {})
        assert client.service_calls == []

        # Переход в активный режим без подтверждения бэкапа блокируется
        # _validate_mode_change — сознательно: force=True здесь означал бы, что
        # проверка обходится молча.
        deployment.set_backup_created(deployment.config_path)
        assert deployment.set_mode(DeploymentMode.ACTIVE, force=True) is True

        await adapter.call_service("light", "turn_on", "light.kitchen", {})
        assert len(client.service_calls) == 1

    @pytest.mark.asyncio
    async def test_switching_back_to_shadow_stops_commands(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("SHADOW_MODE", "false")
        deployment = DeploymentManager.from_env()
        adapter, client = make_adapter(deployment)

        await adapter.call_service("light", "turn_on", "light.kitchen", {})
        assert len(client.service_calls) == 1

        deployment.set_mode(DeploymentMode.SHADOW, force=True)

        await adapter.call_service("light", "turn_off", "light.kitchen", {})
        assert len(client.service_calls) == 1


class TestAdapterWithoutDeploymentManager:
    """Поведение адаптера, которому не передали менеджер развёртывания."""

    @pytest.mark.asyncio
    async def test_command_reaches_home_assistant(self) -> None:
        """Отсутствие менеджера не должно молча блокировать команду.

        Иначе починка режима тени тихо отключила бы автоматику у всех, кто не
        передал менеджер: сбой выглядел бы как «свет не включается».
        """
        adapter = HAAdapter(
            mode="websocket",
            ws_url="ws://fake/api/websocket",
            token="fake-token",
        )
        client = RecordingWSClient("ws://fake/api/websocket", "fake-token")
        adapter._ws_client = client  # noqa: SLF001

        assert await adapter.call_service("light", "turn_on", "light.kitchen", {}) is True
        assert len(client.service_calls) == 1
