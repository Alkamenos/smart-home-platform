"""Условия климата: нагрев, охлаждение, влажность (B80).

Вынесено из `builtin.py`. Защита техники (мороз, дренаж) и комфорт живут
рядом: их правят вместе.
"""

import logging
from collections.abc import Callable
from typing import Any

from core.guards.context import (
    _comfort_max_value as _comfort_max_value,
    _humidity_value as _humidity_value,
    _hysteresis_value as _hysteresis_value,
    _setpoint_value as _setpoint_value,
    _temperature_value as _temperature_value,
    _threshold as _threshold,
)


logger = logging.getLogger(__name__)


def make_humidity_above() -> Callable[[Any, dict[str, Any]], bool]:
    """Построить guard «влажность выше порога» (``humidity_above_60``)."""

    def humidity_above(state: Any, context: dict[str, Any]) -> bool:
        """Разрешить переход, только если влажность известна и выше порога."""
        humidity = _humidity_value(context)
        if humidity is None:
            return False
        return humidity > _threshold(context)

    return humidity_above


def make_humidity_below() -> Callable[[Any, dict[str, Any]], bool]:
    """Построить guard «влажность ниже порога» (``humidity_below_60``)."""

    def humidity_below(state: Any, context: dict[str, Any]) -> bool:
        """Разрешить переход, только если влажность известна и ниже порога."""
        humidity = _humidity_value(context)
        if humidity is None:
            return False
        return humidity < _threshold(context)

    return humidity_below


def _colder_than_setpoint(context: dict[str, Any]) -> bool | None:
    """Холоднее ли в комнате, чем целевая температура, с учётом гистерезиса.

    Args:
        context: Контекст перехода.

    Returns:
        True, если обогревать нужно; False, если не нужно; ``None``, если
        решения принимать не на чем — нет показания или уставки.
    """
    temperature = _temperature_value(context)
    setpoint, usable = _setpoint_value(context)
    if temperature is None or not usable or setpoint is None:
        return None
    return temperature < setpoint - _hysteresis_value(context)


def make_below_setpoint() -> Callable[[Any, dict[str, Any]], bool]:
    """Построить условие «в комнате холоднее цели — обогреватель нужен».

    Сравнивает показание датчика комнаты с целевой температурой дома за вычетом
    гистерезиса. Гистерезис обязателен не для красоты: без него обогреватель
    включается и выключается на границе цели, и датчик, шлющий показания часто,
    заставит его работать впустую.

    Args:
        Ничего.

    Returns:
        Функция ``(state, context) -> bool`` с ``deny_reason``.
    """

    def below_setpoint(state: Any, context: dict[str, Any]) -> bool:
        """Разрешить переход, если в комнате холоднее цели.

        Args:
            state: Текущее состояние автомата.
            context: Контекст перехода.

        Returns:
            True, если обогревать нужно.
        """
        del state  # состояние на решение не влияет: решают датчик и уставка
        return _colder_than_setpoint(context) is True

    def deny_reason(state: Any, context: dict[str, Any]) -> str | None:
        """Назвать причину отказа: «данных нет» или «уставка негодна».

        Args:
            state: Текущее состояние автомата.
            context: Контекст перехода.

        Returns:
            ``setpoint_unavailable``, если уставка прочитана, но вне диапазона;
            ``guard_data_missing``, если не хватает показания или уставки;
            иначе None (решение «не греть» причины не требует — оно не отказ).
        """
        del state
        raw = context.get("climate_setpoint")
        if raw is not None and not isinstance(raw, bool):
            _, usable = _setpoint_value(context)
            if not usable:
                return "setpoint_unavailable"
        return "guard_data_missing" if _colder_than_setpoint(context) is None else None

    below_setpoint.deny_reason = deny_reason  # type: ignore[attr-defined]
    return below_setpoint


