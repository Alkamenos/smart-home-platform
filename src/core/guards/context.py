"""Общее чтение контекста, время и суточные окна (B80).

Здесь то, чем пользуются все дома: время и пояс дома, чтение чисел из контекста,
эхо движения, требования к данным и общие условия (сутки, устройство включено,
датчик жив). Вынесено из `builtin.py`, где это лежало вперемешку с условиями
света, климата и вентиляции.
"""

import logging
import os
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from core.events.fsm_events import REASON_NOT_APPLICABLE


logger = logging.getLogger(__name__)

DEFAULT_HUMIDITY_THRESHOLD = 60.0

DEFAULT_DAY_TIME_RANGE = "07:00-23:00"

#: Срок ручной блокировки, если правила дома его не задали.
#:
#: Значение по умолчанию, а не «истина»: действует ровно то, что стоит в
#: манифесте (`global_manual_lockout_min`), — иначе условия и посредник
#: руководствовались бы разными сроками (аудит 2026-10-16, К-9).
DEFAULT_LOCKOUT_MINUTES = 60

DEFAULT_QUIET_FROM = "23:00"

DEFAULT_DAY_START_MINUTES = 7 * 60

DEFAULT_DAY_END_MINUTES = 23 * 60

DEFAULT_QUIET_TO = "06:30"

DEFAULT_MOTION_ECHO_SEC = 5.0

DEFAULT_HYSTERESIS = 0.5

MIN_SETPOINT = 5.0

MAX_SETPOINT = 35.0

DEFAULT_WINTER_THRESHOLD = 5.0

MIN_SPEED = 0

MAX_SPEED = 100

DEFAULT_SPEED_NORMAL = 42.0

DEFAULT_SPEED_MIN = 14.0

DEFAULT_SPEED_COLD_REFERENCE = 5.0

DEFAULT_SPEED_COLD_GAIN = 2.0

DEFAULT_EXHAUST_TEMPERATURE = 25.0

DEFAULT_EXHAUST_HUMIDITY = 65.0

REGISTERED_GUARDS = (
    "is_day_time",
    "is_night_time",
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
    "device_is_off",
    "device_is_on",
    "speed_within_limits",
    "covers_should_close",
    "covers_should_open",
    "owner_wants_airing",
    "should_run_exhaust",
    "exhaust_should_stop",
    "ventilation_should_stop",
    "sensor_is_alive",
)


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


def _motion_echo_window(context: dict[str, Any]) -> float:
    """Окно эха датчика в секундах.

    Args:
        context: Контекст перехода (параметр поведения `motion_echo_sec`).

    Returns:
        Окно в секундах; 0 — правило выключено.
    """
    raw = context.get("motion_echo_sec", DEFAULT_MOTION_ECHO_SEC)
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        return DEFAULT_MOTION_ECHO_SEC
    return max(0.0, float(raw))


def _motion_is_echo(context: dict[str, Any], wall_clock: Callable[[], float]) -> bool:
    """Считать ли движение эхом нашего же выключения света.

    Датчик, который видит сам свет (камера), срабатывает на смену освещённости:
    платформа гасит фонари, камера сообщает «движение», свет зажигается снова —
    и мигает (боевой случай 2026-10-14). Признак эха — время нашей команды
    выключения (`light_off_at` в контексте состояния).

    Args:
        context: Контекст перехода.
        wall_clock: Настенные часы (время команды тоже настенное и переживает
            перезапуск платформы).

    Returns:
        True, если движение пришло в окне эха.
    """
    window = _motion_echo_window(context)
    off_at = context.get("light_off_at")
    if window <= 0 or isinstance(off_at, bool) or not isinstance(off_at, (int, float)):
        return False
    return wall_clock() - float(off_at) <= window


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


def make_is_night_time(
    day_range: str = DEFAULT_DAY_TIME_RANGE,
    *,
    now: Callable[[], datetime] | None = None,
) -> Callable[[Any, dict[str, Any]], bool]:
    """Построить guard «сейчас ночь» — отрицание ``is_day_time``.

    Нужен возврату к автоматике после ручного вмешательства (BACKLOG B57):
    декоративный свет по таймауту оверрайда должен вернуться в «горит», если ещё
    ночь, и погаснуть, если уже день. Диапазон дня тот же, что у ``is_day_time``,
    поэтому день и ночь не разъедутся.

    Args:
        day_range: Диапазон дня ``HH:MM-HH:MM``.
        now: Источник времени; подменяется в тестах.

    Returns:
        Функцию ``(state, context) -> bool``.
    """
    is_day = make_is_day_time(day_range, now=now)

    def is_night_time(state: Any, context: dict[str, Any]) -> bool:
        """Разрешить переход, если сейчас не день."""
        return not is_day(state, context)

    return is_night_time


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


