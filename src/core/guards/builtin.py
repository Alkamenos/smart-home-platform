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
    движению. Первый — спим ли: пока модификатор «мы спим» включён (сущность
    Home Assistant, которую владелец включает своей автоматизацией), яркий свет
    не включается нигде — ночной свет сбивает циркадные ритмы (требование
    владельца 2026-10-09; до этого санузел светил в полную яркость ночью).

    Ночью (окно ``quiet_from``–``quiet_to``) при **известном** модификаторе
    решает только он: True — запрет, False — включение по движению разрешено,
    если темно. Список ``night_motion_rooms`` и окно тишины остаются фолбэком
    на случай, когда сущности в доме нет (``sleep_modifier_on is None``):
    пропавшая в HA сущность не должна молча погасить свет в доме. Решение
    владельца 2026-10-09: «свет по движению всегда, кроме периода мы спим» —
    ночью привязка идёт к модификатору, а не к часам платформы.

    Второй вопрос — темно ли настолько, что свет вообще нужен: при дневном
    свете включение бессмысленно, и владелец на это указал прямо (свет над
    столом зажигался среди дня).

    Темнота определяется по солнцу: датчиков освещённости в доме нет, а
    ``sun.sun`` Home Assistant публикует всегда, и его состояние приходит в
    контексте события (``daylight``). Пока данных нет — платформа только что
    поднялась и ещё не видела событий от солнца — решение падает на время суток в
    часах дома: ночью можно, днём нельзя.

    Отсутствие модификатора — не признак сна: если сущности нет или её
    состояние неизвестно (``sleep_modifier_on is None``), решение принимают
    солнце и окно тишины, как раньше. Иначе пропавшая в HA сущность молча
    погасила бы свет в доме, и никто не понял бы почему.

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

        # «Мы спим» — запрет первым и выше прочих: пока владелец держит
        # модификатор включённым, яркий свет не включается ни в одной комнате,
        # включая ночные (санузел иначе светит в полную яркость, когда все спят —
        # и сбивает циркадные ритмы). Состояние приходит из Home Assistant;
        # None — сущности нет или её состояние ещё не прочитано, тогда проходят
        # ниже, к солнцу и окну тишины.
        modifier = context.get("sleep_modifier_on")
        if modifier is True:
            return False

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

        # Комната без окон. Солнце над горизонтом освещает только те комнаты,
        # где есть окно: в санузле и контейнере днём ровно так же темно, как и
        # ночью, и единственный свет там — электрический. Отказ по «светло» в
        # таких комнатах означал, что датчик движения срабатывал, а свет не
        # включался (боевой дефект 2026-10-10, отказ `daylight` в санузле).
        # Поэтому солнце здесь не спрашивается вовсе.
        always_rooms = {str(item) for item in context.get("always_on_motion_rooms") or ()}
        if room in always_rooms:
            return True

        minutes = current.hour * 60 + current.minute
        start_minutes = start[0] * 60 + start[1]
        end_minutes = end[0] * 60 + end[1]
        in_quiet = (
            start_minutes <= minutes <= end_minutes
            if start_minutes <= end_minutes
            else minutes >= start_minutes or minutes <= end_minutes
        )

        if in_quiet:
            # Ночью при известном модификаторе решает только он: False —
            # владелец не спит, и движение включает свет, если темно (по
            # правилу владельца «свет по движению всегда, кроме периода мы
            # спим»). Окно тишины спрашивается, только когда сущности в доме
            # нет: тогда ночь уходит в ночные комнаты, как раньше.
            if modifier is False:
                return _dark_enough(context, current)
            return room in night_rooms
        return _dark_enough(context, current)

    def deny_reason(state: Any, context: dict[str, Any]) -> str | None:
        """Назвать причину отказа: «мы спим», «ночь», «светло» или «нечем объяснить».

        Причины держатся раздельно (``sleep_modifier`` против ``quiet_hours``
        против ``daylight``): ночное окно платформа считает сама, модификатор
        включает владелец в Home Assistant, а светло — штатное решение солнца.
        В журнале утра они означают разные вещи: «спим» — «я включил флаг»,
        «ночь» — «расписание сработало», «светло» — «датчиков нет, решает
        солнце». Имя должно совпадать с константой из ``core.events.fsm_events``:
        словарь причин узкий, и «свой» словарь здесь означал бы молчаливый
        откат в ``guard_failed`` (проверяется тестом).

        Args:
            state: Текущее состояние автомата.
            context: Контекст перехода.

        Returns:
            ``sleep_modifier`` при активном модификаторе, ``quiet_hours`` внутри
            ночного окна без сущности модификатора, ``daylight``, если светло;
            иначе None.
        """
        del state
        modifier = context.get("sleep_modifier_on")
        if modifier is True:
            return "sleep_modifier"
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
        if in_quiet and modifier is not False:
            # Ночное окно — фолбэк, когда сущности модификатора в доме нет:
            # отказывает список ночных комнат. При известном False отказывает
            # только свет, и ниже.
            room = str(context.get("room") or "")
            night_rooms = {str(item) for item in context.get("night_motion_rooms") or ()}
            always_rooms = {str(item) for item in context.get("always_on_motion_rooms") or ()}
            if room not in night_rooms and room not in always_rooms:
                return "quiet_hours"
        room = str(context.get("room") or "")
        if room in {str(item) for item in context.get("always_on_motion_rooms") or ()}:
            # Комната без окон: солнце не влияет, отказано быть не может.
            return None
        if not _dark_enough(context, current):
            return "daylight"
        return None

    may_turn_on.deny_reason = deny_reason  # type: ignore[attr-defined]
    return may_turn_on


