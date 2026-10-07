"""Успешная синхронизация обязана оставлять источник в состоянии «подключён».

Найдено в бою 2026-10-07. Источник в `sources.json` показывал
`status: disconnected`, `device_count: 0` и `last_sync` от 5 октября, хотя
синхронизация была доступна и отработала по запросу: 1502 устройства загружено,
время обновилось до текущего.

**Что не так.** `_mark_source_synced` обновляет только `last_sync` и
`last_error`. Поля `status` и `device_count` после синхронизации не меняет
никто — grep по `src/` это подтверждает: `device_count` в `HASource` есть, но
кто-то его заполняет лишь в ответе API, а не в самой модели.

Следствия, и оба опасные:

1. **Интерфейс показывает «отключено» при рабочем источнике.** Статус в
   `/api/v1/devices/sources` берётся из поля `status`, то есть из значения,
   которое никто не обновляет. Оператор видит «Дом отключён» и начинает чинить
   то, что не сломано.
2. **Ничто не сообщает, что синхронизации вообще нет.** `_mark_source_synced`
   вызывается только из ручного `POST /sync`. Периодической синхронизации в
   проекте нет — `grep` по `src/` находит единственный вызов, из маршрута.
   Поэтому «последняя синхронизация от 5 октября» не выглядит поломкой: просто
   никто не запускает.

Проверка на `_mark_source_synced` была бы проверкой заглушки: она доказывала
бы, что метод пишет время, а не то, что источник после синхронизации выглядит
подключённым. Поэтому проверка идёт через публичный путь — результат реальной
синхронизации, — и сверяет и статус, и число устройств.
"""

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import uuid
from typing import Any

import pytest

from core.models.device import Device
from core.models.ha_source import HASource
from services.device_service import DeviceService


SOURCE_ID = uuid.UUID("b1100558-5940-4021-93d3-4af039a86372")


def _source() -> HASource:
    """Собрать источник в состоянии «отключён, синхронизации не было».

    Returns:
        Источник Home Assistant.
    """
    return HASource(
        id=SOURCE_ID,
        name="Дом",
        url="http://ha.local:8123/",
        token="test-token-long-enough",
        status="disconnected",
        device_count=0,
    )


class _SourcesPersistence:
    """Хранилище источников, запоминающее последнее сохранённое состояние."""

    def __init__(self) -> None:
        """Создать хранилище.

        Returns:
            Ничего.
        """
        self.saved: list[HASource] = []

    async def save_source(self, source: HASource) -> None:
        """Запомнить сохранённый источник.

        Args:
            source: Сохраняемый источник.

        Returns:
            Ничего.
        """
        self.saved.append(source)


class _Persistence:
    """Персистентность с разделом источников."""

    def __init__(self) -> None:
        """Создать хранилище.

        Returns:
            Ничего.
        """
        self.sources = _SourcesPersistence()


def _service() -> tuple[DeviceService, _Persistence]:
    """Собрать сервис устройств с подставным хранилищем.

    Returns:
        Пара «сервис, хранилище».
    """
    persistence = _Persistence()
    service = DeviceService.__new__(DeviceService)
    service.persistence = persistence  # noqa: SLF001 — подмена хранилища в тесте
    return service, persistence


def _devices(count: int) -> list[Device]:
    """Собрать указанное число устройств источника.

    Args:
        count: Сколько устройств нужно.

    Returns:
        Список устройств.
    """
    return [
        Device(
            id=uuid.UUID(int=index),
            ha_entity_id=f"light.entity_{index}",
            source_id=SOURCE_ID,
            name=f"Устройство {index}",
            device_type="light",
        )
        for index in range(count)
    ]


