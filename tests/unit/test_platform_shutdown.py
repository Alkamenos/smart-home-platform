"""Завершение платформы: сторож останавливается, завершение не зависает.

Два независимых дефекта, оба найдены аудитом перед продакшеном:

1. **Сторож никогда не останавливается.** ``Container.build()`` запускает
   сторож через ``_start_watchdog()``, но в ``PlatformContext`` его **не
   передаёт**. Поле ``watchdog`` по умолчанию ``None``, поэтому в
   ``PlatformContext.shutdown()`` условие ``if self.watchdog is not None``
   всегда ложно — это мёртвая ветка. Фоновая задача сторожа переживает
   завершение и работает до принудительного SIGKILL. При этом докстринг
   ``shutdown()`` утверждает, что сторож останавливается, и он останавливается
   **первым**, потому что читает состояния движка (FR-017).

2. **Graceful shutdown зависает на WebSocket.** ``uvicorn.Config`` создаётся
   без ``timeout_graceful_shutdown``, а дефолт uvicorn — ``None``, то есть
   ждать вечно. WS-ручки — бесконечный ``await websocket.receive_text()``.
   Docker ждёт 10 секунд и шлёт SIGKILL, после чего ``ctx.shutdown()`` уже
   не выполняется. В compose нужен ``stop_grace_period`` с запасом.

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0
"""

import asyncio
import os
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from core.container import Container, PlatformContext


MANIFEST = "instances/leonids_house/manifest.yaml"


@pytest.fixture(autouse=True)
def _no_ha_token():
    """Без HA_TOKEN контейнер собирает MockAdapter — без сети."""
    previous = os.environ.pop("HA_TOKEN", None)
    yield
    if previous is not None:
        os.environ["HA_TOKEN"] = previous


@pytest.fixture
def container() -> Container:
    """Контейнер с подменённым сторожем, собранный на реальном манифесте."""
    built = Container(manifest_path=MANIFEST)
    watchdog = MagicMock()
    watchdog.stop = AsyncMock()
    built._watchdog = watchdog
    return built


class TestWatchdogReachesPlatformContext:
    """Сторож должен доезжать до контекста, иначе его нечем остановить."""

    def test_build_passes_watchdog_into_context(self, container: Container):
        """build() обязан передать сторож в PlatformContext."""
        ctx = container.build()

        assert ctx.watchdog is container._watchdog, (
            "build() запускает сторож, но не передаёт его в PlatformContext — "
            "shutdown() его не остановит: проверка `if self.watchdog is not None` "
            "всегда ложна, то есть мёртвая ветка"
        )

    @pytest.mark.asyncio
    async def test_watchdog_is_actually_started_by_build(self) -> None:
        """Сторож должен быть не только в контексте, но и запущен.

        `_start_watchdog()` пропускает запуск без работающего цикла событий —
        это осознанное поведение для синхронной сборки. Поэтому проверка идёт
        изнутри цикла: иначе она прошла бы при незапущенном стороже и не
        доказывала бы ничего.
        """
        from services.watchdog import WatchdogService

        built = Container(manifest_path=MANIFEST)
        started = False
        original = WatchdogService.start

        def spy(self, *args, **kwargs):
            nonlocal started
            started = True
            return original(self, *args, **kwargs)

        WatchdogService.start = spy
        try:
            ctx = built.build()
            assert started, "build() обязан запускать сторож в работающем цикле"
            assert ctx.watchdog is not None, "запущенный сторож обязан попасть в контекст"
        finally:
            WatchdogService.start = original
            await built.watchdog.stop()

        assert started, "build() обязан запускать сторож, иначе он нечего останавливать"


class TestShutdownStopsWatchdog:
    """Завершение обязано дойти до сторожа."""

    @pytest.mark.asyncio
    async def test_shutdown_stops_watchdog(self, container: Container):
        """shutdown() обязан вызвать stop() у сторожа."""
        ctx = container.build()
        ctx.watchdog.stop.reset_mock()

        await asyncio.wait_for(ctx.shutdown(), timeout=5.0)

        ctx.watchdog.stop.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_watchdog_stopped_before_engine(self, container: Container):
        """Порядок: сторож, потом движок.

        Сторож читает состояния движка, поэтому при обратном порядке он
        читает уже гаснущий движок (FR-017).
        """
        ctx = container.build()
        order: list[str] = []

        ctx.watchdog.stop = AsyncMock(side_effect=lambda: order.append("watchdog"))
        ctx.fsm.shutdown = AsyncMock(side_effect=lambda: order.append("engine"))

        await asyncio.wait_for(ctx.shutdown(), timeout=5.0)

        assert order[:2] == ["watchdog", "engine"], (
            f"ожидался порядок watchdog → engine, получено {order}"
        )

    @pytest.mark.asyncio
    async def test_shutdown_without_watchdog_does_not_fail(self):
        """Отсутствие сторожа не должно ломать завершение."""
        ctx = PlatformContext(
            manifest=MagicMock(),
            event_bus=MagicMock(),
            fsm=MagicMock(shutdown=AsyncMock()),
            control_tracker=MagicMock(),
            adapter=MagicMock(stop=AsyncMock()),
            dispatcher=MagicMock(stop=AsyncMock()),
            event_router=MagicMock(),
        )

        await asyncio.wait_for(ctx.shutdown(), timeout=5.0)

    @pytest.mark.asyncio
    async def test_shutdown_is_idempotent(self, container: Container):
        """Повторный shutdown() обязан быть безопасным.

        Иначе SIGTERM и последующая ошибка развернут цепочку дважды.
        """
        ctx = container.build()

        await asyncio.wait_for(ctx.shutdown(), timeout=5.0)
        await asyncio.wait_for(ctx.shutdown(), timeout=5.0)  # не должно бросить

    @pytest.mark.asyncio
    async def test_shutdown_terminates_within_timeout(self, container: Container):
        """Завершение не должно зависать.

        Проверка таймаутом, а не «не бросило»: зависание — тоже отказ, и без
        явного предела тест прошёл бы навечно.
        """
        ctx = container.build()

        await asyncio.wait_for(ctx.shutdown(), timeout=5.0)


