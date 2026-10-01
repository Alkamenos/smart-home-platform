"""
Тесты подписчиков шины в слоях персистентности (R-05, T020, T021).

Обработчики `FSMPersistence` и `ContextManager` объявлены как обычные функции,
тогда как шина объявляет обработчики асинхронными. Из-за несовместимости
сигнатур каждая доставка завершалась ложной ошибкой в журнале. Тесты фиксируют
исправленный контракт: подписчик — `async def (event_type, payload, trace_id=None)`.

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0
"""

from __future__ import annotations

import inspect
from typing import Any
from unittest.mock import MagicMock

import pytest
from loguru import logger
from src.core.events.event_bus import EventBus
from src.core.events.fsm_events import EVENT_FSM_TRANSITIONED, EVENT_PLATFORM_STARTED


class TestFSMPersistenceSubscriber:
    """Подписчик персистентности состояний (T020)."""

    def test_should_subscribe_to_transitioned_event_when_initialized(self) -> None:
        """Подписка выполняется на fsm.transitioned, а не на непубликуемое имя."""
        from src.core.fsm.persistence import FSMPersistence

        bus = EventBus()

        FSMPersistence(
            event_bus=bus,
            fsm_engine=MagicMock(),
            adapter=MagicMock(),
            logger=logger,
        )

        assert bus._subscribers[EVENT_FSM_TRANSITIONED]

    def test_should_not_subscribe_to_unpublished_legacy_event_when_initialized(self) -> None:
        """Имя fsm.transition больше не используется (различало бы успех и отказ)."""
        from src.core.fsm.persistence import FSMPersistence

        bus = EventBus()

        FSMPersistence(
            event_bus=bus,
            fsm_engine=MagicMock(),
            adapter=MagicMock(),
            logger=logger,
        )

        assert "fsm.transition" not in bus._subscribers

    async def test_should_deliver_without_false_error_when_transition_published(self) -> None:
        """Публикация перехода не порождает ошибку доставки."""
        from src.core.fsm.persistence import FSMPersistence

        bus = EventBus()
        persistence = FSMPersistence(
            event_bus=bus,
            fsm_engine=MagicMock(),
            adapter=MagicMock(),
            logger=logger,
        )
        persistence.enable_for_entity("light.kitchen", "kitchen_mode")
        persistence._save_state = MagicMock()  # type: ignore[method-assign]

        errors: list[str] = []
        logger.remove()
        logger.add(lambda m: errors.append(m), level="DEBUG")
        try:
            await bus.publish(
                EVENT_FSM_TRANSITIONED,
                {"fsm_id": "light.kitchen", "to_state": "ON_MOTION"},
            )
        finally:
            logger.remove()

        assert not [e for e in errors if "Handler error" in e]
        persistence._save_state.assert_called_once()

    async def test_should_read_state_from_contract_payload_keys_when_transition_published(
        self,
    ) -> None:
        """Обработчик читает fsm_id и to_state — ключи контракта события."""
        from src.core.fsm.persistence import FSMPersistence

        bus = EventBus()
        persistence = FSMPersistence(
            event_bus=bus,
            fsm_engine=MagicMock(),
            adapter=MagicMock(),
            logger=logger,
        )
        persistence.enable_for_entity("light.kitchen", "kitchen_mode")
        persistence._save_state = MagicMock()  # type: ignore[method-assign]

        await bus.publish(
            EVENT_FSM_TRANSITIONED,
            {"fsm_id": "light.kitchen", "to_state": "ON_MOTION"},
        )

        persistence._save_state.assert_called_once_with(
            "kitchen_mode", "ON_MOTION", "light.kitchen"
        )


class TestContextManagerSubscriber:
    """Подписчик менеджера контекста (T021)."""

    async def test_should_deliver_without_false_error_when_platform_started_published(self) -> None:
        """Публикация platform.started не порождает ошибку доставки."""
        from src.core.persistence.context_manager import ContextManager

        bus = EventBus()
        manager = ContextManager(event_bus=bus, fsm_engine=MagicMock(), logger=logger)
        manager._start_schedule_checker = MagicMock()  # type: ignore[method-assign]

        errors: list[str] = []
        logger.remove()
        logger.add(lambda m: errors.append(m), level="DEBUG")
        try:
            await bus.publish(EVENT_PLATFORM_STARTED, {"started": True})
        finally:
            logger.remove()

        assert not [e for e in errors if "Handler error" in e]
        manager._start_schedule_checker.assert_called_once()

    async def test_should_update_context_when_state_change_published(self) -> None:
        """Синхронный подписчик обрабатывает изменение состояния сенсора."""
        from src.core.persistence.context_manager import ContextManager

        bus = EventBus()
        manager = ContextManager(event_bus=bus, fsm_engine=MagicMock(), logger=logger)
        manager.subscribe_sensor("binary_sensor.motion", "living_room_motion")
        manager._trigger_affected_fsms = MagicMock()  # type: ignore[method-assign]

        await bus.publish(
            "ha.state_changed",
            {"entity_id": "binary_sensor.motion", "new_state": "on"},
        )

        assert manager.get_context("living_room_motion") is True
        manager._trigger_affected_fsms.assert_called_once()


class TestNewSubscribersAreAsync:
    """Новые обработчики моста обязаны быть асинхронными."""

    def test_bridge_handlers_should_be_coroutine_functions(self) -> None:
        """Обработчики моста состояний — async с контрактной сигнатурой."""
        from src.services.fsm_state_bridge import FSMStateBridge

        bridge_handlers = [
            FSMStateBridge.on_transitioned,
            FSMStateBridge.on_rejected,
        ]

        for handler in bridge_handlers:
            assert inspect.iscoroutinefunction(handler)
            parameters = list(inspect.signature(handler).parameters)
            assert parameters == ["self", "event_type", "payload", "trace_id"]


@pytest.fixture(autouse=True)
def _restore_logger() -> Any:
    """Восстановить обработчики журнала после каждого теста."""
    yield
    logger.remove()
    logger.add(lambda _message: None)
