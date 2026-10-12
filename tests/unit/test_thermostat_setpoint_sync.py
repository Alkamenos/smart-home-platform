"""Синхронизация «термостат ↔ уставка» — требование владельца 2026-10-12.

Владелец менял уставку на термостате `climate.termostat_gostinaia`, а платформа
читает `input_number.temperatura` — сущности не связаны ничем, и «обрыв» выглядел
как баг «обогреватели не включаются». Решение: платформа-синхронизатор в оба
направления.

Уставку задаёт `climate.termostat_gostinaia`, и цель у него живёт в атрибуте
`temperature`, а не в состоянии: состояние климат-сущности — это режим
(`heat`/`off`). Раньше роль `setpoint` читала состояние, и климат-термостат
положил бы в `climate_setpoint` строку `heat`, которая не читается как число —
условия обогрева отказали бы.

Петля: наша команда синхронизации возвращается из HA с тем же `context.id`
(учтено в `_own_context_ids`), и обратная синхронизация не запускается.

Уточнения владельца по составу: `climate.termostat_gostinaia` — основной
термостат, `climate.esphome_web_*` — кондиционер, `kitchen_ac` и
`beok_tr9b_thermostat{,_2}` — legacy (владелец удалит из HA сам).
"""

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from typing import Any

import pytest

from adapters.ha_adapter import HAAdapter


THERMOSTAT = "climate.termostat_gostinaia"
SETPOINT_ENTITY = "input_number.temperatura"


def _adapter(**attrs: Any) -> HAAdapter:
    """Адаптер без сети с заданными атрибутами.

    Args:
        attrs: Атрибуты адаптера.

    Returns:
        Готовый адаптер.
    """
    adapter = HAAdapter.__new__(HAAdapter)
    adapter._entity_units = {}
    adapter._manifest = None
    adapter._ws_client = None
    adapter.climate_entities = {"setpoint": SETPOINT_ENTITY, "thermostat": THERMOSTAT}
    for name, value in attrs.items():
        setattr(adapter, name, value)
    return adapter