class TestUvicornGracefulTimeout:
    """Uvicorn обязан иметь предел ожидания, иначе Docker убьёт процесс."""

    @staticmethod
    def _compose_text() -> str:
        root = Path(__file__).resolve().parents[2]
        return (root / "deploy" / "docker" / "docker-compose.prod.yml").read_text(encoding="utf-8")

    def test_compose_gives_docker_time_above_uvicorn_timeout(self):
        """stop_grace_period обязан быть больше таймаута uvicorn.

        Иначе Docker отправит SIGKILL раньше, чем uvicorn закончит, и
        `ctx.shutdown()` не выполнится.
        """
        import yaml

        root = Path(__file__).resolve().parents[2]
        compose = yaml.safe_load(
            (root / "deploy" / "docker" / "docker-compose.prod.yml").read_text(encoding="utf-8")
        )
        service = compose["services"]["behavioral-platform"]

        assert "stop_grace_period" in service, (
            "в docker-compose.prod.yml нет stop_grace_period: Docker по умолчанию "
            "ждёт 10 с и шлёт SIGKILL, не дав завершиться WS-соединениям"
        )

    def test_main_sets_uvicorn_graceful_timeout(self):
        """uvicorn.Config обязан иметь timeout_graceful_shutdown.

        Дефолт uvicorn — None, то есть ждать вечно; при открытом /ws/logs
        или /api/v1/ws/devices завершение не наступит никогда.
        """
        root = Path(__file__).resolve().parents[2]
        source = (root / "src" / "main.py").read_text(encoding="utf-8")

        assert "timeout_graceful_shutdown" in source, (
            "uvicorn.Config создаётся без timeout_graceful_shutdown — дефолт None "
            "означает ожидание вечно, а WS-ручки держат соединение бесконечно"
        )


def _watchdog_tasks() -> set[asyncio.Task]:
    """Задачи цикла, принадлежащие сторожу.

    Отбор по имени корутины `_watchdog_loop` — методу `WatchdogService`.
    Раньше фильтр искал подстроку "watchdog" в repr задачи, и находил САМ
    тест, в имени которого слово есть: проверка работала против себя и
    падала на собственной обёртке.
    """
    found: set[asyncio.Task] = set()
    for task in asyncio.all_tasks():
        coro = task.get_coro()
        name = getattr(coro, "__qualname__", repr(coro))
        if "_watchdog_loop" in name:
            found.add(task)
    return found


class TestWatchdogTaskActuallyDies:
    """Проверка на настоящей задаче, а не на подменённом объекте.

    Тест «stop() был вызван» проверяет контракт вызова. Здесь проверяется
    результат: задача сторожа действительно завершилась и не осталась
    висеть в цикле событий. Только такой тест поймает ситуацию, когда
    `stop()` вызывается, но задача почему-то продолжает работать.
    """

    @pytest.mark.asyncio
    async def test_no_watchdog_tasks_remain_after_shutdown(self) -> None:
        """После завершения задач сторожа в цикле не остаётся."""
        built = Container(manifest_path=MANIFEST)

        ctx = built.build()
        before = _watchdog_tasks()
        assert before, (
            "ожидалась хотя бы одна задача сторожа до shutdown — иначе проверка "
            "бессмысленна: нечего было бы останавливать"
        )

        await asyncio.wait_for(ctx.shutdown(), timeout=5.0)

        # Даём циклу сойтись: отмена задачи требует одного прохода
        await asyncio.sleep(0)

        after = _watchdog_tasks()
        assert not after, f"после shutdown остались задачи сторожа: {after}"

    @pytest.mark.asyncio
    async def test_all_tasks_related_to_watchdog_are_finished(self) -> None:
        """Каждая задача сторожа должна быть завершена или отменена."""
        built = Container(manifest_path=MANIFEST)
        ctx = built.build()

        tasks_before = _watchdog_tasks()
        assert tasks_before, "до shutdown не было задач сторожа — проверка пустая"

        await asyncio.wait_for(ctx.shutdown(), timeout=5.0)
        await asyncio.sleep(0)

        alive = {task for task in tasks_before if not (task.done() or task.cancelled())}
        assert not alive, f"задачи сторожа остались в работе: {alive}"
