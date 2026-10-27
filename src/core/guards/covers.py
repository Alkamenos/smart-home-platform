"""Условия штор: закрыть к ночи, открыть утром (B80).

Вынесено из `builtin.py`: шторы задают вопрос «пора ли», а не «как управлять».
"""

import logging
from collections.abc import Callable
from typing import Any


logger = logging.getLogger(__name__)

#: Флаги дома, от которых зависит решение штор. Ручное положение в `MANUAL`
#: держится, пока ни один из них не сменился (B104).
COVER_FLAGS = (
    "my_doma",
    "sobaki_doma",
    "covers_close_night",
    "cover_emergency",
    "covers_enabled",
    "sleep_modifier_on",
)


def _manual_flags_changed(state: Any, context: dict[str, Any]) -> bool:
    """Сменились ли флаги дома с момента ручного движения шторы.

    В ручном состоянии `MANUAL` штора стоит там, где её оставил человек:
    обычные `settings_changed` (температура, вентиляция и прочее) не должны
    её двигать. Решение снова действует только когда изменился хотя бы один
    флаг, от которого это решение зависит.

    Args:
        state: Текущее состояние автомата (у него есть контекст с прежними
            значениями флагов).
        context: Контекст перехода с текущими значениями.

    Returns:
        True, если флаги сменились или состояние не ручное.
    """
    current = str(getattr(state, "current_state", "")).upper()
    if current != "MANUAL":
        return True
    previous = getattr(state, "context", None) or {}
    return any(previous.get(key) != context.get(key) for key in COVER_FLAGS)


def _cover_close_reason(context: dict[str, Any]) -> str | None:
    """Почему штора не должна закрываться сейчас (спека 015).

    Правила владельца, и каждое обязано быть названо: утренний разбор по одной
    записи должен отличать «не спим», «штора над дверью при людях», «ночью
    закрывать не разрешено» и «дома собаки — эта комната не закрывается», а не
    видеть одинаковое ``guard_failed``.

    Args:
        context: Контекст перехода.

    Returns:
        Имя причины отказа либо ``None``, если закрываться пора.
    """
    # Аварийный флаг старше всего: он открывает шторы, игнорируя остальные
    # правила, — даже выключенный фиче-флаг дома его не отменяет.
    if context.get("cover_emergency") is True:
        return "cover_emergency"
    if context.get("covers_enabled") is False:
        return "covers_disabled"
    my_doma = context.get("my_doma")
    if my_doma is False:
        # Людей нет. Собак нет (или неизвестно) — закрывается всё, включая
        # штору над дверью; собаки дома — только спальня и кабинет.
        if context.get("sobaki_doma") is not True:
            return None
        if context.get("closes_when_dogs_only") is True:
            return None
        return "covers_dogs_only"
    # Кто-то дома (или признак неизвестен — считаем, что люди есть: так
    # безопаснее, двери не запирает).
    if context.get("cover_role") == "door":
        # Пожарная безопасность: закрытая штора над дверью мешает выходу.
        return "cover_fire_safety"
    if context.get("sleep_modifier_on") is not True:
        return "covers_stay_open"
    if context.get("covers_close_night") is not True:
        return "covers_night_close_off"
    return None


def make_covers_should_close() -> Callable[[Any, dict[str, Any]], bool]:
    """Построить условие «штору пора закрыть».

    Шторы решаются только флагами дома: спим ли, кто-то ли дома, дома ли собаки,
    разрешено ли закрывать ночью. Физику шторы не считают, поэтому решение —
    «закрыть или не закрыть», а само движение делает прибор.

    Returns:
        Функция ``(state, context) -> bool`` с ``deny_reason``.
    """

    def covers_should_close(state: Any, context: dict[str, Any]) -> bool:
        """Проверить, должна ли штора быть закрыта.

        Args:
            state: Состояние автомата; в `MANUAL` помнит прежние флаги.
            context: Контекст перехода.

        Returns:
            True, если штору пора закрыть.
        """
        if not _manual_flags_changed(state, context):
            return False
        return _cover_close_reason(context) is None

    def deny_reason(state: Any, context: dict[str, Any]) -> str | None:
        """Назвать причину, по которой штора не закрывается.

        Args:
            state: Состояние автомата.
            context: Контекст перехода.

        Returns:
            Имя причины либо ``None``.
        """
        if not _manual_flags_changed(state, context):
            return "manual_position"
        return _cover_close_reason(context)

    covers_should_close.deny_reason = deny_reason  # type: ignore[attr-defined]
    return covers_should_close


def make_covers_should_open() -> Callable[[Any, dict[str, Any]], bool]:
    """Построить условие «штору пора открыть».

    Открыть — либо аварийный случай (открыть всё, игнорируя остальные правила),
    либо обычное «закрываться не нужно». Штора над дверью открыта всегда, пока
    кто-то дома: закрытой её держит только правило по уставке-отсутствию людей.

    Returns:
        Функция ``(state, context) -> bool`` с ``deny_reason``.
    """

    def covers_should_open(state: Any, context: dict[str, Any]) -> bool:
        """Проверить, должна ли штора быть открыта.

        Args:
            state: Состояние автомата; в `MANUAL` помнит прежние флаги.
            context: Контекст перехода.

        Returns:
            True, если штору пора открыть.
        """
        if not _manual_flags_changed(state, context):
            return False
        if context.get("cover_emergency") is True:
            return True
        if context.get("covers_enabled") is False:
            return False
        return _cover_close_reason(context) is not None

    def deny_reason(state: Any, context: dict[str, Any]) -> str | None:
        """Назвать причину, по которой штора не открывается.

        Args:
            state: Состояние автомата.
            context: Контекст перехода.

        Returns:
            Имя причины либо ``None``.
        """
        if not _manual_flags_changed(state, context):
            return "manual_position"
        if context.get("cover_emergency") is True:
            return None
        if context.get("covers_enabled") is False:
            return "covers_disabled"
        return "covers_stay_closed"

    covers_should_open.deny_reason = deny_reason  # type: ignore[attr-defined]
    return covers_should_open
