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
    """Клиент WebSocket с полями глобальных значений.

    Настоящий класс `SimpleHAWebSocketClient` используется везде, где проверяется
    чтение значений: у него есть `store_global`, который и кладёт их в поля.
    Заглушка с собственными полями проверяла бы не код, а саму себя — так
    уже случилось с тестами фазы 1, они подставляли ключи руками и проходили
    при отсутствии писателя.
    """

    def __init__(self) -> None:
        self.climate_setpoint: float | None = None
        self.comfort_max: float | None = None
        self.is_winter: bool | None = None
        self.climate_enabled: bool | None = None
        self.ac_allowed: bool | None = None
        self.ventilation_on: bool | None = None
        self.airing_on: bool | None = None
        self.exhaust_on: bool | None = None
        self.ventilation_enabled: bool | None = None
        self.outside_temperature: float | None = None

    def store_global(self, role: str, state: str | None, entity: str) -> None:
        """Положить значение в поле — как это делает настоящий клиент.

        Args:
            role: Роль сущности.
            state: Состояние.
            entity: Идентификатор сущности.

        Returns:
            Ничего.
        """
        from adapters.ha_adapter import _BOOLEAN_ROLES, _NUMERIC_ROLES, GLOBAL_ENTITY_FIELDS

        field = GLOBAL_ENTITY_FIELDS.get(role)
        if field is None or state is None:
            return
        if role in _BOOLEAN_ROLES:
            if state in ("on", "off"):
                setattr(self, field, state == "on")
        elif role in _NUMERIC_ROLES:
            try:
                setattr(self, field, float(state))
            except ValueError:
                return


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


