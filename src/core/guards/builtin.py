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
    "mode_for_weather": ("outside_temperature",),
    "should_run_max_supply": ("temperature",),
    # Температура комнаты приходит под именем роли `temperature`, а не под
    # `source_room_temperature`: прежний ключ никто не писал, и объявленное
    # требование останавливало условие на «данных нет» при живом датчике.
    # Отсутствие температуры называет само условие причиной `sensor_stale`.
    "speed_within_limits": ("outside_temperature",),
    "sensor_is_alive": ("outside_temperature",),
    "may_stop_heating": ("temperature",),
    "has_usable_reading": ("temperature",),
    "may_cool": ("temperature",),
    "may_dry": ("humidity",),
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
        "mode_for_weather": make_mode_for_weather(),
        "should_run_max_supply": make_should_run_max_supply(),
        "airing_should_end": make_airing_should_end(),
        "startup_reapply": make_startup_reapply(),
        "speed_within_limits": make_speed_within_limits(),
        "covers_should_close": make_covers_should_close(),
        "covers_should_open": make_covers_should_open(),
        "owner_wants_airing": make_owner_wants_airing(),
        "should_run_exhaust": make_should_run_exhaust(),
        "exhaust_should_stop": make_exhaust_should_stop(),
        "ventilation_should_stop": make_ventilation_should_stop(),
        "sensor_is_alive": make_sensor_is_alive(),
        "may_cool": make_may_cool(),
        "may_dry": make_may_dry(),
        "may_stay_idle": make_may_stay_idle(),
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


def make_may_stay_idle() -> Callable[[Any, dict[str, Any]], bool]:
    """Построить условие «комната остаётся в покое — и это объяснимо».

    Отвечает на вопрос, который иначе теряется: если в комнате жарко, но
    охладить запрещено (зима или нет гейта владельца), решение «ничего не
    делать» всё равно правильное — однако из-за него отказ по охлаждению не
    попадал ни в один счётчик, и по журналу выглядело так, будто автоматика
    молчит, а сама не заметила жары.

    Условие пропускает «покой» только когда охлаждение действительно не
    требуется; иначе автомат остаётся в покое **как отказ** с названной
    причиной, и владелец видит, что мешает.
    """

    def may_stay_idle(state: Any, context: dict[str, Any]) -> bool:
        """Разрешить остаться в покое, если это штатное решение.

        Args:
            state: Текущее состояние автомата.
            context: Контекст перехода.

        Returns:
            True, если покой объясним.
        """
        del state
        if _temperature_value(context) is None:
            return False
        return _cooling_denial(context) == "not_above_comfort"

    def deny_reason(state: Any, context: dict[str, Any]) -> str | None:
        """Назвать причину: охлаждение требуется, но запрещено.

        Args:
            state: Текущее состояние автомата.
            context: Контекст перехода.

        Returns:
            Имя причины либо ``None``.
        """
        del state
        if _temperature_value(context) is None:
            return "guard_data_missing"
        if _cooling_denial(context) == "not_above_comfort":
            return None
        return _cooling_denial(context) or "guard_data_missing"

    may_stay_idle.deny_reason = deny_reason  # type: ignore[attr-defined]
    return may_stay_idle


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
        return _drying_denial(context)

    may_dry.deny_reason = deny_reason  # type: ignore[attr-defined]
    return may_dry


def _drying_denial(context: dict[str, Any]) -> str | None:
    """Первая по порядку причина, по которой осушать нельзя.

    Args:
        context: Контекст перехода.

    Returns:
        Имя причины либо ``None``, если осушение разрешено.
    """
    if context.get("ac_allowed") is not True:
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
    if context.get("ac_allowed") is not True:
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


def _comfort_max_value(context: dict[str, Any]) -> float | None:
    """Потолок комфорта как число.

    Args:
        context: Контекст перехода.

    Returns:
        Потолок в градусах либо ``None``, если прочитать нечего.
    """
    raw = context.get("comfort_max")
    if isinstance(raw, bool) or raw is None:
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


#: Порог температуры улицы, ниже которого дом считается зимним. Значение по
#: умолчанию — 5 °C; это решение дома, а не свойство движка, поэтому оно
#: приходит параметром поведения.
DEFAULT_WINTER_THRESHOLD = 5.0

