"""Встроенные guard'ы, требуемые шаблонами поведений.

Шаг 0 варианта (а). До этого модуля в проекте не было ни одного зарегистрированного
guard'а, хотя `src/features/*.yaml` на них ссылаются. Проверки в движке
(`FSMEngine._evaluate_guard`) при отсутствии обработчика **отклоняют переход** и
пишут ошибку, то есть платформа выглядела исправной, но не переключала ничего.

Каждый guard — фабрика, возвращающая функцию ``(state, context) -> bool``.
Фабрика, а не обычная функция, потому что guard'ам нужны сервисы: трекер
ручного вмешательства и диапазон дня. Обычная функция не смогла бы их получить
из реестра, который хранит только функции.

Общий принцип — **отказ при нехватке данных**. Если нет значения датчика или
идентификатора устройства, переход запрещается: разрешить автоматику вслепую
хуже, чем не включить свет.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


logger = logging.getLogger(__name__)

#: Порог влажности по умолчанию. Зашит в именах guard'ов
#: (``humidity_above_60``), поэтому используется, когда параметр не задан.
DEFAULT_HUMIDITY_THRESHOLD = 60.0

#: Диапазон дня по умолчанию. Дополняет ночное расписание ``23:00-07:00``
#: из манифеста; переопределяется через ``DAY_TIME_RANGE``.
DEFAULT_DAY_TIME_RANGE = "07:00-23:00"


def _now_utc() -> datetime:
    """Текущее время в UTC."""
    return datetime.now(UTC)


def _resolve_house_tz() -> Any:
    """Часовой пояс дома.

     Условия, которые решают «светло ли сейчас» и «не ночь ли», обязаны считать
     время в часах дома, а не контейнера: контейнер живёт в UTC, дом — в своём
     поясе, и разница в пять часов открывала окно «день» с 02:00 до 04:00 по
     местному. Источник — ``HOUSE_TIMEZONE``, затем ``TZ``; если обоих нет,
     берётся локальное время с предупреждением, потому что молча угадывать не
    льзя: неверный пояс означает ночные включения.

     Returns:
         ``tzinfo`` для расчётов времени дома.
    """
    for name in ("HOUSE_TIMEZONE", "TZ"):
        value = os.environ.get(name)
        if not value:
            continue
        try:
            return ZoneInfo(value)
        except ZoneInfoNotFoundError:
            logger.warning(f"{name}={value!r} — неизвестный часовой пояс, беру следующий источник")
    logger.warning(
        "Часовой пояс дома не задан (HOUSE_TIMEZONE/TZ), беру локальное время "
        "контейнера: если дом в другом поясе, ночные правила считаются неверно"
    )
    return datetime.now().astimezone().tzinfo or UTC


#: Часовой пояс дома, разрешённый один раз при импорте.
HOUSE_TZ: Any = _resolve_house_tz()

#: Окно тишины по умолчанию: с этого часа движение не включает свет.
DEFAULT_QUIET_FROM = "23:00"

#: Границы дня для запасного решения, когда состояние солнца ещё неизвестно.
DEFAULT_DAY_START_MINUTES = 7 * 60
DEFAULT_DAY_END_MINUTES = 23 * 60

#: До этого часа (включительно) движение свет не включает.
DEFAULT_QUIET_TO = "06:30"


def _now_in(tz: Any) -> datetime:
    """Текущее время в указанном часовом поясе.

    Args:
        tz: Часовой пояс.

    Returns:
        Локальное время с зоной.
    """
    return datetime.now(tz)


def _parse_hhmm(value: str) -> tuple[int, int]:
    """Разобрать время ``HH:MM``.

    Args:
        value: Строка вида ``HH:MM``.

    Returns:
        Час и минута.

    Raises:
        ValueError: Строка не разобралась.
    """
    parts = value.strip().split(":")
    if len(parts) != 2:
        raise ValueError(f"Ожидалось HH:MM, получено {value!r}")
    hour, minute = int(parts[0]), int(parts[1])
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise ValueError(f"Время вне диапазона: {value!r}")
    return hour, minute


def _context_zone(context: dict[str, Any]) -> Any:
    """Часовой пояс для расчёта: из контекста, иначе часовой пояс дома.

    Args:
        context: Контекст перехода.

    Returns:
        ``tzinfo``.
    """
    value = context.get("time_zone")
    if isinstance(value, str) and value:
        try:
            return ZoneInfo(value)
        except ZoneInfoNotFoundError:
            logger.warning(f"time_zone={value!r} — неизвестный пояс, беру часовой пояс дома")
    return HOUSE_TZ


def _dark_enough(context: dict[str, Any], current: datetime) -> bool:
    """Темно ли так, что движение должно включать свет.

    Датчиков освещённости в доме нет, поэтому «темно» определяется по солнцу,
    которое Home Assistant публикует всегда (``sun.sun``), а состояние приходит в
    контексте события (``daylight``). Пока данных нет (платформа только поднялась
    и ещё не видела ни одного события от солнца), решение падает на время суток в
    часах дома: ночью — можно, днём — нельзя. Без этого движение днём включало бы
    свет там, где и так светло (жалоба владельца 2026-10-09).

    Args:
        context: Контекст перехода.
        current: Время, для которого считается решение.

    Returns:
        True, если темно.
    """
    daylight = context.get("daylight")
    if isinstance(daylight, bool):
        return not daylight
    minutes = current.hour * 60 + current.minute
    return not (DEFAULT_DAY_START_MINUTES <= minutes < DEFAULT_DAY_END_MINUTES)


def make_may_turn_on(
    *,
    now: Callable[[Any], datetime] = _now_in,
) -> Callable[[Any, dict[str, Any]], bool]:
    """Построить guard «сейчас можно включать свет».

    Отвечает сразу на два вопроса, которые шаблон задаёт каждым переходом по
    движению. Первый — прочь ли из ночи: внутри окна тишины движение не включает
    свет нигде, кроме перечисленных в ``night_motion_rooms`` комнат (санузел,
    контейнер): встать за водой ночью должно быть можно. Второй — темно ли
    настолько, что свет вообще нужен: при дневном свете включение бессмысленно, и
    владелец на это указал прямо (свет над столом зажигался среди дня).

    Темнота определяется по солнцу: датчиков освещённости в доме нет, а
    ``sun.sun`` Home Assistant публикует всегда, и его состояние приходит в
    контексте события (``daylight``). Пока данных нет — платформа только что
    поднялась и ещё не видела событий от солнца — решение падает на время суток в
    часах дома: ночью можно, днём нельзя.

    Время считается в часах дома (``time_zone`` из параметров поведения, иначе
    ``HOUSE_TIMEZONE``). Неизвестный пояс или неразобранное окно ведут к отказу:
    «непонятная ночь» не должна разрешать включать свет.

    Args:
        now: Источник времени; подменяется в тестах.

    Returns:
        Функция ``(state, context) -> bool``.
    """

    def may_turn_on(state: Any, context: dict[str, Any]) -> bool:
        """Разрешить переход, если момент допускает включение света.

        Args:
            state: Текущее состояние автомата.
            context: Контекст перехода.

        Returns:
            True, если включать можно.
        """
        del state  # состояние на решение не влияет: решает момент и комната

        current = now(_context_zone(context))
        quiet_from = str(context.get("quiet_from") or DEFAULT_QUIET_FROM)
        quiet_to = str(context.get("quiet_to") or DEFAULT_QUIET_TO)
        try:
            start = _parse_hhmm(quiet_from)
            end = _parse_hhmm(quiet_to)
        except ValueError:
            logger.error(f"Нераспознанное окно тишины {quiet_from}-{quiet_to}: свет не включаю")
            return False

        room = str(context.get("room") or "")
        night_rooms = {str(item) for item in context.get("night_motion_rooms") or ()}
        minutes = current.hour * 60 + current.minute
        start_minutes = start[0] * 60 + start[1]
        end_minutes = end[0] * 60 + end[1]
        in_quiet = (
            start_minutes <= minutes <= end_minutes
            if start_minutes <= end_minutes
            else minutes >= start_minutes or minutes <= end_minutes
        )

        if in_quiet:
            # Ночью свет нужен только в комнатах, которые владелец назвал ночными.
            return room in night_rooms
        return _dark_enough(context, current)

    def deny_reason(state: Any, context: dict[str, Any]) -> str | None:
        """Назвать причину отказа: «ночь» или «нечем объяснить».

        Args:
            state: Текущее состояние автомата.
            context: Контекст перехода.

        Returns:
            ``quiet_hours``, если отказ вызван ночным окном; иначе None.
        """
        del state
        try:
            start = _parse_hhmm(str(context.get("quiet_from") or DEFAULT_QUIET_FROM))
            end = _parse_hhmm(str(context.get("quiet_to") or DEFAULT_QUIET_TO))
        except ValueError:
            return None
        current = now(_context_zone(context))
        minutes = current.hour * 60 + current.minute
        start_minutes = start[0] * 60 + start[1]
        end_minutes = end[0] * 60 + end[1]
        in_quiet = (
            start_minutes <= minutes <= end_minutes
            if start_minutes <= end_minutes
            else minutes >= start_minutes or minutes <= end_minutes
        )
        return "quiet_hours" if in_quiet else None

    may_turn_on.deny_reason = deny_reason  # type: ignore[attr-defined]
    return may_turn_on


def make_is_day_time(
    day_range: str = DEFAULT_DAY_TIME_RANGE,
    *,
    now: Callable[[], datetime] | None = None,
) -> Callable[[Any, dict[str, Any]], bool]:
    """Построить guard «сейчас день».

    Шаблон освещения использует его для перехода в режим движения: ночью
    движение не должно включать яркий свет.

    Args:
        day_range: Диапазон дня ``HH:MM-HH:MM``. Диапазон через полночь
            (``22:00-06:00``) поддерживается.
        now: Источник времени; подменяется в тестах.

    Returns:
        Функцию ``(state, context) -> bool``.
    """
    clock = now or (lambda: _now_in(HOUSE_TZ))
    try:
        start_raw, end_raw = day_range.split("-")
        start = _parse_hhmm(start_raw)
        end = _parse_hhmm(end_raw)
    except ValueError as exc:
        # Ошибка конфигурации обязана вести к отказу: «непонятный день» не
        # должен разрешать включать свет ночью.
        logger.error(f"Некорректный диапазон дня {day_range!r}: {exc}")

        def always_denied(state: Any, context: dict[str, Any]) -> bool:
            return False

        return always_denied

    def is_day_time(state: Any, context: dict[str, Any]) -> bool:
        """Разрешить переход, если текущее время входит в диапазон дня."""
        current = clock()
        minutes = current.hour * 60 + current.minute
        start_minutes = start[0] * 60 + start[1]
        end_minutes = end[0] * 60 + end[1]

        if start_minutes <= end_minutes:
            return start_minutes <= minutes <= end_minutes
        return minutes >= start_minutes or minutes <= end_minutes

    return is_day_time


def _humidity_value(context: dict[str, Any]) -> float | None:
    """Прочитать влажность из контекста.

    Args:
        context: Контекст перехода.

    Returns:
        Значение влажности либо ``None``, если его нет или оно не число.
    """
    raw = context.get("humidity")
    if raw is None:
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        logger.warning(f"Влажность не число: {raw!r}")
        return None


def _threshold(context: dict[str, Any]) -> float:
    """Порог из параметров поведения, иначе значение по умолчанию.

    Имя guard'а содержит ``60``, но манифест задаёт ``humidity_threshold``
    (в ``leonids_house`` это 65). Параметр поведения важнее имени: иначе
    настройка в интерфейсе молча не влияла бы на поведение.
    """
    raw = context.get("humidity_threshold")
    if raw is None:
        return DEFAULT_HUMIDITY_THRESHOLD
    try:
        return float(raw)
    except (TypeError, ValueError):
        logger.warning(f"Порог влажности не число: {raw!r}, беру {DEFAULT_HUMIDITY_THRESHOLD}")
        return DEFAULT_HUMIDITY_THRESHOLD


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


def make_is_manual_override_enabled(
    control_tracker: Any,
    *,
    lockout_minutes: int = 60,
) -> Callable[[Any, dict[str, Any]], bool]:
    """Построить guard «автоматике можно вмешиваться».

    После ручного управления устройством (`ControlTracker`) автоматика обязана
    уступить на время блокировки, иначе она немедленно вернёт устройство в
    режим автоматики и человек не сможет им пользоваться.

    Args:
        control_tracker: Трекер ручного вмешательства с методом
            ``was_manual_within(device_id, minutes)``.
        lockout_minutes: Длительность блокировки в минутах.

    Returns:
        Функцию ``(state, context) -> bool``.
    """

    def is_manual_override_enabled(state: Any, context: dict[str, Any]) -> bool:
        """Разрешить переход, если ручного вмешательства не было недавно."""
        device_id = (
            context.get("target_device_id") or context.get("entity_id") or context.get("device_id")
        )
        if not device_id:
            logger.warning("is_manual_override_enabled: нет entity_id в контексте")
            return False

        try:
            in_lockout = bool(control_tracker.was_manual_within(device_id, lockout_minutes))
        except Exception as exc:  # noqa: BLE001 - причина попадает в журнал
            logger.warning(f"Проверка блокировки не удалась для {device_id}: {exc}")
            return False

        return not in_lockout

    return is_manual_override_enabled


#: Имена guard'ов, которым нужны данные датчиков, и сами данные. Ключ — имя
#: условия, значение — ключи контекста перехода, без которых решение выносить
#: не по чему, и отказ должен называться «данных нет», а не «значение не подходит».
GUARD_DATA_REQUIREMENTS: dict[str, tuple[str, ...]] = {
    "humidity_above_60": ("humidity",),
    "humidity_below_60": ("humidity",),
}


def with_requirements(
    guard_fn: Callable[[Any, dict[str, Any]], bool],
    *requires: str,
) -> Callable[[Any, dict[str, Any]], bool]:
    """Пометить условие как требующее данные из контекста перехода.

    Требование едет вместе с функцией, а не хранится отдельно: фабрика подставляет
    в переход **вызов** условия, а не его имя, и отдельная таблица «имя → данные»
    разошлась бы с тем, что реально вызывается. Подпись условия при этом не
    меняется — это по-прежнему функция «да/нет».

    Args:
        guard_fn: Функция условия.
        *requires: Ключи контекста, без которых условие не может решить.

    Returns:
        Та же функция с атрибутом ``requires``.
    """
    # Промежуточная переменная типизируется как Any: условие остаётся функцией
    # «да/нет», а атрибут требований — её свойством. Через setattr ruff возвращает
    # прямую присваивание, а через прямую присваивание mypy требует знать об
    # атрибуте у произвольной функции; здесь не спорит ни один из них.
    guarded: Any = guard_fn
    guarded.requires = tuple(requires)
    return guarded


def build_guards(
    control_tracker: Any,
    *,
    day_range: str = DEFAULT_DAY_TIME_RANGE,
    lockout_minutes: int = 60,
) -> dict[str, Callable[[Any, dict[str, Any]], bool]]:
    """Собрать все встроенные guard'ы для реестра.

    Args:
        control_tracker: Трекер ручного вмешательства.
        day_range: Диапазон дня для ``is_day_time``.
        lockout_minutes: Блокировка после ручного управления.

    Returns:
        Словарь «имя guard'а → функция». Имена совпадают с теми, что указаны в
        шаблонах ``src/features/*.yaml``.
    """
    guards: dict[str, Callable[[Any, dict[str, Any]], bool]] = {
        "is_day_time": make_is_day_time(day_range),
        "is_manual_override_enabled": make_is_manual_override_enabled(
            control_tracker, lockout_minutes=lockout_minutes
        ),
        "humidity_above_60": make_humidity_above(),
        "humidity_below_60": make_humidity_below(),
        "may_turn_on": make_may_turn_on(),
    }
    # Требования объявляются здесь, рядом с условием: объявление в стороне
    # разошлось бы с ним при первом же переименовании.
    for name, requires in GUARD_DATA_REQUIREMENTS.items():
        guard = guards.get(name)
        if guard is not None:
            with_requirements(guard, *requires)
    return guards


#: Имена guard'ов, которые должны существовать в реестре движка.
#: Используется проверкой целостности: сверка с шаблонами по имени.
REGISTERED_GUARDS = (
    "is_day_time",
    "is_manual_override_enabled",
    "may_turn_on",
    "humidity_above_60",
    "humidity_below_60",
)


def register_all_guards(registry: Any, control_tracker: Any) -> None:
    """Зарегистрировать встроенные guard'ы в реестре.

    Args:
        registry: Реестр движка.
        control_tracker: Трекер ручного вмешательства.
    """
    import os

    guards = build_guards(
        control_tracker,
        day_range=os.environ.get("DAY_TIME_RANGE", DEFAULT_DAY_TIME_RANGE),
    )
    for name, guard in guards.items():
        registry.register_guard(name, guard)
    logger.info(f"Registered {len(guards)} guards: {', '.join(sorted(guards))}")