def _client_with(climate: dict[str, str], ventilation: dict[str, str]) -> Any:
    """Клиент WebSocket с заданными глобальными сущностями.

    Args:
        climate: Сущности климата: роль → entity_id.
        ventilation: Сущности вентиляции: роль → entity_id.

    Returns:
        Готовый клиент.
    """
    from adapters.ha_adapter import GLOBAL_ENTITY_FIELDS, SimpleHAWebSocketClient

    client = SimpleHAWebSocketClient.__new__(SimpleHAWebSocketClient)
    client.climate_entities = dict(climate)
    client.ventilation_entities = dict(ventilation)
    client.global_fields = dict(GLOBAL_ENTITY_FIELDS)
    # Поля значений заводит `__init__` клиента; тест создаёт объект напрямую,
    # поэтому их нужно выставить — иначе проверка падала бы на отсутствии
    # атрибута, а не на поведении.
    for name in GLOBAL_ENTITY_FIELDS.values():
        setattr(client, name, None)
    client.daylight = None
    client.asleep = None
    client._filtered_out = 0
    client.entity_filter_provider = None
    client.filtered_entity_ids: set[str] = set()
    client._filter_size_last_seen = 0
    client.sleep_modifier_entity = None
    client._pending_sunset = False
    client._pending_sunrise = False
    client.on_sleep_started = None
    return client


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
    async def test_setpoint_reaches_the_event_context(self) -> None:
        """Прочитанная уставка доезжает до контекста решения — второй конец провода.

        Боевой дефект 2026-10-11: уставка читалась и хранилась, а в контекст
        события не попадала — `may_heat` получал «данных нет» и отказывал при
        любой температуре. Владелец поднял уставку до 30 °C, и **ни один
        обогреватель в доме не включился**: условие не видело цели ни разу.

        Прежняя проверка смотрела только на чтение из Home Assistant, поэтому
        разрыв между «прочитано» и «доставлено» остался незамеченным: обе
        половины выглядели исправными по отдельности.

        Returns:
            Ничего.
        """
        adapter, client = _adapter_with_states({"input_number.temperatura": "30.0"})
        adapter.climate_entities = {"setpoint": "input_number.temperatura"}
        adapter._ws_client = client  # type: ignore[attr-defined]

        await HAAdapter._refresh_climate_globals(adapter)  # type: ignore[arg-type]

        context = HAAdapter._event_context(adapter)  # type: ignore[arg-type]

        assert context.get("climate_setpoint") == 30.0, (
            "уставка прочитана, но не дошла до контекста решения: условие "
            "may_heat читает именно оттуда, поэтому обогрев не включается ни "
            "при какой температуре, а платформа показывает исправную работу"
        )

    @pytest.mark.asyncio
    async def test_event_carries_globals_into_the_decision(self) -> None:
        """Контекст события, уходящий в решение, содержит уставку.

        Третий конец того же провода: `_event_context()` сам по себе возвращает
        глобалы, но вызывать его было неоткуда — условие получало «данных нет»
        при любой температуре. Проверка смотрит на то, что реально уходит в
        `route_state_change`, а не на сам метод.

        Returns:
            Ничего.
        """
        adapter, client = _adapter_with_states({"input_number.temperatura": "30.0"})
        adapter.climate_entities = {"setpoint": "input_number.temperatura"}
        adapter._ws_client = client  # type: ignore[attr-defined]
        await HAAdapter._refresh_climate_globals(adapter)  # type: ignore[arg-type]

        captured: dict[str, Any] = {}

        async def route(entity_id: str, new_state: str, old_state: str, context: Any) -> None:
            captured.update(context or {})

        adapter._event_router = type(  # type: ignore[attr-defined]
            "R", (), {"route_state_change": staticmethod(route)}
        )()
        adapter.heater_timer_of = {}
        adapter._engine = type("E", (), {"event_bus": None})()  # type: ignore[assignment]

        await HAAdapter.on_state_change(  # type: ignore[arg-type]
            adapter,
            "sensor.datchik_temperatury_spalnia_temperature",
            "20.0",
            "21.0",
        )

        assert captured.get("climate_setpoint") == 30.0, (
            "событие датчика ушло в решение без уставки: условие may_heat читает "
            "climate_setpoint именно отсюда, поэтому обогрев не включается ни "
            "в одной комнате, хотя платформа показывает исправную работу "
            "(боевой дефект 2026-10-11, уставка 30 °C не включила ни одного "
            "обогревателя)"
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
        client = _client_with({"setpoint": "input_number.temperatura"}, {})
        with caplog.at_level(logging.WARNING, logger="adapters.ha_adapter"):
            client.store_global("setpoint", "21.5", "input_number.temperatura")

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
        client = _client_with({"outside_temp": "sensor.temperatura_na_ulitse_srednee"}, {})
        with caplog.at_level(logging.WARNING, logger="adapters.ha_adapter"):
            client.store_global("outside_temp", "11.84", "sensor.temperatura_na_ulitse_srednee")

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
        client = _client_with({"setpoint": "input_number.temperatura"}, {})
        with caplog.at_level(logging.WARNING, logger="adapters.ha_adapter"):
            client.store_global("setpoint", "unavailable", "input_number.temperatura")

        assert client.climate_setpoint is None, (
            "нечитаемая уставка не должна превращаться в число: иначе обогрев "
            "поедет по выдуманной цели"
        )
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
        client = _client_with({}, {})
        with caplog.at_level(logging.WARNING, logger="adapters.ha_adapter"):
            client.store_global("no_such_role", "on", "input_boolean.что_то")

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


class TestGlobalsAreSubscribed:
    """Глобальные сущности попадают в подписку, а не читаются один раз (FR-001).

    Боевой дефект 2026-10-10: сущности читались только при подключении, и
    подписка их не включала. Владелец поднял уставку с 21 до 25 — в контексте
    осталось 21, и комнаты, действительно холодные, получали решение «не холодно».
    Спека требует применять уставку без перезапуска (FR-001).
    """

    def test_global_entities_are_accepted(self) -> None:
        """Сущности глобальных значений не отбрасываются фильтром подписки.

        Returns:
            Ничего.
        """
        client = _client_with(
            {"setpoint": "input_number.temperatura"}, {"enable": "input_boolean.ventiliatsiia"}
        )

        assert (
            client._accepts({"entity_id": "input_number.temperatura", "new_state": "25.0"}) is True
        ), (
            "уставка обязана быть в подписке: иначе её изменение не дойдёт до "
            "платформы, и обогрев будет держаться на старой цели до перезапуска"
        )
        assert (
            client._accepts({"entity_id": "input_boolean.ventiliatsiia", "new_state": "on"}) is True
        )

    def test_other_entities_stay_filtered(self) -> None:
        """Остальные сущности дома по-прежнему отфильтровываются.

        Returns:
            Ничего.
        """
        client = _client_with({"setpoint": "input_number.temperatura"}, {})
        # Непустой фильтр: в коде пустой провайдер означает «фильтр выключен»,
        # и тогда пропускается всё — это осознанное поведение при пустом манифесте.
        client.entity_filter_provider = lambda: {"input_number.temperatura"}

        assert (
            client._accepts({"entity_id": "light.svet_nad_stolom", "new_state": "on"}) is False
        ), "подписка на весь дом — Known Issue #82, он закрыт фильтрацией"

    def test_state_change_updates_stored_value(self) -> None:
        """Изменение сущности обновляет прочитанное значение.

        Returns:
            Ничего.
        """
        client = _client_with({"setpoint": "input_number.temperatura"}, {})

        assert (
            client._accepts({"entity_id": "input_number.temperatura", "new_state": "25.0"}) is True
        )
        assert client.climate_setpoint == 25.0, (
            "уставка должна обновляться на лету: владелец меняет её сам, "
            "и ждать перезапуска платформы — значит греть не по той цели"
        )
