"""Отменённая задача чтения — это обрыв, а не остановка платформы (#70).

Найдено на живом стенде. Heartbeat при устаревшем соединении отменяет задачу
чтения; основной цикл это видит и вызывает `listen_task.result()`. На отменённой
задаче `result()` бросает `asyncio.CancelledError`, а он **не наследует
`Exception`** — значит `except Exception` его не ловил, исключение уходило в
обработчик отмены самого цикла, цикл выходил, и переподключения не происходило
никогда. Проверено на стенде: `reconnect loop cancelled - no retry will happen`,
`reconnect loop exited`, итераций цикла за срок контейнера — одна.

Исключение специально вынесено в отдельный метод: различать `CancelledError` и
обычные ошибки здесь необходимо, а различение легко потерять при следующей
правке, если три строки будут лежать в теле цикла.

Проверка берёт настоящие задачи asyncio: отменённую, упавшую и завершившуюся
нормально. Никаких заглушек на месте задачи быть не должно — именно на
отменённой задаче и ломается всё.
"""

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from adapters.ha_adapter import HAAdapter


class _Log:
    """Журнал соединения."""

    def __init__(self) -> None:
        """Создаёт журнал.

        Returns:
            Ничего.
        """
        self.warnings: list[str] = []

    def warning(self, message: str) -> None:
        """Запоминает предупреждение.

        Args:
            message: Текст.
        """
        self.warnings.append(message)


async def _cancelled_task() -> None:
    """Задача, которую отменят снаружи.

    Returns:
        Ничего.
    """
    await asyncio.sleep(3600)


async def _failing_task() -> None:
    """Задача, которая падает.

    Returns:
        Ничего.
    """
    raise RuntimeError("соединение оборвалось")


@pytest.mark.asyncio
class TestListenTaskReason:
    """Классификация завершения задачи чтения."""

    async def test_cancelled_task_is_a_disconnect_not_a_shutdown(self) -> None:
        """Отменённая задача даёт обрыв, а не выход из цикла.

        Returns:
            Ничего.
        """
        task = asyncio.create_task(_cancelled_task())
        await asyncio.sleep(0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

        reason = HAAdapter._listen_task_reason(task, _Log())  # noqa: SLF001

        assert reason == "listen task cancelled", (
            "отменённая задача чтения — ожидаемый исход при закрытии устаревшего "
            "соединения, а не отмена цикла подключения"
        )

    async def test_cancelled_task_must_not_raise(self) -> None:
        """Главное: метод не выпускает `CancelledError` наружу.

        Именно выпущенное наружу исключение уводило цикл в ветку отмены. Если
        проверка на `reason` когда-то станет проверкой лишь на текст, а метод
        снова начнёт бросать, дефект вернётся незамеченным.

        Returns:
            Ничего.
        """
        task = asyncio.create_task(_cancelled_task())
        await asyncio.sleep(0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

        try:
            HAAdapter._listen_task_reason(task, _Log())  # noqa: SLF001
        except asyncio.CancelledError:  # pragma: no cover - сам дефект
            pytest.fail(
                "метод выпустил CancelledError — цикл подключения воспримет это как "
                "свою отмену и выйдет без переподключения (Known Issue #70)"
            )

    async def test_failed_task_is_reported_with_its_error(self) -> None:
        """Упавшая задача даёт обрыв с текстом ошибки.

        Returns:
            Ничего.
        """
        task = asyncio.create_task(_failing_task())
        await asyncio.sleep(0)
        with pytest.raises(RuntimeError):
            await task

        reason: str = HAAdapter._listen_task_reason(task, _Log())  # noqa: SLF001

        assert reason.startswith("listen task failed:"), reason
        assert "соединение оборвалось" in reason

    async def test_completed_task_is_plain_disconnect(self) -> None:
        """Завершившаяся без ошибок задача — обычный обрыв.

        Returns:
            Ничего.
        """
        task: Any = asyncio.create_task(asyncio.sleep(0))
        await task

        assert HAAdapter._listen_task_reason(task, _Log()) == "listen task ended"  # noqa: SLF001

    async def test_failure_is_logged(self) -> None:
        """Упавшая задача попадает в журнал: молча терять ошибку нельзя.

        Returns:
            Ничего.
        """
        task = asyncio.create_task(_failing_task())
        await asyncio.sleep(0)
        with pytest.raises(RuntimeError):
            await task
        log = _Log()

        HAAdapter._listen_task_reason(task, log)  # noqa: SLF001

        assert log.warnings, "ошибка задачи чтения должна попадать в журнал"
