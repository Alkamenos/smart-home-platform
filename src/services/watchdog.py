"""
Сторож платформы: периодические снимки состояний и сигналы о проблемах.

Сторож отвечает на вопрос, на который платформа иначе не отвечает: «что
застряло?». Он снимает состояния автоматов, сравнивает время пребывания с
ожидаемым и сообщает о зависании; отдельно следит за связью с внешней
системой.

Три свойства, ради которых модуль переписан (решение D-1):

- **Ожидаемое время пребывания выводится из описания автомата**
  (``FSMEngine.expected_timeout_sec``), а не задаётся числом в конфигурации.
  Ручной порог стал бы вторым источником правды, способным разойтись с
  описанием автомата.
- **Состояние без таймингованных переходов зависшим не считается**: оно живёт,
  пока не придёт событие. Иначе «зависанием» был бы всякий ночной свет.
- **Снимок асинхронный.** Прежний цикл вызывал синхронный метод через
  ``await``, падал с ``TypeError`` на первом же проходе и повторял ошибку до
  остановки платформы.

Настройки приходят из переменных окружения; сбой одной проверки не прерывает
цикл и не влияет на работу автоматики (FR-018).

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import time
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from typing import Any, Protocol

from core.events.fsm_events import (
    EVENT_PLATFORM_PROBLEM,
    PROBLEM_DEVICE_MISMATCH,
    PROBLEM_FSM_STUCK,
    PROBLEM_HA_DISCONNECTED,
)
from core.fsm.engine import _diagnostic_context, _is_diagnostic_entity
from core.logger import get_logger


logger = get_logger(__name__)


# Настройки сторожа читаются из переменных окружения по образцу работающего
# ``hot_reload_enabled()`` (FR-019, R-07). Схема манифеста не меняется.
WATCHDOG_ENABLED_ENV = "WATCHDOG_ENABLED"
WATCHDOG_INTERVAL_ENV = "WATCHDOG_INTERVAL_SEC"
WATCHDOG_GRACE_ENV = "WATCHDOG_STUCK_GRACE_SEC"
WATCHDOG_HA_LOSS_ENV = "WATCHDOG_HA_LOSS_SEC"

DEFAULT_INTERVAL_SEC = 60.0
DEFAULT_STUCK_GRACE_SEC = 30.0
DEFAULT_HA_LOSS_SEC = 300.0

_TRUTHY_VALUES = ("1", "true", "yes", "on")

# Результаты проверок для метрики watchdog_checks_total
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
    mismatch_reason: str | None = None

    @property
    def mismatch(self) -> bool:
        """Расходится ли прибор с решением автомата.

        Returns:
            True, если расхождение названо.
        """
        return self.mismatch_reason is not None


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
                        "mismatch": entry.mismatch_reason,
                    }
                    for entry in self.entries
                },
            },
            ensure_ascii=False,
        )


class EngineProtocol(Protocol):
    """Минимальный контракт движка состояний, нужный сторожу."""

    def get_all_states(self) -> dict[str, Any]: ...

    def expected_timeout_sec(self, entity_id: str) -> float | None: ...

    def device_id_of(self, entity_id: str) -> str | None: ...

    def get_last_transition_time(self, entity_id: str) -> str | None: ...

    def explain(self, entity_id: str) -> Any | None: ...


class AdapterProtocol(Protocol):
    """Минимальный контракт внешней системы, нужный сторожу.

    Объявлен вместо импорта класса адаптера: сторож спрашивает лишь признак
    связи и состояние прибора, и не должен зависеть от конкретной реализации
    (R-13).
    """

    # Имя именно `is_connected`: так объявляют обе настоящие реализации —
    # `HAAdapter.is_connected` и `MockAdapter.is_connected`. Раньше здесь стояло
    # `connected`, и сторож в контейнере падал каждый цикл с AttributeError.
    @property
    def is_connected(self) -> bool: ...

    async def get_entity_state(self, entity_id: str) -> str | None: ...


class MetricsProtocol(Protocol):
    """Минимальный контракт сборщика показателей, нужный сторожу."""

    def record_watchdog_check(self, result: str) -> None: ...

    def record_fsm_stuck(self, fsm_name: str, state: str) -> None: ...

    def set_fsm_stuck(self, fsm_name: str, count: int) -> None: ...

    def set_ha_connection_lost(self, lost: bool) -> None: ...

    def set_watchdog_snapshot_timestamp(self, timestamp: float) -> None: ...


def _now_timestamp() -> str:
    """Текущее настенное время в формате интерфейса.

    Returns:
        Время ISO-8601 без часового пояса.
    """
    return datetime.now(UTC).replace(tzinfo=None).isoformat(timespec="seconds")


def watchdog_enabled() -> bool:
    """Проверить, включён ли сторож (по умолчанию включён).

    Returns:
        True, если сторож должен работать.
    """
    return os.getenv(WATCHDOG_ENABLED_ENV, "1").strip().lower() in _TRUTHY_VALUES


def _positive_number(env_name: str, default: float) -> float:
    """Прочитать положительное число из окружения.

    Некорректное значение (не число, ноль, отрицательное) заменяется
    значением по умолчанию с предупреждением: сбой настройки не должен ронять
    старт платформы (FR-019).

    Args:
        env_name: Имя переменной окружения.
        default: Значение по умолчанию.

    Returns:
        Значение настройки.
    """
    raw = os.getenv(env_name)
    if raw is None:
        return default
    try:
        value = float(raw)
    except ValueError:
        logger.warning(f"Invalid {env_name}={raw!r}; using default {default}")
        return default
    if value <= 0:
        logger.warning(f"{env_name}={raw!r} is not positive; using default {default}")
        return default
    return value


def watchdog_interval_sec() -> float:
    """Прочитать интервал проверок состояний.

    Returns:
        Интервал в секундах.
    """
    return _positive_number(WATCHDOG_INTERVAL_ENV, DEFAULT_INTERVAL_SEC)


def watchdog_stuck_grace_sec() -> float:
    """Прочитать запас сверх ожидаемого времени пребывания.

    Returns:
        Запас в секундах.
    """
    return _positive_number(WATCHDOG_GRACE_ENV, DEFAULT_STUCK_GRACE_SEC)


def watchdog_ha_loss_sec() -> float:
    """Прочитать порог потери связи с внешней системой.

    Returns:
        Порог в секундах.
    """
    return _positive_number(WATCHDOG_HA_LOSS_ENV, DEFAULT_HA_LOSS_SEC)


def watchdog_settings() -> WatchdogSettings:
    """Собрать настройки сторожа из окружения.

    Returns:
        Настройки сторожа.
    """
    return WatchdogSettings(
        enabled=watchdog_enabled(),
        interval_sec=watchdog_interval_sec(),
        stuck_grace_sec=watchdog_stuck_grace_sec(),
        ha_loss_sec=watchdog_ha_loss_sec(),
    )


@dataclass
class _TrackedProblem:
    """Активная проблема, ожидающая устранения.

    Attributes:
        kind: Вид проблемы.
        entity_id: Автомат либо ``None`` для потери связи.
        detected_at: Настенное время обнаружения.
        detected_monotonic: Монотонное время обнаружения.
    """

    kind: str
    entity_id: str | None
    detected_at: str
    detected_monotonic: float


def _device_mismatch_reason(expected: frozenset[str], actual: str | None) -> str | None:
    """Назвать расхождение «автомат ↔ прибор».

    Args:
        expected: Допустимые состояния прибора по решению автомата.
        actual: Фактическое состояние прибора; ``None`` — не прочитано.

    Returns:
        Вид расхождения либо ``None``, если прибор согласен с решением или
        ответа не было (молчание — не согласие, но и не приговор: его называют
        отдельным видом ``device_unavailable`` только по явному состоянию).
    """
    if actual is None:
        return None
    if actual in DEVICE_UNAVAILABLE_STATES:
        return MISMATCH_DEVICE_UNAVAILABLE
    if actual in expected:
        return None
    if actual in DEVICE_ON_STATES:
        return MISMATCH_DEVICE_ON_DECISION_OFF
    if actual in DEVICE_OFF_STATES:
        return MISMATCH_DEVICE_OFF_DECISION_ON
    return None


@dataclass
class WatchdogService:
    """Периодическая проверка состояний автоматов и связи с внешней системой.

    Args:
        fsm_engine: Движок состояний.
        metrics: Сборщик показателей; может быть ``None`` — тогда проверки
            идут, но в показатели ничего не пишется.
        adapter: Внешняя система; ``None`` в автономном режиме.
        settings: Настройки проверок.
        event_bus: Шина событий для публикации обнаруженных проблем; может
            быть ``None``.
        clock: Источник монотонного времени; подменяется в тестах.
    """

    fsm_engine: EngineProtocol
    metrics: MetricsProtocol | None = None
    adapter: AdapterProtocol | None = None
    settings: WatchdogSettings = field(default_factory=WatchdogSettings)
    event_bus: Any | None = None
    clock: Callable[[], float] = time.monotonic

    # Последний снимок хранится, чтобы проверка готовности могла судить о
    # свежести: без него «сторож молчит» и «сторож не работает» неразличимы.
    _last_snapshot: FsmSnapshot | None = None
    _task: asyncio.Task[None] | None = None
    _running: bool = False
    _disconnected_since: float | None = None
    _problems: dict[tuple[str, str | None], _TrackedProblem] = field(default_factory=dict)
    _publish_tasks: set[asyncio.Task[None]] = field(default_factory=set)

    # Жизненный цикл

    @property
    def last_snapshot(self) -> FsmSnapshot | None:
        """Последний снимок проверки.

        Нужен читателям (готовность, тревоги интерфейса): без него «сторож
        молчит» и «сторож не работает» неразличимы.

        Returns:
            Снимок либо ``None``, если проверок ещё не было.
        """
        return self._last_snapshot

    def start(self) -> None:
        """Запустить фоновый цикл проверок.

        Синхронный метод намеренно: контейнер собирает платформу синхронно, и
        ожидаемая корутина без ``await`` там была бы ошибкой, из-за которой
        сторож не запускался бы вовсе.

        Повторный запуск игнорируется: второй цикл удваивал бы нагрузку и
        число проверок в показателях.
        """
        if self._running:
            logger.warning("Watchdog already running")
            return
        self._running = True
        self._task = asyncio.create_task(self._watchdog_loop())
        logger.info(f"Watchdog started (interval={self.settings.interval_sec}s)")

    async def stop(self) -> None:
        """Остановить фоновый цикл и дождаться его завершения."""
        self._running = False
        task, self._task = self._task, None
        if task is not None and not task.done():
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        await self._drain_publish_tasks()
        logger.info("Watchdog stopped")

    async def _drain_publish_tasks(self) -> None:
        """Дождаться публикаций событий проблем, чтобы они не потерялись."""
        pending = list(self._publish_tasks)
        if not pending:
            return
        done, still_pending = await asyncio.wait(pending, timeout=PUBLISH_DRAIN_TIMEOUT_SEC)
        del done
        for task in still_pending:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

    async def _watchdog_loop(self) -> None:
        """Цикл проверок: сбой одной проверки не прерывает цикл (FR-018).

        Первая проверка выполняется сразу, а не через интервал: иначе после
        запуска платформы первый снимок появлялся бы через минуту, и за это
        окно не был бы виден ни один зависший автомат.
        """
        while self._running:
            try:
                await self.check_once()
            except asyncio.CancelledError:
                break
            except Exception as exc:  # noqa: BLE001 - цикл обязан выжить
                logger.warning(f"Watchdog check failed unexpectedly: {type(exc).__name__}: {exc}")
            await asyncio.sleep(self.settings.interval_sec)

    # Проверка

    async def check_once(self) -> FsmSnapshot:
        """Выполнить одну проверку и вернуть снимок.

        Returns:
            Снимок состояний. При сбое чтения состояний возвращается снимок с
            ``failed=True`` и пустым списком автоматов: сбой проверки не должен
            приводить к остановке проверок (FR-018).
        """
        try:
            entries = self._collect_entries()
        except Exception as exc:  # noqa: BLE001 - проверка обязана быть устойчивой
            logger.warning(f"Failed to collect FSM states: {type(exc).__name__}: {exc}")
            snapshot = FsmSnapshot(taken_at=_now_timestamp(), failed=True)
            self._last_snapshot = snapshot
            self._record_metrics(snapshot)
            return snapshot

        entries = await self._with_device_states(entries)
        snapshot = self._with_connection(entries)
        self._last_snapshot = snapshot
        self._record_metrics(snapshot)
        self._publish_problems(snapshot)
        logger.info(f"[WATCHDOG] {snapshot.to_json()}")
        self._log_diagnostics()
        return snapshot

    def _log_diagnostics(self) -> None:
        """Записать снимок входов климата и вентиляции.

        Раз в интервал в журнал уходит не только состояние автомата, но и
        контекст последнего решения: утренний разбор должен видеть ряд значений
        (улица, уставка, флаги, режим, скорость), даже если датчики молчали и
        событий не было. Без этого «ничего не происходило» неотличимо от
        «происходило, но вход был пуст».
        """
        explain = getattr(self.fsm_engine, "explain", None)
        for entity_id, state in self.fsm_engine.get_all_states().items():
            if not _is_diagnostic_entity(entity_id):
                continue
            reason = None
            if explain is not None:
                decision = explain(entity_id)
                reason = getattr(decision, "reason_code", None) if decision else None
            logger.info(
                f"[ДИАГНОСТИКА] {entity_id}: состояние {state.current_state}, "
                f"последнее решение {reason}, вход: "
                f"{_diagnostic_context(getattr(state, 'context', {}) or {})}"
            )

    def _collect_entries(self) -> tuple[FsmSnapshotEntry, ...]:
        """Собрать записи снимка по всем автоматам.

        Returns:
            Кортеж записей снимка.
        """
        now = self.clock()
        entries = []
        for entity_id, state in self.fsm_engine.get_all_states().items():
            expected = self.fsm_engine.expected_timeout_sec(entity_id)
            stuck = self._is_stuck(now, state.entered_at, expected)
            entries.append(
                FsmSnapshotEntry(
                    entity_id=entity_id,
                    device=self.fsm_engine.device_id_of(entity_id) or "",
                    state=state.current_state,
                    entered_at=state.entered_at,
                    last_transition=self.fsm_engine.get_last_transition_time(entity_id),
                    stuck=stuck,
                    expected_timeout_sec=expected,
                )
            )
        return tuple(entries)

    def _is_stuck(self, now: float, entered_at: float, expected_sec: float | None) -> bool:
        """Определить зависание по ожидаемому времени пребывания.

        Args:
            now: Текущее монотонное время.
            entered_at: Момент входа в состояние.
            expected_sec: Ожидаемое время пребывания; ``None`` — не проверять.

        Returns:
            True, если автомат застрял.
        """
        if expected_sec is None:
            return False
        return (now - entered_at) > expected_sec + self.settings.stuck_grace_sec

    async def _with_device_states(
        self, entries: tuple[FsmSnapshotEntry, ...]
    ) -> tuple[FsmSnapshotEntry, ...]:
        """Дополнить снимок фактическим состоянием приборов (концепция §7, п. 4).

        «Автомат ↔ прибор» — отдельное наблюдаемое состояние. Решение может быть
        «выключено», а прибор гореть: команда не применилась, прибор недоступен,
        кто-то включил свет мимо платформы. Без сверки такое расхождение невидимо,
        и утренний разбор не отличает «не мог» от «сделал». Сбой чтения — не
        расхождение: молчание внешней системы не повод объявлять отказ решения.

        Args:
            entries: Записи снимка по автоматам.

        Returns:
            Записи с фактическим состоянием прибора и названным расхождением.
        """
        reader = getattr(self.adapter, "get_entity_state", None)
        if reader is None:
            return entries

        enriched: list[FsmSnapshotEntry] = []
        for entry in entries:
            expected = self._expected_device_state(entry.entity_id, entry.state)
            if expected is None or not entry.device:
                enriched.append(entry)
                continue
            actual = await self._read_device_state(reader, entry.device)
            reason = _device_mismatch_reason(expected, actual)
            if reason is not None:
                logger.warning(
                    f"Расхождение «автомат ↔ прибор»: {entry.device} — автомат "
                    f"{entry.entity_id} в состоянии {entry.state}, прибор {actual!r} "
                    f"({reason})"
                )
            enriched.append(replace(entry, device_state=actual, mismatch_reason=reason))
        return tuple(enriched)

    async def _read_device_state(self, reader: Any, entity_id: str) -> str | None:
        """Прочитать состояние прибора, не роняя проверку.

        Args:
            reader: Асинхронный читатель состояния у адаптера.
            entity_id: Сущность прибора.

        Returns:
            Состояние в нижнем регистре либо ``None``, если прибор не ответил.
        """
        try:
            value = await reader(entity_id)
        except Exception as exc:  # noqa: BLE001 — проверка обязана быть устойчивой
            logger.warning(f"Сторож: состояние прибора {entity_id} не прочитано: {exc}")
            return None
        if value is None:
            return None
        return str(value).strip().lower()

    def _expected_device_state(self, entity_id: str, state: str) -> frozenset[str] | None:
        """Каким должен быть прибор по решению автомата.

        Сначала спрашивается решение движка (``outcome`` — «on»/«off»): оно
        записано действием перехода, а не выведено из имени состояния. Если
        решения нет (переход без действия), состояние читается по имени:
        ``OFF``/``IDLE``/``CLOSED`` — «выключено», ``ON*`` и работа климата и
        вентиляции — «включено».

        Args:
            entity_id: Автомат.
            state: Текущее состояние автомата.

        Returns:
            Допустимые состояния прибора; ``None`` — сверять нечего (состояние
            неизвестно движку, и угадывать по нему нельзя).
        """
        device = self.fsm_engine.device_id_of(entity_id) or ""
        is_cover = device.split(".", 1)[0] == "cover"

        explain = getattr(self.fsm_engine, "explain", None)
        outcome: str | None = None
        if callable(explain):
            decision = explain(entity_id)
            outcome = getattr(decision, "outcome", None) if decision is not None else None

        if outcome == "off":
            device_on = False
        elif outcome == "on":
            device_on = True
        else:
            name = state.strip().upper()
            if name in IDLE_LIKE_STATES:
                device_on = False
            elif name.startswith("ON") or name in ACTIVE_STATES:
                device_on = True
            else:
                return None

        if is_cover:
            return frozenset({"open"}) if device_on else frozenset({"closed"})
        return frozenset({"on"}) if device_on else frozenset({"off"})

    def _with_connection(self, entries: tuple[FsmSnapshotEntry, ...]) -> FsmSnapshot:
        """Дополнить снимок состоянием связи с внешней системой.

        В автономном режиме внешней системы нет, и её отсутствие проблемой не
        является (FR-014).

        Args:
            entries: Записи снимка.

        Returns:
            Итоговый снимок.
        """
        now = self.clock()
        checked, disconnected = self._check_connection(now)
        return FsmSnapshot(
            taken_at=_now_timestamp(),
            entries=entries,
            problem_count=sum(1 for entry in entries if entry.stuck or entry.mismatch),
            ha_checked=checked,
            ha_disconnected=disconnected,
        )

    def _check_connection(self, now: float) -> tuple[bool, bool]:
        """Оценить связь с внешней системой.

        Args:
            now: Текущее монотонное время.

        Returns:
            Пара ``(проверялась ли связь, зафиксирована ли потеря)``.
        """
        if self.adapter is None:
            self._disconnected_since = None
            return False, False

        if self.adapter.is_connected:
            self._disconnected_since = None
            return True, False

        if self._disconnected_since is None:
            self._disconnected_since = now
            return True, False
        return True, (now - self._disconnected_since) >= self.settings.ha_loss_sec

    # Показатели и события

    def _record_metrics(self, snapshot: FsmSnapshot) -> None:
        """Записать результат проверки в показатели.

        Args:
            snapshot: Снимок после проверки.
        """
        if self.metrics is None:
            return
        now = self.clock()
        self.metrics.record_watchdog_check(snapshot.result)
        self.metrics.set_watchdog_snapshot_timestamp(now)
        self.metrics.set_ha_connection_lost(snapshot.ha_disconnected)
        for entry in snapshot.entries:
            was_stuck = (PROBLEM_FSM_STUCK, entry.entity_id) in self._problems
            if entry.stuck and not was_stuck:
                self.metrics.record_fsm_stuck(entry.entity_id, entry.state)
            self.metrics.set_fsm_stuck(
                entry.entity_id,
                int(STUCK_LABEL_VALUE) if entry.stuck else 0,
            )

    def _publish_problems(self, snapshot: FsmSnapshot) -> None:
        """Опубликовать появление и устранение проблем.

        Публикуется только при смене состояния проблемы: повторные проверки
        зависшего автомата новых событий не порождают (FR-016).

        Args:
            snapshot: Снимок после проверки.
        """
        self._sync_fsm_problems(snapshot)
        self._sync_connection_problem(snapshot)
        self._sync_device_problems(snapshot)

    def _sync_device_problems(self, snapshot: FsmSnapshot) -> None:
        """Согласовать проблемы расхождения «автомат ↔ прибор» со снимком.

        Публикация идёт только при появлении и устранении расхождения: повторная
        проверка того же прибора новых событий не порождает (FR-016).

        Args:
            snapshot: Снимок после проверки.
        """
        for entry in snapshot.entries:
            key = (PROBLEM_DEVICE_MISMATCH, entry.entity_id)
            if entry.mismatch and key not in self._problems:
                self._problems[key] = self._start_problem(PROBLEM_DEVICE_MISMATCH, entry.entity_id)
                self._publish(PROBLEM_DEVICE_MISMATCH, entry.entity_id, entry.state, resolved=False)
            elif not entry.mismatch and key in self._problems:
                self._resolve_problem(key, state=entry.state)

    def _sync_fsm_problems(self, snapshot: FsmSnapshot) -> None:
        """Согласовать активные проблемы зависания со снимком.

        Args:
            snapshot: Снимок после проверки.
        """
        stuck_ids = {entry.entity_id for entry in snapshot.entries if entry.stuck}
        for entity_id in stuck_ids:
            key = (PROBLEM_FSM_STUCK, entity_id)
            if key in self._problems:
                continue
            state = next(
                (entry.state for entry in snapshot.entries if entry.entity_id == entity_id),
                "",
            )
            self._problems[key] = self._start_problem(PROBLEM_FSM_STUCK, entity_id)
            self._publish(PROBLEM_FSM_STUCK, entity_id, state, resolved=False)

        for entry in snapshot.entries:
            key = (PROBLEM_FSM_STUCK, entry.entity_id)
            if not entry.stuck and key in self._problems:
                self._resolve_problem(key, state=entry.state)

    def _sync_connection_problem(self, snapshot: FsmSnapshot) -> None:
        """Согласовать проблему потери связи со снимком.

        Args:
            snapshot: Снимок после проверки.
        """
        key = (PROBLEM_HA_DISCONNECTED, None)
        if snapshot.ha_disconnected and key not in self._problems:
            self._problems[key] = self._start_problem(PROBLEM_HA_DISCONNECTED, None)
            self._publish(PROBLEM_HA_DISCONNECTED, None, None, resolved=False)
        elif not snapshot.ha_disconnected and key in self._problems:
            self._resolve_problem(key, state=None)

    def _start_problem(self, kind: str, entity_id: str | None) -> _TrackedProblem:
        """Зафиксировать начало проблемы.

        Args:
            kind: Вид проблемы.
            entity_id: Автомат либо ``None``.

        Returns:
            Запись о проблеме.
        """
        problem = _TrackedProblem(
            kind=kind,
            entity_id=entity_id,
            detected_at=_now_timestamp(),
            detected_monotonic=self.clock(),
        )
        return problem

    def _resolve_problem(self, key: tuple[str, str | None], state: str | None) -> None:
        """Зафиксировать устранение проблемы и опубликовать событие.

        Args:
            key: Ключ проблемы.
            state: Состояние автомата на момент устранения.
        """
        problem = self._problems.pop(key, None)
        if problem is None:
            return
        duration = max(0.0, self.clock() - problem.detected_monotonic)
        self._publish(
            problem.kind,
            problem.entity_id,
            state,
            resolved=True,
            resolved_at=_now_timestamp(),
            duration_sec=round(duration, 3),
        )

    def _publish(
        self,
        kind: str,
        entity_id: str | None,
        state: str | None,
        resolved: bool,
        resolved_at: str | None = None,
        duration_sec: float | None = None,
    ) -> None:
        """Опубликовать событие проблемы, если шина подключена.

        Args:
            kind: Вид проблемы.
            entity_id: Автомат либо ``None``.
            state: Состояние автомата.
            resolved: Устранена ли проблема.
            resolved_at: Время устранения.
            duration_sec: Длительность проблемы.
        """
        if self.event_bus is None:
            return
        problem = self._problems.get((kind, entity_id))
        payload = {
            "kind": kind,
            "entity_id": entity_id,
            "state": state,
            "resolved": resolved,
            "detected_at": problem.detected_at if problem else _now_timestamp(),
            "resolved_at": resolved_at,
            "duration_sec": duration_sec,
        }
        coroutine = self.event_bus.publish(EVENT_PLATFORM_PROBLEM, payload)
        if not asyncio.iscoroutine(coroutine):
            return
        # Ссылка на задачу хранится до завершения: без неё сборщик мусора
        # может удалить задачу на середине, и событие пропадёт.
        task = asyncio.create_task(coroutine)
        self._publish_tasks.add(task)
        task.add_done_callback(self._publish_tasks.discard)


def create_watchdog(
    fsm_engine: EngineProtocol,
    metrics: MetricsProtocol | None = None,
    adapter: AdapterProtocol | None = None,
    settings: WatchdogSettings | None = None,
    event_bus: Any | None = None,
) -> WatchdogService:
    """Создать сторожа с настройками по умолчанию или заданными.

    Args:
        fsm_engine: Движок состояний.
        metrics: Сборщик показателей.
        adapter: Внешняя система либо ``None`` в автономном режиме.
        settings: Настройки; читаются из окружения при отсутствии.
        event_bus: Шина событий.

    Returns:
        Экземпляр сторожа.
    """
    return WatchdogService(
        fsm_engine=fsm_engine,
        metrics=metrics,
        adapter=adapter,
        settings=settings or watchdog_settings(),
        event_bus=event_bus,
    )


def get_watchdog() -> WatchdogService | None:
    """Получить последнего созданного сторожа.

    Returns:
        Созданный ранее сторож либо ``None``, если он не создавался.
    """
    return _watchdog_instance


_watchdog_instance: WatchdogService | None = None
