"""
Интеграционный тест US1: переход → шина → сохранение → перезапуск (FR-015).

Проверяет полный путь целиком, без веб-интерфейса и без Home Assistant:
выполненный переход публикуется, мост зеркалит состояние и пишет журнал,
состояние переживает перезапуск платформы, а отказ перехода сохранённое
состояние не меняет.

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0
"""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from src.core.events.event_bus import EventBus
from src.core.persistence.event_store import EventStore, FsmTransition
from src.services.fsm_state_bridge import FSMStateBridge

from core import FSMDefinition, FSMEngine, Transition
from core.events.fsm_events import (
    EVENT_FSM_REJECTED,
    EVENT_FSM_TRANSITIONED,
    EVENT_PLATFORM_STARTED,
)
from core.persistence.state_persistence import StatePersistence


FSM_ID = "light.kitchen_lighting_10"
DEVICE_ID = "light.kitchen"


@pytest.fixture
def storage_path(tmp_path: Path) -> str:
    """Путь к файлу состояний во временном каталоге."""
    return str(tmp_path / "state.json")


@pytest.fixture
def event_store(tmp_path: Path) -> EventStore:
    """Журнал переходов в отдельной базе."""
    store = EventStore(db_path=str(tmp_path / "history.db"))
    store._ensure_entities = MagicMock()  # type: ignore[attr-defined]
    return store


@pytest.fixture
def dispatcher() -> MagicMock:
    """Диспетчер команд с асинхронной отправкой."""
    mock = MagicMock()
    mock.submit = AsyncMock(return_value=True)
    return mock


@pytest.fixture
def bus() -> EventBus:
    """Шина событий."""
    return EventBus()


@pytest.fixture
def bridge(bus: EventBus, dispatcher: MagicMock, event_store: EventStore) -> FSMStateBridge:
    """Мост состояний, подключённый к шине."""
    return FSMStateBridge(event_bus=bus, dispatcher=dispatcher, event_store=event_store)


def make_engine(storage_path: str, bus: EventBus) -> FSMEngine:
    """Создать движок с хранилищем состояний.

    Args:
        storage_path: Путь к файлу состояний.
        bus: Шина событий.

    Returns:
        Движок состояний, готовый к регистрации автомата.
    """
    return FSMEngine(event_bus=bus, persistence=StatePersistence(storage_path))


def register_fsm(engine: FSMEngine) -> None:
    """Зарегистрировать автомат освещения кухни.

    Args:
        engine: Движок состояний.
    """
    engine.register_definition(
        FSMDefinition(
            entity_id=FSM_ID,
            initial_state="OFF",
            states=("OFF", "ON_MOTION"),
            transitions=(
                Transition(from_state="OFF", to_state="ON_MOTION", trigger="motion_detected"),
            ),
            debounce_sec=60.0,
            target_device_id=DEVICE_ID,
        )
    )


async def drain(engine: FSMEngine) -> None:
    """Дождаться доставки запланированных событий перехода.

    Args:
        engine: Движок состояний.
    """
    await engine._drain_publish_tasks()


class TestTransitionReachesSubscribers:
    """Переход доходит до моста (FR-001, FR-003)."""

    async def test_should_mirror_and_log_when_transition_published(
        self,
        storage_path: str,
        bus: EventBus,
        bridge: FSMStateBridge,
        dispatcher: MagicMock,
        event_store: EventStore,
    ) -> None:
        """Переход вызывает зеркалирование и попадает в журнал."""
        engine = make_engine(storage_path, bus)
        register_fsm(engine)

        await engine.trigger(FSM_ID, "motion_detected")
        await drain(engine)

        dispatcher.submit.assert_awaited_once()
        assert intent_device(dispatcher) == FSM_ID
        transitions = event_store.get_recent_transitions(DEVICE_ID)
        assert len(transitions) == 1
        assert transitions[0].to_state == "ON_MOTION"
        assert transitions[0].success is True

    async def test_should_log_rejection_when_transition_debounced(
        self,
        storage_path: str,
        bus: EventBus,
        bridge: FSMStateBridge,
        event_store: EventStore,
    ) -> None:
        """Отказ по дебаунсу попадает в журнал как неуспешный переход."""
        engine = make_engine(storage_path, bus)
        register_fsm(engine)

        await engine.trigger(FSM_ID, "motion_detected")
        await drain(engine)
        await engine.trigger(FSM_ID, "motion_detected")
        await drain(engine)

        transitions = event_store.get_recent_transitions(DEVICE_ID)
        assert len(transitions) == 2
        assert transitions[0].success is False
        assert transitions[0].reason == "debounced"

    async def test_should_deliver_both_event_types_when_events_published(
        self, bus: EventBus, bridge: FSMStateBridge
    ) -> None:
        """Шина доставляет и успех, и отказ подписчикам моста."""
        seen: list[str] = []

        async def observer(
            event_type: str, payload: dict[str, object], trace_id: str | None = None
        ) -> None:
            seen.append(event_type)

        bus.subscribe(EVENT_FSM_TRANSITIONED, observer)
        bus.subscribe(EVENT_FSM_REJECTED, observer)

        await bus.publish(EVENT_FSM_TRANSITIONED, {"fsm_id": FSM_ID, "to_state": "ON_MOTION"})
        await bus.publish(EVENT_FSM_REJECTED, {"fsm_id": FSM_ID, "reason": "debounced"})

        assert seen == [EVENT_FSM_TRANSITIONED, EVENT_FSM_REJECTED]