#: Границы скорости рекуператора. Устройство принимает 0–100, и выход за них
#: означает либо отказ Home Assistant, либо молчаливое ограничение прибором.
MIN_SPEED = 0
MAX_SPEED = 100

#: Обычная скорость рекуператора, %. Боевой прибор (Vakio Base Smart) округляет
#: запрошенный процент **вверх** к ближайшей из своих семи ступеней
#: (14,29,43,57,71,86,100): запрос 43 попадает на ступень 57 %, а 42 — на 43 %
#: (research.md D24). Поэтому обычная скорость — 42, а не «номинальные» 43:
#: ступень 3 и есть задуманные ~43 %.
DEFAULT_SPEED_NORMAL = 42.0

#: Минимальная скорость рекуператора, %. Ниже неё прибор работает впустую; это
#: решение дома, поэтому рабочее значение приходит параметром поведения
#: (``speed_min``), а это — запасное.
DEFAULT_SPEED_MIN = 14.0

#: Температура улицы, °C, при которой скорость рекуператора обычная. Теплее —
#: обычная, холоднее — скорость падает: гнать морозный воздух в дом дороже, чем
#: сберечь тепло. Решение дома, поэтому рабочее значение — параметр
#: (``speed_cold_reference``).
DEFAULT_SPEED_COLD_REFERENCE = 5.0

#: На сколько процентов снижать скорость рекуператора на каждый градус улицы
#: ниже ``speed_cold_reference``. Рабочее значение — параметр (``speed_cold_gain``).
DEFAULT_SPEED_COLD_GAIN = 2.0

#: Порог температуры санузла, °C, с которого вытяжка считается нужной (T086).
#: Владелец выбрал 25 °C: зимой санузел держится на 23–24 °C, а выше — уже
#: заметный перегрев от печи или душа.
DEFAULT_EXHAUST_TEMPERATURE = 25.0

#: Порог влажности санузла, %, с которого вытяжка считается нужной (T086).
#: 65 % — тот же порог, что у прежнего шаблона humidity_ventilation.
DEFAULT_EXHAUST_HUMIDITY = 65.0


def _number(context: dict[str, Any], key: str) -> float | None:
    """Число из контекста; неприводимое или отсутствующее — ``None``.

    Args:
        context: Контекст перехода.
        key: Имя значения.

    Returns:
        Число либо ``None``.
    """
    raw = context.get(key)
    if raw is None or isinstance(raw, bool):
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def _clamp_speed(value: float) -> int:
    """Ограничить скорость диапазоном устройства.

    Args:
        value: Рассчитанная скорость.

    Returns:
        Целое в пределах 0–100.
    """
    return int(max(MIN_SPEED, min(MAX_SPEED, round(value))))


def _room_temperature(context: dict[str, Any]) -> float | None:
    """Температура комнаты автомата вентиляции.

    Роутер кладёт показание датчика комнаты под именем его роли —
    ``temperature`` (``event_router.py::route_state_change``). Ключ
    ``source_room_temperature`` — прежнее имя, оставшееся запасным: условия
    читали его, но писать его было некому, и скорость вентиляции отказывала
    «датчик не даёт показания» при живом датчике. Запасной ключ сохраняет
    совместимость с уже сохранённым состоянием автоматов.

    Args:
        context: Контекст перехода.

    Returns:
        Температура в градусах либо ``None``, если показания нет.
    """
    value = _number(context, "temperature")
    if value is None:
        value = _number(context, "source_room_temperature")
    return value


def _room_is_above_comfort(context: dict[str, Any], room: float | None) -> bool:
    """В комнате жарче потолка комфорта: нужен максимальный приток.

    Порог — глобальная ``comfort_max`` (``input_number.maksimalno_komfortnaia_temperatura``),
    единый для дома: то же значение решает, пора ли охлаждать кондиционером
    (``may_cool``). Отдельного порога вентиляции нет намеренно — две ручки для
    «жарко» разошлись бы, и владелец настраивал бы одну из двух.

    Потолка нет — приток не включается: «жарко» неизвестно, а на морозе
    угадывание означало бы лишний приток свежего воздуха (уточнение владельца
    2026-10-12, research.md D22).

    Args:
        context: Контекст перехода.
        room: Температура комнаты в градусах либо ``None``, если показания нет.

    Returns:
        True, если комната строго выше потолка комфорта.
    """
    if room is None:
        return False
    ceiling = _comfort_max_value(context)
    if ceiling is None:
        return False
    return room > ceiling


