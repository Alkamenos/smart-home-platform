"""Watchdog lifecycle (spec 018, T058).

Extracted from WatchdogService: the background loop and shutdown are a lifecycle
concern, separate from checks, reassertion and problem publication.
"""

# mypy: disable-error-code="attr-defined"

from __future__ import annotations

import asyncio
import contextlib

from core.logger import get_logger
from services.watchdog_models import PUBLISH_DRAIN_TIMEOUT_SEC, FsmSnapshot


logger = get_logger(__name__)


class WatchdogLifecycleMixin:
    """Run and stop the periodic watchdog loop."""

    _task: asyncio.Task[None] | None
    _running: bool
    _publish_tasks: set[asyncio.Task[None]]

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
