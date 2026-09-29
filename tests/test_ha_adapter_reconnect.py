"""
Тесты надёжности WebSocket-восстановления HAAdapter (спецификация 003, US2).

Покрывают research.md R6:
1. обрыв (завершение listen-задачи) → повторная попытка connect();
2. порядок backoff 1→2→4→…≤60с и сброс после успеха;
3. shutdown во время backoff — мгновенно, без висящих asyncio-задач;
4. детект обрыва через исключение в listen-задаче;
5. метрика websocket_disconnects_total при потере соединения (FR-006);
6. логирование обрыва с номером попытки (FR-006, contracts §4).
"""

from __future__ import annotations

import asyncio
import logging
import time

import pytest
import src.adapters.ha_adapter as ha_adapter_module
import src.core.metrics as core_metrics_module
from src.adapters.ha_adapter import HAAdapter


LISTEN_DIE_DELAY = 0.05


class FakeWSClient:
    """Фейковый WS-клиент: без сети, управляет жизненным циклом listen-задачи."""

    connect_calls = 0
    fail_connects = 0
    listen_behavior = "finishes"

    @classmethod
    def reset(cls) -> None:
        cls.connect_calls = 0
        cls.fail_connects = 0
        cls.listen_behavior = "finishes"

    def __init__(self, url: str, token: str, session=None) -> None:
        self.url = url
        self.token = token
        self.session = session
        self.connected = False
        self._listen_task: asyncio.Task | None = None

    async def connect(self) -> None:
        type(self).connect_calls += 1
        if type(self).fail_connects > 0:
            type(self).fail_connects -= 1
            raise ConnectionError("simulated connect failure")
        self.connected = True

    async def subscribe(self, handler, filter_dict) -> None:
        async def _listen() -> None:
            await asyncio.sleep(LISTEN_DIE_DELAY)
            if type(self).listen_behavior == "raises":
                raise ConnectionError("simulated listen failure")

        self._listen_task = asyncio.create_task(_listen())

    async def close(self) -> None:
        if self._listen_task and not self._listen_task.done():
            self._listen_task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await self._listen_task
        self.connected = False


@pytest.fixture
def fake_ws(monkeypatch: pytest.MonkeyPatch) -> type[FakeWSClient]:
    """Подменить HomeAssistantWS в модуле адаптера и сбросить состояние."""
    FakeWSClient.reset()
    monkeypatch.setattr(ha_adapter_module, "HomeAssistantWS", FakeWSClient)
    return FakeWSClient


def _make_adapter() -> HAAdapter:
    return HAAdapter(mode="websocket", ws_url="ws://fake-ha:8123", token="test-token")


