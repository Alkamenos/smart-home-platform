"""Ключи глобальных сущностей климата доезжают до условий (фаза 1, T001–T002).

Боевой разрыв 2026-10-10: условия обогрева читают `climate_setpoint` и
`climate_enabled`, но **писателя нет нигде** — ни в адаптере, ни в роутере,
ни в движке (`research.md` D1). В тестах ключи подставлялись руками, поэтому
отсутствие писателя не было видно: тест проходил, подставив значение руками.

Из этого следует, что в бою `may_heat` всегда получает «данных нет» и обогрев
не включается ни в одной комнате. Это и есть невыполненная T007 спеки 011.

Тесты проверяют ровно то, чего не хватает: ключ, который условие читает, обязан
приезжать в контекст перехода сам, из Home Assistant, без участия теста.

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0
"""

from __future__ import annotations

import logging
from typing import Any

import pytest

from adapters.ha_adapter import HAAdapter


class _StubWsClient:
    """Клиент WebSocket, накапливающий прочитанные глобальные значения.

    Условия читают значения из полей клиента, поэтому тест проверяет, что
    адаптер их туда положил. Пустой клиент означал бы «никто не прочитал» —
    и это ровно тот дефект, который тест ловит.
    """

    def __init__(self) -> None:
        self.climate_setpoint: float | None = None
        self.comfort_max: float | None = None
        self.is_winter: bool | None = None
        self.climate_enabled: bool | None = None
        self.ac_allowed: bool | None = None


def _adapter_with_states(states: dict[str, str]) -> tuple[HAAdapter, _StubWsClient]:
    """Адаптер с клиентом, отдающим заданные состояния сущностей.

    Args:
        states: Соответствие идентификатора сущности её состоянию.

    Returns:
        Адаптер и клиент, между которыми он читает.
    """
    client = _StubWsClient()

    class _Response:
        """Ответ Home Assistant с одним состоянием."""

        def __init__(self, state: str) -> None:
            self.status = 200
            self._state = state

        async def __aenter__(self) -> _Response:
            """Войти в контекст.

            Returns:
                Сама от��етка.
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
                Словарь с единственным полем `state`.
            """
            return {"state": self._state}

    class _Session:
        """Сессия, отвечающая по заранее заданным состояниям."""

        def get(self, url: str, **kwargs: Any) -> Any:
            """Ответ на запрос состояния сущности.

            Args:
                url: Адрес с идентификатором сущности на конце.
                **kwargs: Заголовки и таймаут, не используются.

            Returns:
                Ответ с состоянием этой сущности.
            """
            entity = url.rsplit("/", 1)[-1]
            return _Response(states.get(entity, "unavailable"))

    adapter = HAAdapter.__new__(HAAdapter)
    adapter._ws_client = client  # type: ignore[attr-defined]
    adapter._session = _Session()  # type: ignore[attr-defined]
    adapter._token = "stub"  # type: ignore[attr-defined]
    adapter._ws_url = "ws://localhost:8123/api/websocket"  # type: ignore[attr-defined]
    return adapter, client