def make_at_or_above_setpoint() -> Callable[[Any, dict[str, Any]], bool]:
    """Построить условие «цель достигнута — обогреватель можно выключать».

    Зеркало условия включения с одной важной разницей: обогреватель выключается
    **сразу** при достижении цели, без гистерезиса. Держать его включённым
    ещё полградуса — значит перегревать комнату, которая уже достаточно тёплая.

    Args:
        Ничего.

    Returns:
        Функция ``(state, context) -> bool`` с ``deny_reason``.
    """

    def at_or_above_setpoint(state: Any, context: dict[str, Any]) -> bool:
        """Разрешить переход, если комната не холоднее цели.

        Args:
            state: Текущее состояние автомата.
            context: Контекст перехода.

        Returns:
            True, если цель достигнута.
        """
        del state
        colder = _colder_than_setpoint(context)
        return colder is False

    def deny_reason(state: Any, context: dict[str, Any]) -> str | None:
        """Назвать причину отказа: данных не хватает либо обогревать нужно.

        Args:
            state: Текущее состояние автомата.
            context: Контекст перехода.

        Returns:
            ``guard_data_missing`` при отсутствии данных; ``None`` в остальных
            случаях — в том числе когда обогревать ещё нужно: это не отказ, а
            штатная работа условия.
        """
        del state
        return "guard_data_missing" if _colder_than_setpoint(context) is None else None

    at_or_above_setpoint.deny_reason = deny_reason  # type: ignore[attr-defined]
    return at_or_above_setpoint


def make_climate_is_enabled() -> Callable[[Any, dict[str, Any]], bool]:
    """Построить условие «климат не выключен владельцем».

    Фиче-флаг ``input_boolean.feature_climate`` — это право владельца остановить
    климат одной кнопкой, не трогая конфигурацию платформы (FR-013). Отсутствие
    флага в доме — **не** отказ: в таких домах климат просто работает, иначе
    фича молча выключалась бы везде, где флаг не настроен.

    Args:
        Ничего.

    Returns:
        Функция ``(state, context) -> bool`` с ``deny_reason``.
    """

    def climate_is_enabled(state: Any, context: dict[str, Any]) -> bool:
        """Разрешить переход, если владелец не выключил климат.

        Args:
            state: Текущее состояние автомата.
            context: Контекст перехода.

        Returns:
            True, если климат включён.
        """
        del state
        enabled = context.get("climate_enabled")
        return True if enabled is None else bool(enabled)

    def deny_reason(state: Any, context: dict[str, Any]) -> str | None:
        """Назвать причину отказа: климат выключен владельцем.

        Args:
            state: Текущее состояние автомата.
            context: Контекст перехода.

        Returns:
            ``climate_disabled`` при выключенном флаге; иначе None.
        """
        del state
        return None if context.get("climate_enabled") is not False else "climate_disabled"

    climate_is_enabled.deny_reason = deny_reason  # type: ignore[attr-defined]
    return climate_is_enabled


def make_managed_by_hardware_ok() -> Callable[[Any, dict[str, Any]], bool]:
    """Построить условие «в комнате нет штатного термостата».

    В гостиной стоит аппаратный термостат, который сам держит температуру и
    управляет тёплым полом. Платформа, включившая там свой обогреватель, создала
    бы в одной комнате два регулятора, а они будут бороться: термостат греет по
    своей уставке, обогреватель — по платформенной (FR-007).

    Args:
        Ничего.

    Returns:
        Функция ``(state, context) -> bool`` с ``deny_reason``.
    """

    def managed_by_hardware_ok(state: Any, context: dict[str, Any]) -> bool:
        """Разрешить переход, если комната не отдана штатному термостату.

        Args:
            state: Текущее состояние автомата.
            context: Контекст перехода.

        Returns:
            True, если комнатой управляет платформа.
        """
        del state
        return context.get("managed_by_hardware") is not True

    def deny_reason(state: Any, context: dict[str, Any]) -> str | None:
        """Назвать причину отказа: комнатой управляет термостат.

        Args:
            state: Текущее состояние автомата.
            context: Контекст перехода.

        Returns:
            ``managed_by_hardware`` для комнат с термостатом; иначе None.
        """
        del state
        return None if context.get("managed_by_hardware") is not True else "managed_by_hardware"

    managed_by_hardware_ok.deny_reason = deny_reason  # type: ignore[attr-defined]
    return managed_by_hardware_ok


