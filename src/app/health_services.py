"""Health-уведомления и проверка команд в composition root (спека 019).

Вынесено из `house_services`, чтобы контейнер не разрастался: здесь только
persistent-уведомление Home Assistant и минутная проверка ожиданий команд.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any


async def _no_notification(*args: Any, **kwargs: Any) -> bool:
    """Заглушка уведомления, если адаптер его не умеет.

    Args:
        *args: Параметры.
        **kwargs: Параметры.

    Returns:
        True.
    """
    del args, kwargs
    return True


async def _no_notification_dismiss(*args: Any, **kwargs: Any) -> bool:
    """Заглушка снятия уведомления.

    Args:
        *args: Параметры.
        **kwargs: Параметры.

    Returns:
        True.
    """
    del args, kwargs
    return True


class ContainerHealthMixin:
    """Persistent-уведомление и проверка неприменённых команд."""

    _health_notifier: Any
    adapter: Any
    manifest: Any
    command_expectations: Any
    problem_registry: Any

    def _observe_entity_state_change(self, entity_id: str, old_state: str, new_state: str) -> None:
        """Снять ожидание команды, если прибор уже показал нужное состояние.

        Событие приходит на каждое изменение в Home Assistant, в том числе для
        приборов без автоматов. Это закрывает ложное «команда не применена»,
        когда команда сработала, а потом прибор изменили снаружи.

        Args:
            entity_id: Сущность Home Assistant.
            old_state: Состояние до события.
            new_state: Состояние после события.

        Returns:
            Ничего.
        """
        self.command_expectations.observe_state(entity_id, old_state, new_state)

    if TYPE_CHECKING:

        def _device_names(self) -> dict[str, str]:
            """Имена приборов; реализация — в ContainerHouseMixin."""
            ...

        def _health_areas(self) -> dict[str, tuple[str, str]]:
            """Места приборов; реализация — в ContainerHouseMixin."""
            ...

    @property
    def health_notifier(self) -> Any:
        """Persistent-уведомление Home Assistant о проблемах дома.

        Returns:
            Уведомитель; создаётся один раз.
        """
        if self._health_notifier is None:
            from core.services.health_notifier import HealthNotifier

            adapter = self.adapter
            create = getattr(adapter, "create_persistent_notification", None)
            dismiss = getattr(adapter, "dismiss_persistent_notification", None)
            rules = getattr(self.manifest.automation_rules, "sensor_health", None)
            raw_repeat = getattr(rules, "notification_repeat_hours", 24.0)
            repeat_hours = float(raw_repeat) if isinstance(raw_repeat, (int, float)) else 24.0
            self._health_notifier = HealthNotifier(
                create=create or _no_notification,
                dismiss=dismiss or _no_notification_dismiss,
                registry=self.problem_registry,
                repeat_hours=repeat_hours,
            )
        return self._health_notifier

    async def _command_problems(self) -> list[dict[str, Any]]:
        """Проверить ожидания команд по фактическому состоянию приборов.

        Обход дома идёт раз в 15 минут, а команда должна быть замечена
        неприменённой за минуты. Здесь читаются только те приборы, по которым
        есть ожидание, — это дешевле полного обхода.

        Returns:
            Список проблем ``command_not_applied``.
        """
        tracker = self.command_expectations
        now = time.time()
        pending = tracker.pending(now)
        if not pending:
            return []
        reader = getattr(self.adapter, "get_entity_state", None)
        if not callable(reader):
            return []
        names = self._device_names()
        places = self._health_areas()
        rules = getattr(self.manifest.automation_rules, "sensor_health", None)
        raw_grace = getattr(rules, "command_grace_minutes", 5.0)
        grace = float(raw_grace) if isinstance(raw_grace, (int, float)) else 5.0
        problems: list[dict[str, Any]] = []
        for expectation in pending:
            if expectation.age_sec(now) < grace * 60.0:
                continue
            try:
                actual = await reader(expectation.device_id)
            except Exception:  # noqa: BLE001 — чтение прибора не роняет сводку
                actual = None
            if actual is None:
                # Прибор не прочитался — это не доказательство отказа.
                # Ожидание оставляем до следующего чтения или TTL.
                continue
            if tracker.is_applied(expectation, actual):
                tracker.clear(expectation.device_id)
                continue
            if tracker.is_transitional(actual):
                if str(actual).lower() in ("unavailable", "unknown"):
                    tracker.clear(expectation.device_id)
                continue
            area = (places.get(expectation.device_id) or ("", ""))[1]
            problems.append(
                tracker.problem(
                    expectation,
                    actual=actual,
                    area=area,
                    name=names.get(expectation.device_id, expectation.device_id),
                    now=now,
                )
            )
            # Ожидание остаётся: проблема живёт до смены состояния прибора
            # или до TTL, а не один цикл опроса.
        return problems