class TestClimateGlobalsRead:
    """Адаптер читает глобальные сущности климата."""

    @pytest.mark.asyncio
    async def test_setpoint_is_read_into_client(self) -> None:
        """Цель обогрева читается и попадает в клиент."""
        adapter, client = _adapter_with_states({"input_number.temperatura": "21.5"})
        adapter.climate_entities = {"setpoint": "input_number.temperatura"}

        await HAAdapter._refresh_climate_globals(adapter)  # type: ignore[arg-type]

        assert client.climate_setpoint == 21.5, (
            "уставку обогрева должен читать адаптер из Home Assistant: условие "
            "may_heat читает climate_setpoint, и сегодня писателя нет нигде, "
            "поэтому обогрев не включается ни в одной комнате"
        )

    @pytest.mark.asyncio
    async def test_season_is_read_into_client(self) -> None:
        """Сезон читается: без него кондиционер не знает, что зима."""
        adapter, client = _adapter_with_states({"input_boolean.zima": "on"})
        adapter.climate_entities = {"season": "input_boolean.zima"}

        await HAAdapter._refresh_climate_globals(adapter)  # type: ignore[arg-type]

        assert client.is_winter is True, (
            "сезон должен читаться из Home Assistant: зимой кондиционер "
            "включать нельзя, и без этого признака проверка невозможна"
        )

    @pytest.mark.asyncio
    async def test_comfort_ceiling_is_read(self) -> None:
        """Потолок комфорта читается: выше него — жарко."""
        adapter, client = _adapter_with_states(
            {"input_number.maksimalno_komfortnaia_temperatura": "25.0"}
        )
        adapter.climate_entities = {
            "comfort_max": "input_number.maksimalno_komfortnaia_temperatura"
        }

        await HAAdapter._refresh_climate_globals(adapter)  # type: ignore[arg-type]

        assert client.comfort_max == 25.0

    @pytest.mark.asyncio
    async def test_feature_flag_is_read(self) -> None:
        """Фиче-флаг климата читается: при выключенном платформа наблюдает."""
        adapter, client = _adapter_with_states({"input_boolean.feature_climate": "off"})
        adapter.climate_entities = {"feature": "input_boolean.feature_climate"}

        await HAAdapter._refresh_climate_globals(adapter)  # type: ignore[arg-type]

        assert client.climate_enabled is False

    @pytest.mark.asyncio
    async def test_ac_gate_is_read(self) -> None:
        """Гейт кондиционера читается: без разрешения владельца не включаем."""
        adapter, client = _adapter_with_states({"input_boolean.ispolzovat_konditsioner": "on"})
        adapter.climate_entities = {"ac_gate": "input_boolean.ispolzovat_konditsioner"}

        await HAAdapter._refresh_climate_globals(adapter)  # type: ignore[arg-type]

        assert client.ac_allowed is True

    @pytest.mark.asyncio
    async def test_missing_entity_leaves_value_unknown(self) -> None:
        """Непрочитанное значение остаётся неизвестным, а не становится нулём."""
        adapter, client = _adapter_with_states({})
        adapter.climate_entities = {"setpoint": "input_number.temperatura"}

        await HAAdapter._refresh_climate_globals(adapter)  # type: ignore[arg-type]

        assert client.climate_setpoint is None, (
            "непрочитанная уставка должна остаться неизвестной: ноль градусов "
            "означал бы «в комнате ноль», и обогрев поехал бы вслепую"
        )


class TestNumericGlobalsAreLogged:
    """Числовые значения не только пишутся, но и попадают в журнал.

    Регрессия 2026-10-10: в числовой ветке ``_store_global`` стоял ``return``
    до записи в журнал, поэтому уставка и уличная температура сохранялись, но
    не печатались — и в бою выглядело так, будто платформа их не читает.
    """

    def test_setpoint_value_is_logged(self, caplog: Any) -> None:
        """Уставка попадает в журнал.

        Args:
            caplog: Захват журнала.

        Returns:
            Ничего.
        """
        client = _StubWsClient()
        with caplog.at_level(logging.WARNING, logger="adapters.ha_adapter"):
            HAAdapter._store_global(  # type: ignore[arg-type]
                client,
                {"setpoint": "climate_setpoint"},
                "setpoint",
                "21.5",
                "input_number.temperatura",
            )

        assert client.climate_setpoint == 21.5
        assert any("input_number.temperatura" in record.message for record in caplog.records), (
            f"уставка записана, но в журнал не попала: {[r.message for r in caplog.records]}"
        )

    def test_outside_temperature_value_is_logged(self, caplog: Any) -> None:
        """Уличная температура попадает в журнал.

        Args:
            caplog: Захват журнала.

        Returns:
            Ничего.
        """
        client = _StubWsClient()
        with caplog.at_level(logging.WARNING, logger="adapters.ha_adapter"):
            HAAdapter._store_global(  # type: ignore[arg-type]
                client,
                {"outside_temp": "outside_temperature"},
                "outside_temp",
                "11.84",
                "sensor.temperatura_na_ulitse_srednee",
            )

        assert client.outside_temperature == 11.84
        assert any(
            "temperatura_na_ulitse_srednee" in record.message for record in caplog.records
        ), "уличная температура записана, но в журнал не попала"

    def test_unreadable_number_is_reported(self, caplog: Any) -> None:
        """Нечитаемое число называется в журнале, а не молча отбрасывается.

        Args:
            caplog: Захват журнала.

        Returns:
            Ничего.
        """
        client = _StubWsClient()
        with caplog.at_level(logging.WARNING, logger="adapters.ha_adapter"):
            HAAdapter._store_global(  # type: ignore[arg-type]
                client,
                {"setpoint": "climate_setpoint"},
                "setpoint",
                "unavailable",
                "input_number.temperatura",
            )

        assert client.climate_setpoint is None
        assert any("не прочитана как число" in record.message for record in caplog.records), (
            "нечитаемое число должно называться: иначе решает поломка, а не сбой данных"
        )

    def test_unknown_role_is_reported(self, caplog: Any) -> None:
        """Неизвестная роль называется: иначе значение молча пропадает.

        Args:
            caplog: Захват журнала.

        Returns:
            Ничего.
        """
        client = _StubWsClient()
        with caplog.at_level(logging.WARNING, logger="adapters.ha_adapter"):
            HAAdapter._store_global(  # type: ignore[arg-type]
                client, {}, "no_such_role", "on", "input_boolean.что_то"
            )

        assert any("не описана" in record.message for record in caplog.records)


