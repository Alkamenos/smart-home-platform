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
        _manual_lockout_middleware: Any
        _is_recent_command: Any
        on_light_turned_on: Any

    def _note_physical_manual(
        self,
        entity_id: str,
        new_state: str,
        user_id: Any,
        automation_id: Any,
        context: dict[str, Any],
        own_action: bool,
        human_action: bool,
    ) -> bool:
        """Отметить физическое действие прибора без ``user_id``/``parent_id``.

        Настенный выключатель света и розетка/выключатель обогревателя не
        оставляют в Home Assistant ни пользователя, ни автоматизации. Это
        доказательство человека, а не команда платформы: иначе выключенный рукой
        свет следующее движение включало бы снова (B89), а обогреватель остался
        бы в HEATING с выключенным прибором (живая находка 2026-11-08).

        Включение обогревателя сюда не входит: включённый мимо платформы прибор
        при решении «не греть» остаётся проблемой дома (B113), а не уступкой.

        Args:
            entity_id: Сущность, изменившая состояние.
            new_state: Новое состояние.
            user_id: Пользователь из контекста Home Assistant.
            automation_id: Родительская автоматизация/сценарий.
            context: Контекст события.
            own_action: Изменение вызвано командой платформы.
            human_action: Человек уже опознан по пользователю или автоматизации.

        Returns:
            True, если физическое действие опознано и его нужно отдать автомату.
        """
        if own_action or human_action or automation_id:
            return False

        value = str(new_state).strip().lower()
        is_light = entity_id.startswith("light.") and (
            value in MANUAL_ON_VALUES or value in MANUAL_OFF_VALUES
        )
        is_climate_off = (
            entity_id.startswith("switch.")
            and value in MANUAL_OFF_VALUES
            and self._is_climate_actuator(entity_id)
        )
        if not (is_light or is_climate_off):
            return False

        kind = "света" if is_light else "обогревателя"
        logger.warning(
            f"HAAdapter: внешнее действие {kind} — {entity_id}, "
            f"user={user_id or '-'}, автоматизация=-, "
            f"context={context.get('ha_context_id')}, "
            f"своя команда этому прибору: "
            f"{'была' if self._is_recent_command(entity_id) else 'не найдена'}"
        )
        if self._manual_lockout_middleware:
            self._manual_lockout_middleware.record_manual_control(entity_id)
        return True

    def _is_climate_actuator(self, entity_id: str) -> bool:
        """Является ли переключатель исполнительным прибором климата.

        Физическое выключение обогревателя (розетка, выключатель) не оставляет
        в Home Assistant ни ``user_id``, ни ``parent_id``. Для климата это
        доказательство человека: автомат должен уйти в ручное состояние, иначе
        он останется в HEATING с выключенным прибором, а сторож будет считать
        это проблемой каждую минуту (живая находка 2026-11-08).

        Args:
            entity_id: Сущность, изменившая состояние.

        Returns:
            True, если у прибора есть автомат шаблона ``climate_control``.
        """
        get_fsms = getattr(self._engine, "get_entities_by_device", None)
        if not callable(get_fsms):
            return False
        try:
            automata = get_fsms(entity_id)
        except Exception as e:  # noqa: BLE001 — классификация не должна ронять приём
            logger.warning(f"HAAdapter: не удалось найти автоматы {entity_id}: {e}")
            return False
        return any("_climate_control_" in str(fsm) for fsm in automata)

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