async def _wait_until(condition, timeout: float = 3.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if condition():
            return True
        await asyncio.sleep(0.01)
    return False


@pytest.mark.asyncio
async def test_reconnects_after_listen_task_death(fake_ws: type[FakeWSClient]) -> None:
    """Обрыв (listen-задача завершилась) → адаптер делает повторный connect()."""
    adapter = _make_adapter()
    await adapter.start()
    try:
        assert await _wait_until(lambda: fake_ws.connect_calls >= 2), (
            f"ожидался 2-й connect(), фактически {fake_ws.connect_calls}"
        )
    finally:
        await adapter.stop()


@pytest.mark.asyncio
async def test_reconnects_after_listen_task_exception(fake_ws: type[FakeWSClient]) -> None:
    """Исключение в listen-задаче детектируется как обрыв → reconnect."""
    fake_ws.listen_behavior = "raises"
    adapter = _make_adapter()
    await adapter.start()
    try:
        assert await _wait_until(lambda: fake_ws.connect_calls >= 2)
    finally:
        await adapter.stop()


@pytest.mark.asyncio
async def test_backoff_sequence_grows_and_caps_at_60(
    fake_ws: type[FakeWSClient], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Неудачные попытки: задержки 1→2→4→… с ограничением максимума 60с."""
    fake_ws.fail_connects = 10_000
    delays: list[float] = []
    real_sleep = asyncio.sleep

    async def record_sleep(delay: float) -> None:
        # Фильтруем внутренние микро-sleep'ы хелперов, пишем только backoff
        if delay >= 1.0:
            delays.append(delay)
        await real_sleep(0)

    monkeypatch.setattr(ha_adapter_module.asyncio, "sleep", record_sleep)

    adapter = _make_adapter()
    await adapter.start()
    try:
        assert await _wait_until(lambda: len(delays) >= 4), f"задержки: {delays}"
        assert delays[:4] == [1.0, 2.0, 4.0, 8.0], f"не тот порядок backoff: {delays}"
        assert all(d <= 60.0 for d in delays), f"задержка больше максимума: {delays}"
        assert all(b >= a for a, b in zip(delays, delays[1:], strict=False)), (
            f"задержки не растут: {delays}"
        )
    finally:
        fake_ws.fail_connects = 0
        await adapter.stop()


@pytest.mark.asyncio
async def test_stop_during_backoff_is_immediate_and_leaves_no_hanging_tasks(
    fake_ws: type[FakeWSClient],
) -> None:
    """Shutdown во время задержки backoff выходит мгновенно и без висящих задач."""
    fake_ws.fail_connects = 10_000
    adapter = _make_adapter()
    await adapter.start()

    # Первая попытка падает → адаптер засыпает на 1с (реальный sleep)
    await asyncio.sleep(0.1)

    started = time.monotonic()
    await asyncio.wait_for(adapter.stop(), timeout=0.9)
    elapsed = time.monotonic() - started
    assert elapsed < 0.9, f"stop() ждал окончания backoff: {elapsed:.2f}s"

    assert adapter._reconnect_task is None
    current = asyncio.current_task()
    hanging = [
        t
        for t in asyncio.all_tasks()
        if t is not current and not t.done() and "connect_websocket" in repr(t.get_coro())
    ]
    assert not hanging, f"остались висящие задачи: {hanging}"

    fake_ws.fail_connects = 0


@pytest.mark.asyncio
async def test_disconnect_increments_metric(
    fake_ws: type[FakeWSClient], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Каждая потеря соединения увеличивает websocket_disconnects_total (FR-006)."""
    collector = type("C", (), {})()
    collector.record_websocket_disconnect = lambda: setattr(
        collector, "calls", getattr(collector, "calls", 0) + 1
    )
    monkeypatch.setattr(core_metrics_module, "get_metrics_collector", lambda: collector)

    adapter = _make_adapter()
    await adapter.start()
    try:
        assert await _wait_until(lambda: getattr(collector, "calls", 0) >= 1), (
            "record_websocket_disconnect не вызван после обрыва"
        )
    finally:
        await adapter.stop()


@pytest.mark.asyncio
async def test_disconnect_logs_attempt_number_and_backoff(
    fake_ws: type[FakeWSClient], caplog: pytest.LogCaptureFixture
) -> None:
    """Обрыв — WARNING с номером попытки и задержкой, успех — INFO о сбросе backoff."""
    adapter = _make_adapter()
    with caplog.at_level(logging.INFO, logger="src.adapters.ha_adapter"):
        await adapter.start()
        try:
            assert await _wait_until(lambda: fake_ws.connect_calls >= 2)
            lost_records = [
                r
                for r in caplog.records
                if "WebSocket lost" in r.getMessage() and "attempt" in r.getMessage()
            ]
            assert lost_records, (
                "нет WARNING о потере соединения с номером попытки; "
                f"записи: {[r.getMessage() for r in caplog.records][:10]}"
            )
            assert "delay" in lost_records[0].getMessage(), (
                f"в WARNING нет задержки: {lost_records[0].getMessage()}"
            )
            assert lost_records[0].levelno == logging.WARNING
            success_records = [r for r in caplog.records if "backoff reset" in r.getMessage()]
            assert success_records, "нет INFO о сбросе backoff после подключения"
        finally:
            await adapter.stop()