def _state_event(
    entity_id: str, state: str, attributes: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Событие изменения состояния в форме, которую шлёт Home Assistant.

    Args:
        entity_id: Сущность.
        state: Состояние.
        attributes: Атрибуты нового состояния.

    Returns:
        Конверт события (`event.data`).
    """
    return {
        "entity_id": entity_id,
        "new_state": {"entity_id": entity_id, "state": state, "attributes": attributes or {}},
        "old_state": {"entity_id": entity_id, "state": "", "attributes": {}},
    }


class TestSetpointReadsThermostatAttribute:
    """Уставка читает цель термостата, а не его режим."""

    def test_thermostat_event_carries_target_temperature(self) -> None:
        """В глобал уставки кладётся атрибут temperature, а не состояние heat.

        Returns:
            Ничего.
        """
        adapter = _adapter()
        payload = _state_event(THERMOSTAT, "heat", {"temperature": 30.0})

        stored = adapter.setpoint_from_event(THERMOSTAT, payload)

        assert stored == "30.0", (
            f"в уставку попало {stored!r}: состояние климат-сущности — это режим "
            "(heat/off), а цель живёт в атрибуте temperature. Условия обогрева "
            "получили бы «данных нет»"
        )

    def test_input_number_event_keeps_state(self) -> None:
        """У обычного input_number уставка берётся из состояния.

        Returns:
            Ничего.
        """
        adapter = _adapter()
        payload = _state_event(SETPOINT_ENTITY, "21.5")

        assert adapter.setpoint_from_event(SETPOINT_ENTITY, payload) == "21.5"


class TestThermostatTargetMirrorsToSetpoint:
    """Цель термостата зеркалируется в уставку."""

    @pytest.mark.asyncio
    async def test_target_change_sends_set_value(self) -> None:
        """Термостат поменяли — уставке шлётся новое значение.

        Returns:
            Ничего.
        """
        calls: list[tuple[str, str, str, dict[str, Any]]] = []

        async def call_service(
            domain: str, service: str, entity_id: str, data: dict[str, Any] | None = None, **_: Any
        ) -> bool:
            calls.append((domain, service, entity_id, data or {}))
            return True

        async def get_state(entity_id: str) -> str | None:
            return "21.0"

        adapter = _adapter()
        adapter.call_service = call_service  # type: ignore[assignment]
        adapter.get_state = get_state  # type: ignore[assignment]

        await adapter.sync_setpoint(THERMOSTAT, "30.0", own_action=False)

        assert calls, (
            "цель термостата изменилась, а уставку никто не зеркалировал: "
            "платформа продолжает решать по старой цели"
        )
        domain, service, entity, data = calls[0]
        assert (domain, service, entity) == ("input_number", "set_value", SETPOINT_ENTITY)
        assert data["value"] == 30.0

    @pytest.mark.asyncio
    async def test_no_command_when_values_match(self) -> None:
        """Совпадающие значения не порождают команду — петля и шум отсекаются.

        Returns:
            Ничего.
        """
        calls: list[Any] = []

        async def call_service(*args: Any, **kwargs: Any) -> bool:
            calls.append(args)
            return True

        async def get_state(entity_id: str) -> str | None:
            return "30.0"

        adapter = _adapter()
        adapter.call_service = call_service  # type: ignore[assignment]
        adapter.get_state = get_state  # type: ignore[assignment]

        await adapter.sync_setpoint(THERMOSTAT, "30.0", own_action=False)

        assert not calls, (
            "совпадающие значения дали команду: каждое событие породило бы зеркало в обе стороны"
        )

    @pytest.mark.asyncio
    async def test_own_action_is_not_mirrored(self) -> None:
        """Собственная команда синхронизатора обратно не зеркалируется.

        Returns:
            Ничего.
        """
        calls: list[Any] = []

        async def call_service(*args: Any, **kwargs: Any) -> bool:
            calls.append(args)
            return True

        async def get_state(entity_id: str) -> str | None:
            return "21.0"

        adapter = _adapter()
        adapter.call_service = call_service  # type: ignore[assignment]
        adapter.get_state = get_state  # type: ignore[assignment]

        await adapter.sync_setpoint(SETPOINT_ENTITY, "27.0", own_action=True)

        assert not calls, (
            "собственная команда вызвала обратную синхронизацию: термостат и "
            "уставка ввались бы в петлю и переключались бы, пока не разъехались"
        )


class TestSetpointMirrorsToThermostat:
    """Изменение уставки пишется в цель термостата."""

    @pytest.mark.asyncio
    async def test_setpoint_change_updates_thermostat(self) -> None:
        """Слайдер уставки двигнул человек — цель термостата догоняет.

        Returns:
            Ничего.
        """
        calls: list[tuple[str, str, str, dict[str, Any]]] = []

        async def call_service(
            domain: str, service: str, entity_id: str, data: dict[str, Any] | None = None, **_: Any
        ) -> bool:
            calls.append((domain, service, entity_id, data or {}))
            return True

        async def get_state(entity_id: str) -> str | None:
            return "heat"

        async def get_attribute(entity_id: str, attribute: str) -> Any:
            return 24.0

        adapter = _adapter()
        adapter.call_service = call_service  # type: ignore[assignment]
        adapter.get_state = get_state  # type: ignore[assignment]
        adapter.get_attribute = get_attribute  # type: ignore[assignment]

        await adapter.sync_setpoint(SETPOINT_ENTITY, "30.0", own_action=False)

        assert calls, "уставку поменяли, а термостат остался на старой цели"
        domain, service, entity, data = calls[0]
        assert (domain, service, entity) == ("climate", "set_temperature", THERMOSTAT)
        assert data["temperature"] == 30.0

    @pytest.mark.asyncio
    async def test_no_mirroring_when_thermostat_unconfigured(self) -> None:
        """Без настроенного термостата синхронизация не делает ничего.

        Returns:
            Ничего.
        """
        calls: list[Any] = []

        async def call_service(*args: Any, **kwargs: Any) -> bool:
            calls.append(args)
            return True

        async def get_state(entity_id: str) -> str | None:
            return None

        adapter = _adapter(climate_entities={"setpoint": SETPOINT_ENTITY})
        adapter.call_service = call_service  # type: ignore[assignment]
        adapter.get_state = get_state  # type: ignore[assignment]

        await adapter.sync_setpoint(SETPOINT_ENTITY, "30.0", own_action=False)

        assert not calls, "без термостата в правилах синхронизатор пытался кому-то писать"


class TestEventWiresTheSync:
    """Событие термостата доходит до синхронизатора (врезка в on_state_change)."""

    @pytest.mark.asyncio
    async def test_thermostat_event_triggers_sync(self) -> None:
        """Событие климат-термостата вызывает sync_setpoint.

        Роль термостата — `thermostat`, а не `setpoint`: проверка только по
        `setpoint` пропускала событие целиком, и синхронизация не запускалась
        вовсе (живой прогон 2026-10-12).

        Returns:
            Ничего.
        """
        called: list[tuple[str, str, bool]] = []

        async def sync_setpoint(entity_id: str, value: str, own_action: bool) -> None:
            called.append((entity_id, value, own_action))

        class _Client:
            def global_role(self, entity: str) -> str:
                return "thermostat" if entity == THERMOSTAT else "setpoint"

            daylight = True
            asleep = False

        adapter = _adapter()
        adapter._ws_client = _Client()  # type: ignore[assignment]
        adapter.sync_setpoint = sync_setpoint  # type: ignore[assignment]
        adapter._manual_lockout_middleware = None
        adapter._own_context_ids = __import__("collections").deque()
        adapter._token = None
        adapter._session = None
        adapter._engine = None
        adapter._event_router = None
        adapter.heater_timer_of = {}

        await adapter.on_state_change(THERMOSTAT, "heat", "heat", {})

        assert called, (
            "событие термостата не дошло до синхронизатора: роль `thermostat` "
            "не обрабатывается, и «термостат → уставка» молчит"
        )
        assert called[0][0] == THERMOSTAT
