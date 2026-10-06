"""`close()` обязан оставлять след на каждом шаге (#70).

На живом стенде heartbeat входит в `close()` и не возвращается: видны две записи —
вход в ветку и начало закрытия — а записи о завершении нет. По этому нельзя было
сказать, на каком именно ожидании встали: отменяется задача чтения или закрывается
сокет.

Проверка требует, чтобы были видны **оба** края каждого шага. Запись только на входе
не годится: именно её я и добавил сначала, и она ничего не различала.

Уровень проверяется отдельно: логи клиента наследуют корневой обработчик, где
`INFO` не виден. На `INFO` инструментация молчала и не могла ответить на вопрос,
для которого сделана, — это и случилось в проде.
"""

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import re
from pathlib import Path


SOURCE = Path(__file__).resolve().parents[2] / "src" / "adapters" / "ha_adapter.py"


def _lines() -> list[str]:
    """Читает исходник клиента.

    Returns:
        Строки файла.
    """
    return SOURCE.read_text(encoding="utf-8").splitlines()


class TestCloseIsObservable:
    """Каждый шаг закрытия оставляет запись до и после."""

    def test_should_log_both_sides_of_listen_task_cancel(self) -> None:
        """Отмена задачи чтения видна с обеих сторон.

        До: без записи «после» нельзя отличить «отмена прошла, встали дальше» от
        «застряли на самой отмене».

        Args:
            None.
        """
        source = "\n".join(_lines())

        assert "close() cancel sent" in source, "нет записи об отправке отмены"
        assert "close() listen_task awaited" in source, (
            "нет записи о завершении ожидания задачи чтения — по этой строке и "
            "определяется, встали мы на отмене или дальше"
        )

    def test_should_log_both_sides_of_websocket_close(self) -> None:
        """Закрытие сокета видно с обеих сторон.

        Args:
            None.
        """
        source = "\n".join(_lines())

        assert "close() closing websocket" in source
        assert "close() websocket closed" in source

    def test_should_log_entry_to_close(self) -> None:
        """Вход в `close()` виден: иначе запись «после» повисает в воздухе.

        Args:
            None.
        """
        assert "close() start" in "\n".join(_lines())

    def test_should_use_visible_log_level(self) -> None:
        """Все записи инструментации — WARNING, иначе их не видно.

        Запись может быть разбита на несколько строк (аргумент переносится
        форматтером), поэтому уровень ищется по всему выражению, а не в одной
        строке: проверка «в этой же строке есть logger.warning» молча пропускала
        бы перенесённые вызовы.

        Args:
            None.
        """
        source = "\n".join(_lines())
        markers = (
            "close() start",
            "close() cancel sent",
            "close() listen_task awaited",
            "close() closing websocket",
            "close() websocket closed",
        )
        for marker in markers:
            match = re.search(rf"logger\.(\w+)\((?:[^()]|\([^()]*\))*?{re.escape(marker)}", source)
            assert match, f"вызов журнала с записью {marker} не найден"
            assert match.group(1) == "warning", (
                f"запись {marker} должна быть WARNING: логи клиента наследуют "
                f"корневой обработчик, где INFO не виден — найден "
                f"logger.{match.group(1)}"
            )

    def test_should_log_absent_listen_task(self) -> None:
        """Отсутствие задачи чтения тоже видно.

        Иначе ветка без задачи выглядит как ветка, где запись просто забыли, и
        различие снова приходилось бы угадывать.

        Args:
            None.
        """
        assert "close() no listen_task" in "\n".join(_lines())
