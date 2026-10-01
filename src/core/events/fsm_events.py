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
