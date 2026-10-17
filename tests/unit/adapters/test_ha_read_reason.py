"""Чтение сущности по имени: «сущности нет в доме» и «не прочитали» — разные вещи.

Аудит 2026-10-16, К-5. Прежде чтение отдавало ``None`` и когда сущности в доме
нет (Home Assistant отвечает `404`), и когда прочитать не удалось (нет связи,
таймаут, ответ `5xx`). Именно эта неразличимость стояла за боевым дефектом
`may_heat`: уставка читается по имени, и «данных нет» выглядело одинаково и для
опечатки в манифесте, и для обрыва связи — обогрев не включался, а причина
называлась одна и та же.

Здесь проверяется, что причина называется: `404` — «сущности нет в доме» (дело
оператора: поправить манифест или вернуть прибор), всё остальное — «не прочитали»
(временная беда, лечится повтором). Отсутствие называется один раз на процесс:
иначе одна опечатка в манифесте забивала бы журнал при каждом подключении.

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0
"""

from __future__ import annotations

import logging
from typing import Any

import pytest

from adapters.ha_adapter import HAAdapter


#: Сущность, которой в доме нет (ответ 404).
ABSENT_ENTITY = "input_number.net_takoi_sushchnosti"


class _Response:
    """Ответ Home Assistant с заданным кодом и телом."""

    def __init__(self, status: int, payload: Any = None, broken: bool = False) -> None:
        """Запомнить ответ.

        Args:
            status: Код ответа.
            payload: Разобранное тело.
            broken: Ломать ли разбор тела.
        """
        self.status = status
        self._payload = payload
        self._broken = broken

    async def __aenter__(self) -> _Response:
        """Войти в контекст.

        Returns:
            Сам ответ.
        """
        return self

    async def __aexit__(self, *args: Any) -> None:
        """Выйти из контекста.

        Args:
            *args: Не используются.

        Returns:
            Ничего.
        """
        return None

    async def json(self) -> Any:
        """Разобрать тело ответа.

        Returns:
            Тело ответа.

        Raises:
            ValueError: Если тело задано испорченным.
        """
        if self._broken:
            raise ValueError("тело не разобрано")
        return self._payload


class _Session:
    """Сессия-двойник: на любой запрос отвечает одним и тем же."""

    def __init__(self, status: int = 200, payload: Any = None, broken: bool = False) -> None:
        """Запомнить ответ.

        Args:
            status: Код ответа.
            payload: Разобранное тело.
            broken: Ломать ли разбор тела.
        """
        self._status = status
        self._payload = payload
        self._broken = broken

    def get(self, url: str, **kwargs: Any) -> _Response:
        """Ответ на запрос состояния сущности.

        Args:
            url: Адрес с идентификатором сущности на конце.
            **kwargs: Заголовки и таймаут, не используются.

        Returns:
            Заготовленный ответ.
        """
        return _Response(self._status, self._payload, self._broken)


class _Client:
    """Клиент-двойник: помнит, что адаптер положил в глобальные значения."""

    def __init__(self) -> None:
        """Создать пустой клиент."""
        self.stored: dict[str, tuple[str | None, str]] = {}

    def store_global(self, role: str, state: str | None, entity: str) -> None:
        """Записать глобальное значение.

        Args:
            role: Роль сущности.
            state: Прочитанное состояние.
            entity: Идентификатор сущности.
        """
        self.stored[role] = (state, entity)


def _adapter(session: Any) -> tuple[HAAdapter, _Client]:
    """Адаптер с заданной сессией и клиентом-двойником.

    Тесты соседних файлов собирают адаптер через ``__new__`` и выставляют поля
    руками; причина — полноценный ``__init__`` поднимает очереди и подписки,
    которых чтению одной сущности не нужно.

    Args:
        session: Сессия (двойник) либо ``None``: связи нет.

    Returns:
        Адаптер и клиент-двойник.
    """
    client = _Client()
    adapter = HAAdapter.__new__(HAAdapter)
    adapter._ws_client = client
    adapter._session = session
    adapter._token = "stub"
    adapter._ws_url = "ws://localhost:8123/api/websocket"
    adapter.climate_entities = {"setpoint": ABSENT_ENTITY}
    adapter._absent_reported = set()
    return adapter, client