def _speed_from_context(context: dict[str, Any]) -> float:
    """Скорость рекуператора от температуры улицы и модификатора сна.

    Правило владельца (FR-052, FR-053, research.md D22): не холоднее опорной
    температуры улицы (``speed_cold_reference``) скорость обычная
    (``speed_normal``); холоднее — падает на ``speed_cold_gain`` процентов за
    градус и не опускается ниже ``speed_min``. Ночью при нормальной температуре
    комнаты скорость — минимальная.

    Показания улицы нет — берётся обычная скорость: это не «данные есть», а
    безопасное значение по умолчанию (вентиляция тише обычной не сломает дом).

    Args:
        context: Контекст перехода.

    Returns:
        Скорость в процентах, ещё не ограниченная 0–100.
    """
    normal = _number(context, "speed_normal")
    normal = DEFAULT_SPEED_NORMAL if normal is None else normal
    minimum = _number(context, "speed_min")
    minimum = DEFAULT_SPEED_MIN if minimum is None else minimum

    # Ночью при нормальной температуре — минимум: тишина важнее воздухообмена,
    # а жаркую комнату в это время ведёт уже «Приток MAX», не эта ветка.
    if _is_night(context):
        return min(normal, minimum)

    outside = _number(context, "outside_temperature")
    if outside is None:
        return normal

    reference = _number(context, "speed_cold_reference")
    reference = DEFAULT_SPEED_COLD_REFERENCE if reference is None else reference
    gain = _number(context, "speed_cold_gain")
    gain = DEFAULT_SPEED_COLD_GAIN if gain is None else gain

    speed = normal if outside >= reference else normal - (reference - outside) * gain
    return min(normal, max(minimum, speed))


def _is_night(context: dict[str, Any]) -> bool:
    """Признак ночи для вентиляции.

    Ночью рекуператор должен работать тихо (FR-022, T088). Платформа часов не
    считает: ночь задаёт модификатор владельца «мы спим»
    (``input_boolean.sleep_mode``), который роутер кладёт в контекст как
    ``sleep_modifier_on``. Ключ ``is_night`` остаётся запасным для сохранённого
    состояния автоматов.

    Args:
        context: Контекст перехода.

    Returns:
        True, если сейчас ночь.
    """
    if context.get("is_night") is True:
        return True
    return context.get("sleep_modifier_on") is True


def _ventilation_role(context: dict[str, Any]) -> str:
    """Роль устройства в шаблоне вентиляции.

    Один шаблон обслуживает и рекуператор (режим + скорость), и вытяжку
    санузла (только вкл/выкл). Роль приходит параметром поведения
    (``ventilation_role``), иначе первая же смена температуры заставила бы
    вытяжку «выбирать режим», которого у неё нет.

    Args:
        context: Контекст перехода.

    Returns:
        ``supply`` для рекуператора, ``exhaust`` для вытяжки.
    """
    role = context.get("ventilation_role")
    return role if isinstance(role, str) and role else "supply"


def _ventilation_allowed(context: dict[str, Any]) -> tuple[bool, str | None]:
    """Право автоматики вентиляции работать сейчас.

    Порядок проверок — по силе права: фиче-флаг дома выключает вентиляцию
    целиком (T090), выключатель владельца сильнее любого правила (FR-027), а
    рекуператор в комнате холоднее уставки не работает вовсе: приток свежего
    воздуха в остывающий дом бессмысленен (FR-049). Это правило заменило прежнее
    «выключать при работающем обогреве» (T089, FR-055): пока комнате нужен
    обогрев, она ниже уставки, и вентиляция стоит сама.

    Комнатная температура спрашивается только у рекуператора: вытяжка санузла
    работает и в остывающем доме — санузел сушат не ради тепла.

    Если уставка не прочитана, правило «холодно» не применяется и вентиляция
    продолжает работать: воздух в доме важнее остановки из-за молчащей ручки.
    Это осознанный выбор, а не пропуск — пропажу уставки видно по глобальным
    настройкам, тогда как лишняя остановка вентиляции заметна только по дому.

    Args:
        context: Контекст перехода.

    Returns:
        Пару «разрешено ли» и имя причины отказа, если нет.
    """
    if context.get("ventilation_enabled") is False:
        return False, "ventilation_disabled"
    if context.get("ventilation_on") is False:
        return False, "turned_off_by_owner"
    if _ventilation_role(context) == "supply":
        room = _room_temperature(context)
        setpoint = _number(context, "climate_setpoint")
        if room is not None and setpoint is not None and room < setpoint:
            return False, "room_below_setpoint"
    return True, None


