"""
Имена событий перехода автомата и сборка их полезной нагрузки.

Модуль отделяет формат событий от мест их публикации и потребления: движок
состояний формирует полезную нагрузку здесь, подписчики (хранилище состояний,
журнал переходов, веб-мост) читают её в этом же формате.

Формат — плоский словарь с настенным временем ISO-8601, тем же, что уже
используют события жизненного цикла устройств (`contracts/fsm-events.md`).

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Final


# Имена событий
EVENT_FSM_TRANSITIONED: Final[str] = "fsm.transitioned"
EVENT_FSM_REJECTED: Final[str] = "fsm.rejected"
EVENT_FSM_RESTORED: Final[str] = "fsm.restored"
EVENT_PLATFORM_STARTED: Final[str] = "platform.started"
# Проблема платформы: зависший автомат или потеря связи с внешней системой.
# Публикуется сторожем только при появлении и устранении, а не каждый цикл.
EVENT_PLATFORM_PROBLEM: Final[str] = "platform.problem"

# Виды проблем
PROBLEM_FSM_STUCK: Final[str] = "fsm_stuck"
PROBLEM_HA_DISCONNECTED: Final[str] = "ha_disconnected"

# Признак выполненного перехода и признак отказа
OUTCOME_TRANSITIONED: Final[str] = "transitioned"
OUTCOME_REJECTED: Final[str] = "rejected"

# Источник перехода
SOURCE_MANUAL: Final[str] = "manual"
SOURCE_AUTOMATIC: Final[str] = "automatic"

# Префиксы имён событий, означающих ручное вмешательство пользователя.
# Признак источника выводится из имени триггера: движок состояний не хранит
# ни приоритетов, ни признака источника (research R-03).
MANUAL_EVENT_PREFIXES: Final[tuple[str, ...]] = ("manual_",)

# Причины отказа в переходе
REASON_UNKNOWN_ENTITY: Final[str] = "unknown_entity"
REASON_NO_STATE: Final[str] = "no_state"
REASON_DEBOUNCED: Final[str] = "debounced"
REASON_NO_TRANSITION: Final[str] = "no_transition"
REASON_GUARD_FAILED: Final[str] = "guard_failed"
#: Отдельная причина для условия, которому не передали данные.
#:
#: Раньше «данных не было» и «значение не подходит» давали одну и ту же
#: формулировку, и владелец не мог отличить штатную работу от молчащей поломки:
#: поведение, описанное в манифесте, просто не срабатывало, и это выглядело как
#: «влажность ниже порога», а не как «влажности не было никогда».
REASON_GUARD_DATA_MISSING: Final[str] = "guard_data_missing"
#: Отказ из-за ночного окна: условие «можно ли включать» отказало по времени.
#:
#: Отдельное имя нужно потому, что «условие не прошло» и «сейчас ночь» — разные
#: ситуации для владельца: во втором случае он ждёт утра, а в первом стоит искать,
#: почему датчик молчит. В журнале ночная защита выглядела как отказ без причины.
REASON_QUIET_HOURS: Final[str] = "quiet_hours"
#: Отказ из-за модификатора «мы спим»: владелец включил его в Home Assistant,
#: и яркий свет не включается — это отдельная от ночного окна ситуация.
#:
#: Ночное окно платформа считает сама по часам, а модификатор владелец включает
#: своей автоматизацией HA. В журнале их нельзя смешивать: утром по «quiet_hours»
#: владелец решил бы, что расписание сработало не так, хотя на самом деле он сам
#: включил «спим» (требование 2026-10-09: лог должен позволять сравнить
#: поведение с ожидаемой логикой).
REASON_SLEEP_MODIFIER: Final[str] = "sleep_modifier"
#: Причины климата (спека 011). Каждая отвечает на свой вопрос утреннего
#: анализа, и склеивать их нельзя: «уставку не прочитали», «уставка 95 °C»,
#: «климат выключен владельцем» и «в комнате свой термостат» — это четыре разные
#: ситуации, и по одной записи в журнале утром должно быть видно, что именно
#: мешало.
#:
#: Уставка вне диапазона отделена от её отсутствия: молчаливый отказ при
#: сломанной настройке выглядел бы как «данных нет», и поломка жила бы годами.
REASON_SETPOINT_UNAVAILABLE: Final[str] = "setpoint_unavailable"
REASON_CLIMATE_DISABLED: Final[str] = "climate_disabled"
REASON_AC_NOT_ALLOWED: Final[str] = "ac_not_allowed"
REASON_AC_FORBIDDEN_IN_WINTER: Final[str] = "ac_forbidden_in_winter"
REASON_MANAGED_BY_HARDWARE: Final[str] = "managed_by_hardware"
#: Отказ ночника: модификатор «мы спим» известен и выключен — штатное решение
#: (ночник работает только, пока владелец спит). Раньше оно оставалось
#: ``guard_failed`` — «условие отказало», — и утренний анализ не мог отличить
#: «ночник не включался, потому что не спим» от поломки: в живом журнале
#: 2026-10-09 каждое вечернее движение давало ночнику guard_failed.
REASON_MODIFIER_OFF: Final[str] = "modifier_off"
#: Отказ, потому что светло: солнце над горизонтом или часы дома говорят «день».
#:
#: Раньше такой отказ не имел своего имени и попадал в ``guard_failed`` —
#: «условие отказало» не объясняет владельцу ничего, а утренний анализ требует
#: различать «спим», «ночь», «данных нет» и «просто светло» (правило о логах
#: 2026-10-09). Отказ «светло» — штатное решение, а не поломка датчика.
REASON_DAYLIGHT: Final[str] = "daylight"

#: Причины, которые условие может назвать само (словарь ограничен, чтобы метрика
#: не расползалась новыми метками). ``guard_data_missing`` здесь потому, что
#: условие ночника тоже умеет назвать его само: модификатор «мы спим» — булево,
#: а не показание датчика, и штатный путь «данных не было» (по ``requires``) на
#: нём не срабатывает; без имени отказ выглядел бы одинаково и при «спим», и
#: при «состояние не прочитано» — утром эти две ситуации надо различать.
GUARD_DENIAL_REASONS: Final[frozenset[str]] = frozenset(
    {
        REASON_QUIET_HOURS,
        REASON_SLEEP_MODIFIER,
        REASON_MODIFIER_OFF,
        REASON_GUARD_DATA_MISSING,
        REASON_DAYLIGHT,
        REASON_SETPOINT_UNAVAILABLE,
        REASON_CLIMATE_DISABLED,
        REASON_AC_NOT_ALLOWED,
        REASON_AC_FORBIDDEN_IN_WINTER,
        REASON_MANAGED_BY_HARDWARE,
    }
)

# Человеческие формулировки причин отказа (T007, FR-008).
# Используются в интерфейсе (карточка) и совпадают с журналом.
REASON_TEXT: Final[dict[str, str]] = {
    REASON_UNKNOWN_ENTITY: "сущность не найдена",
    REASON_NO_STATE: "состояние не инициализировано",
    REASON_DEBOUNCED: "слишком быстрые события",
    REASON_NO_TRANSITION: "нет подходящего переходов",
    REASON_GUARD_FAILED: "условие не пройдено",  # fallback for unknown guard denials
    REASON_GUARD_DATA_MISSING: "нет данных для проверки",
    REASON_QUIET_HOURS: "ночное окно закрыто",
    REASON_SLEEP_MODIFIER: "выключено модификатором сна",
    REASON_MODIFIER_OFF: "ночник отключен",
    REASON_DAYLIGHT: "светло",
    REASON_SETPOINT_UNAVAILABLE: "уставка недоступна",
    REASON_CLIMATE_DISABLED: "климат отключен",
    REASON_AC_NOT_ALLOWED: "кондиционер запрещен",
    REASON_AC_FORBIDDEN_IN_WINTER: "кондиционер зимой не разрешен",
    REASON_MANAGED_BY_HARDWARE: "управляется отдельным контроллером",
    # Коды действий (T007)
    "action_on": "включено по расписанию",
    "action_off": "выключено по расписанию",
    "action": "изменено по расписанию",
}

# Формат времени во всех разделах интерфейса (FR-023)
TIMESTAMP_FORMAT: Final[str] = "%Y-%m-%dT%H:%M:%S.%f"


def now_timestamp() -> str:
    """Получить текущее настенное время в формате интерфейса.

    Returns:
        Строка времени в формате ISO-8601 без часового пояса.
    """
    return datetime.now(UTC).replace(tzinfo=None).strftime(TIMESTAMP_FORMAT)


def classify_source(event: str) -> str:
    """Определить источник перехода по имени события-триггера.

    Args:
        event: Имя события, вызвавшего переход.

    Returns:
        ``manual``, если имя события начинается с известного ручного префикса,
        иначе ``automatic``.
    """
    return SOURCE_MANUAL if event.startswith(MANUAL_EVENT_PREFIXES) else SOURCE_AUTOMATIC


def split_fsm_id(fsm_id: str) -> tuple[str, str]:
    """Разделить идентификатор автомата на устройство и имя поведения.

    Идентификатор строится по схеме ``{устройство}_{шаблон}_{приоритет}``
    (ADR-003): устройство может содержать точки, но не подчёркивания, поэтому
    разбор идёт справа: последний сегмент — приоритет, предпоследний — шаблон,
    всё остальное — устройство.

    Args:
        fsm_id: Идентификатор автомата.

    Returns:
        Пара ``(устройство, имя поведения)``. Если идентификатор не соответствует
        схеме, возвращается исходное значение и пустое имя поведения.
    """
    parts = fsm_id.rsplit("_", 2)
    if len(parts) != 3 or not parts[0] or not parts[1]:
        return fsm_id, ""
    return parts[0], parts[1]


def build_transition_payload(
    fsm_id: str,
    device_id: str,
    from_state: str | None,
    to_state: str | None,
    event: str,
    outcome: str,
    trace_id: str | None = None,
    reason: str | None = None,
) -> dict[str, Any]:
    """Собрать полезную нагрузку события перехода.

    Args:
        fsm_id: Идентификатор автомата.
        device_id: Фактическое устройство автомата.
        from_state: Предыдущее состояние; ``None`` при первом входе.
        to_state: Новое состояние; ``None`` при отказе.
        event: Имя события-триггера.
        outcome: ``transitioned`` или ``rejected``.
        trace_id: Идентификатор трассы для корреляции по журналу.
        reason: Причина отказа; обязательна при ``outcome="rejected"``.

    Returns:
        Плоский словарь с полями события (``contracts/fsm-events.md``).

    Raises:
        ValueError: Если обязательное поле отсутствует: пустой ``fsm_id``,
            отсутствуют ``to_state`` или ``event`` для выполненного перехода,
            отсутствует ``reason`` для отказа.
    """
    if not fsm_id:
        raise ValueError("fsm_id is required to build a transition payload")

    if outcome == OUTCOME_TRANSITIONED and (not to_state or not event):
        raise ValueError("to_state and event are required for a performed transition")

    if outcome == OUTCOME_REJECTED and not reason:
        raise ValueError("reason is required for a rejected transition")

    behavior = split_fsm_id(fsm_id)[1]

    return {
        "fsm_id": fsm_id,
        "device_id": device_id,
        "behavior": behavior,
        "from_state": from_state,
        "to_state": to_state,
        "event": event,
        "source": classify_source(event),
        "timestamp": now_timestamp(),
        "outcome": outcome,
        "trace_id": trace_id,
        "reason": reason,
    }
