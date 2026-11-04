"""Manual event routing for the Home Assistant adapter.

Extracted from HAAdapter (spec 018, US4): a human change in Home Assistant is
delivered to the device FSMs, and the light colour service is re-applied.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from adapters.ha_constants import MANUAL_OFF_VALUES, MANUAL_ON_VALUES


logger = logging.getLogger(__name__)


class ManualEventsMixin:
    """Route manual state changes to FSM automata."""

    if TYPE_CHECKING:
        _engine: Any
        on_light_turned_on: Any

    async def _route_manual_event(self, entity_id: str, new_state: str, log: Any) -> None:
        """Отправить автоматам устройства ручное событие (BACKLOG B57).

        Ручное изменение в Home Assistant меняет состояние прибора, и автомату
        нужно узнать об этом, чтобы войти в ручное состояние и через срок
        оверрайда вернуться к автоматике. События ``manual_switch_on``/
        ``manual_switch_off`` уже объявлены шаблонами света; UI-путь их слал,
        а изменения из Home Assistant — нет.

        Args:
            entity_id: Сущность, которую изменил человек.
            new_state: Новое состояние.
            log: Логгер с трассой.
        """
        engine = self._engine
        get_fsms = getattr(engine, "get_entities_by_device", None)
        trigger = getattr(engine, "trigger", None)
        if not callable(get_fsms) or not callable(trigger):
            return

        value = str(new_state).strip().lower()
        if value in MANUAL_ON_VALUES:
            event = "manual_switch_on"
        elif value in MANUAL_OFF_VALUES:
            event = "manual_switch_off"
        else:
            return

        for fsm_id in get_fsms(entity_id):
            try:
                await trigger(
                    fsm_id,
                    event,
                    {"entity_id": entity_id, "target_device_id": entity_id, "source": "ha_manual"},
                )
            except Exception as e:  # noqa: BLE001 — ручное событие не должно ронять приём
                log.warning(f"HAAdapter: ручное событие {event} не доставлено {fsm_id}: {e}")

        # Лампа включена человеком и восстановила прошлый оттенок. Общий свет
        # дома должен примениться сразу, а не через пять минут и не после
        # часовой блокировки (требование владельца 2026-10-24). Служба сама
        # отсеет нелампы и ночной режим.
        if event == "manual_switch_on" and self.on_light_turned_on is not None:
            try:
                await self.on_light_turned_on(entity_id)
            except Exception as e:  # noqa: BLE001 — температура не должна ронять приём
                log.warning(f"HAAdapter: температура после включения {entity_id} не применена: {e}")