def _bathroom_is_uncomfortable(context: dict[str, Any]) -> bool | None:
    """Нужна ли вытяжка санузла по его температуре и/или влажности.

    Показаний может не быть вовсе (датчик влажности в доме пока не поставлен):
    тогда возвращается ``None``, и решение принимает модификатор владельца.
    ``True`` — санузел жаркий или влажный, ``False`` — сухо и не жарко.

    Args:
        context: Контекст перехода.

    Returns:
        ``True``/``False`` при пригодных показаниях, иначе ``None``.
    """
    temperature = _number(context, "temperature")
    humidity = _number(context, "humidity")
    if temperature is None and humidity is None:
        return None

    temperature_threshold = _number(context, "exhaust_temp_threshold")
    humidity_threshold = _number(context, "exhaust_humidity_threshold")
    temperature_threshold = (
        DEFAULT_EXHAUST_TEMPERATURE if temperature_threshold is None else temperature_threshold
    )
    humidity_threshold = (
        DEFAULT_EXHAUST_HUMIDITY if humidity_threshold is None else humidity_threshold
    )

    hot = temperature is not None and temperature >= temperature_threshold
    wet = humidity is not None and humidity >= humidity_threshold
    return hot or wet


def _choose_normal_mode(context: dict[str, Any]) -> Any:
    """Выбрать обычный (не охлаждающий) режим рекуператора.

    Обычный режим — сезонная рекуперация: при известном сезоне имя берётся из
    параметров (``mode_winter``/``mode_summer``), при неизвестном — по порогу
    температуры улицы. Охлаждающий «Приток MAX» здесь не выбирается: им
    заведует отдельное состояние ``AIRING``.

    Args:
        context: Контекст перехода.

    Returns:
        Имя режима либо ``None``, если выбирать не по чему.
    """
    is_winter = context.get("is_winter")
    if is_winter is True:
        return context.get("mode_winter")
    if is_winter is False:
        return context.get("mode_summer")
    outside = _number(context, "outside_temperature")
    if outside is None:
        return None
    threshold = _number(context, "winter_mode_threshold")
    if threshold is None:
        threshold = DEFAULT_WINTER_THRESHOLD
    return context.get("mode_winter") if outside <= threshold else context.get("mode_summer")