def make_may_dry() -> Callable[[Any, dict[str, Any]], bool]:
    """Построить условие «осушение разрешено».

    Осушение и охлаждение — одно решение на комнату: у кондиционера общий
    режим, и оба автомата, дергающие его попеременно, выглядели бы как поломка
    (FR-017). Поэтому осушение разрешено, когда охлаждение не требуется: если
    комната выше потолка комфорта, работает компрессор, а не вентилятор.
    """

    def may_dry(state: Any, context: dict[str, Any]) -> bool:
        """Разрешить, если осушать есть смысл и можно.

        Args:
            state: Текущее состояние автомата.
            context: Контекст перехода.

        Returns:
            True, если осушение разрешено.
        """
        del state
        if not _cooling_applicable(context):
            return False
        return _drying_denial(context) is None

    def deny_reason(state: Any, context: dict[str, Any]) -> str | None:
        """Назвать причину отказа.

        Args:
            state: Текущее состояние автомата.
            context: Контекст перехода.

        Returns:
            Имя причины либо ``None``.
        """
        del state
        if not _cooling_applicable(context):
            return "not_applicable"
        return _drying_denial(context)

    may_dry.deny_reason = deny_reason  # type: ignore[attr-defined]
    return may_dry


def _cooling_applicable(context: dict[str, Any]) -> bool:
    """Относится ли охлаждение к этому прибору.

    Обогреватель не охлаждает: переход «включить кондиционер» к нему не
    относится, и это не отказ решения. Признак берётся из манифеста — параметр
    поведения `cooling` объявляет кондиционер; без него прибор считается
    обогревателем (B66).

    Args:
        context: Контекст перехода.

    Returns:
        True, если прибор умеет охлаждать.
    """
    return context.get("cooling") is True


def _drying_denial(context: dict[str, Any]) -> str | None:
    """Первая по порядку причина, по которой осушать нельзя.

    Args:
        context: Контекст перехода.

    Returns:
        Имя причины либо ``None``, если осушение разрешено.
    """
    # Гейт владельца — его **явный** запрет, а не отсутствие поля: когда гейта в
    # манифесте нет вовсе (убрали 2026-10-15 как «вообще не то»), охлаждение не
    # запрещается. Технику защищают мороз и сезон — они по-прежнему строги.
    if context.get("ac_allowed") is False:
        return "ac_not_allowed"
    if context.get("is_winter") is not False:
        return "ac_forbidden_in_winter"
    if context.get("managed_by_hardware") is True:
        return "managed_by_hardware"
    if _humidity_value(context) is None:
        return "guard_data_missing"
    # Охлаждение приоритетнее: комната выше потолка — работает компрессор, а не
    # вентилятор, иначе оба режима включатся в одной комнате сразу.
    if _cooling_denial(context) is None:
        return "not_above_comfort"
    return None


def make_may_cool() -> Callable[[Any, dict[str, Any]], bool]:
    """Построить условие «кондиционер можно включать».

    Проверки идут по цене ошибки, и порядок здесь не декоративен: гейт
    владельца важнее сезона, а сезон важнее замера. В самую холодную погоду
    кондиционер включился бы там, где владелец его запретил, если бы порядок был
    обратным.

    Неизвестное значение запрещает, а не разрешает. Для сезона это значит, что
    непрочитанный ``zima`` не равен «не зима»: единственная цена ошибки — порча
    техники зимой, противоположная цена — лишний день электричества летом.
    """

    def may_cool(state: Any, context: dict[str, Any]) -> bool:
        """Разрешить переход, если охлаждать есть смысл и можно.

        Args:
            state: Текущее состояние автомата.
            context: Контекст перехода.

        Returns:
            True, если кондиционер можно включать.
        """
        del state
        if not _cooling_applicable(context):
            return False
        return _cooling_denial(context) is None

    def deny_reason(state: Any, context: dict[str, Any]) -> str | None:
        """Назвать причину отказа — первую по порядку проверок.

        Args:
            state: Текущее состояние автомата.
            context: Контекст перехода.

        Returns:
            Имя причины либо ``None``, когда охлаждать можно.
        """
        del state
        if not _cooling_applicable(context):
            return "not_applicable"
        return _cooling_denial(context)

    may_cool.deny_reason = deny_reason  # type: ignore[attr-defined]
    return may_cool


def _cooling_denial(context: dict[str, Any]) -> str | None:
    """Первая по порядку причина, по которой охлаждать нельзя.

    Args:
        context: Контекст перехода.

    Returns:
        Имя причины либо ``None``, если охлаждение разрешено.
    """
    # Гейт владельца — его **явный** запрет, а не отсутствие поля: когда гейта в
    # манифесте нет вовсе (убрали 2026-10-15 как «вообще не то»), охлаждение не
    # запрещается. Технику защищают мороз и сезон — они по-прежнему строги.
    if context.get("ac_allowed") is False:
        return "ac_not_allowed"
    if context.get("is_winter") is not False:
        return "ac_forbidden_in_winter"
    # Комната со штатным термостатом: он уже решает про температуру, и
    # кондиционер рядом с ним — два источника в одной комнате (FR-018).
    if context.get("managed_by_hardware") is True:
        return "managed_by_hardware"

    comfort_max = _comfort_max_value(context)
    if comfort_max is None:
        return "guard_data_missing"
    temperature = _temperature_value(context)
    if temperature is None:
        return "guard_data_missing"

    if temperature <= comfort_max:
        return "not_above_comfort"
    return None