def make_modifier_is_on() -> Callable[[Any, dict[str, Any]], bool]:
    """Построить guard «модификатор „мы спим“ включён» — условие ночника.

    Пока владелец держит модификатор включённым, свет над столом работает
    ночником: 3% яркости, красный, по движению (требование 2026-10-09). Как
    только модификатор выключен, ночник не включается — дальше действует
    обычный шаблон освещения.

    Состояние приходит из Home Assistant (сущность из правил освещения
    манифеста): расписание «спим» живёт в HA-автоматизации, платформа его не
    считает и не хранит. ``None`` — сущность есть, но состояние не прочитано:
    отказ, потому что включать ночной свет вслепую нельзя (принцип «отказ при
    нехватке данных»). В ``requires`` условие не помечено: требование проверяет
    показания датчика, а булево ему не посчитать — тогда «спим» и «не
    прочитано» слились бы в одну причину, и утром их нельзя было бы различить.

    Args:
        Ничего.

    Returns:
        Функция ``(state, context) -> bool``.
    """

    def modifier_is_on(state: Any, context: dict[str, Any]) -> bool:
        """Разрешить переход, если модификатор «мы спим» включён.

        Args:
            state: Текущее состояние автомата.
            context: Контекст перехода.

        Returns:
            True, если модификатор включён.
        """
        del state  # состояние на решение не влияет: решает только модификатор
        return context.get("sleep_modifier_on") is True

    def deny_reason(state: Any, context: dict[str, Any]) -> str | None:
        """Назвать причину отказа: «не спим» или «данных нет».

        Обе причины именуются: «ночник не включался, потому что не спим» —
        штатное вечернее решение, а «состояние не прочитано» — поломка данных.
        Молчаливый ``guard_failed`` сливал бы их: в живом журнале 2026-10-09
        каждое вечернее движение выглядело одинаково, и утренний анализ
        (правило о логах) не мог их различить.

        Args:
            state: Текущее состояние автомата.
            context: Контекст перехода.

        Returns:
            ``modifier_off``, если модификатор выключен; ``guard_data_missing``,
            если состояние неизвестно; иначе None (отказа нет).
        """
        del state
        modifier = context.get("sleep_modifier_on")
        if modifier is None:
            return "guard_data_missing"
        if modifier is False:
            return "modifier_off"
        return None

    modifier_is_on.deny_reason = deny_reason  # type: ignore[attr-defined]
    return modifier_is_on


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
    # Климат объявляет только показание. Уставку добавлять нельзя: любое число
    # прошло бы как измерение, включая 95.0, и движок вернул бы «данных нет»
    # прежде, чем условие успело сказать «уставка вне диапазона» — а разные
    # причины в журнале означают разное: «датчик молчит» и «уставка негодна».
    "may_heat": ("temperature",),
    "may_stop_heating": ("temperature",),
    "has_usable_reading": ("temperature",),
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
        "modifier_is_on": make_modifier_is_on(),
        "below_setpoint": make_below_setpoint(),
        "at_or_above_setpoint": make_at_or_above_setpoint(),
        "climate_is_enabled": make_climate_is_enabled(),
        "managed_by_hardware_ok": make_managed_by_hardware_ok(),
        "stops_on_sleep": make_stops_on_sleep(),
        "stops_on_sunrise": make_stops_on_sunrise(),
        "may_heat": make_may_heat(),
        "may_stop_heating": make_may_stop_heating(),
        "has_usable_reading": make_has_usable_reading(),
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
#: Гистерезис обогревателя по умолчанию, °C.
#:
#: Меньше — обогреватель дёргается на каждом градусе колебаний датчика, больше —
#: промахивается мимо комфорта и перегревает комнату. Полградуса — компромисс
#: между ними, и он же виден в поведении: обогреватель начинает работу заранее,
#: но не «дрожит» на границе.
DEFAULT_HYSTERESIS = 0.5