def make_mode_for_weather() -> Callable[[Any, dict[str, Any]], bool]:
    """Построить условие «выбрать обычный режим вентиляции».

    Физику теплообмена платформа не считает: у рекуператора есть готовые режимы,
    и вычислять приближение — значит заменить работу устройства худшим
    результатом (``research.md`` D7). Условие выбирает режим из списка,
    заданного параметрами поведения, и кладёт его в контекст под именем
    ``chosen_mode``.

    Режим задаёт модификатор владельца «зима» (FR-050, research.md D22): при
    ``is_winter`` = true — ``mode_winter`` («Рекуперация (зима)»), при false —
    ``mode_summer`` («Рекуперация (лето)»). Охлаждающий максимальный приток здесь
    не выбирается: им заведует отдельное условие ``should_run_max_supply``,
    которое ведёт автомат в ``AIRING`` с таймером. Пока модификатор не прочитан,
    режим определяется порогом температуры улицы (``winter_mode_threshold``).

    Без показания улицы режим **не выбирается**: при морозе угадывание означало
    бы лишний приток свежего воздуха, летом — душный дом.

    Условие отказывает и тогда, когда вентиляции работать нельзя: фиче-флаг
    выключен, выключатель владельца в off или в комнате холоднее уставки
    (FR-027, FR-049). Иначе перехода в SUPPLY из IDLE не было бы вовсе, и
    причина отказа осталась бы неназванной.

    Args:
        Ничего.

    Returns:
        Функция ``(state, context) -> bool`` с ``deny_reason``.
    """

    def mode_for_weather(state: Any, context: dict[str, Any]) -> bool:
        """Выбрать режим по модификатору «зима» и погоде.

        Args:
            state: Состояние автомата (не используется).
            context: Контекст перехода.

        Returns:
            True, если режим выбран.
        """
        del state
        allowed, _ = _ventilation_allowed(context)
        if not allowed or _ventilation_role(context) != "supply":
            return False

        chosen: Any = _choose_normal_mode(context)
        if chosen is None:
            return False

        context["chosen_mode"] = chosen
        # Скорость считается здесь же: переход IDLE → SUPPLY шлёт одним
        # действием и режим, и скорость, а накопленный контекст может не
        # содержать процента с прошлого раза — тогда команда скорости уходила бы
        # без значения и Home Assistant её отвергал.
        context["percentage"] = _clamp_speed(_speed_from_context(context))
        return bool(chosen)

    def deny_reason(state: Any, context: dict[str, Any]) -> str | None:
        """Назвать причину отказа.

        Args:
            state: Состояние автомата.
            context: Контекст перехода.

        Returns:
            Имя причины либо ``None``.
        """
        del state
        allowed, reason = _ventilation_allowed(context)
        if not allowed:
            return reason
        if _ventilation_role(context) != "supply":
            return None
        if _number(context, "outside_temperature") is None:
            return "outside_temp_missing"
        return None

    mode_for_weather.deny_reason = deny_reason  # type: ignore[attr-defined]
    return mode_for_weather


def make_should_run_max_supply() -> Callable[[Any, dict[str, Any]], bool]:
    """Построить условие «в комнате жарко — пора на максимальный приток».

    Жарко — это температура комнаты строго выше потолка комфорта
    (``input_number.maksimalno_komfortnaia_temperatura``). Тогда платформа
    включает «Приток MAX» на срок ``airing_seconds``, а возврат к обычному
    режиму делает таймер шаблона (FR-051, research.md D22). Порог берётся из
    переменной дома, а не зашит в код (FR-056): второй ручки «жарко» быть не
    должно.

    Условие отказывает, когда вентиляции работать нельзя (фиче-флаг,
    выключатель владельца, комната холоднее уставки): жаркой комнаты при
    выключенной вентиляции не бывает, но причина отказа должна быть названа.

    Args:
        Ничего.

    Returns:
        Функция ``(state, context) -> bool`` с ``deny_reason``.
    """

    def should_run_max_supply(state: Any, context: dict[str, Any]) -> bool:
        """Проверить, жарче ли в комнате потолка комфорта.

        Args:
            state: Состояние автомата (не используется).
            context: Контекст перехода.

        Returns:
            True, если комната строго выше потолка комфорта.
        """
        del state
        allowed, _ = _ventilation_allowed(context)
        if not allowed or _ventilation_role(context) != "supply":
            return False
        return _room_is_above_comfort(context, _room_temperature(context))

    def deny_reason(state: Any, context: dict[str, Any]) -> str | None:
        """Назвать причину отказа.

        Args:
            state: Состояние автомата.
            context: Контекст перехода.

        Returns:
            Имя причины либо ``None``: если в комнате не жарко, это штатное
            решение, и называть его незачем.
        """
        del state
        allowed, reason = _ventilation_allowed(context)
        if not allowed:
            return reason
        if _ventilation_role(context) != "supply":
            return None
        if _comfort_max_value(context) is None:
            return "guard_data_missing"
        if _room_temperature(context) is None:
            return "sensor_stale"
        return None

    should_run_max_supply.deny_reason = deny_reason  # type: ignore[attr-defined]
    return should_run_max_supply


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
            state: Состояние автомата (не используется).
            context: Контекст перехода.

        Returns:
            True, если штору пора закрыть.
        """
        del state
        return _cover_close_reason(context) is None

    def deny_reason(state: Any, context: dict[str, Any]) -> str | None:
        """Назвать причину, по которой штора не закрывается.

        Args:
            state: Состояние автомата.
            context: Контекст перехода.

        Returns:
            Имя причины либо ``None``.
        """
        del state
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
            state: Состояние автомата (не используется).
            context: Контекст перехода.

        Returns:
            True, если штору пора открыть.
        """
        del state
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
        del state
        if context.get("cover_emergency") is True:
            return None
        if context.get("covers_enabled") is False:
            return "covers_disabled"
        return "covers_stay_closed"

    covers_should_open.deny_reason = deny_reason  # type: ignore[attr-defined]
    return covers_should_open


