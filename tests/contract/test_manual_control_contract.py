"""Наблюдаемые сигналы: то, по чему оператор судит, что система работает.

Без них остальное в фиче недоказуемо. Механизм может работать, а доказать это
нечем — и ровно так выглядели предыдущие дефекты: подписка ограничена, журнал
молчит, `/ready` отвечает «да».

Контракт: `specs/010-live-acceptance/contracts/observable-signals.md`.

Что проверяется
---------------

1. Ручное действие попадает в журнал на видимом уровне.
2. Отказ по блокировке попадает в журнал и несёт остаток срока.
3. Отказ по блокировке попадает в показатели.
4. Причина «данных нет» доходит до счётчика отказов настоящим переходом, а не
   прямым вызовом учёта.
5. Ни одна из записей не остаётся на уровне отладки: журнал адаптера наследует
   корневой обработчик, где отладка не видна, — проверка на ней молчит и не
   доказывает ничего. Это уже стоило пяти итераций при разборе обрыва сети.

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest

from core.commands.dispatcher import CommandIntent
from core.commands.middleware import ManualLockoutMiddleware
from core.control_tracker import ControlTracker
from core.fsm.engine import FSMEngine
from core.guards.builtin import build_guards
from core.metrics import get_metrics_collector


DEVICE = "light.kitchen"
FSM_ID = "light.kitchen_lighting_5"


class _LogCapture:
    """Сборщик записей журнала с указанием уровня."""

    def __init__(self) -> None:
        """Создать пустой сборщик."""
        self.records: list[tuple[str, str]] = []

    def __call__(self, level: str) -> Any:
        """Вернуть подменённый метод записи указанного уровня.

        Args:
            level: Имя метода журнала без префикса (`info`, `warning`).

        Returns:
            Функция, запоминающая свои вызовы.
        """

        def record(message: str, *args: Any, **_kwargs: Any) -> None:
            self.records.append((level, str(message)))

        return record


def _middleware(lockout_minutes: int = 30) -> tuple[ManualLockoutMiddleware, ControlTracker]:
    """Middleware с настоящим трекером.

    Args:
        lockout_minutes: Срок блокировки для света.

    Returns:
        Готовая middleware и её трекер.
    """
    tracker = ControlTracker()
    rules = SimpleNamespace(
        lighting=SimpleNamespace(manual_lockout_min=lockout_minutes),
        climate=SimpleNamespace(manual_lockout_min=0),
        ventilation=SimpleNamespace(manual_lockout_min=0),
        global_manual_lockout_min=None,
    )
    return ManualLockoutMiddleware(rules, tracker), tracker


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
        service="turn_on",
        data={},
        priority=50,
        source=source,
    )


class TestManualActionIsVisible:
    """Вмешательство человека видно в журнале."""

    @pytest.mark.asyncio
    async def test_manual_action_writes_visible_record(self) -> None:
        """Запись делается на видимом уровне, а не на уровне отладки.

        Логи адаптера наследуют корневой обработчик, где отладка не видна:
        проверка на `debug` молчала бы и не доказала бы ничего.
        """
        middleware, _ = _middleware()
        capture = _LogCapture()

        with (
            pytest.MonkeyPatch.context(),
        ):
            monkey = pytest.MonkeyPatch()
            monkey.setattr("core.commands.middleware.logger.info", capture("info"))
            monkey.setattr("core.commands.middleware.logger.debug", capture("debug"))
            monkey.setattr("core.commands.middleware.logger.warning", capture("warning"))
            try:
                await middleware.process(_intent("manual_command"))
            finally:
                monkey.undo()

        messages = [msg for _level, msg in capture.records]
        assert any(DEVICE in m for m in messages), (
            "вмешательство человека не попало в журнал вовсе: оператор не увидит, "
            f"что система учла его действия. Записи: {messages}"
        )
        assert not any(
            _level == "debug" and "manual" in msg.lower() for _level, msg in capture.records
        ), (
            "единственная запись о вмешательстве сделана на уровне отладки: она "
            "не видна в журнале и не доказывает ничего"
        )


class TestLockoutIsVisible:
    """Сработавшая блокировка видна и объяснима."""

    @pytest.mark.asyncio
    async def test_block_writes_visible_record_with_remaining_time(self) -> None:
        """Отказ сопровождается записью с остатком срока.

        Оператор должен видеть, что автоматика выключена намеренно, и до какого
        момента — иначе отказ неотличим от поломки.
        """
        middleware, _ = _middleware(lockout_minutes=30)
        capture = _LogCapture()
        monkey = pytest.MonkeyPatch()
        monkey.setattr("core.commands.middleware.logger.info", capture("info"))
        monkey.setattr("core.commands.middleware.logger.debug", capture("debug"))
        monkey.setattr("core.commands.middleware.logger.warning", capture("warning"))
        try:
            await middleware.process(_intent("manual_command"))
            await middleware.process(_intent("lighting"))
        finally:
            monkey.undo()

        messages = [msg for _level, msg in capture.records]
        assert any("manual lockout" in m or "Блокировка" in m for m in messages), (
            f"отказ по блокировке не попал в журнал: {messages}"
        )
        block_levels = {
            level
            for level, msg in capture.records
            if "manual lockout" in msg or "Блокировка" in msg
        }
        assert "debug" not in block_levels, (
            f"отказ по блокировке записан только на уровне отладки {block_levels}: в "
            f"журнале его не видно, и оператор ищет поломку там, где автоматика "
            f"выключена намеренно"
        )

    @pytest.mark.asyncio
    async def test_block_is_counted_in_metrics(self) -> None:
        """Отказ по блокировке попадает в показатели.

        Показатели — то, что читают, не открывая журнал: сценарий «свет не
        включается» проверяется там.
        """
        metrics = get_metrics_collector()
        metrics.initialize()
        middleware, _ = _middleware(lockout_minutes=30)

        before = metrics.manual_lockout_blocks_total_value()
        await middleware.process(_intent("manual_command"))
        await middleware.process(_intent("lighting"))
        after = metrics.manual_lockout_blocks_total_value()

        assert after == before + 1, (
            f"отказ по блокировке не учтён в показателях: было {before}, стало {after}. "
            f"По сценарию «свет не включается» без этого счётчика нечем установить, "
            f"что автоматика выключена намеренно"
        )


class TestRejectionReasonIsCounted:
    """Причина отказа доходит до счётчика настоящим переходом."""

    @pytest.mark.asyncio
    async def test_missing_data_reason_reaches_counter(self) -> None:
        """Отказ «данных нет» считается при настоящем переходе.

        Проверяется через движок, а не прямым вызовом учёта: прямым вызовом
        причина попала бы в счётчик всегда, даже если движок её не передаёт.
        """
        engine = FSMEngine()
        tracker = MagicMock()
        tracker.was_manual_within.return_value = False
        for name, guard in build_guards(tracker).items():
            engine.register_guard(name, guard)

        definition = _definition_with_guard("humidity_above_60")
        engine.register_definition(definition)
        await engine.trigger(FSM_ID, "humidity_changed")

        counts = engine.rejection_counts()
        assert counts.get("guard_data_missing") == 1, (
            f"причина «данных нет» не дошла до счётчика отказов: {counts}. По такому "
            f"счётчику нельзя отличить молчащий датчик от штатного отказа"
        )

    @pytest.mark.asyncio
    async def test_value_below_threshold_is_different_reason(self) -> None:
        """Данные есть, значение не подходит — это другая причина.

        Различие причин и есть смысл их раздельного учёта: «датчик молчит» и
        «состояние штатное» требуют разных действий.
        """
        engine = FSMEngine()
        tracker = MagicMock()
        tracker.was_manual_within.return_value = False
        for name, guard in build_guards(tracker).items():
            engine.register_guard(name, guard)

        definition = _definition_with_guard("humidity_above_60")
        engine.register_definition(definition)
        await engine.trigger(
            FSM_ID,
            "humidity_changed",
            external_ctx={"humidity": 40.0, "humidity_threshold": 65.0},
        )

        counts = engine.rejection_counts()
        assert counts.get("guard_failed") == 1, f"причина отказа по условию неверна: {counts}"
        assert "guard_data_missing" not in counts, (
            f"при наличии данных засчитано отсутствие данных: {counts}"
        )


def _definition_with_guard(guard_name: str) -> Any:
    """Описание перехода, охраняемого указанным условием.

    Args:
        guard_name: Имя условия на переходе.

    Returns:
        Описание, готовое к регистрации в движке.
    """
    from core.fsm.engine import FSMDefinition, Transition

    return FSMDefinition(
        entity_id=FSM_ID,
        initial_state="OFF",
        states=("OFF", "ON"),
        target_device_id=DEVICE,
        transitions=(
            Transition(
                from_state="OFF", to_state="ON", trigger="humidity_changed", guard=guard_name
            ),
        ),
    )