def _temperature_value(context: dict[str, Any]) -> float | None:
    """Показание датчика комнаты как число.

    Значение приходит в контексте под именем роли датчика (``temperature``) и
    роутер уже приводит его к числу, когда это возможно
    (``event_router.py::as_measurement``). Остаётся отсечь нечисловые значения:
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
        if not context.get("_startup_reapply"):
            return False
        return _ventilation_role(context) == "supply"

    def deny_reason(state: Any, context: dict[str, Any]) -> str | None:
        """Назвать причину: признак разовый — без него переход не к этому случаю.

        Признак ``_startup_reapply`` ставит адаптер на одном пересмотре при
        подключении. На обычном событии его нет, и переход не относится к этому
        случаю вовсе — это не отказ решения: движок пропускает такие переходы
        молча (BACKLOG B66/B74), иначе журнал наполнялся бы «условие не прошло»
        на каждом событии.

        Args:
            state: Состояние автомата (не используется).
            context: Контекст перехода.

        Returns:
            Имя причины либо ``None``, когда переход к случаю относится.
        """
        del state
        if not context.get("_startup_reapply"):
            return REASON_NOT_APPLICABLE
        return None if _ventilation_role(context) == "supply" else REASON_NOT_APPLICABLE

    startup_reapply.deny_reason = deny_reason  # type: ignore[attr-defined]
    return startup_reapply


def make_device_is_off() -> Callable[[Any, dict[str, Any]], bool]:
    """Построить условие «сторож сообщил, что прибор остановлен».

    Команда может быть принята Home Assistant («выполнен»), но не применена
    прибором: на боевой приёмке 2026-10-13 кабинет включился только со второй
    попытки (B54). Остановленный рекуператор сам не поднимется — подтверждение
    шлёт только режим (включение с процентом повторять нельзя, оно сбрасывает
    режим), — поэтому сторож читает настоящее состояние прибора и сообщает факт
    «прибор off» одноразовым признаком, а решение принимает шаблон: вход в
    «Приток MAX» уходит с включением прибора.

    Признак одноразовый (ключ с ведущим подчёркиванием), в накопленный контекст
    он не попадает — иначе всплыл бы на следующем событии.

    Returns:
        Функция ``(state, context) -> bool``.
    """

    def device_is_off(state: Any, context: dict[str, Any]) -> bool:
        """Проверить, что сторож сообщил об остановленном приборе.

        Args:
            state: Состояние автомата (не используется).
            context: Контекст перехода.

        Returns:
            True, если прибор остановлен.
        """
        del state
        return bool(context.get("_device_is_off"))

    def deny_reason(state: Any, context: dict[str, Any]) -> str | None:
        """Признак одноразовый: без него переход не к этому случаю (B74).

        Args:
            state: Состояние автомата (не используется).
            context: Контекст перехода.

        Returns:
            ``not_applicable``, когда сторож не сообщал об остановленном приборе.
        """
        del state
        return None if context.get("_device_is_off") else REASON_NOT_APPLICABLE

    device_is_off.deny_reason = deny_reason  # type: ignore[attr-defined]
    return device_is_off


def make_device_is_on() -> Callable[[Any, dict[str, Any]], bool]:
    """Построить условие «сторож сообщил, что прибор работает».

    Обратная сторона ``device_is_off`` (B55). Автомат стоит — значит решения
    вентилировать не было. Если в это время прибор работает (владелец включил сам,
    потерялась команда, команда не дошла), вентиляция идёт без решения: в бою
    2026-10-12 рекуператор спальни работал, а автомат считал ``IDLE`` (B40).
    Сторож читает настоящее состояние прибора и сообщает факт «прибор on»; шаблон
    сам решает — гасит прибор, — но только когда никакого другого решения нет
    (условие стоит последним в группе).

    Returns:
        Функция ``(state, context) -> bool``.
    """

    def device_is_on(state: Any, context: dict[str, Any]) -> bool:
        """Проверить, что сторож сообщил о работающем приборе.

        Args:
            state: Состояние автомата (не используется).
            context: Контекст перехода.

        Returns:
            True, если прибор работает.
        """
        del state
        return bool(context.get("_device_is_on"))

    def deny_reason(state: Any, context: dict[str, Any]) -> str | None:
        """Признак одноразовый: без него переход не к этому случаю (B74).

        Args:
            state: Состояние автомата (не используется).
            context: Контекст перехода.

        Returns:
            ``not_applicable``, когда сторож не сообщал о работающем приборе.
        """
        del state
        return None if context.get("_device_is_on") else REASON_NOT_APPLICABLE

    device_is_on.deny_reason = deny_reason  # type: ignore[attr-defined]
    return device_is_on


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


logger = logging.getLogger(__name__)

HOUSE_TZ: Any = _resolve_house_tz()
