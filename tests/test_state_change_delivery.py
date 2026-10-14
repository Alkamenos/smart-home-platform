"""Доставка изменений состояния Home Assistant до потребителей.

Known Issue #9 был записан как «избыточный мёртвый канал `params.motion_sensor`».
Проверкой кода установлено, что мёртвой была вся доставка, а не тот канал:
``HAAdapter.on_state_change`` публиковал ``state_change`` на шину движка только
при ``hasattr(engine, "event_bus")``, а у настоящего ``FSMEngine`` шина названа
``_event_bus`` (``core/fsm/engine.py``). На ``MagicMock`` движке атрибут
появляется сам, поэтому прежние тесты адаптера проходили по ветке, которую в
бою не проходит никто, — и закрепляли её как рабочую.

Что из этого следует в бою (и что здесь закреплено):

- состояние устройства обновлялось только синхронизацией, то есть оставалось
  таким, каким было при последнем ручном ``POST /sync``;
- ``broadcast_state_change()`` не получал данных для отправки клиентам;
- ``FSMStateBridge`` не писал события устройств в журнал, хотя графики
  активности читают именно эту таблицу (F2, US4);
- каждое изменение состояния порождало отказ движка ``unknown_entity``: вызов
  шёл в ``engine.trigger()`` по идентификатору сущности Home Assistant
  (``light.living_room_main``), а автоматы называются
  ``light.living_room_main_lighting_5``. Отказы замолчали в #79, счётчик остался.

Тесты строятся на настоящих движке, шине и сервисе устройств: подмена движка
на ``MagicMock`` здесь и прятала дефект.

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from adapters.ha_adapter import HAAdapter
from core.events.event_bus import EventBus
from core.fsm.engine import FSMEngine
from core.models.device import Device
from services.device_service import DeviceService


#: Сущность манифеста: именно на такие подписан адаптер после #82.
ENTITY = "light.living_room_main"


def _device(entity_id: str = ENTITY) -> Device:
    """Устройство с начальным состоянием ``off``.

    Args:
        entity_id: Идентификатор сущности Home Assistant.

    Returns:
        Модель устройства.
    """
    return Device(
        ha_entity_id=entity_id,
        source_id=uuid4(),
        name="Люстра",
        device_type="light",
        state={"state": "off"},
    )


def _adapter(engine: FSMEngine | None) -> HAAdapter:
    """Адаптер в режиме pyscript с настоящим движком.

    Args:
        engine: Движок автоматов либо ``None``.

    Returns:
        Готовый адаптер.
    """
    return HAAdapter(mode="pyscript", engine=engine, hass=MagicMock())


def _service(bus: EventBus) -> DeviceService:
    """Сервис устройств, подписанный на события шины.

    Args:
        bus: Шина событий платформы.

    Returns:
        Сервис, уже подписанный на изменения состояния.
    """
    service = DeviceService(event_bus=bus)
    service.subscribe_state_changes()
    return service


class TestEngineEventBus:
    """Шина движка должна быть видна снаружи."""

    def test_should_return_bus_engine_was_built_with(self):
        """Движок обязан отдавать ту шину, с которой он собран.

        Именно на её наличии держится доставка событий Home Assistant: пока у
        движка было только `_event_bus`, адаптер получал `hasattr(...) is False`
        на настоящем движке и уходил в другую ветку.
        """
        bus = EventBus()

        engine = FSMEngine(event_bus=bus)

        assert engine.event_bus is bus

    def test_should_return_none_when_built_without_bus(self):
        """Движок без шины отдаёт `None`, а не исключение.

        Иначе проверка наличия шины в адаптере падала бы на сборке без шины —
        то есть ровно там, где проверка и нужна.
        """
        engine = FSMEngine()

        assert engine.event_bus is None


class TestAdapterPublishesToRealBus:
    """Адаптер публикует на шину настоящего движка."""

    @pytest.mark.asyncio
    async def test_should_publish_state_change_payload(self):
        """Подписчик должен получить сущность и оба состояния."""
        bus = EventBus()
        received: list[dict[str, Any]] = []

        async def collect(event_type: str, payload: dict[str, Any]) -> None:
            received.append({"event_type": event_type, **payload})

        bus.subscribe("state_change", collect)
        adapter = _adapter(FSMEngine(event_bus=bus))

        await adapter.on_state_change(
            entity_id=ENTITY,
            new_state="on",
            old_state="off",
            context={},
        )

        assert len(received) == 1
        assert received[0]["event_type"] == "state_change"
        assert received[0]["entity_id"] == ENTITY
        assert received[0]["new_state"] == "on"
        assert received[0]["old_state"] == "off"

    @pytest.mark.asyncio
    async def test_should_keep_trace_id_from_context(self):
        """Трасса из контекста доходит до подписчика."""
        bus = EventBus()
        traces: list[str] = []

        async def collect(event_type: str, payload: dict[str, Any], trace_id: str) -> None:
            traces.append(trace_id)

        bus.subscribe("state_change", collect)
        adapter = _adapter(FSMEngine(event_bus=bus))

        await adapter.on_state_change(
            entity_id=ENTITY,
            new_state="on",
            old_state="off",
            context={"trace_id": "custom123"},
        )

        assert traces == ["custom123"]

    @pytest.mark.asyncio
    async def test_should_not_publish_when_engine_has_no_bus(self):
        """Движок без шины — публиковать некуда, и это не ошибка.

        Сборка без шины встречается в тестах и локальных запусках; адаптер не
        должен ни падать, ни подменять доставку вызовом движка.
        """
        adapter = _adapter(FSMEngine())

        result = await adapter.on_state_change(
            entity_id=ENTITY,
            new_state="on",
            old_state="off",
            context={},
        )

        assert result is None

    @pytest.mark.asyncio
    async def test_should_not_publish_when_engine_absent(self):
        """Адаптер без движка не публикует и не падает."""
        adapter = _adapter(None)

        result = await adapter.on_state_change(
            entity_id=ENTITY,
            new_state="on",
            old_state="off",
            context={},
        )

        assert result is None

    @pytest.mark.asyncio
    async def test_should_not_break_adapter_when_publish_fails(self):
        """Отказ шины не должен подниматься в адаптер.

        Иначе одно зависшее событие обрывало бы разбор входа Home Assistant и
        с подпиской, и маршрутизацию: они идут следом по той же цепочке.

        Обработчик помечает, что его позвали, и только потом падает: без этой
        отметки тест проходил бы и при полном отсутствии публикации, то есть
        проверял бы «не бросило» вместо «доставил и пережил отказ».
        """
        bus = EventBus()
        called: list[str] = []

        async def failing(event_type: str, payload: dict[str, Any]) -> None:
            called.append(event_type)
            raise RuntimeError("шина недоступна")

        bus.subscribe("state_change", failing)
        adapter = _adapter(FSMEngine(event_bus=bus))

        result = await adapter.on_state_change(
            entity_id=ENTITY,
            new_state="on",
            old_state="off",
            context={},
        )

        assert result is None
        assert called == ["state_change"]


class TestDeadBranchRemoved:
    """Вызов `engine.trigger()` по сущности Home Assistant — не доставка."""

    @pytest.mark.asyncio
    async def test_should_not_record_unknown_entity_rejection(self):
        """Изменение состояния не должно попадать в отказы движка.

        Идентификатор сущности Home Assistant не является именем автомата, и
        запасная ветка адаптера отправляла его в `trigger()` именно как имя
        автомата. Отказ честный, но состояние не доставлял он никому.
        """
        engine = FSMEngine(event_bus=EventBus())
        adapter = _adapter(engine)

        await adapter.on_state_change(
            entity_id=ENTITY,
            new_state="on",
            old_state="off",
            context={},
        )

        assert engine.rejection_counts() == {}

    @pytest.mark.asyncio
    async def test_should_not_trigger_registered_fsm_directly(self):
        """Событие Home Assistant не должно двигать автомат напрямую.

        Автоматом управляет EventRouter, который переводит движение датчика в
        `motion_detected`. Прямой вызов по имени `{сущность}_changed` не
        соответствует ни одному триггеру шаблонов и потому отказен.
        """
        engine = FSMEngine(event_bus=EventBus())
        triggers: list[tuple[str, str]] = []

        async def record_trigger(entity_id: str, event: str, **_: Any) -> bool:
            triggers.append((entity_id, event))
            return True

        engine.trigger = record_trigger  # type: ignore[method-assign]
        adapter = _adapter(engine)

        await adapter.on_state_change(
            entity_id=ENTITY,
            new_state="on",
            old_state="off",
            context={},
        )

        assert triggers == []


class TestDeliveryToDeviceService:
    """Событие доходит до сервиса устройств — того ради чего оно публикуется."""

    @pytest.mark.asyncio
    async def test_should_update_device_state_in_service(self):
        """Состояние устройства обновляется событием, а не синхронизацией.

        До починки в бою это обновление не происходило ни разу: состояние в
        базе меняла только ручная синхронизация, поэтому список устройств
        показывал значения на момент последнего `POST /sync`.
        """
        bus = EventBus()
        adapter = _adapter(FSMEngine(event_bus=bus))

        device = _device()
        service = _service(bus)
        service._devices[device.id] = device

        await adapter.on_state_change(
            entity_id=ENTITY,
            new_state="on",
            old_state="off",
            context={},
        )

        assert service._devices[device.id].state["state"] == "on"

    @pytest.mark.asyncio
    async def test_should_ignore_event_for_unknown_entity(self):
        """Событие чужой сущности не создаёт устройство и не падает.

        В доме 1502 сущности против 6 описанных в манифесте; подписка после #82
        ограничена манифестом, но обработчик обязан оставаться терпимым к
        остальным — молчание об отказе не то же самое, что отказ.
        """
        bus = EventBus()
        adapter = _adapter(FSMEngine(event_bus=bus))
        service = _service(bus)

        await adapter.on_state_change(
            entity_id="sensor.temperature_outside",
            new_state="7",
            old_state="6",
            context={},
        )

        assert service._devices == {}


class TestBridgeRecordsEvents:
    """Журнал событий наполняется фактическими данными."""

    @pytest.mark.asyncio
    async def test_bridge_should_receive_state_change(self):
        """Мост состояний должен получать событие устройства.

        График активности за 24 часа читает `SensorEvent`, и писателей у этой
        таблицы не было ни одного: единственный издатель события молчал.
        """
        bus = EventBus()
        adapter = _adapter(FSMEngine(event_bus=bus))
        recorded: list[dict[str, Any]] = []

        async def on_state_change(event_type: str, payload: dict[str, Any]) -> None:
            recorded.append(payload)

        bus.subscribe("state_change", on_state_change)

        await adapter.on_state_change(
            entity_id=ENTITY,
            new_state="on",
            old_state="off",
            context={},
        )

        assert [payload["entity_id"] for payload in recorded] == [ENTITY]


class TestNoDuplicateFsmDelivery:
    """Публикация на шину не должна дублировать переходы автоматов."""

    @pytest.mark.asyncio
    async def test_state_change_should_not_trigger_transition(self):
        """Событие состояния не исполняет переход автомата само по себе.

        Публикация на шину — доставка потребителям (сервис устройств, журнал).
        Переходы вызывает EventRouter отдельно; если бы `state_change` ещё и
        двигал автоматы, каждое изменение состояния давало бы двойной переход.
        """
        bus = EventBus()
        engine = FSMEngine(event_bus=bus)
        transitions: list[dict[str, Any]] = []

        async def on_transitioned(event_type: str, payload: dict[str, Any]) -> None:
            transitions.append(payload)

        bus.subscribe("fsm.transitioned", on_transitioned)
        adapter = _adapter(engine)

        await adapter.on_state_change(
            entity_id=ENTITY,
            new_state="on",
            old_state="off",
            context={},
        )

        assert transitions == []
        assert engine.get_all_states() == {}
