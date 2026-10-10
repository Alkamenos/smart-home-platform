"""Низкий заряд батареи датчика виден до того, как он замолчит (FR-048).

Датчики уже отдают заряд в Home Assistant отдельной сущностью
(`sensor.*_battery`), и в доме это измеримая величина: 2026-10-10 датчик террасы
показывал 1 %. Платформа это значение не читала, и о батарейке узнавали по
молчанию — то есть уже потеряв датчик.

Отдельная система проверки здоровья всего дома вынесена в `BACKLOG.md` (F6).
Здесь только то, без чего климат небезопасен: следить за зарядом датчиков,
которые решают, включать ли обогрев, и предупреждать о падении ниже порога.

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from core.services.sensor_health import SensorHealthService


BATTERY_TERASSA = "sensor.datchik_temperatury_terassa_battery"
BATTERY_SPALNIA = "sensor.datchik_temperatury_spalnia_battery"

LOW = 20.0


class _StubAdapter:
    """Адаптер, отдающий заранее заданные состояния."""

    def __init__(self, states: dict[str, str]) -> None:
        self._states = states
        self.requested: list[str] = []

    async def get_entity_state(self, entity_id: str) -> str | None:
        """Состояние сущности.

        Args:
            entity_id: Идентификатор сущности.

        Returns:
            Состояние либо None.
        """
        self.requested.append(entity_id)
        return self._states.get(entity_id)


def _service(adapter: _StubAdapter) -> SensorHealthService:
    """Сервис наблюдения за батарейками двух датчиков.

    Args:
        adapter: Адаптер с состояниями.

    Returns:
        Готовый сервис.
    """
    return SensorHealthService(
        adapter=adapter,
        battery_entities=[BATTERY_TERASSA, BATTERY_SPALNIA],
        low_threshold=LOW,
    )


@contextmanager
def _capture_warnings() -> Iterator[list[str]]:
    """Собрать предупреждения журнала за время работы блока.

    Returns:
        Список предупреждений.
    """
    from loguru import logger

    messages: list[str] = []
    sink_id = logger.add(lambda message: messages.append(str(message)), level="WARNING")
    try:
        yield messages
    finally:
        logger.remove(sink_id)


class TestLowBatteryWarns:
    """Падение заряда ниже порога даёт предупреждение."""

    async def test_low_battery_is_reported(self) -> None:
        """Заряд 1 % попадает в список проблем.

        Returns:
            Ничего.
        """
        service = _service(_StubAdapter({BATTERY_TERASSA: "1", BATTERY_SPALNIA: "81"}))

        problems = await service.check_once()

        assert problems == [BATTERY_TERASSA], (
            f"датчик террасы на 1 % обязан попасть в список: {problems}"
        )

    async def test_healthy_battery_is_not_reported(self) -> None:
        """Заряд 81 % не тревожит.

        Returns:
            Ничего.
        """
        service = _service(_StubAdapter({BATTERY_TERASSA: "81", BATTERY_SPALNIA: "81"}))

        assert await service.check_once() == []

    async def test_boundary_is_not_low(self) -> None:
        """Ровно порог — ещё не низкий.

        Returns:
            Ничего.
        """
        service = _service(_StubAdapter({BATTERY_TERASSA: "20", BATTERY_SPALNIA: "19"}))

        problems = await service.check_once()

        assert problems == [BATTERY_SPALNIA], "19 % ниже порога, 20 % — нет"


class TestUnknownBatteryIsSilent:
    """Непрочитанный заряд — неизвестность, а не тревога."""

    async def test_unavailable_battery_says_nothing(self) -> None:
        """Устройство не ответило — молчим, а не врём про 0 %.

        Returns:
            Ничего.
        """
        service = _service(_StubAdapter({BATTERY_TERASSA: "unavailable", BATTERY_SPALNIA: "81"}))

        assert await service.check_once() == [], (
            "непрочитанный заряд означает «неизвестно»: в списке проблем он был бы "
            "ложным, а нулевой заряд привёл бы к предупреждению о батарейке, "
            "которой проблемы нет"
        )

    async def test_nan_battery_says_nothing(self) -> None:
        """Нечисловое значение молчит.

        Returns:
            Ничего.
        """
        service = _service(_StubAdapter({BATTERY_TERASSA: "nan", BATTERY_SPALNIA: "81"}))

        assert await service.check_once() == []


class TestRepeatedChecksStayQuiet:
    """Повторные проверки не превращаются в поток одинаковых записей."""

    async def test_same_problem_warns_once(self) -> None:
        """Десять проходов подряд — одно предупреждение в журнале.

        Проверяется журнал, а не возвращаемое значение: список проблем должен
        показывать проблему каждый проход (он читается как сводка), а вот
        предупреждение повторяться не должно.

        Returns:
            Ничего.
        """
        service = _service(_StubAdapter({BATTERY_TERASSA: "1", BATTERY_SPALNIA: "81"}))

        with _capture_warnings() as messages:
            for _ in range(10):
                await service.check_once()

        battery_warnings = [m for m in messages if BATTERY_TERASSA in m]

        assert len(battery_warnings) == 1, (
            f"пока заряд не изменился, повторять предупреждение незачем: "
            f"{len(battery_warnings)} записей за десять проходов"
        )

    async def test_recovered_battery_stops_reporting(self) -> None:
        """Батарейку заменили — проблема исчезает.

        Returns:
            Ничего.
        """
        adapter = _StubAdapter({BATTERY_TERASSA: "1", BATTERY_SPALNIA: "81"})
        service = _service(adapter)

        assert await service.check_once() == [BATTERY_TERASSA]

        adapter._states[BATTERY_TERASSA] = "95"

        assert await service.check_once() == [], (
            "батарейку заменили: проблема снята, и повторно сообщать о ней нельзя, "
            "иначе в списке проблем будет значиться то, что уже починено"
        )


class TestDescribe:
    """Состояние наблюдения видно в сводке готовности."""

    async def test_describe_reports_counts(self) -> None:
        """Сводка содержит порог и число проблем.

        Returns:
            Ничего.
        """
        service = _service(_StubAdapter({BATTERY_TERASSA: "1", BATTERY_SPALNIA: "81"}))

        await service.check_once()
        summary: dict[str, Any] = service.describe()

        assert summary["low_threshold"] == LOW
        assert summary["low_batteries"] == [BATTERY_TERASSA]
        assert summary["checked"] == 2
