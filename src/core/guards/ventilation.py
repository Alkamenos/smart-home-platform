"""Условия вентиляции: режим по погоде, скорость, приток и вытяжка (B80).

Вынесено из `builtin.py`.
"""

import logging
from collections.abc import Callable
from typing import Any

from core.events.fsm_events import REASON_NOT_APPLICABLE
from core.guards.context import (
    DEFAULT_EXHAUST_HUMIDITY as DEFAULT_EXHAUST_HUMIDITY,
    DEFAULT_EXHAUST_TEMPERATURE as DEFAULT_EXHAUST_TEMPERATURE,
    DEFAULT_SPEED_COLD_GAIN as DEFAULT_SPEED_COLD_GAIN,
    DEFAULT_SPEED_COLD_REFERENCE as DEFAULT_SPEED_COLD_REFERENCE,
    DEFAULT_SPEED_MIN as DEFAULT_SPEED_MIN,
    DEFAULT_SPEED_NORMAL as DEFAULT_SPEED_NORMAL,
    DEFAULT_WINTER_THRESHOLD as DEFAULT_WINTER_THRESHOLD,
    MAX_SPEED as MAX_SPEED,
    MIN_SPEED as MIN_SPEED,
    _comfort_max_value as _comfort_max_value,
    _is_night as _is_night,
    _number as _number,
    _room_temperature as _room_temperature,
    _ventilation_role as _ventilation_role,
)


logger = logging.getLogger(__name__)


def _clamp_speed(value: float) -> int:
    """Ограничить скорость диапазоном устройства.

    Args:
        value: Рассчитанная скорость.

    Returns:
        Целое в пределах 0–100.
    """
    return int(max(MIN_SPEED, min(MAX_SPEED, round(value))))


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
            # Ветка притока у вытяжки: переход не к этому прибору (BACKLOG B74).
            return REASON_NOT_APPLICABLE
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
            return REASON_NOT_APPLICABLE
        if _comfort_max_value(context) is None:
            return "guard_data_missing"
        if _room_temperature(context) is None:
            return "sensor_stale"
        return None

    should_run_max_supply.deny_reason = deny_reason  # type: ignore[attr-defined]
    return should_run_max_supply


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
            # Ветка притока у вытяжки: переход не к этому прибору (BACKLOG B74).
            return REASON_NOT_APPLICABLE
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
        if _ventilation_role(context) != "supply":
            # Проветривание — режим притока: у вытяжки его нет (BACKLOG B74).
            return REASON_NOT_APPLICABLE
        allowed, reason = _ventilation_allowed(context)
        return reason if not allowed else None

    owner_wants_airing.deny_reason = deny_reason  # type: ignore[attr-defined]
    return owner_wants_airing


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
            return REASON_NOT_APPLICABLE
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
