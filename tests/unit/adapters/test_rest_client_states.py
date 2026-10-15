"""Ответ дома с кодом ошибки — отказ чтения, а не «приборов нет» (аудит 2026-10-16, К-1).

Самое дорогое место платформы было здесь: ``fetch_devices`` возвращал пустой
список и на ответ 500. Пустой результат ниже по пути означает «источник без
приборов», поэтому синхронизация помечала **каждый известный прибор** исчезнувшим
и снимала с него автоматику. Один ответ 500 — и дом терял управление светом,
климатом и шторами, показывая «источник подключён, синхронизация успешна».

Здесь проверяется рубеж: код ошибки обязан стать исключением. Пустой список при
настоящем ответе 200 остаётся законным «в источнике ничего нет».
"""

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from typing import Any

import pytest

from adapters.home_assistant.rest_client import HARestClient, HAStatesUnavailableError


class _Response:
    """Ответ Home Assistant, каким его видит клиент."""

    def __init__(self, status: int, payload: Any = None) -> None:
        """Собрать ответ.

        Args:
            status: Код ответа.
            payload: Разобранное тело ответа.
        """
        self.status = status
        self._payload = payload

    async def __aenter__(self) -> _Response:
        """Войти в контекст ответа.

        Returns:
            Сам ответ.
        """
        return self

    async def __aexit__(self, *args: Any) -> None:
        """Выйти из контекста ответа.

        Args:
            *args: Доводы контекста.

        Returns:
            Ничего.
        """
        return None

    async def json(self) -> Any:
        """Тело ответа.

        Returns:
            Разобранное тело.
        """
        return self._payload


class _Session:
    """HTTP-сессия, отвечающая заготовленным ответом."""

    def __init__(self, response: _Response) -> None:
        """Собрать сессию.

        Args:
            response: Ответ на любой запрос.
        """
        self._response = response

    def get(self, *args: Any, **kwargs: Any) -> _Response:
        """Запросить состояния.

        Args:
            *args: Доводы запроса.
            **kwargs: Доводы запроса.

        Returns:
            Заготовленный ответ.
        """
        del args, kwargs
        return self._response


def _client(response: _Response) -> HARestClient:
    """Клиент, считающий себя подключённым и отвечающий заготовкой.

    Args:
        response: Ответ дома.

    Returns:
        Клиент Home Assistant.
    """
    client = HARestClient("http://ha.local:8123", "token_12345")
    client.session = _Session(response)  # type: ignore[assignment]
    client._connected = True  # noqa: SLF001 — состояние подключения для проверки
    return client


class TestErrorCodeIsNotAnEmptyHouse:
    """Код ошибки не должен выглядеть как «дом без приборов»."""

    @pytest.mark.asyncio
    async def test_error_status_raises(self) -> None:
        """Ответ 500 становится исключением, а не пустым списком.

        Returns:
            Ничего.
        """
        client = _client(_Response(500))

        with pytest.raises(HAStatesUnavailableError):
            await client.fetch_devices()

    @pytest.mark.asyncio
    async def test_malformed_body_raises(self) -> None:
        """Ответ 200 не списком — тоже отказ чтения, а не «пусто».

        Returns:
            Ничего.
        """
        client = _client(_Response(200, {"unexpected": "shape"}))

        with pytest.raises(HAStatesUnavailableError):
            await client.fetch_devices()

    @pytest.mark.asyncio
    async def test_empty_list_is_still_legal(self) -> None:
        """Пустой список при ответе 200 — законное «в источнике нет приборов».

        Returns:
            Ничего.
        """
        client = _client(_Response(200, []))

        assert await client.fetch_devices() == []

    @pytest.mark.asyncio
    async def test_states_are_returned(self) -> None:
        """Обычный ответ возвращается состояниями.

        Returns:
            Ничего.
        """
        states = [{"entity_id": "light.kitchen", "state": "on", "attributes": {}}]
        client = _client(_Response(200, states))

        assert await client.fetch_devices() == states
