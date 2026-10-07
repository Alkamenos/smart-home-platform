"""Факт ручного действия должен пережить перезапуск.

Почему именно это
-----------------

Перезапуск контейнера — обычное дело: правка манифеста, обновление, перезагрузка
узла. И это ровно тот момент, когда жилец пробует выключить свет и обнаруживает,
что «ничего не помогает»: автоматика возвращает его в первую же минуту. Срок
блокировки измеряется десятками минут, а перезапуск случается в течение суток
несколько раз.

Сбрасывать блокировку при старте — значит оставлять дыру именно там, где её
заметят.

Почему не в файле состояний автоматов
--------------------------------------

`state.json` перезаписывается при горячей перезагрузке манифеста, то есть
потерял бы факт ручного действия именно тогда, когда он нужнее всего. Поэтому
факт живёт отдельно и атомарно.

Что проверяется
---------------

1. Записанное ручное действие восстанавливается при старте.
2. Восстановленное действие продолжает блокировать автоматику.
3. Повреждённый файл не ломает старт: платформа поднимается, блокировки нет.
4. Отсутствие файла — не ошибка: платформа, которой ещё не пользовались,
   поднимается штатно.
5. Хранится только последнее действие по устройству, а не история.

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from core.commands.dispatcher import CommandIntent
from core.commands.middleware import ManualLockoutMiddleware
from core.control_tracker import ControlTracker
from core.persistence.manual_control_store import ManualControlStore


DEVICE = "light.kitchen"


def _rules(lockout_minutes: int = 30) -> Any:
    """Правила автоматизации с заданным сроком блокировки освещения.

    Args:
        lockout_minutes: Срок блокировки для света.

    Returns:
        Объект правил, как их видит middleware.
    """
    return MagicMock(
        lighting=MagicMock(manual_lockout_min=lockout_minutes),
        climate=MagicMock(manual_lockout_min=0),
        ventilation=MagicMock(manual_lockout_min=0),
        global_manual_lockout_min=None,
    )


def _intent(source: str) -> CommandIntent:
    """Команда от указанного источника.

    Args:
        source: Источник команды.

    Returns:
        Интент для отправки в middleware.
    """
    return CommandIntent(
        device_id=DEVICE,
        domain="light",
        service="turn_off",
        data={},
        priority=50,
        source=source,
    )


class TestManualActionSurvivesRestart:
    """Факт ручного действия сохраняется и восстанавливается."""

    @pytest.mark.asyncio
    async def test_action_is_written_on_disk(self, tmp_path: Path) -> None:
        """Вмешательство человека записывается в каталог данных."""
        store = ManualControlStore(tmp_path)
        tracker = ControlTracker(store=store)
        middleware = ManualLockoutMiddleware(_rules(), tracker)

        await middleware.process(_intent("manual_command"))

        assert store.file_path.is_file(), (
            "вмешательство человека осталось только в памяти: перезапуск "
            "контейнера сотрёт блокировку, и человек убедится, что ничего не помогает"
        )

    @pytest.mark.asyncio
    async def test_action_is_restored_on_start(self, tmp_path: Path) -> None:
        """После перезапуска факт на месте и блокировка действует.

        Проверяется через поведение, а не через чтение файла: восстановленный
        факт должен снова блокировать автоматику, иначе он просто лежит на диске
        мёртвым грузом.
        """
        store = ManualControlStore(tmp_path)
        first_tracker = ControlTracker(store=store)
        first_middleware = ManualLockoutMiddleware(_rules(), first_tracker)
        await first_middleware.process(_intent("manual_command"))

        # «Перезапуск»: трекер и middleware собираются заново поверх того же
        # каталога данных — ровно как при старте контейнера.
        store_after_restart = ManualControlStore(tmp_path)
        second_tracker = ControlTracker(store=store_after_restart, restore=True)
        second_middleware = ManualLockoutMiddleware(_rules(), second_tracker)

        blocked = await second_middleware.process(_intent("lighting"))

        assert blocked is None, (
            "после перезапуса блокировка перестала действовать: человек выключил "
            "свет, перезапустил контейнер — и свет включился снова"
        )

    @pytest.mark.asyncio
    async def test_only_last_action_is_kept(self, tmp_path: Path) -> None:
        """Хранится последнее действие по устройству, а не история.

        История управления устройством ведёт журнал переходов; хранить её здесь
        означало бы завести второй источник правды о том, когда и как устройством
        управляли.
        """
        store = ManualControlStore(tmp_path)
        tracker = ControlTracker(store=store)
        middleware = ManualLockoutMiddleware(_rules(), tracker)

        await middleware.process(_intent("manual_command"))
        await middleware.process(_intent("manual_command"))

        records = json.loads(store.file_path.read_text(encoding="utf-8"))

        assert isinstance(records, dict), f"ожидалась карта устройств, а не список: {records}"
        assert list(records) == [DEVICE], f"в файле не одно устройство: {list(records)}"


class TestUnreadableStorageDoesNotBreakStart:
    """Хранилище не должно ронять старт платформы."""

    def test_missing_file_is_not_an_error(self, tmp_path: Path) -> None:
        """Платформа, которой ещё не пользовались, поднимается штатно."""
        tracker = ControlTracker(store=ManualControlStore(tmp_path), restore=True)

        assert tracker.get_last_manual(DEVICE) is None

    def test_corrupt_file_is_tolerated(self, tmp_path: Path) -> None:
        """Повреждённый файл означает отсутствие блокировки, а не отказ старта.

        Иначе единственный оборванный JSON поднимает весь контейнер, и
        восстановление потребует ручного вмешательства внутрь тома.
        """
        store = ManualControlStore(tmp_path)
        store.file_path.parent.mkdir(parents=True, exist_ok=True)
        store.file_path.write_text("{ это не json", encoding="utf-8")

        tracker = ControlTracker(store=store, restore=True)

        assert tracker.get_last_manual(DEVICE) is None

    def test_unwritable_directory_does_not_break_tracking(self, tmp_path: Path) -> None:
        """Неудачная запись не мешает работать в текущем процессе.

        Каталог может оказаться только для чтения; тогда блокировка не переживёт
        перезапуск, но платформа продолжает работать, а не падает на каждом
        вмешательстве жильца.
        """
        store = MagicMock()
        store.save.side_effect = OSError("нет прав")
        tracker = ControlTracker(store=store)

        tracker.record(DEVICE, "manual", "turn_off")

        assert tracker.get_last_manual(DEVICE) is not None, (
            "неудачная запись на диск отключила учёт в самом процессе"
        )


class TestOnlyManualActionsAreStored:
    """На диск попадает только вмешательство человека."""

    def test_automated_control_is_not_stored(self, tmp_path: Path) -> None:
        """Автоматика не засчитывается как ручное действие."""
        store = ManualControlStore(tmp_path)
        tracker = ControlTracker(store=store)

        tracker.record(DEVICE, "automation", "turn_on")

        assert not store.file_path.exists(), (
            "автоматическое действие записано как ручное: после перезапута "
            "система заблокирует саму себя"
        )
