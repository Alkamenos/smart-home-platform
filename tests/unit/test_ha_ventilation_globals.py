"""Ключи глобальных сущностей вентиляции доезжают до условий (фаза 1, T003).

Второй разрыв того же рода, что и в климате: чтобы рекуператорами можно было
управлять, платформа обязана знать, выключил ли владелец вентиляцию и включил ли
проветривание. Механизма чтения произвольных глобальных сущностей нет — в
адаптере ровно два захардкоженных исключения, солнце и «мы спим»
(`research.md` D6).

Подписка на все сущности дома не предлагается: это Known Issue #82, который
закрыт фильтрацией списка из манифеста. Возврат означал бы 1500 устройств и
возврат дефекта. Поэтому список остаётся явным.

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0
"""

from __future__ import annotations

from typing import Any

import pytest

from adapters.ha_adapter import HAAdapter


class _StubWsClient:
    """Клиент WebSocket с полями вентиляции."""

    def __init__(self) -> None:
        self.ventilation_on: bool | None = None
        self.airing_on: bool | None = None
        self.exhaust_on: bool | None = None
        self.ventilation_enabled: bool | None = None
        self.outside_temperature: float | None = None


def _adapter_with_states(states: dict[str, str]) -> tuple[HAAdapter, _StubWsClient]:
    """Адаптер, отвечающий заранее заданными состояниями.

    Args:
        states: Соответствие идентификатора сущности её состоянию.

    Returns:
        Адаптер и клиент.
    """

    class _Response:
        """Ответ Home Assistant с одним состоянием."""

        def __init__(self, state: str) -> None:
            self.status = 200
            self._state = state

        async def __aenter__(self) -> _Response:
            """Войти в контекст.

            Returns:
                Сама отметка.
            """
            return self

        async def __aexit__(self, *args: Any) -> None:
            """Выйти из контекста.

            Args:
                *args: Не используются.

            Returns:
                Ничего.
            """
            return None

        async def json(self) -> dict[str, str]:
            """Состояние сущности.

            Returns:
                Словарь с полем `state`.
            """
            return {"state": self._state}

    class _Session:
        """Сессия, отвечающая по заданным состояниям."""

        def get(self, url: str, **kwargs: Any) -> Any:
            """Ответ на запрос состояния.

            Args:
                url: Адрес с идентификатором сущности.
                **kwargs: Не используются.

            Returns:
                Ответ с состоянием сущности.
            """
            entity = url.rsplit("/", 1)[-1]
            return _Response(states.get(entity, "unavailable"))

    client = _StubWsClient()
    adapter = HAAdapter.__new__(HAAdapter)
    adapter._ws_client = client  # type: ignore[attr-defined]
    adapter._session = _Session()  # type: ignore[attr-defined]
    adapter._token = "stub"  # type: ignore[attr-defined]
    adapter._ws_url = "ws://localhost:8123/api/websocket"  # type: ignore[attr-defined]
    return adapter, client


