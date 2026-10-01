"""
Мост состояний автоматов: от события перехода к потребителям.

Мост подписывается на события перехода, публикуемые движком состояний, и
выполняет три независимых действия, каждое из которых не должно влиять на
остальные и на сам переход (FR-003, FR-015):

- зеркалирование состояния в Home Assistant через существующий диспетчер
  команд (режим HA; лучшее усилие — ошибка только в журнале);
- запись перехода в журнал ``EventStore`` — источник фактических данных для
  визуализаций вместо сгенерированных значений (FR-033);
- доставка живого обновления подключённым клиентам (FR-024), если раздатчик
  подключён.

Сохранение состояния в файл выполняет сам движок через ``StatePersistence``;
источник истины остаётся один (R-06).

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Any, Protocol

from loguru import logger

from core.commands.dispatcher import CommandIntent
from core.events.fsm_events import (
    EVENT_FSM_REJECTED,
    EVENT_FSM_TRANSITIONED,
    TIMESTAMP_FORMAT,
)
from core.persistence.event_store import EventStore, FsmTransition, SensorEvent


# Канал Home Assistant с изменениями состояния устройств: по нему появляются
# фактические данные для графиков активности и истории (FR-033).
EVENT_HA_STATE_CHANGE = "state_change"


# Домен и сервис Home Assistant для зеркалирования состояния автомата.
# Используется существующий путь dispatcher -> adapter.call_service, поэтому
# новый метод адаптера не вводится (R-06).
MIRROR_DOMAIN = "input_text"
MIRROR_SERVICE = "set_value"
MIRROR_PRIORITY = 1
MIRROR_SOURCE = "fsm_state"


class DispatcherProtocol(Protocol):
    """Минимальный контракт диспетчера команд, нужный мосту."""

    async def submit(self, intent: CommandIntent) -> bool: ...


class BroadcasterProtocol(Protocol):
    """Минимальный контракт раздатчика живых обновлений."""

    async def __call__(self, payload: dict[str, Any]) -> None: ...


def parse_timestamp(value: Any) -> float | None:
    """Преобразовать время события в число секунд.

    Args:
        value: Время события — строка в формате интерфейса или число.

    Returns:
        Время в секундах либо None, если значение не удалось разобрать.
    """
    if value is None:
        return None
    if isinstance(value, int | float):
        return float(value)
    try:
        return datetime.strptime(str(value), TIMESTAMP_FORMAT).timestamp()
    except ValueError:
        logger.debug(f"Unparsable event timestamp: {value!r}")
        return None


class FSMStateBridge:
    """Подписчик событий перехода, обслуживающий потребителей состояния."""

    def __init__(
        self,
        event_bus: Any,
        dispatcher: DispatcherProtocol | None = None,
        event_store: EventStore | None = None,
        broadcaster: BroadcasterProtocol | None = None,
    ) -> None:
        """Подписать мост на события перехода.

        Args:
            event_bus: Шина событий платформы.
            dispatcher: Диспетчер команд для зеркалирования в Home Assistant.
            event_store: Журнал переходов и событий.
            broadcaster: Раздатчик живых обновлений; подключается позже, когда
                веб-слой уже собран (T041).
        """
        self._event_bus = event_bus
        self._dispatcher = dispatcher
        self._event_store = event_store
        self._broadcaster = broadcaster

        event_bus.subscribe(EVENT_FSM_TRANSITIONED, self.on_transitioned)
        event_bus.subscribe(EVENT_FSM_REJECTED, self.on_rejected)
        event_bus.subscribe(EVENT_HA_STATE_CHANGE, self.on_state_change)
        logger.info("FSM state bridge initialized")

    def set_broadcaster(self, broadcaster: BroadcasterProtocol) -> None:
        """Подключить раздатчик живых обновлений (T041).

        Args:
            broadcaster: Раздатчик живых обновлений.
        """
        self._broadcaster = broadcaster

    async def on_transitioned(
        self, event_type: str, payload: dict[str, Any], trace_id: str | None = None
    ) -> None:
        """Обработать выполненный переход автомата.

        Args:
            event_type: Имя события.
            payload: Полезная нагрузка события перехода.
            trace_id: Идентификатор трассы.
        """
        log = logger.bind(trace_id=trace_id)
        log.debug(f"Transition recorded for {payload.get('fsm_id')}")
        await self._mirror_state(payload)
        self._record_transition(payload, success=True)
        await self._broadcast(payload)

    async def on_rejected(
        self, event_type: str, payload: dict[str, Any], trace_id: str | None = None
    ) -> None:
        """Обработать отказ в переходе автомата.

        Args:
            event_type: Имя события.
            payload: Полезная нагрузка события отказа.
            trace_id: Идентификатор трассы.
        """
        log = logger.bind(trace_id=trace_id)
        log.debug(f"Transition rejected for {payload.get('fsm_id')}: {payload.get('reason')}")
        self._record_transition(payload, success=False)

    async def on_state_change(
        self, event_type: str, payload: dict[str, Any], trace_id: str | None = None
    ) -> None:
        """Записать изменение состояния устройства в журнал событий.

        Args:
            event_type: Имя события.
            payload: Полезная нагрузка изменения состояния.
            trace_id: Идентификатор трассы.
        """
        self._record_state_change(payload or {})

    def _record_state_change(self, payload: dict[str, Any]) -> None:
        """Сохранить событие устройства в журнал.

        Args:
            payload: Полезная нагрузка изменения состояния.
        """
        if self._event_store is None:
            return

        entity_id = payload.get("entity_id")
        new_state = payload.get("new_state")
        if not entity_id or new_state is None:
            return

        context = payload.get("context") or {}
        try:
            self._event_store.save_sensor_event(
                SensorEvent(
                    entity_id=entity_id,
                    old_state=payload.get("old_state") or "",
                    new_state=str(new_state),
                    event_type=payload.get("event_type") or "state_changed",
                    trace_id=context.get("trace_id"),
                    timestamp=parse_timestamp(payload.get("timestamp")),
                )
            )
        except Exception as e:  # noqa: BLE001 - журнал не влияет на переход
            logger.warning(f"Failed to record device state change: {e}")

    async def _mirror_state(self, payload: dict[str, Any]) -> None:
        """Записать состояние автомата в Home Assistant через диспетчер.

        Лучшее усилие: отсутствие ``input_text`` в Home Assistant или обрыв связи
        не должны влиять на переход и на сохранение состояния в файл (R-06).

        Args:
            payload: Полезная нагрузка события перехода.
        """
        if self._dispatcher is None:
            return

        fsm_id = payload.get("fsm_id")
        to_state = payload.get("to_state")
        if not fsm_id or not to_state:
            logger.debug("Skipping Home Assistant mirror: missing fsm_id or to_state")
            return

        intent = CommandIntent(
            device_id=fsm_id,
            domain=MIRROR_DOMAIN,
            service=MIRROR_SERVICE,
            data={"value": to_state},
            priority=MIRROR_PRIORITY,
            source=MIRROR_SOURCE,
        )
        try:
            await self._dispatcher.submit(intent)
        except Exception as e:  # noqa: BLE001 - зеркалирование не влияет на переход
            logger.warning(f"Failed to mirror FSM state to Home Assistant: {e}")

    def _record_transition(self, payload: dict[str, Any], *, success: bool) -> None:
        """Записать переход в журнал.

        Args:
            payload: Полезная нагрузка события перехода.
            success: Признак выполненного перехода.
        """
        if self._event_store is None:
            return

        fsm_id = payload.get("fsm_id")
        if not fsm_id:
            return

        try:
            self._event_store.save_fsm_transition(
                FsmTransition(
                    entity_id=payload.get("device_id") or fsm_id,
                    from_state=payload.get("from_state") or "",
                    to_state=payload.get("to_state") or "",
                    trigger_name=payload.get("event") or "",
                    trace_id=payload.get("trace_id"),
                    timestamp=parse_timestamp(payload.get("timestamp")),
                    success=success,
                    reason=payload.get("reason"),
                )
            )
        except Exception as e:  # noqa: BLE001 - журнал не влияет на переход
            logger.warning(f"Failed to record FSM transition: {e}")

    async def _broadcast(self, payload: dict[str, Any]) -> None:
        """Разослать живое обновление подключённым клиентам.

        Args:
            payload: Полезная нагрузка события перехода.
        """
        broadcaster = self._broadcaster
        if broadcaster is None:
            return
        try:
            await broadcaster(payload)
        except Exception as e:  # noqa: BLE001 - доставка не влияет на переход
            logger.warning(f"Failed to broadcast FSM transition: {e}")


# Тип раздатчика для подключения из веб-слоя.
Broadcaster = Callable[[dict[str, Any]], Awaitable[None]]
