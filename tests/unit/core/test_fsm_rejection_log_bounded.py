"""Шумный отказ должен уметь молчать, а не тонуть в полезном.

Контекст. В бою синхронизировано 1489 устройств HA против 6 в манифесте, и
движок отбивает каждое изменение состояния любой сущности: 7384 отказа с
причиной `unknown_entity` и 258 с `no_transition` за всё время. В журнале это
две строки на событие, то есть 80% объёма — шум, в котором не видно ничего
остального.

Проверка на `unknown_entity` как на дефект была бы неверной: отказ честный,
сущности действительно нет в манифесте. Неверно то, что **каждый** отказ
записывается в журнал: сущностей тысячи, повторяется это тысячи раз, и
ценность несёт первое упоминание, а не третье тысячное.

Отказ при этом обязан оставаться наблюдаемым — иначе неизвестная сущность
проходит мимо, и о том, что устройство не описано в манифесте, никто не узнает.
Поэтому отказ перестаёт писать в журнал, но продолжает:
- попадать в историю переходов (там он и нужен — по нему видно, какие сущности
  платформа отбивает, и это основание для сужения набора устройств);
- один раз упоминаться в журнале на сущность.

Второе — то, что делает шум управляемым: число строк растёт с числом
**различных** сущностей, а не с числом событий.

Что проверяется
---------------

1. По умолчанию отказ не пишется в журнал на каждом событии: повторные отказы
   одной сущности молчат.
2. Первое упоминание сущности в журнале есть — иначе неизвестная сущность
   прошла бы незамеченной.
3. Отказ по-прежнему попадает в историю переходов: наблюдаемость не потеряна,
   просто переехала туда, где она полезна.
4. Флаг включает прежнее поведение целиком — на случай разбора в доме, когда
   шум полезен.
5. Счётчик отказов виден: он и есть признак, по которому сужение набора
   устройств и обосновывается.
"""

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import asyncio
import logging
from collections.abc import Iterator
from typing import Any

import pytest
from loguru import logger

from core.fsm.engine import FSMDefinition, FSMEngine, Transition


ENTITY_ID = "light.kitchen_lighting_10"

#: Сущности, которых нет в манифесте — как 1483 из 1489 синхронизированных.
UNKNOWN_ENTITIES = ("sun.sun", "sensor.temperature_humidity_sensor_7c65_temperature")

#: Имя переменной окружения, включающей прежнее поведение целиком.
FLAG_ENV = "FSM_LOG_REJECTIONS"


def _lighting_definition() -> FSMDefinition:
    """Собрать определение автомата освещения.

    Returns:
        Определение с одним автоматом.
    """
    return FSMDefinition(
        entity_id=ENTITY_ID,
        initial_state="OFF",
        states=["OFF", "ON_MOTION"],
        transitions=[
            Transition(
                from_state="OFF",
                to_state="ON_MOTION",
                trigger="motion_detected",
                action=lambda *a, **k: None,
            ),
        ],
    )


def _count_warnings(messages: list[str], needle: str) -> int:
    """Посчитать записи журнала, содержащие подстроку.

    Движок пишет через loguru, а не через stdlib logging, поэтому `caplog`
    pytest его не видит: проверка на `caplog` молчала бы и не доказала бы
    ничего — тот же урок, что и с невидимым INFO (#70). Захват сделан сокетом
    loguru.

    Args:
        messages: Захваченные сообщения.
        needle: Подстрока для поиска.

    Returns:
        Число подходящих записей.
    """
    return sum(1 for message in messages if needle in message)


@pytest.fixture
def captured() -> Iterator[list[str]]:
    """Захватывать сообщения loguru на время проверки.

    Yields:
        Список сообщений, пополняемый по ходу выполнения.
    """
    messages: list[str] = []

    def _sink(message: Any) -> None:
        messages.append(message)

    handler_id = logger.add(_sink, level="DEBUG")
    try:
        yield messages
    finally:
        logger.remove(handler_id)