#: Границы целевой температуры, °C.
#:
#: Уставка вне этих границ — поломка настройки, а не пожелание владельца:
#: 95 °C в комнате означает, что число пришло из другой сущности или из
#: неисправного сценария. Дальше этого климат не идёт: сначала в журнал, иначе
#: молчаливый перегрев.
MIN_SETPOINT = 5.0
MAX_SETPOINT = 35.0


def _temperature_value(context: dict[str, Any]) -> float | None:
    """Показание датчика комнаты как число.

    Значение приходит в контексте под именем роли датчика (``temperature``) и
    роутер уже приводит его к числу, когда это возможно
    (``event_router.py::_as_measurement``). Остаётся отсечь нечисловые значения:
    ``unavailable``, ``unknown``, пустая строка — это отсутствие данных, а не
    ноль градусов.

    Args:
        context: Контекст перехода.

    Returns:
        Температура в градусах либо ``None``, если показания пригодных нет.
    """
    raw = context.get("temperature")
    if isinstance(raw, bool) or raw is None:
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def _setpoint_value(context: dict[str, Any]) -> tuple[float | None, bool]:
    """Целевая температура дома и признак, что она пригодна.

    Args:
        context: Контекст перехода.

    Returns:
        Пара ``(уставка, пригодна ли она)``. Уставка ``None`` означает «не
        прочитана»; пригодность False при непустой уставке означает «прочитана,
        но вне диапазона» — для утреннего анализа это разные поломки.
    """
    raw = context.get("climate_setpoint")
    if raw is None or isinstance(raw, bool):
        return None, False
    try:
        setpoint = float(raw)
    except (TypeError, ValueError):
        return None, False
    if not (MIN_SETPOINT <= setpoint <= MAX_SETPOINT):
        return None, False
    return setpoint, True


def _hysteresis_value(context: dict[str, Any]) -> float:
    """Гистерезис из контекста, с запасным значением.

    Args:
        context: Контекст перехода.

    Returns:
        Ширина мёртвой зоны в градусах; нечитаемое значение заменяется
        умолчанием, а не нулём: нулевой гистерезис означал бы работу обогревателя
        на границе цели.
    """
    raw = context.get("hysteresis", DEFAULT_HYSTERESIS)
    if isinstance(raw, bool) or raw is None:
        return DEFAULT_HYSTERESIS
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return DEFAULT_HYSTERESIS
    return value if 0.0 <= value <= 2.0 else DEFAULT_HYSTERESIS


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