class TestClimateGlobalsReachContext:
    """Прочитанные значения попадают в контекст перехода."""

    def test_context_carries_climate_values(self) -> None:
        """Ключи климата едут в контекст вместе с признаком сна.

        Args:
            Ничего.

        Returns:
            Ничего.
        """
        client = _StubWsClient()
        client.climate_setpoint = 21.5
        client.comfort_max = 25.0
        client.is_winter = True
        client.climate_enabled = True
        client.ac_allowed = False

        context = _climate_context(client)

        assert context["climate_setpoint"] == 21.5, (
            "условие обогрева читает climate_setpoint из контекста: без него "
            "may_heat всегда получает «данных нет»"
        )
        assert context["comfort_max"] == 25.0
        assert context["is_winter"] is True
        assert context["climate_enabled"] is True
        assert context["ac_allowed"] is False

    def test_unknown_values_reach_context_as_none(self) -> None:
        """Неизвестные значения доезжают как `None`, а не выпадают из контекста.

        Args:
            Ничего.

        Returns:
            Ничего.
        """
        context = _climate_context(_StubWsClient())

        for key in ("climate_setpoint", "comfort_max", "is_winter", "climate_enabled"):
            assert key in context, f"{key} обязан присутствовать в контексте, даже когда неизвестен"
            assert context[key] is None


def _climate_context(client: Any) -> dict[str, Any]:
    """Контекст события, как его собирает адаптер.

    Args:
        client: Клиент WebSocket с прочитанными значениями.

    Returns:
        Словарь контекста.
    """
    from adapters.ha_adapter import HAAdapter

    adapter = HAAdapter.__new__(HAAdapter)
    adapter._ws_client = client  # type: ignore[attr-defined]
    return HAAdapter._event_context(adapter)  # type: ignore[arg-type]


class TestClimateGuardReadsSetpoint:
    """Условие обогрева читает уставку, которая теперь доезжает."""

    def test_may_heat_needs_only_manifest_setpoint(self) -> None:
        """Справочная проверка: условие отказывает без данных.

        Args:
            Ничего.

        Returns:
            Ничего.
        """
        from core.control_tracker import ControlTracker
        from core.guards.builtin import register_all_guards
        from core.registry import Registry

        registry = Registry()
        register_all_guards(registry, ControlTracker())
        may_heat = registry.get_guard("may_heat")

        assert may_heat is not None
        assert may_heat(None, {"temperature": 19.0}) is False, (
            "без уставки обогревать нельзя: условие обязано возвращать отказ, "
            "иначе платформа включит обогрев по одному показанию"
        )


class TestClimateEntitiesDeclared:
    """Сущности климата объявляются в правилах автоматизации."""

    def test_manifest_accepts_climate_entity_names(self) -> None:
        """Правила климата принимают имена сущностей.

        Returns:
            Ничего.
        """
        from core.models.manifest import AutomationRules

        rules = AutomationRules.model_validate(
            {
                "climate": {
                    "setpoint_entity": "input_number.temperatura",
                    "comfort_max_entity": "input_number.maksimalno_komfortnaia_temperatura",
                    "season_entity": "input_boolean.zima",
                    "feature_entity": "input_boolean.feature_climate",
                    "ac_gate_entity": "input_boolean.ispolzovat_konditsioner",
                    "setpoint_min": 5.0,
                    "setpoint_max": 30.0,
                }
            }
        )

        assert rules.climate.setpoint_entity == "input_number.temperatura", (
            "правила климата обязаны принимать имя сущности уставки: иначе "
            "платформе неоткуда взять цель обогрева"
        )
        assert rules.climate.setpoint_max == 30.0

    def test_empty_entity_name_is_rejected(self) -> None:
        """Пустая сущность — ошибка, а не «молча не работает».

        Returns:
            Ничего.
        """
        from pydantic import ValidationError

        from core.models.manifest import AutomationRules

        with pytest.raises(ValidationError):
            AutomationRules.model_validate({"climate": {"setpoint_entity": ""}})

    def test_setpoint_range_must_be_ordered(self) -> None:
        """Границы уставки обязаны быть в правильном порядке.

        Returns:
            Ничего.
        """
        from pydantic import ValidationError

        from core.models.manifest import AutomationRules

        with pytest.raises(ValidationError):
            AutomationRules.model_validate({"climate": {"setpoint_min": 30.0, "setpoint_max": 5.0}})