@pytest.mark.asyncio
class TestRejectionLogIsBounded:
    """Повторный отказ одной сущности молчит."""

    async def test_repeated_rejection_of_same_entity_is_silent(self, captured: list[str]) -> None:
        """Сто отказов одной сущности дают одну запись, а не сто.

        Returns:
            Ничего.
        """
        engine = FSMEngine()
        engine.register_definition(_lighting_definition())

        for _ in range(100):
            await engine.trigger("sun.sun", "sun.sun_changed")

        assert _count_warnings(captured, "sun.sun") == 1, (
            f"отказ по одной сущности записан "
            f"{_count_warnings(captured, 'sun.sun')} раз из 100: в доме сущностей "
            f"тысячи, и повторяется это тысячи раз. Ценность несёт первое "
            f"упоминание, а не третье тысячное"
        )

    async def test_first_mention_is_logged(self, captured: list[str]) -> None:
        """Первое упоминание неизвестной сущности в журнале есть.

        Returns:
            Ничего.
        """
        engine = FSMEngine()
        engine.register_definition(_lighting_definition())

        await engine.trigger("sensor.unknown_sensor", "sensor.unknown_sensor_changed")

        assert _count_warnings(captured, "sensor.unknown_sensor") >= 1, (
            "неизвестная сущность прошла бы незамеченной: молчание должно "
            "начинаться со второго отказа, а не с первого"
        )

    async def test_different_entities_are_mentioned_separately(self, captured: list[str]) -> None:
        """Разные сущности упоминаются каждая: молчание относится к повтору.

        Returns:
            Ничего.
        """
        engine = FSMEngine()
        engine.register_definition(_lighting_definition())

        for entity in UNKNOWN_ENTITIES:
            await engine.trigger(entity, f"{entity}_changed")

        for entity in UNKNOWN_ENTITIES:
            assert _count_warnings(captured, entity) >= 1, (
                f"{entity} не упомянута: счётчик молчания привязан к сущности, "
                f"и разные сущности не должны глушить друг друга"
            )

    async def test_rejection_still_reaches_history(self, captured: list[str]) -> None:
        """Отказ по-прежнему попадает в историю переходов.

        Returns:
            Ничего.
        """
        engine = FSMEngine()
        engine.register_definition(_lighting_definition())

        for _ in range(10):
            await engine.trigger("sun.sun", "sun.sun_changed")

        assert engine.rejection_counts().get("unknown_entity") == 10, (
            f"отказы перестали учитываться: {engine.rejection_counts()}. Тишина в "
            f"журнале уводит наблюдаемость, а не отменяет её: по счётчику видно, "
            f"какие сущности платформа отбивает — это и есть основание сузить "
            f"набор устройств"
        )

    async def test_flag_restores_full_logging(
        self, captured: list[str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Флаг возвращает прежнее поведение целиком.

        Args:
            captured: Захваченные сообщения журнала.
            monkeypatch: Подмена окружения.
        """
        monkeypatch.setenv(FLAG_ENV, "1")
        engine = FSMEngine()
        engine.register_definition(_lighting_definition())

        for _ in range(10):
            await engine.trigger("sun.sun", "sun.sun_changed")

        assert _count_warnings(captured, "sun.sun") == 10, (
            "флаг не подействовал: разбирать дом с включённым шумом должно быть "
            "возможно, иначе флаг — обещание без действия"
        )

    async def test_flag_ignored_for_bad_value(
        self, captured: list[str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Нераспознанное значение флага не включает шум обратно.

        Args:
            captured: Захваченные сообщения журнала.
            monkeypatch: Подмена окружения.
        """
        # Опечатка в настройке не должна возвращать 80% шума в журнал: тот же
        # принцип, что и в SHADOW_MODE — нераспознанное значение не включаёт
        # небезопасное поведение.
        monkeypatch.setenv(FLAG_ENV, "да")
        engine = FSMEngine()
        engine.register_definition(_lighting_definition())

        for _ in range(10):
            await engine.trigger("sun.sun", "sun.sun_changed")

        assert _count_warnings(captured, "sun.sun") == 1, (
            "нераспознанное значение флага включило шум целиком"
        )

    async def test_counters_are_separate_per_reason(self, captured: list[str]) -> None:
        """Счётчики различают причины: молчание не склеивает отказы.

        Args:
            captured: Захваченные сообщения журнала.

        Returns:
            Ничего.
        """
        engine = FSMEngine()
        engine.register_definition(_lighting_definition())

        for _ in range(3):
            await engine.trigger("sun.sun", "sun.sun_changed")
        # Из ON_MOTION нет перехода по motion_cleared — другой отказ.
        await engine.trigger(ENTITY_ID, "motion_detected")
        await engine.trigger(ENTITY_ID, "motion_cleared")

        counts = engine.rejection_counts()
        assert counts.get("unknown_entity") == 3, counts
        assert counts.get("no_transition") == 1, (
            f"отказы разных причин склеились: {counts}. По склеенному счётчику "
            f"нельзя понять, что именно платформа отбивает"
        )


class TestPingsAreNotLogged:
    """Бинарный обмен WebSocket не должен попадать в журнал платформы."""

    def test_websockets_logger_is_quieted_at_setup(self) -> None:
        """Журнал библиотеки поднят до INFO независимо от LOG_LEVEL.

        Returns:
            Ничего.
        """
        from core.logging_setup import configure_library_logging

        root = logging.getLogger()
        original = root.level
        root.setLevel(logging.DEBUG)
        try:
            configure_library_logging()

            ws_logger = logging.getLogger("websockets")
            assert ws_logger.level == logging.INFO, (
                f"журнал websockets остался на {ws_logger.level}: при LOG_LEVEL=DEBUG "
                f"он пишет бинарный обмен (`> PING b3 d2 62 82 [binary, 4 bytes]`) "
                f"на каждое сообщение. Это 80% объёма журнала и ни одного полезного "
                f"байта в нём"
            )
        finally:
            root.setLevel(original)

    def test_other_libraries_keep_debug(self) -> None:
        """Тишина относится к WebSocket, а не ко всем библиотекам сразу.

        Returns:
            Ничего.
        """
        from core.logging_setup import configure_library_logging

        root = logging.getLogger()
        original = root.level
        root.setLevel(logging.DEBUG)
        try:
            configure_library_logging()

            assert logging.getLogger("websockets.client").level >= logging.INFO
            assert logging.getLogger("websockets.protocol").level >= logging.INFO
        finally:
            root.setLevel(original)


@pytest.mark.asyncio
async def test_rejection_counter_survives_repeated_state() -> None:
    """Счётчик отказов не растёт от успешных переходов.

    Returns:
        Ничего.
    """
    engine = FSMEngine()
    engine.register_definition(_lighting_definition())

    for _ in range(3):
        await engine.trigger(ENTITY_ID, "motion_detected")

    assert "unknown_entity" not in engine.rejection_counts(), (
        f"успешные переходы попали в счётчик отказов: {engine.rejection_counts()}"
    )
    await asyncio.sleep(0)