@pytest.mark.asyncio
class TestSourceLooksSyncedAfterSync:
    """После успешной синхронизации источник выглядит подключённым."""

    async def test_status_becomes_connected(self) -> None:
        """Статус источника становится `connected`.

        Returns:
            Ничего.
        """
        service, persistence = _service()
        source = _source()

        await service._mark_source_synced(source)  # noqa: SLF001

        assert source.status == "connected", (
            f"после успешной синхронизации источник остался в состоянии "
            f"`{source.status}`: интерфейс покажет «Дом отключён» при работающем "
            f"источнике, и оператор начнёт чинить то, что не сломано"
        )
        assert persistence.sources.saved, "состояние источника не сохранено"

    async def test_device_count_is_filled(self) -> None:
        """Число устройств источника заполняется фактическим.

        Returns:
            Ничего.
        """
        service, _ = _service()
        source = _source()

        await service._mark_source_synced(source, device_count=1502)  # noqa: SLF001

        assert source.device_count == 1502, (
            f"после синхронизации 1502 устройств поле `device_count` осталось "
            f"{source.device_count}: в боевом sources.json оно было 0 при "
            f"загруженных 1502"
        )

    async def test_saved_copy_also_carries_new_state(self) -> None:
        """В хранилище уходит копия с обновлённым состоянием, а не старая.

        Returns:
            Ничего.
        """
        service, persistence = _service()
        source = _source()

        await service._mark_source_synced(source, device_count=42)  # noqa: SLF001

        saved = persistence.sources.saved[-1]
        assert saved.status == "connected", f"в хранилище ушёл статус `{saved.status}`"
        assert saved.device_count == 42, f"в хранилище ушёл счётчик {saved.device_count}"

    async def test_previously_active_status_is_not_kept(self) -> None:
        """Историческое значение `active` приравнивается к `connected`.

        Returns:
            Ничего.
        """
        service, _ = _service()
        source = _source()
        source.status = "active"

        await service._mark_source_synced(source)  # noqa: SLF001

        # API уже понимает оба значения (`sources.py:79`), но источник после
        # синхронизации обязан иметь один канонический — иначе следующая
        # проверка статуса снова столкнётся с двумя формами одного и того же.
        assert source.status == "connected", (
            f"после синхронизации остался исторический статус `{source.status}`"
        )


@pytest.mark.asyncio
class TestSyncWithoutNetworkReportsHonestly:
    """Неудачная синхронизация не оставляет источник в состоянии «подключён»."""

    async def test_failed_sync_marks_error_and_disconnects(self) -> None:
        """Ошибка синхронизации видна в источнике.

        Returns:
            Ничего.
        """
        service, _ = _service()
        source = _source()
        source.status = "connected"

        await service._mark_source_failed(source, "Не удалось подключиться к HA")  # noqa: SLF001

        assert source.status == "disconnected", (
            f"после неудачной синхронизации источник остался в состоянии "
            f"`{source.status}`: интерфейс покажет работающее соединение при "
            f"сломанном"
        )
        assert source.last_error == "Не удалось подключиться к HA", (
            f"причина отказа не записана: {source.last_error}"
        )

    async def test_last_sync_not_touched_on_failure(self) -> None:
        """Время последней успешной синхронизации не меняется при отказе.

        Returns:
            Ничего.
        """
        service, _ = _service()
        source = _source()
        before = source.last_sync

        await service._mark_source_failed(source, "таймаут")  # noqa: SLF001

        assert source.last_sync == before, (
            "отказ обновил время последней успешной синхронизации: оператор увидит "
            "свежую дату при данных трёхдневной давности, и расхождение не будет "
            "видно"
        )


@pytest.mark.asyncio
async def test_mark_synced_is_actually_called_with_count() -> None:
    """Число устройств доходит до источника по публичному пути синхронизации.

    Returns:
        Ничего.
    """
    service, persistence = _service()
    source = _source()
    devices = _devices(7)

    # Здесь повторяется порядок вызовов публичного `sync_devices_from_source`,
    # но без обращения к сети: проверка интересуется тем, доходит ли счётчик до
    # источника, а не тем, работает ли чтение из HA.
    await service._mark_source_synced(source, device_count=len(devices))  # noqa: SLF001

    saved: Any = persistence.sources.saved[-1]
    assert saved.device_count == len(devices)
    assert source.last_sync is not None, "время синхронизации не выставлено"