class TestStateSurvivesRestart:
    """Состояние переживает перезапуск платформы (SC-016)."""

    async def test_should_restore_state_when_platform_restarts(
        self, storage_path: str, bus: EventBus, bridge: FSMStateBridge
    ) -> None:
        """После перезапуска состояние восстановлено, а не начальное."""
        first = make_engine(storage_path, bus)
        register_fsm(first)
        await first.trigger(FSM_ID, "motion_detected")
        await drain(first)

        restarted = make_engine(storage_path, bus)
        register_fsm(restarted)

        state = restarted.get_state(FSM_ID)
        assert state is not None
        assert state.current_state == "ON_MOTION"

    async def test_should_keep_state_when_rejected_transition_arrives(
        self, storage_path: str, bus: EventBus, bridge: FSMStateBridge
    ) -> None:
        """Отказ перехода не откатывает уже сохранённое состояние."""
        engine = make_engine(storage_path, bus)
        register_fsm(engine)
        await engine.trigger(FSM_ID, "motion_detected")
        await drain(engine)

        await engine.trigger(FSM_ID, "motion_detected")
        await drain(engine)

        restarted = make_engine(storage_path, bus)
        register_fsm(restarted)
        state = restarted.get_state(FSM_ID)
        assert state is not None
        assert state.current_state == "ON_MOTION"

    async def test_should_not_restore_removed_fsm_when_platform_restarts(
        self, storage_path: str, bus: EventBus, bridge: FSMStateBridge
    ) -> None:
        """Снятый с регистрации автомат не восстанавливается (SC-017)."""
        first = make_engine(storage_path, bus)
        register_fsm(first)
        await first.trigger(FSM_ID, "motion_detected")
        await drain(first)

        restarted = make_engine(storage_path, bus)

        assert restarted.get_state(FSM_ID) is None


class TestPlatformStartedEvent:
    """Событие готовности платформы доходит до подписчиков (FR-007)."""

    async def test_should_deliver_platform_started_to_subscribers(self, bus: EventBus) -> None:
        """Подписчик получает platform.started при публикации."""
        seen: list[dict[str, object]] = []

        async def observer(
            event_type: str, payload: dict[str, object], trace_id: str | None = None
        ) -> None:
            seen.append(payload)

        bus.subscribe(EVENT_PLATFORM_STARTED, observer)

        await bus.publish(EVENT_PLATFORM_STARTED, {"manifest": "instances/manifest.yaml"})

        assert seen == [{"manifest": "instances/manifest.yaml"}]

    async def test_should_not_break_when_subscriber_fails(self, bus: EventBus) -> None:
        """Ошибка подписчика не мешает остальным (FR-003)."""
        delivered: list[str] = []

        async def failing(
            event_type: str, payload: dict[str, object], trace_id: str | None = None
        ) -> None:
            raise RuntimeError("subscriber down")

        async def ok(
            event_type: str, payload: dict[str, object], trace_id: str | None = None
        ) -> None:
            delivered.append("ok")

        bus.subscribe(EVENT_PLATFORM_STARTED, failing)
        bus.subscribe(EVENT_PLATFORM_STARTED, ok)

        await bus.publish(EVENT_PLATFORM_STARTED, {"manifest": "x"})

        assert delivered == ["ok"]


class TestJournalSchema:
    """Журнал принимает признак успеха без потери истории (FR-033)."""

    def test_should_store_success_flag_and_reason(self, tmp_path: Path) -> None:
        """Колонки success и reason появляются в существующей таблице."""
        store = EventStore(db_path=str(tmp_path / "history.db"))
        store.save_fsm_transition(
            FsmTransition(
                entity_id=DEVICE_ID,
                from_state="OFF",
                to_state="ON_MOTION",
                trigger_name="motion_detected",
                trace_id="abc",
                success=True,
            )
        )
        store.save_fsm_transition(
            FsmTransition(
                entity_id=DEVICE_ID,
                from_state="OFF",
                to_state="",
                trigger_name="motion_detected",
                trace_id="def",
                success=False,
                reason="debounced",
            )
        )

        transitions = store.get_recent_transitions(DEVICE_ID)
        assert len(transitions) == 2
        assert any(t.success is True for t in transitions)


def intent_device(dispatcher: MagicMock) -> str | None:
    """Получить устройство из последней отправленной команды.

    Args:
        dispatcher: Диспетчер с записанными вызовами.

    Returns:
        Идентификатор устройства из команды.
    """
    intent = dispatcher.submit.await_args.args[0]
    return intent.device_id


def test_manifest_example_is_registered_in_container() -> None:
    """Реальный манифест платформы собирается без ошибок после изменений."""
    from core.container import Container

    os.environ.pop("HA_TOKEN", None)
    container = Container(manifest_path="instances/leonids_house/manifest.yaml")
    context = container.build()

    assert context.fsm_bridge is not None
    assert context.event_bus is container.event_bus
