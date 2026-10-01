"""
Тесты моста состояний автоматов (FR-015, FR-016, T016).

Мост подписывается на события перехода и: зеркалирует состояние в Home Assistant
через диспетчер команд (лучшее усилие) и пишет запись в журнал переходов.
Ошибка любого из назначений не влияет на переход и на сохранение состояния.

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from src.core.events.event_bus import EventBus
from src.core.events.fsm_events import EVENT_FSM_REJECTED, EVENT_FSM_TRANSITIONED
from src.services.fsm_state_bridge import FSMStateBridge


TRANSITION_PAYLOAD: dict[str, Any] = {
    "fsm_id": "light.kitchen_lighting_10",
    "device_id": "light.kitchen",
    "behavior": "lighting",
    "from_state": "OFF",
    "to_state": "ON_MOTION",
    "event": "motion_detected",
    "source": "automatic",
    "timestamp": "2026-10-01T14:23:11.482913",
    "outcome": "transitioned",
    "trace_id": "abc12345",
    "reason": None,
}

REJECTION_PAYLOAD: dict[str, Any] = {
    **TRANSITION_PAYLOAD,
    "to_state": None,
    "outcome": "rejected",
    "reason": "debounced",
}


@pytest.fixture
def dispatcher() -> MagicMock:
    """Диспетчер команд с асинхронной отправкой."""
    mock = MagicMock()
    mock.submit = AsyncMock()
    return mock


@pytest.fixture
def event_store() -> MagicMock:
    """Журнал переходов."""
    return MagicMock()


@pytest.fixture
def bridge(dispatcher: MagicMock, event_store: MagicMock) -> FSMStateBridge:
    """Мост состояний, подключённый к шине."""
    return FSMStateBridge(
        event_bus=EventBus(),
        dispatcher=dispatcher,
        event_store=event_store,
    )


class TestSubscription:
    """Мост подписан на оба события перехода (T019)."""

    def test_should_subscribe_to_transitioned_and_rejected_when_created(self) -> None:
        """Подписки выполняются на fsm.transitioned и fsm.rejected."""
        bus = EventBus()

        FSMStateBridge(event_bus=bus, dispatcher=MagicMock(), event_store=MagicMock())

        assert bus._subscribers[EVENT_FSM_TRANSITIONED]
        assert bus._subscribers[EVENT_FSM_REJECTED]


class TestHomeAssistantMirror:
    """Зеркалирование состояния в Home Assistant (T022)."""

    async def test_should_mirror_state_via_dispatcher_when_transition_occurs(
        self, bridge: FSMStateBridge, dispatcher: MagicMock
    ) -> None:
        """Состояние отправляется в HA через диспетчер, а не через новый метод адаптера."""
        await bridge.on_transitioned(EVENT_FSM_TRANSITIONED, TRANSITION_PAYLOAD)

        dispatcher.submit.assert_awaited_once()
        intent = dispatcher.submit.await_args.args[0]
        assert intent.domain == "input_text"
        assert intent.service == "set_value"
        assert intent.data["value"] == "ON_MOTION"
        assert intent.priority == 1

    async def test_should_use_low_priority_when_mirroring_state(
        self, bridge: FSMStateBridge, dispatcher: MagicMock
    ) -> None:
        """Низкий приоритет не вытесняет команды пользователя (ADR-004)."""
        await bridge.on_transitioned(EVENT_FSM_TRANSITIONED, TRANSITION_PAYLOAD)

        intent = dispatcher.submit.await_args.args[0]
        assert intent.priority < 10

    async def test_should_not_mirror_when_rejected(
        self, bridge: FSMStateBridge, dispatcher: MagicMock
    ) -> None:
        """Отклонённый переход в HA не зеркалируется."""
        await bridge.on_rejected(EVENT_FSM_REJECTED, REJECTION_PAYLOAD)

        dispatcher.submit.assert_not_awaited()

    async def test_should_not_raise_when_dispatcher_fails(
        self, bridge: FSMStateBridge, dispatcher: MagicMock
    ) -> None:
        """Ошибка зеркалирования логируется и не пробрасывается (FR-015)."""
        dispatcher.submit = AsyncMock(side_effect=RuntimeError("adapter down"))

        await bridge.on_transitioned(EVENT_FSM_TRANSITIONED, TRANSITION_PAYLOAD)

    async def test_should_not_raise_when_dispatcher_absent(self) -> None:
        """Без диспетчера (автономный режим) мост работает."""
        bridge = FSMStateBridge(event_bus=EventBus(), dispatcher=None, event_store=MagicMock())

        await bridge.on_transitioned(EVENT_FSM_TRANSITIONED, TRANSITION_PAYLOAD)

    async def test_should_skip_mirror_when_required_fields_absent(
        self, bridge: FSMStateBridge, dispatcher: MagicMock
    ) -> None:
        """Событие без состояния не зеркалируется (FR-008)."""
        await bridge.on_transitioned(EVENT_FSM_TRANSITIONED, {"fsm_id": "light.kitchen"})

        dispatcher.submit.assert_not_awaited()


class TestTransitionLog:
    """Запись переходов в журнал (T026)."""

    async def test_should_record_transition_when_transition_occurs(
        self, bridge: FSMStateBridge, event_store: MagicMock
    ) -> None:
        """Выполненный переход попадает в журнал с признаком успеха."""
        await bridge.on_transitioned(EVENT_FSM_TRANSITIONED, TRANSITION_PAYLOAD)

        event_store.save_fsm_transition.assert_called_once()
        saved = event_store.save_fsm_transition.call_args.args[0]
        assert saved.entity_id == "light.kitchen"
        assert saved.from_state == "OFF"
        assert saved.to_state == "ON_MOTION"
        assert saved.trigger_name == "motion_detected"
        assert saved.success is True

    async def test_should_record_rejection_when_transition_rejected(
        self, bridge: FSMStateBridge, event_store: MagicMock
    ) -> None:
        """Отказ попадает в журнал с признаком неуспеха."""
        await bridge.on_rejected(EVENT_FSM_REJECTED, REJECTION_PAYLOAD)

        event_store.save_fsm_transition.assert_called_once()
        saved = event_store.save_fsm_transition.call_args.args[0]
        assert saved.success is False

    async def test_should_not_raise_when_event_store_fails(
        self, bridge: FSMStateBridge, event_store: MagicMock
    ) -> None:
        """Ошибка записи в журнал не влияет на переход (FR-003)."""
        event_store.save_fsm_transition.side_effect = RuntimeError("db locked")

        await bridge.on_transitioned(EVENT_FSM_TRANSITIONED, TRANSITION_PAYLOAD)

    async def test_should_not_raise_when_event_store_absent(self) -> None:
        """Без журнала мост продолжает работать."""
        bridge = FSMStateBridge(event_bus=EventBus(), dispatcher=None, event_store=None)

        await bridge.on_transitioned(EVENT_FSM_TRANSITIONED, TRANSITION_PAYLOAD)


class TestEndToEndViaBus:
    """Доставка события шиной вызывает действия моста (FR-003)."""

    async def test_should_mirror_and_record_when_event_published(
        self, dispatcher: MagicMock, event_store: MagicMock
    ) -> None:
        """Опубликованное событие доходит до зеркала и журнала."""
        bus = EventBus()
        FSMStateBridge(event_bus=bus, dispatcher=dispatcher, event_store=event_store)

        await bus.publish(EVENT_FSM_TRANSITIONED, TRANSITION_PAYLOAD)

        dispatcher.submit.assert_awaited_once()
        event_store.save_fsm_transition.assert_called_once()