def make_airing_should_end() -> Callable[[Any, dict[str, Any]], bool]:
    """Построить условие «жара прошла — вернуть обычный режим».

    Автомат выходит из «Притока MAX» и по часовому таймеру, но ждать его, если
    жара спала раньше, нельзя: рекуператор продолжит дуть максимумом и
    переохладит дом (улица 11 °C). Условие молчит, пока идёт проветривание
    владельца (``airing_on``): его держит свой таймер, и отменять его раньше
    времени нельзя.

    Returns:
        Функция ``(state, context) -> bool`` с ``deny_reason``.
    """

    def airing_should_end(state: Any, context: dict[str, Any]) -> bool:
        """Проверить, пора ли вернуть обычный режим.

        Args:
            state: Состояние автомата (не используется).
            context: Контекст перехода.

        Returns:
            True, если жара прошла и это не проветривание владельца.
        """
        del state
        allowed, _ = _ventilation_allowed(context)
        if not allowed or _ventilation_role(context) != "supply":
            return False
        if context.get("airing_on") is True:
            return False
        if _room_is_above_comfort(context, _room_temperature(context)):
            return False
        chosen = _choose_normal_mode(context)
        if not chosen:
            return False
        # Действие вернёт режим и скорость — кладём их в контекст здесь же, как
        # это делает выбор режима по погоде.
        context["chosen_mode"] = chosen
        context["percentage"] = _clamp_speed(_speed_from_context(context))
        return True

    def deny_reason(state: Any, context: dict[str, Any]) -> str | None:
        """Назвать причину отказа.

        Args:
            state: Состояние автомата.
            context: Контекст перехода.

        Returns:
            Имя причины отказа владельца либо ``None`` (жара ещё не прошла).
        """
        del state
        allowed, reason = _ventilation_allowed(context)
        return reason if not allowed else None

    airing_should_end.deny_reason = deny_reason  # type: ignore[attr-defined]
    return airing_should_end


def make_startup_reapply() -> Callable[[Any, dict[str, Any]], bool]:
    """Построить условие «это первый пересмотр после запуска платформы».

    При запуске автомат восстанавливает прежнее состояние, но входа в него нет —
    и команда прибору не уходит: рекуператор остаётся в том режиме, в котором был,
    а после потери питания — выключенным, хотя автомат считает себя в «Притоке
    MAX» (боевая находка B43). Адаптер при подключении шлёт один общий пересмотр
    ``settings_changed`` и помечает его этим признаком: тогда восстановленный
    «Приток MAX» подтверждается как обычный вход — с включением прибора, — а
    не только режимом.

    Returns:
        Функция ``(state, context) -> bool``.
    """

    def startup_reapply(state: Any, context: dict[str, Any]) -> bool:
        """Проверить, что пересмотр пришёл от запуска платформы.

        Args:
            state: Состояние автомата (не используется).
            context: Контекст перехода.

        Returns:
            True для первого пересмотра и роли ``supply``.
        """
        del state
        if not context.get("startup_reapply"):
            return False
        return _ventilation_role(context) == "supply"

    return startup_reapply