def make_may_heat() -> Callable[[Any, dict[str, Any]], bool]:
    """Построить условие «в этой комнате обогреватель нужен и им можно греть».

    Одно условие вместо трёх — не уплотнение, а требование движка: на переход
    допускается ровно одно имя условия (`YAMLTransition.guard`, строка), а
    менять это — значит менять структуру FSMDefinition, что конституция I
    разрешает только по явному согласованию. Значит, объединять решения должен
    сам модуль условий.

    Проверки идут по цене ошибки, и порядок не декоративен: право владельца
    (выключил климат) важнее того, что комната чуть-чуть не хватает до цели,
    а «в комнате свой термостат» важнее замера — платформа не должна дергать
    обогреватель там, где решение принимает штатное устройство. Первое же
    невыполненное условие и называет причину: утром в журнале видно, что
    мешало, а не «условие не прошло».
    """

    def may_heat(state: Any, context: dict[str, Any]) -> bool:
        """Разрешить переход, если обогревать нужно и это допустимо.

        Args:
            state: Текущее состояние автомата.
            context: Контекст перехода.

        Returns:
            True, если обогреватель можно включать.
        """
        del state
        return _heating_denial(context) is None

    def deny_reason(state: Any, context: dict[str, Any]) -> str | None:
        """Назвать причину отказа — первую по порядку проверок.

        Args:
            state: Текущее состояние автомата.
            context: Контекст перехода.

        Returns:
            Имя причины отказа либо ``None``, когда греть можно.
        """
        del state
        return _heating_denial(context)

    may_heat.deny_reason = deny_reason  # type: ignore[attr-defined]
    return may_heat


def _heating_denial(context: dict[str, Any]) -> str | None:
    """Первая по порядку причина, по которой греть нельзя.

    Args:
        context: Контекст перехода.

    Returns:
        Имя причины либо ``None``, если обогревать можно.
    """
    enabled = context.get("climate_enabled")
    if enabled is False:
        return "climate_disabled"
    if context.get("managed_by_hardware") is True:
        return "managed_by_hardware"

    colder = _colder_than_setpoint(context)
    if colder is None:
        raw = context.get("climate_setpoint")
        if raw is not None and not isinstance(raw, bool):
            _, usable = _setpoint_value(context)
            if not usable:
                return "setpoint_unavailable"
        return "guard_data_missing"
    return None if colder else "not_cold_enough"


def _not_cold_enough_reason(_state: Any, context: dict[str, Any]) -> str | None:
    """Причина, по которой переход к обогреву не нужен: «и так достаточно тепло».

    Это не поломка и не запрет владельца: комната в порядке, и движок запишет
    это как `guard_failed`. Называть причину здесь незачем — называть нечего,
    а выдуманное имя в журнале вводило бы в заблуждение при утреннем разборе.

    Args:
        state: Текущее состояние автомата.
        context: Контекст перехода.

    Returns:
        Всегда ``None``.
    """
    del _state, context
    return None


def make_may_stop_heating() -> Callable[[Any, dict[str, Any]], bool]:
    """Построить условие «цель достигнута — обогреватель можно выключать».

    Зеркало `may_heat` со стороны выключения: комната не холоднее цели и климат
    не запрещён. Проверка «климат выключен» здесь лишняя — выключать обогреватель
    не вредно даже тогда, когда владелец отключил климат, — но оставлена ради
    симметрии: решение «выключить» принимается по тем же данным, что и «включить».
    """

    def may_stop_heating(state: Any, context: dict[str, Any]) -> bool:
        """Разрешить выключение, если цель достигнута.

        Args:
            state: Текущее состояние автомата.
            context: Контекст перехода.

        Returns:
            True, если обогреватель пора выключать.
        """
        del state
        return _colder_than_setpoint(context) is False

    may_stop_heating.deny_reason = _not_cold_enough_reason  # type: ignore[attr-defined]
    return may_stop_heating