class TestVentilationGlobalsRead:
    """Адаптер читает глобальные сущности вентиляции."""

    @pytest.mark.asyncio
    async def test_owner_switch_is_read(self) -> None:
        """Выключалка вентиляции читается: при off рекуператоры в ноль."""
        adapter, client = _adapter_with_states({"input_boolean.ventiliatsiia": "off"})
        adapter.ventilation_entities = {"enable": "input_boolean.ventiliatsiia"}

        await HAAdapter._refresh_ventilation_globals(adapter)  # type: ignore[arg-type]

        assert client.ventilation_on is False, (
            "право владельца выключить вентиляцию должно читаться платформой: "
            "иначе автоматика продолжит крутить рекуператоры вопреки кнопке"
        )

    @pytest.mark.asyncio
    async def test_airing_is_read(self) -> None:
        """Проветривание читается."""
        adapter, client = _adapter_with_states({"input_boolean.provetrivanie": "on"})
        adapter.ventilation_entities = {"airing": "input_boolean.provetrivanie"}

        await HAAdapter._refresh_ventilation_globals(adapter)  # type: ignore[arg-type]

        assert client.airing_on is True

    @pytest.mark.asyncio
    async def test_exhaust_is_read(self) -> None:
        """Режим вытяжки читается."""
        adapter, client = _adapter_with_states({"input_boolean.provetrivanie_vytyazhka": "on"})
        adapter.ventilation_entities = {"exhaust": "input_boolean.provetrivanie_vytyazhka"}

        await HAAdapter._refresh_ventilation_globals(adapter)  # type: ignore[arg-type]

        assert client.exhaust_on is True

    @pytest.mark.asyncio
    async def test_feature_flag_is_read(self) -> None:
        """Фиче-флаг вентиляции читается."""
        adapter, client = _adapter_with_states({"input_boolean.feature_ventilation": "off"})
        adapter.ventilation_entities = {"feature": "input_boolean.feature_ventilation"}

        await HAAdapter._refresh_ventilation_globals(adapter)  # type: ignore[arg-type]

        assert client.ventilation_enabled is False

    @pytest.mark.asyncio
    async def test_outside_temperature_is_read(self) -> None:
        """Уличная температура читается как число.

        Returns:
            Ничего.
        """
        adapter, client = _adapter_with_states({"sensor.temperatura_na_ulitse_srednee": "11.84"})
        adapter.ventilation_entities = {"outside_temp": "sensor.temperatura_na_ulitse_srednee"}

        await HAAdapter._refresh_ventilation_globals(adapter)  # type: ignore[arg-type]

        assert client.outside_temperature == 11.84, (
            "разница температур улицы и комнаты решает режим рекуператора: "
            "без числа решение принимать не на чем"
        )

    @pytest.mark.asyncio
    async def test_unreadable_temperature_stays_unknown(self) -> None:
        """Нечитаемая улица остаётся неизвестной, а не нулём градусов.

        Returns:
            Ничего.
        """
        adapter, client = _adapter_with_states(
            {"sensor.temperatura_na_ulitse_srednee": "unavailable"}
        )
        adapter.ventilation_entities = {"outside_temp": "sensor.temperatura_na_ulitse_srednee"}

        await HAAdapter._refresh_ventilation_globals(adapter)  # type: ignore[arg-type]

        assert client.outside_temperature is None, (
            "ноль градусов на улице означал бы «зима», и вентиляция перешла бы "
            "в режим охлаждения по неверным данным"
        )


class TestVentilationContext:
    """Прочитанные значения попадают в контекст перехода."""

    @pytest.mark.asyncio
    async def test_values_reach_event_context(self) -> None:
        """Ключи вентиляции едут в контекст события.

        Returns:
            Ничего.
        """
        adapter, client = _adapter_with_states(
            {
                "input_boolean.ventiliatsiia": "on",
                "input_boolean.provetrivanie": "off",
                "sensor.temperatura_na_ulitse_srednee": "11.84",
            }
        )
        adapter.ventilation_entities = {
            "enable": "input_boolean.ventiliatsiia",
            "airing": "input_boolean.provetrivanie",
            "outside_temp": "sensor.temperatura_na_ulitse_srednee",
        }
        await HAAdapter._refresh_ventilation_globals(adapter)  # type: ignore[arg-type]

        context = HAAdapter._event_context(adapter)  # type: ignore[arg-type]

        assert context["ventilation_on"] is True
        assert context["airing_on"] is False
        assert context["outside_temperature"] == 11.84


class TestVentilationRulesDeclared:
    """Сущности вентиляции объявляются в правилах автоматизации."""

    def test_manifest_accepts_ventilation_entity_names(self) -> None:
        """Правила вентиляции принимают имена сущностей.

        Returns:
            Ничего.
        """
        from core.models.manifest import AutomationRules

        rules = AutomationRules.model_validate(
            {
                "ventilation": {
                    "feature_entity": "input_boolean.feature_ventilation",
                    "enable_entity": "input_boolean.ventiliatsiia",
                    "airing_entity": "input_boolean.provetrivanie",
                    "exhaust_entity": "input_boolean.provetrivanie_vytyazhka",
                    "outside_temp_entity": "sensor.temperatura_na_ulitse_srednee",
                    "manual_lockout_min": 15,
                }
            }
        )

        assert rules.ventilation.enable_entity == "input_boolean.ventiliatsiia"
        assert rules.ventilation.outside_temp_entity == "sensor.temperatura_na_ulitse_srednee"

    def test_empty_entity_name_is_rejected(self) -> None:
        """Пустая сущность — ошибка загрузки.

        Returns:
            Ничего.
        """
        from pydantic import ValidationError

        from core.models.manifest import AutomationRules

        with pytest.raises(ValidationError):
            AutomationRules.model_validate({"ventilation": {"enable_entity": ""}})

    def test_negative_lockout_is_rejected(self) -> None:
        """Отрицательный срок блокировки — ошибка.

        Returns:
            Ничего.
        """
        from pydantic import ValidationError

        from core.models.manifest import AutomationRules

        with pytest.raises(ValidationError):
            AutomationRules.model_validate({"ventilation": {"manual_lockout_min": -1}})
