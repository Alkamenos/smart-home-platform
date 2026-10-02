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
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Protocol

from core.events.fsm_events import (
    EVENT_PLATFORM_PROBLEM,
    PROBLEM_FSM_STUCK,
    PROBLEM_HA_DISCONNECTED,
)
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
    """

    entity_id: str
    device: str
    state: str
    entered_at: float
    last_transition: str | None
    stuck: bool
    expected_timeout_sec: float | None


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


class AdapterProtocol(Protocol):
    """Минимальный контракт внешней системы, нужный сторожу.

    Объявлен вместо импорта класса адаптера: сторож спрашивает лишь признак
    связи и не должен зависеть от конкретной реализации (R-13).
    """

    @property
    def connected(self) -> bool: ...


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

    _task: asyncio.Task[None] | None = None
    _running: bool = False
    _disconnected_since: float | None = None
    _problems: dict[tuple[str, str | None], _TrackedProblem] = field(default_factory=dict)
    _publish_tasks: set[asyncio.Task[None]] = field(default_factory=set)

    # Жизненный цикл

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
            self._record_metrics(snapshot)
            return snapshot

        snapshot = self._with_connection(entries)
        self._record_metrics(snapshot)
        self._publish_problems(snapshot)
        logger.info(f"[WATCHDOG] {snapshot.to_json()}")
        return snapshot

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
            problem_count=sum(1 for entry in entries if entry.stuck),
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

        if self.adapter.connected:
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