def make_speed_within_limits() -> Callable[[Any, dict[str, Any]], bool]:
    """Построить условие «посчитать скорость и ограничить её».

    Формула из ``data-model.md`` §5 (FR-052): не холоднее опорной температуры
    улицы — ``speed_normal``, холоднее — ниже на ``speed_cold_gain`` процентов за
    градус, не ниже ``speed_min``; ночью при нормальной температуре — минимум
    (FR-053).

    Выключачка владельца ``ventilation_on = off`` сильнее любого правила
    (FR-027): условие отказывает с причиной ``turned_off_by_owner``, а переход
    ``SUPPLY → IDLE`` гасит прибор — «полностью выключает», а не «крутит на
    нуле» (T090). То же у выключенного фиче-флага и у комнаты холоднее уставки.

    Args:
        Ничего.

    Returns:
        Функция ``(state, context) -> bool`` с ``deny_reason``.
    """

    def speed_within_limits(state: Any, context: dict[str, Any]) -> bool:
        """Посчитать скорость и положить её в контекст как ``percentage``.

        Args:
            state: Состояние автомата (не используется).
            context: Контекст перехода.

        Returns:
            True, если скорость посчитана.
        """
        del state

        allowed, _ = _ventilation_allowed(context)
        if not allowed or _ventilation_role(context) != "supply":
            return False

        if _number(context, "outside_temperature") is None:
            return False

        context["percentage"] = _clamp_speed(_speed_from_context(context))
        return True

    def deny_reason(state: Any, context: dict[str, Any]) -> str | None:
        """Назвать причину отказа.

        Args:
            state: Состояние автомата.
            context: Контекст перехода.

        Returns:
            Имя причины либо ``None``.
        """
        del state
        allowed, reason = _ventilation_allowed(context)
        if not allowed:
            return reason
        if _ventilation_role(context) != "supply":
            return None
        if _number(context, "outside_temperature") is None:
            return "outside_temp_missing"
        return None

    speed_within_limits.deny_reason = deny_reason  # type: ignore[attr-defined]
    return speed_within_limits


def make_owner_wants_airing() -> Callable[[Any, dict[str, Any]], bool]:
    """Построить условие «владелец попросил проветрить».

    Проветривание включается только человеком (``input_boolean.provetrivanie``)
    и само отключается по таймеру шаблона (FR-024, T085). По влажности платформа
    его не включает: на улице бывает влажнее, чем дома, и решение владельца не
    принято (``research.md`` D14).

    Проветривание — это о рекуператоре (роль ``supply``). Вытяжке санузла приток
    не задаётся вовсе.

    Args:
        Ничего.

    Returns:
        Функция ``(state, context) -> bool`` с ``deny_reason``.
    """

    def owner_wants_airing(state: Any, context: dict[str, Any]) -> bool:
        """Разрешить проветривание, если его просил человек.

        Args:
            state: Состояние автомата (не используется).
            context: Контекст перехода.

        Returns:
            True, если проветривание запрошено.
        """
        del state
        allowed, _ = _ventilation_allowed(context)
        if not allowed or _ventilation_role(context) != "supply":
            return False
        return bool(context.get("airing_on"))

    def deny_reason(state: Any, context: dict[str, Any]) -> str | None:
        """Назвать причину отказа.

        Args:
            state: Состояние автомата.
            context: Контекст перехода.

        Returns:
            Причину запрета вентиляции либо ``None`` (проветривание просто не
            просили — это не поломка).
        """
        del state
        allowed, reason = _ventilation_allowed(context)
        return reason if not allowed else None

    owner_wants_airing.deny_reason = deny_reason  # type: ignore[attr-defined]
    return owner_wants_airing


def make_sensor_is_alive() -> Callable[[Any, dict[str, Any]], bool]:
    """Построить условие «показания датчиков годны».

    Отказ датчика улицы останавливает только пересчёт скорости: обогрев и
    остальная вентиляция работают (FR-046).

    Args:
        Ничего.

    Returns:
        Функция ``(state, context) -> bool`` с ``deny_reason``.
    """

    def sensor_is_alive(state: Any, context: dict[str, Any]) -> bool:
        """Разрешить, если температура улицы читается числом.

        Args:
            state: Состояние автомата (не используется).
            context: Контекст перехода.

        Returns:
            True, если показание пригодно.
        """
        del state
        return _number(context, "outside_temperature") is not None

    def deny_reason(state: Any, context: dict[str, Any]) -> str | None:
        """Назвать причину отказа.

        Args:
            state: Состояние автомата.
            context: Контекст перехода.

        Returns:
            ``sensor_stale`` либо ``None``.
        """
        del state
        if _number(context, "outside_temperature") is None:
            return "sensor_stale"
        return None

    sensor_is_alive.deny_reason = deny_reason  # type: ignore[attr-defined]
    return sensor_is_alive


