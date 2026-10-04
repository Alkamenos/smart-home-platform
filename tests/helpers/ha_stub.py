"""Заглушка внешней системы (Home Assistant) для интеграционных тестов.

Назначение — сделать так, чтобы ни один тест не зависел от наличия Home
Assistant в сети машины (FR-010) и чтобы отказ внешней системы был штатным
проверяемым сценарием, а не случайностью (R-03).

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0

Почему перехват именно здесь
----------------------------
`DeviceService._fetch_source_devices()` (`src/services/device_service.py:266-294`)
делает три шага подряд:

    async with HARestClient(source.url, source.token) as client:
        if not await client.connect_to_ha():      # ← уходит в сеть
            raise RuntimeError(...)
        ha_states = await client.fetch_devices()  # ← тоже сеть

Подмена одного лишь `fetch_devices` **не мешает коду дойти до соединения** —
именно так устроен текущий падающий `test_full_access_control_flow`, который
подменял выдачу устройств, но не подключение и потому уходил на
`192.168.1.100:8123`. Поэтому `stub_ha` подменяет `connect_to_ha` в первую
очередь, а `fetch_devices` — только вместе с ним.

`HARestClient` импортируется **внутри** функции, поэтому подмена атрибута
класса разрешается в момент вызова и работает корректно.

Факт о различимости отказов
---------------------------
`HARestClient.connect_to_ha()` (`rest_client.py:44-75`) **никогда не бросает
исключений**: любой сбой — отказ в соединении, таймаут, битый сертификат —
гасится и превращается в `return False`. Значит на уровне HTTP API отказ
соединения и таймаут **неразличимы**: оба дают 500 с одним и тем же
сообщением. Различить их можно только на уровне самого клиента.

Это не недостаток заглушки, а свойство производственного кода, и тесты не
должны делать вид, будто различают. Режимы `refused` и `timeout`
различаются здесь, на шве клиента, — и соответствующие тесты проверяют именно
клиент. Тесты уровня HTTP утверждают наблюдаемое: 500 с сообщением, называющим
адрес.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from enum import Enum
from typing import Any
from unittest.mock import patch


__all__ = [
    "HAUnavailable",
    "HAStub",
    "async_value",
    "stub_ha",
]


class HAUnavailable(Enum):
    """Как именно недоступна внешняя система.

    Values:
        AVAILABLE: Подключение удаётся, устройства выдаются.
        REFUSED: Соединение отклонено (хост недоступен).
        TIMEOUT: Истекает время ожидания ответа.
        ERROR: На подключении возникает неожиданная ошибка.
    """

    AVAILABLE = "available"
    REFUSED = "refused"
    TIMEOUT = "timeout"
    ERROR = "error"


def async_value(value: Any) -> Any:
    """Создаёт асинхронную функцию, всегда возвращающую значение.

    Принимает произвольные аргументы, потому что подставляется на место
    **методов экземпляра**: `patch(..., new=<функция>)` не превращает функцию в
    дескриптор, поэтому `self` приходит первым позиционным аргументом.
    Объявление без параметров даёт `TypeError: takes 0 positional arguments
    but 1 was given` — ровно то, что вскрыла самопроверка инфраструктуры.

    Args:
        value: Значение, которое вернёт вызов.

    Returns:
        Асинхронная функция, принимающая любые аргументы.
    """

    async def _value(*_args: Any, **_kwargs: Any) -> Any:
        return value

    return _value


def async_raiser(error: BaseException) -> Any:
    """Создаёт асинхронную функцию, всегда выбрасывающую исключение.

    Аргументы принимаются произвольно — по той же причине, что и в
    :func:`async_value`: подстановка идёт на место метода с ``self``.

    Args:
        error: Исключение, которое нужно выбросить.

    Returns:
        Асинхронная функция, принимающая любые аргументы.
    """

    async def _raise(*_args: Any, **_kwargs: Any) -> Any:
        raise error

    return _raise


class HAStub:
    """Описание состояния внешней системы для подмены.

    Attributes:
        mode: Как именно недоступна система.
        states: Список состояний, который вернёт выдача устройств.
        areas: Список областей; по умолчанию одна.
    """

    def __init__(
        self,
        mode: HAUnavailable = HAUnavailable.AVAILABLE,
        states: list[dict[str, Any]] | None = None,
        areas: list[dict[str, Any]] | None = None,
    ) -> None:
        """Инициализирует описание подмены.

        Args:
            mode: Режим доступности.
            states: Состояния устройств; при REFUSED/TIMEOUT не используются.
            areas: Области Home Assistant.
        """
        self.mode = mode
        self.states = states if states is not None else []
        self.areas = areas if areas is not None else [{"area_id": "test_area", "name": "Test"}]

    @property
    def connected(self) -> bool:
        """Удалось ли подключение при текущем режиме.

        Returns:
            True, если режим допускает подключение.
        """
        return self.mode is HAUnavailable.AVAILABLE

    def states_response(self) -> list[dict[str, Any]]:
        """Возвращает состояния с учётом режима.

        Returns:
            Список состояний; пустой, если система недоступна.
        """
        if not self.connected:
            return []
        return self.states

    def client_patch_target(self) -> str:
        """Возвращает путь атрибута, который подменяется для подключения.

        Returns:
            Dotted-путь до метода установки подключения.
        """
        return "adapters.home_assistant.rest_client.HARestClient.connect_to_ha"


@contextmanager
def stub_ha(
    states: list[dict[str, Any]] | None = None,
    mode: HAUnavailable = HAUnavailable.AVAILABLE,
    areas: list[dict[str, Any]] | None = None,
) -> Iterator[HAStub]:
    """Подменяет обращение к внешней системе на время теста.

    Подменяются три метода: `connect_to_ha` (шов установки соединения),
    `fetch_devices` и `fetch_areas`. Подмена `connect_to_ha` обязательна —
    без неё тест дойдёт до реального сетевого вызова.

    Args:
        states: Состояния устройств, которые вернёт выдача.
        mode: Как именно недоступна система.
        areas: Области Home Assistant.

    Yields:
        Описание подмены, по которому можно утверждать, что было подменено.
    """
    stub = HAStub(mode=mode, states=states, areas=areas)

    if mode is HAUnavailable.TIMEOUT:
        # Подменяем таймаут на шве клиента: на уровне API он неотличим от
        # отказа, но на уровне клиента — разные ситуации.
        connect = async_raiser(TimeoutError("превышено время ожидания"))
    elif mode is HAUnavailable.ERROR:
        connect = async_raiser(RuntimeError("неожиданный сбой подключения"))
    elif mode is HAUnavailable.REFUSED:
        # Точное поведение production-кода: сбой гасится и превращается в False.
        connect = async_value(False)
    else:
        connect = async_value(True)

    with (
        patch(stub.client_patch_target(), new=connect),
        patch(
            "adapters.home_assistant.rest_client.HARestClient.fetch_devices",
            new=async_value(stub.states_response()),
        ),
        patch(
            "adapters.home_assistant.rest_client.HARestClient.fetch_areas",
            new=async_value(stub.areas),
        ),
    ):
        yield stub
