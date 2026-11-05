"""?????? ?????? ??????? ? ???? ??????????? (????? 018, US4).

???????? ?? `watchdog.py`: ?????? ???????? ? ??? ?????? ? ?????? ???????
?????????. ????? ???????????????? ?? `services.watchdog` ??? ?????????????.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime


DEFAULT_INTERVAL_SEC = 60.0
DEFAULT_STUCK_GRACE_SEC = 30.0
DEFAULT_HA_LOSS_SEC = 300.0


CHECK_RESULT_OK = "ok"
CHECK_RESULT_DEGRADED = "degraded"
CHECK_RESULT_FAILED = "failed"

# --- Расхождение «автомат ↔ прибор» (концепция §7, п. 4) --------------------
#
# Виды расхождения. Названы отдельно, потому что утренний разбор обязан
# отличать «прибор горит, хотя решение — выключено» (команда не применилась)
# от «решение — включить, а прибор не горит» и от «прибор недоступен».
MISMATCH_DEVICE_ON_DECISION_OFF = "device_on_decision_off"
MISMATCH_DEVICE_OFF_DECISION_ON = "device_off_decision_on"
MISMATCH_DEVICE_UNAVAILABLE = "device_unavailable"

#: Обогреватель включён, а решение — «не греть». Отдельное имя, потому что это
#: не та же уступка человеку, что у света: включённый без решения обогреватель
#: греет дом и жжёт энергию, а цена ошибки выше. Боевой повод — 01.11: сбой
#: обнуления таймера оставил радиатор включённым, и сторож назвал это уступкой
#: (`device_on_decision_off`), а не проблемой.
MISMATCH_CLIMATE_ON_DECISION_OFF = "climate_on_decision_off"

#: Расхождение из-за действующего ручного оверрайда: человек вмешался, и
#: автоматика **обязана** уступить (концепция §7, п. 2). Это не отказ: тревоги
#: и счётчика проблем оно не порождает, но в журнале и интерфейсе видно — иначе
#: «почему прибор не как решила автоматика» остаётся без ответа.
MISMATCH_MANUAL_OVERRIDE = "manual_override_active"

#: Виды расхождения, которые являются отказом (проблема), а не уступкой человеку.
#:
#: «Прибор включён, а решение — выключить» здесь **намеренно нет**: такого мы не
#: просили. Включить прибор мог только кто-то другой — человек у выключателя,
#: кнопка, сценарий Home Assistant. Повторять в ответ своё «выключить» значит
#: гасить свет за человеком (боевая жалоба владельца 2026-10-16: включил свет в
#: спальне, через полминуты он погас — и так трижды).
#:
#: Отказ — это обратное: мы решили включить, а прибор не включился (наша команда
#: не дошла). Только такие расхождения и повторяются.
MISMATCH_FAULT_REASONS = frozenset(
    {
        MISMATCH_DEVICE_OFF_DECISION_ON,
        MISMATCH_DEVICE_UNAVAILABLE,
        MISMATCH_CLIMATE_ON_DECISION_OFF,
    }
)

#: Состояния прибора, означающие «включено».
DEVICE_ON_STATES = frozenset({"on", "open", "opening"})

#: Состояния прибора, означающие «выключено».
DEVICE_OFF_STATES = frozenset({"off", "closed", "closing"})

#: Состояния прибора, означающие «прибор не отвечает»: молчание — не согласие.
DEVICE_UNAVAILABLE_STATES = frozenset({"unavailable", "unknown", "none"})

#: Имена состояний автомата, означающие решение «прибор выключен». Нужны, когда
#: движок не сохранил исход решения (переход без действия): тогда состояние
#: читается по имени. Остальные известные состояния — «включён».
IDLE_LIKE_STATES = frozenset({"OFF", "IDLE", "CLOSED", "STANDBY"})

#: Имена состояний автомата, означающие работу прибора: рекуператор и климат
#: называют работу словом, а не префиксом `ON`.
ACTIVE_STATES = frozenset({"HEATING", "COOLING", "SUPPLY", "AIRING", "EXHAUST", "DRY", "OPEN"})

#: Событие «прибор разошёлся с решением»: автомат повторяет **своё** решение тем
#: же действием, что и в обычном переходе. Сторож команду не выдумывает.
DEVICE_DIVERGED_TRIGGER = "device_state_diverged"

#: Сколько раз повторять решение для одного прибора. Прибор, который не отвечает
#: (граница радиосвязи, недоступность), иначе получал бы команду каждый цикл
#: сторожа: после нескольких повторов остаётся тревога, а не поток команд.
DIVERGENCE_REASSERT_ATTEMPTS = 3

# Значение метки, которым помечаются активные зависшие автоматы в показателях.
STUCK_LABEL_VALUE = "1"

# Сколько ждём завершения публикаций событий при остановке.
PUBLISH_DRAIN_TIMEOUT_SEC = 1.0


@dataclass(frozen=True)
class WatchdogSettings:
    """Настройки периодической проверки состояний.

    Attributes:
        enabled: Запускать ли сторож.
        interval_sec: Интервал между проверками.
        stuck_grace_sec: Запас сверх ожидаемого времени пребывания.
        ha_loss_sec: Порог, после которого потеря связи считается проблемой.
    """

    enabled: bool = True
    interval_sec: float = DEFAULT_INTERVAL_SEC
    stuck_grace_sec: float = DEFAULT_STUCK_GRACE_SEC
    ha_loss_sec: float = DEFAULT_HA_LOSS_SEC


@dataclass(frozen=True)
class FsmSnapshotEntry:
    """Состояние одного автомата на момент проверки.

    Attributes:
        entity_id: Идентификатор автомата.
        device: Устройство автомата.
        state: Текущее состояние.
        entered_at: Момент входа в состояние (монотонные часы).
        last_transition: Настенное время последнего перехода.
        stuck: Пребывание дольше ожидаемого.
        expected_timeout_sec: Ожидаемое время пребывания; ``None`` — состояние
            не проверяется зависанием.
        device_state: Фактическое состояние прибора, прочитанное у внешней
            системы; ``None`` — не читали или прибор не ответил.
        device_position: Положение шторы (0–100), если прибор его отдаёт;
            ``None`` — не штора или положение неизвестно.
        device_moving: Прибор в движении (``opening``/``closing``): команду
            посреди хода не повторяем.
        mismatch_reason: Названное расхождение «автомат ↔ прибор»; ``None`` —
            расхождения нет.
    """

    entity_id: str
    device: str
    state: str
    entered_at: float
    last_transition: str | None
    stuck: bool
    expected_timeout_sec: float | None
    device_state: str | None = None
    device_position: int | None = None
    device_moving: bool = False
    mismatch_reason: str | None = None

    @property
    def mismatch(self) -> bool:
        """Расходится ли прибор с решением автомата.

        Returns:
            True, если расхождение названо.
        """
        return self.mismatch_reason is not None

    @property
    def mismatch_is_fault(self) -> bool:
        """Отказ ли это, а не уступка ручному действию человека.

        Returns:
            True, если расхождение — отказ (команда не применилась, прибор
            недоступен); False для уступки ручному оверрайду.
        """
        return self.mismatch_reason in MISMATCH_FAULT_REASONS


@dataclass(frozen=True)
class FsmSnapshot:
    """Снимок состояний всех автоматов на момент одной проверки.

    Attributes:
        taken_at: Время снятия снимка (настенное).
        entries: По одной записи на каждый автомат.
        problem_count: Число зависаний в снимке.
        ha_checked: Проверялась ли связь с внешней системой.
        ha_disconnected: Зафиксирована ли потеря связи.
        failed: Не удалось ли выполнить проверку.
    """

    taken_at: str
    entries: tuple[FsmSnapshotEntry, ...] = ()
    problem_count: int = 0
    ha_checked: bool = False
    ha_disconnected: bool = False
    failed: bool = False

    @property
    def result(self) -> str:
        """Результат проверки для показателя.

        Returns:
            ``failed``, ``degraded`` либо ``ok``.
        """
        if self.failed:
            return CHECK_RESULT_FAILED
        if self.problem_count or self.ha_disconnected:
            return CHECK_RESULT_DEGRADED
        return CHECK_RESULT_OK

    def to_json(self) -> str:
        """Представить снимок строкой JSON для журнала.

        Returns:
            JSON снимка без гарантии порядка ключей.
        """
        return json.dumps(
            {
                "taken_at": self.taken_at,
                "fsm_count": len(self.entries),
                "problem_count": self.problem_count,
                "ha_checked": self.ha_checked,
                "ha_disconnected": self.ha_disconnected,
                "result": self.result,
                "states": {
                    entry.entity_id: {
                        "device": entry.device,
                        "state": entry.state,
                        "last_transition": entry.last_transition,
                        "expected_timeout_sec": entry.expected_timeout_sec,
                        "stuck": entry.stuck,
                        "device_state": entry.device_state,
                        "device_position": entry.device_position,
                        "device_moving": entry.device_moving,
                        "mismatch": entry.mismatch_reason,
                    }
                    for entry in self.entries
                },
            },
            ensure_ascii=False,
        )


def _now_timestamp() -> str:
    """Текущее настенное время в формате интерфейса.

    Returns:
        Время ISO-8601 без часового пояса.
    """
    return datetime.now(UTC).replace(tzinfo=None).isoformat(timespec="seconds")
