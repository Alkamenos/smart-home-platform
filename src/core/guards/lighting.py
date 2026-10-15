"""Условия света и ручного управления (B80).

Вынесено из `builtin.py`: у света своя причина меняться — окна тишины, ночь,
ручная блокировка, сон.
"""

import logging
import time
from collections.abc import Callable
from datetime import datetime
from typing import Any

from core.guards.climate import (
    _cooling_applicable as _cooling_applicable,
    _cooling_denial as _cooling_denial,
    _heating_denial as _heating_denial,
)
from core.guards.context import (
    DEFAULT_QUIET_FROM as DEFAULT_QUIET_FROM,
    DEFAULT_QUIET_TO as DEFAULT_QUIET_TO,
    _context_zone as _context_zone,
    _dark_enough as _dark_enough,
    _motion_is_echo as _motion_is_echo,
    _now_in as _now_in,
    _parse_hhmm as _parse_hhmm,
    _temperature_value as _temperature_value,
)


logger = logging.getLogger(__name__)


def make_may_turn_on(
    *,
    now: Callable[[Any], datetime] = _now_in,
    wall_clock: Callable[[], float] = time.time,
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
        wall_clock: Настенные часы; по ним считается «сколько секунд назад свет
            был выключен» (время команды настенное и переживает перезапуск).

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
        minutes = current.hour * 60 + current.minute
        start_minutes = start[0] * 60 + start[1]
        end_minutes = end[0] * 60 + end[1]
        in_quiet = (
            start_minutes <= minutes <= end_minutes
            if start_minutes <= end_minutes
            else minutes >= start_minutes or minutes <= end_minutes
        )

        if room in always_rooms:
            allowed = True
        elif in_quiet:
            # Ночью при известном модификаторе решает только он: False —
            # владелец не спит, и движение включает свет, если темно (по
            # правилу владельца «свет по движению всегда, кроме периода мы
            # спим»). Окно тишины спрашивается, только когда сущности в доме
            # нет: тогда ночь уходит в ночные комнаты, как раньше.
            allowed = _dark_enough(context, current) if modifier is False else room in night_rooms
        else:
            allowed = _dark_enough(context, current)

        if not allowed:
            return False
        # Последняя проверка — эхо датчика. Настоящие причины уже названы выше
        # (см. `deny_reason`): эхо объясняет только тот случай, когда по всем
        # правилам включать можно было, но движение пришло в первые секунды
        # после нашего же выключения (камера увидела смену освещённости).
        return not _motion_is_echo(context, wall_clock)

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
        # Настоящих причин нет: остаётся эхо датчика — движение в первые секунды
        # после нашего же выключения (камера увидела смену освещённости).
        if _motion_is_echo(context, wall_clock):
            return "motion_echo"
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
        """Отказать: заброшенное условие не должно пропускать переход.

        Заброшенное условие обязано **отказывать**, а не разрешать. Прежде оно
        всегда возвращало «да», и ссылка на него в шаблоне молча пропустила бы
        переход — ровно тот боевой дефект с гирляндой, из-за которого условие и
        убрали. Отказ громкий: «перехода нет» видно в журнале, а тихое «да» не
        видно нигде (аудит 2026-10-16, К-15).

        Args:
            state: Текущее состояние автомата.
            context: Контекст перехода.

        Returns:
            Всегда ``False``.
        """
        del state, context
        return False

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
        if not _cooling_applicable(context):
            # Обогреватель: «ничего не делать» — штатное решение, когда греть
            # незачем по температуре. Гейт кондиционера к обогревателю не
            # относится, и отказ «кондиционер запрещён» по обогревателю был
            # шумом — около 720 записей в сутки (B66).
            return _heating_denial(context) == "not_cold_enough"
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
        if not _cooling_applicable(context):
            # Причину называет обогрев — она и мешала (климат выключен, нет
            # уставки, в комнате свой термостат).
            return _heating_denial(context)
        if _cooling_denial(context) == "not_above_comfort":
            return None
        return _cooling_denial(context) or "guard_data_missing"

    may_stay_idle.deny_reason = deny_reason  # type: ignore[attr-defined]
    return may_stay_idle