def make_has_usable_reading() -> Callable[[Any, dict[str, Any]], bool]:
    """Построить условие «показание пригодно, чтобы что-то решать».

    Существует ради одного перехода в климате: «ничего не делать» — тоже
    решение, и оно обязано быть объяснимо. Переход без условия срабатывал и при
    молчащем датчике, и журнал показывал ноль отказов при комнате, которая не
    отапливалась (боевой разбор 2026-10-10; FR-038).
    """

    def has_usable_reading(state: Any, context: dict[str, Any]) -> bool:
        """Разрешить, если показание датчика пригодно.

        Args:
            state: Текущее состояние автомата.
            context: Контекст перехода.

        Returns:
            True, если показание можно использовать для решения.
        """
        del state
        return _temperature_value(context) is not None

    def deny_reason(state: Any, context: dict[str, Any]) -> str | None:
        """Объяснить отказ: данных нет.

        Args:
            state: Текущее состояние автомата.
            context: Контекст перехода.

        Returns:
            ``guard_data_missing`` либо ``None``.
        """
        del state
        if _temperature_value(context) is not None:
            return None
        return "guard_data_missing"

    has_usable_reading.deny_reason = deny_reason  # type: ignore[attr-defined]
    return has_usable_reading


def make_stops_on_sleep() -> Callable[[Any, dict[str, Any]], bool]:
    """Построить условие «этот свет гаснет по модификатору „мы спим“».

    Разделяет два правила выключения вечернего света. Гирлянда на террасе
    гаснет, когда владелец ложится спать (FR-001 спеки вечернего света);
    ночное освещение — нет, оно горит до рассвета. Одно условие на переход
    означает, что различие живёт в параметре поведения `off_by`, а не в двух
    почти одинаковых шаблонах.
    """

    def stops_on_sleep(state: Any, context: dict[str, Any]) -> bool:
        """Разрешить выключение по «мы спим», если так задано поведением.

        Args:
            state: Текущее состояние автомата.
            context: Контекст перехода.

        Returns:
            True, если свет этого поведения гаснет по модификатору.
        """
        del state
        return str(context.get("off_by", "")).strip().lower() == "sleep"

    def deny_reason(state: Any, context: dict[str, Any]) -> str | None:
        """Объяснить отказ: это не тот свет, который гаснет по модификатору.

        Args:
            state: Текущее состояние автомата.
            context: Контекст перехода.

        Returns:
            ``None``. Отказ здесь — не поломка: свет просто живёт по другому
            правилу, и в журнале это выглядит как `guard_failed`, что верно.
        """
        del state
        return None

    stops_on_sleep.deny_reason = deny_reason  # type: ignore[attr-defined]
    return stops_on_sleep


def make_stops_on_sunrise() -> Callable[[Any, dict[str, Any]], bool]:
    """ЗАБРОШЕНО. Условие больше не используется ни одним шаблоном.

    Изначально разводило выключение вечернего света: `off_by: "sunrise"` —
    гаснет по рассвету, `off_by: "sleep"` — по отбою. Из-за этого рассвет для
    гирлянды становился отказом, и она горела весь день (журнал 2026-10-10).

    Теперь рассвет гасит любой декоративный свет безусловно, а `off_by`
    разводит только выключение по отбою (`stops_on_sleep`). Функция оставлена
    до конца жизни реестра: удаление затрагивает и список зарегистрированных
    условий, и шаблоны, которые ещё не обновлены. Пользоваться ей нельзя —
    это ловушка, возвращающая боевой дефект.
    """

    def stops_on_sunrise(state: Any, context: dict[str, Any]) -> bool:
        """Разрешить выключение по рассвету.

        Args:
            state: Текущее состояние автомата.
            context: Контекст перехода.

        Returns:
            Всегда True: рассвет гасит вечерний свет при любом `off_by`.
        """
        del state, context
        return True

    return stops_on_sunrise


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


REGISTERED_GUARDS = (
    "is_day_time",
    "is_manual_override_enabled",
    "may_turn_on",
    "modifier_is_on",
    "humidity_above_60",
    "humidity_below_60",
    "below_setpoint",
    "at_or_above_setpoint",
    "climate_is_enabled",
    "managed_by_hardware_ok",
    "stops_on_sleep",
    "stops_on_sunrise",
    "may_heat",
    "may_stop_heating",
    "has_usable_reading",
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