def make_should_run_exhaust() -> Callable[[Any, dict[str, Any]], bool]:
    """Построить условие «вытяжку санузла пора включить».

    Вытяжка включается двумя путями и работает, пока есть хоть один повод:

    - модификатор владельца ``input_boolean.provetrivanie_vytyazhka`` — ручное
      «проветрить санузел», с автосбросом по таймеру 60 минут (FR-026, T085);
    - высокая температура и/или влажность самого санузла (FR-026, T086,
      уточнение владельца ``research.md`` D18).

    Условие — только о вытяжке (роль ``exhaust``): рекуператору его переходы не
    адресованы, и режим притока туда не уйдёт.

    Args:
        Ничего.

    Returns:
        Функция ``(state, context) -> bool`` с ``deny_reason``.
    """

    def should_run_exhaust(state: Any, context: dict[str, Any]) -> bool:
        """Разрешить вытяжку, если её просил человек или санузел не в норме.

        Args:
            state: Состояние автомата (не используется).
            context: Контекст перехода.

        Returns:
            True, если вытяжка нужна.
        """
        del state
        allowed, _ = _ventilation_allowed(context)
        if not allowed or _ventilation_role(context) != "exhaust":
            return False
        if context.get("exhaust_on") is True:
            return True
        return _bathroom_is_uncomfortable(context) is True

    def deny_reason(state: Any, context: dict[str, Any]) -> str | None:
        """Назвать причину отказа.

        Args:
            state: Состояние автомата.
            context: Контекст перехода.

        Returns:
            Имя причины либо ``None`` (вытяжка просто не нужна).
        """
        del state
        allowed, reason = _ventilation_allowed(context)
        if not allowed:
            return reason
        if _ventilation_role(context) != "exhaust":
            return None
        if _bathroom_is_uncomfortable(context) is False:
            return "bathroom_comfortable"
        return None

    should_run_exhaust.deny_reason = deny_reason  # type: ignore[attr-defined]
    return should_run_exhaust


def make_exhaust_should_stop() -> Callable[[Any, dict[str, Any]], bool]:
    """Построить условие «вытяжку санузла пора выключить».

    Отдельное условие, а не отрицание `should_run_exhaust`: одно условие — одно
    решение (конституция I). Вытяжка гаснет, когда модификатор владельца снят И
    санузел вернулся в норму ИЛИ вентиляции работать нельзя (фиче-флаг,
    выключатель владельца, комната холоднее уставки).

    Args:
        Ничего.

    Returns:
        Функция ``(state, context) -> bool``.
    """

    def exhaust_should_stop(state: Any, context: dict[str, Any]) -> bool:
        """Разрешить выключение вытяжки.

        Args:
            state: Состояние автомата (не используется).
            context: Контекст перехода.

        Returns:
            True, если вытяжку пора погасить.
        """
        del state
        if _ventilation_role(context) != "exhaust":
            return False
        allowed, _ = _ventilation_allowed(context)
        if not allowed:
            return True
        if context.get("exhaust_on") is True:
            return False
        return _bathroom_is_uncomfortable(context) is not True

    return exhaust_should_stop


def make_ventilation_should_stop() -> Callable[[Any, dict[str, Any]], bool]:
    """Построить условие «вентиляции работать нельзя — погасить».

    Переход в ``IDLE`` из ``SUPPLY``/``AIRING``: фиче-флаг выключен, выключатель
    владельца в off или температура комнаты ниже уставки (FR-027, FR-049).
    Проветривание по модификатору здесь тоже гасится: владелец выключил
    вентиляцию целиком — приток не исключение.

    Args:
        Ничего.

    Returns:
        Функция ``(state, context) -> bool``.
    """

    def ventilation_should_stop(state: Any, context: dict[str, Any]) -> bool:
        """Разрешить выключение вентиляции.

        Args:
            state: Состояние автомата (не используется).
            context: Контекст перехода.

        Returns:
            True, если работать нельзя.
        """
        del state
        if _ventilation_role(context) != "supply":
            return False
        allowed, _ = _ventilation_allowed(context)
        return not allowed

    return ventilation_should_stop


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
    "may_cool",
    "may_dry",
    "may_stay_idle",
    "mode_for_weather",
    "should_run_max_supply",
    "airing_should_end",
    "startup_reapply",
    "speed_within_limits",
    "covers_should_close",
    "covers_should_open",
    "owner_wants_airing",
    "should_run_exhaust",
    "exhaust_should_stop",
    "ventilation_should_stop",
    "sensor_is_alive",
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
