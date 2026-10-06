"""Цикл переподключения обязан оставлять след на каждой итерации (#70).

После срабатывания heartbeat за весь срок контейнера случается **ровно одно**
`connection open`: ни рукопожатия, ни повторной подписки. По журналу нельзя было
понять, остановился цикл или работает молча, потому что все его сообщения
(`attempting`, `retrying`, `subscribed`, `backoff reset`) печатаются либо через
модульный логгер на уровне `info`, либо через per-connection логгер, который в
развёртывании не даёт ни одной строки.

Отсюда требования к проверке:

1. **Видна каждая итерация** — иначе «цикл молчит» и «цикл остановлен» выглядят
   одинаково.
2. **Виден выход из цикла** — без него тихий выход по установленному
   `_shutdown_event` неотличим от зависания.
3. **Виден отказ от паузы из-за остановки** — это и есть тот самый тихий выход,
   который искали.
4. **Уровень WARNING** — на `info` всё это снова станет невидимым.

Заодно проверяется, что видимость не выкушена ценой удвоения шума: `info`-записи
остаются на месте, просто перестают быть единственными.
"""

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import re
from pathlib import Path


SOURCE = Path(__file__).resolve().parents[2] / "src" / "adapters" / "ha_adapter.py"


def _source() -> str:
    """Читает исходник адаптера.

    Returns:
        Текст файла.
    """
    return SOURCE.read_text(encoding="utf-8")


class TestReconnectLoopIsObservable:
    """Каждая итерация и выход из цикла видны."""

    def test_should_log_every_iteration(self) -> None:
        """Начало каждой итерации видно.

        Args:
            None.
        """
        assert "attempting WebSocket connection (iteration)" in _source(), (
            "начало итерации не видно — «цикл молчит» и «цикл остановлен» "
            "неразличимы, а именно это и нужно было различить"
        )

    def test_should_log_backoff_decision(self) -> None:
        """Решение о паузе видно.

        Args:
            None.
        """
        assert "retrying in" in _source(), "пауза перед повтором не видна"

    def test_should_log_skipped_backoff_on_shutdown(self) -> None:
        """Отказ от паузы из-за установленного флага остановки виден.

        Args:
            None.
        """
        assert "backoff skipped, shutdown_event is set" in _source(), (
            "тихий выход из цикла по установленному _shutdown_event не оставлял "
            "следа: без этой записи он неотличим от зависания"
        )

    def test_should_log_loop_exit(self) -> None:
        """Выход из цикла виден.

        Args:
            None.
        """
        assert "reconnect loop exited" in _source(), (
            "выход из цикла не виден — невозможно отличить нормальную остановку "
            "от зависания в середине итерации"
        )

    def test_should_use_visible_log_level(self) -> None:
        """Все новые записи — WARNING, иначе их снова не будет видно.

        Args:
            None.
        """
        source = _source()
        markers = (
            "attempting WebSocket connection (iteration)",
            "retrying in",
            "backoff skipped, shutdown_event is set",
            "reconnect loop exited",
        )
        for marker in markers:
            match = re.search(rf"logger\.(\w+)\((?:[^()]|\([^()]*\))*?{re.escape(marker)}", source)
            assert match, f"вызов журнала с записью {marker} не найден"
            assert match.group(1) == "warning", (
                f"запись {marker} должна быть WARNING: логи адаптера наследуют "
                f"корневой обработчик, где info не виден — найден "
                f"logger.{match.group(1)}"
            )

    def test_should_log_loop_cancellation(self) -> None:
        """Выход по отмене виден.

        Ветка `except asyncio.CancelledError: break` выходит из цикла, не делая
        ни паузы, ни повторного подключения. Пока она печаталась на `info`, её
        нельзя было отличить от зависания — а именно она оказалась причиной
        отсутствия переподключения.

        Args:
            None.
        """
        source = _source()

        assert "reconnect loop cancelled - no retry will happen" in source
        match = re.search(
            r"logger\.(\w+)\((?:[^()]|\([^()]*\))*?"
            r"reconnect loop cancelled - no retry will happen",
            source,
        )
        assert match and match.group(1) == "warning", "запись об отмене должна быть WARNING"

    def test_should_make_stop_and_container_shutdown_visible(self) -> None:
        """`stop()` и `Container.shutdown()` видны: иначе отмена извне неотличима.

        `_reconnect_task.cancel()` встречается в коде ровно в одном месте — в
        `stop()`, который вызывается из `Container.shutdown()`. Пока оба писали
        на `info`, нельзя было отличить «отменил stop()» от отмены изнутри цикла,
        а это и есть последний открытый вопрос #70.

        Args:
            None.
        """
        adapter_source = _source()
        container_source = (
            Path(__file__).resolve().parents[2] / "src" / "core" / "container.py"
        ).read_text(encoding="utf-8")

        assert "stop() called, cancelling reconnect task" in adapter_source
        assert "Container.shutdown() called" in container_source
        for source, marker in (
            (adapter_source, "stop() called, cancelling reconnect task"),
            (container_source, "Container.shutdown() called"),
        ):
            match = re.search(rf"logger\.(\w+)\((?:[^()]|\([^()]*\))*?{re.escape(marker)}", source)
            assert match and match.group(1) == "warning", (
                f"запись {marker} должна быть WARNING: на info её не видно, и "
                "снова придётся угадывать"
            )

    def test_should_keep_existing_info_records(self) -> None:
        """Прежние `info`-записи остаются: видимость не выкупается шумом.

        Args:
            None.
        """
        source = _source()

        assert "HAAdapter: subscribed to state_changed events" in source
        assert "backoff reset" in source