def _absence_records(caplog: pytest.LogCaptureFixture) -> list[logging.LogRecord]:
    """Записи журнала об отсутствии сущности в доме.

    Args:
        caplog: Захваченный журнал.

    Returns:
        Записи, называющие отсутствие.
    """
    return [record for record in caplog.records if "отсутствует в доме" in record.getMessage()]


class TestReadReason:
    """Причина чтения не теряется."""

    @pytest.mark.asyncio
    async def test_absent_entity_is_named_in_the_log(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """404 — «сущности нет в доме», и это сказано прямо.

        Returns:
            Ничего.
        """
        adapter, client = _adapter(_Session(status=404, payload={"message": "Entity not found"}))
        caplog.set_level(logging.WARNING)

        await HAAdapter._refresh_climate_globals(adapter)  # noqa: SLF001

        assert client.stored["setpoint"] == (None, ABSENT_ENTITY), (
            "значение остаётся «нет данных»: чтение не выдумывает состояние"
        )
        assert _absence_records(caplog), "отсутствие сущности обязано быть названо в журнале"
        assert ABSENT_ENTITY in caplog.text

    @pytest.mark.asyncio
    async def test_failed_read_is_not_called_absence(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Ответ 5xx — «не прочитали», а не «сущности нет»: это разные дела.

        Returns:
            Ничего.
        """
        adapter, _ = _adapter(_Session(status=500))
        caplog.set_level(logging.WARNING)

        await HAAdapter._refresh_climate_globals(adapter)  # noqa: SLF001

        assert not _absence_records(caplog), (
            "сбой чтения нельзя выдавать за отсутствие сущности: чинить будут не то"
        )
        assert "500" in caplog.text, "причина отказа чтения обязана быть названа"

    @pytest.mark.asyncio
    async def test_broken_body_is_a_failed_read(self, caplog: pytest.LogCaptureFixture) -> None:
        """Испорченное тело ответа — отказ чтения, а не отсутствие сущности.

        Returns:
            Ничего.
        """
        adapter, _ = _adapter(_Session(status=200, broken=True))
        caplog.set_level(logging.WARNING)

        await HAAdapter._refresh_climate_globals(adapter)  # noqa: SLF001

        assert not _absence_records(caplog)

    @pytest.mark.asyncio
    async def test_no_connection_is_not_absence(self, caplog: pytest.LogCaptureFixture) -> None:
        """Без связи сущности не объявляются отсутствующими.

        Returns:
            Ничего.
        """
        adapter, _ = _adapter(None)
        caplog.set_level(logging.WARNING)

        await HAAdapter._refresh_climate_globals(adapter)  # noqa: SLF001

        assert not _absence_records(caplog), (
            "пока связи нет, «сущности нет в доме» — догадка, а не знание"
        )

    @pytest.mark.asyncio
    async def test_readable_entity_is_stored_without_complaint(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Читаемая сущность попадает в клиент молча.

        Returns:
            Ничего.
        """
        adapter, client = _adapter(_Session(status=200, payload={"state": "21.5"}))
        caplog.set_level(logging.WARNING)

        await HAAdapter._refresh_climate_globals(adapter)  # noqa: SLF001

        assert client.stored["setpoint"] == ("21.5", ABSENT_ENTITY)
        assert not caplog.records, "исправное чтение не должно писать в журнал"

    @pytest.mark.asyncio
    async def test_absence_is_named_once_per_process(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Одна опечатка в манифесте — одна запись, а не на каждом подключении.

        Returns:
            Ничего.
        """
        adapter, _ = _adapter(_Session(status=404))
        caplog.set_level(logging.WARNING)

        await HAAdapter._refresh_climate_globals(adapter)  # noqa: SLF001
        await HAAdapter._refresh_climate_globals(adapter)  # noqa: SLF001

        assert len(_absence_records(caplog)) == 1, (
            "повторные подключения не должны повторять одну и ту же жалобу"
        )

    @pytest.mark.asyncio
    async def test_get_entity_state_keeps_its_contract(self) -> None:
        """Публичное чтение по-прежнему отдаёт только состояние.

        Returns:
            Ничего.
        """
        absent, _ = _adapter(_Session(status=404))
        assert await absent.get_entity_state(ABSENT_ENTITY) is None

        readable, _ = _adapter(_Session(status=200, payload={"state": "21.5"}))
        assert await readable.get_entity_state(ABSENT_ENTITY) == "21.5"
