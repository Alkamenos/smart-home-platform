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
import os
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

from core.logger import get_logger
from services.watchdog_checks import WatchdogChecksMixin
from services.watchdog_lifecycle import WatchdogLifecycleMixin
from services.watchdog_models import (
    ACTIVE_STATES as ACTIVE_STATES,
    CHECK_RESULT_DEGRADED as CHECK_RESULT_DEGRADED,
    CHECK_RESULT_FAILED as CHECK_RESULT_FAILED,
    CHECK_RESULT_OK as CHECK_RESULT_OK,
    DEVICE_DIVERGED_TRIGGER as DEVICE_DIVERGED_TRIGGER,
    DEVICE_OFF_STATES as DEVICE_OFF_STATES,
    DEVICE_ON_STATES as DEVICE_ON_STATES,
    DEVICE_UNAVAILABLE_STATES as DEVICE_UNAVAILABLE_STATES,
    DIVERGENCE_REASSERT_ATTEMPTS as DIVERGENCE_REASSERT_ATTEMPTS,
    IDLE_LIKE_STATES as IDLE_LIKE_STATES,
    MISMATCH_CLIMATE_ON_DECISION_OFF as MISMATCH_CLIMATE_ON_DECISION_OFF,
    MISMATCH_DEVICE_OFF_DECISION_ON as MISMATCH_DEVICE_OFF_DECISION_ON,
    MISMATCH_DEVICE_ON_DECISION_OFF as MISMATCH_DEVICE_ON_DECISION_OFF,
    MISMATCH_DEVICE_UNAVAILABLE as MISMATCH_DEVICE_UNAVAILABLE,
    MISMATCH_FAULT_REASONS as MISMATCH_FAULT_REASONS,
    MISMATCH_MANUAL_OVERRIDE as MISMATCH_MANUAL_OVERRIDE,
    PUBLISH_DRAIN_TIMEOUT_SEC as PUBLISH_DRAIN_TIMEOUT_SEC,
    STUCK_LABEL_VALUE as STUCK_LABEL_VALUE,
    FsmSnapshot as FsmSnapshot,
    FsmSnapshotEntry as FsmSnapshotEntry,
    WatchdogSettings as WatchdogSettings,
)
from services.watchdog_problems import WatchdogProblemsMixin, _TrackedProblem
from services.watchdog_reassert import WatchdogReassertMixin


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
class WatchdogService(
    WatchdogLifecycleMixin,
    WatchdogChecksMixin,
    WatchdogReassertMixin,
    WatchdogProblemsMixin,
):
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

    #: Признак «для прибора действует ручная блокировка». Нужен, чтобы отличать
    #: отказ прибора от уступки человеку: расхождение из-за оверрайда — не
    #: проблема (концепция §7, п. 2).
    manual_override_supplier: Callable[[str], bool] | None = None
    #: Признак «мы сами командовали этому прибору недавно» (BACKLOG B86). Нужен,
    #: чтобы повтор решения не спорил с человеком: повторяем только то, что сами
    #: приказывали (команда не дошла). Если приказа не было, прибор изменил
    #: кто-то другой — человек, кнопка, сценарий — и это уступка, а не отказ.
    #:
    #: Без источника считаем, что приказ был: сторож обязан чинить неотвечающие
    #: приборы, а в бою источник всегда есть (его подставляет контейнер).
    command_recency_supplier: Callable[[str], bool] | None = None

    #: Сколько раз решение уже повторялось для прибора (B64). Сбрасывается, когда
    #: прибор согласился с решением.
    _divergence_attempts: dict[str, int] = field(default_factory=dict)

    # Последний снимок хранится, чтобы проверка готовности могла судить о
    # свежести: без него «сторож молчит» и «сторож не работает» неразличимы.
    _last_snapshot: FsmSnapshot | None = None
    _task: asyncio.Task[None] | None = None
    _running: bool = False
    _disconnected_since: float | None = None
    _problems: dict[tuple[str, str | None], _TrackedProblem] = field(default_factory=dict)
    _publish_tasks: set[asyncio.Task[None]] = field(default_factory=set)

    # Жизненный цикл


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
