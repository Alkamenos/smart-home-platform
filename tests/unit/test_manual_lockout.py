"""Ручное действие человека должно побеждать автоматику.

Три независимые проверки одного и того же класса дефекта: **механизм есть,
выглядит исправным, а данных ему никто не передаёт**. Ручная блокировка написана
и корректна, но включается она сегодня только через `intent.source`, а список
ручных источников неполон и не пополняется тем, что платформа получает на самом
деле.

Почему это главный сценарий фичи
--------------------------------

Человек выключает свет, автоматика включает его обратно — и через несколько дней
её отключают навсегда. Домом с такой системой пользоваться нельзя, и никакая
остальная функция это не компенсирует.

Что проверяется
---------------

1. Событие от Home Assistant с указанием человека засчитывается как ручное
   действие — указание лежит в конверте события, а не в его данных, и именно
   поэтому раньше терялось.
2. Команда из веб-интерфейса платформы засчитывается как ручное действие.
3. Событие **без** указания человека ручным не считается: иначе блокировку
   запускали бы автоматические сценарии сами у себя и система заблокировала бы
   себя.
4. Внутренние служебные команды системы не считаются ручным действием.
5. После ручного действия автоматическая команда отклоняется на срок из
   манифеста и проходит после его истечения.
6. Повторное ручное действие продлевает отсчёт от него.

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0
"""

from __future__ import annotations

import asyncio
import time
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest

from adapters.ha_adapter import HAAdapter, SimpleHAWebSocketClient
from core.commands.dispatcher import CommandIntent
from core.commands.middleware import ManualLockoutMiddleware
from core.control_tracker import ControlTracker
from tests.helpers.ha_stub import state_changed_event


#: Устройство, которым в этой истории вмешивается человек.
DEVICE = "light.kitchen"


def _rules(lockout_minutes: int = 30) -> Any:
    """Правила автоматизации с заданным сроком блокировки освещения.

    Args:
        lockout_minutes: Срок блокировки для света.

    Returns:
        Объект правил, как их видит middleware.
    """
    lighting = SimpleNamespace(manual_lockout_min=lockout_minutes)
    return SimpleNamespace(
        lighting=lighting,
        climate=SimpleNamespace(manual_lockout_min=0),
        ventilation=SimpleNamespace(manual_lockout_min=0),
        global_manual_lockout_min=None,
    )


def _middleware(lockout_minutes: int = 30) -> ManualLockoutMiddleware:
    """Middleware с настоящим трекером и заданным сроком.

    Args:
        lockout_minutes: Срок блокировки для света.

    Returns:
        Готовая middleware и её трекер.
    """
    tracker = ControlTracker()
    return ManualLockoutMiddleware(_rules(lockout_minutes), tracker), tracker


def _intent(source: str, service: str = "turn_on") -> CommandIntent:
    """Команда от указанного источника.

    Args:
        source: Источник команды.
        service: Имя службы.

    Returns:
        Интент для отправки в middleware.
    """
    return CommandIntent(
        device_id=DEVICE,
        domain="light",
        service=service,
        data={},
        priority=50,
        source=source,
    )


class TestEventWithUserIsManual:
    """Указание человека в событии Home Assistant — ручное действие."""

    @pytest.mark.asyncio
    async def test_user_event_is_recorded_as_manual(self) -> None:
        """Человек нажал в приложении — платформа это запомнила.

        Ключевое место — конверт события: Home Assistant кладёт `context` рядом с
        `data`, а не внутрь. Заглушка собирает конверт целиком, иначе проверка
        смотрела бы на форму сообщения, которой Home Assistant не шлёт.
        """
        middleware, tracker = _middleware()
        adapter = HAAdapter(
            mode="pyscript",
            engine=None,
            hass=MagicMock(),
            manual_lockout_middleware=middleware,
        )

        message = state_changed_event(DEVICE, new_state="off", user_id="user-42")
        event = message["event"]
        data = event["data"]
        await adapter._handle_ws_state_change(
            {
                "entity_id": data["entity_id"],
                "old_state": data["old_state"],
                "new_state": data["new_state"],
                "context": event["context"],
            }
        )

        assert tracker.get_last_manual(DEVICE) is not None, (
            "событие с указанием человека не засчитано ручным действием: "
            "указание теряется при разборе конверта, и блокировка не включается"
        )

    @pytest.mark.asyncio
    async def test_event_without_user_is_not_manual(self) -> None:
        """Событие без указания человека ручным действием не является.

        Иначе блокировку запускали бы автоматические сценарии сами у себя:
        каждое событие, порождённое платформой, считалось бы вмешательством
        человека, и система заблокировала бы себя.
        """
        middleware, tracker = _middleware()
        adapter = HAAdapter(
            mode="pyscript",
            engine=None,
            hass=MagicMock(),
            manual_lockout_middleware=middleware,
        )

        message = state_changed_event(DEVICE, new_state="off", user_id=None)
        event = message["event"]
        data = event["data"]
        await adapter._handle_ws_state_change(
            {
                "entity_id": data["entity_id"],
                "old_state": data["old_state"],
                "new_state": data["new_state"],
                "context": event["context"],
            }
        )

        assert tracker.get_last_manual(DEVICE) is None, (
            "событие без указания человека засчитано ручным: система заблокирует сама себя"
        )


class TestWebUiCommandIsManual:
    """Команда из веб-интерфейса платформы — тоже ручное действие."""

    @pytest.mark.asyncio
    async def test_manual_command_is_allowed_and_recorded(self) -> None:
        """Команда человека проходит и засчитывается."""
        middleware, tracker = _middleware()

        result = await middleware.process(_intent("manual_command"))

        assert result is not None, "команда человека отклонена собственным же фильтром"
        assert tracker.get_last_manual(DEVICE) is not None, (
            "команда из веб-интерфейса не засчитана ручным действием: источник "
            "есть в коде, но отсутствует в списке известных"
        )

    @pytest.mark.asyncio
    async def test_manual_command_creates_lockout(self) -> None:
        """После команды человека автоматика уступает этому устройству."""
        middleware, _ = _middleware()

        await middleware.process(_intent("manual_command"))
        blocked = await middleware.process(_intent("lighting"))

        assert blocked is None, (
            "после вмешательства человека автоматика всё равно получила команду: "
            "жилец выключил свет, платформа включила обратно"
        )


class TestSystemCommandsAreNotManual:
    """Внутренние команды системы не должны засчитываться как вмешательство."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "source",
        ["lighting", "climate", "night_light", "fsm_state", "ventilation"],
    )
    async def test_automated_sources_do_not_record_manual(self, source: str) -> None:
        """Автоматика не должна записывать себя в ручные действия.

        Иначе первая же автоматическая команда блокировала бы саму себя: система
        засчитала бы своё действие вмешательством человека и больше не смогла бы
        управлять этим устройством.
        """
        middleware, tracker = _middleware()

        await middleware.process(_intent(source))

        assert tracker.get_last_manual(DEVICE) is None, (
            f"источник {source!r} засчитан как ручное действие: автоматика блокирует саму себя"
        )


class TestLockoutDuration:
    """Срок блокировки берётся из манифеста и отсчитывается от действия."""

    @pytest.mark.asyncio
    async def test_automated_command_blocked_within_period(self) -> None:
        """Внутри срока автоматика не проходит."""
        middleware, _ = _middleware(lockout_minutes=30)

        await middleware.process(_intent("manual_command"))
        blocked = await middleware.process(_intent("lighting"))

        assert blocked is None

    @pytest.mark.asyncio
    async def test_automated_command_allowed_after_period(self) -> None:
        """По истечении срока автоматика снова управляет устройством.

        Отсчёт идёт от времени ручного действия, а не от числа событий: устройством
        могут не пользоваться неделями, и блокировка обязана истечь сама.
        """
        middleware, tracker = _middleware(lockout_minutes=30)

        await middleware.process(_intent("manual_command"))
        assert tracker.get_last_manual(DEVICE) is not None, (
            "вмешательство человека не засчитано: истечение срока нечего проверять"
        )

        _expire_lockout(tracker, minutes=31)
        allowed = await middleware.process(_intent("lighting"))

        assert allowed is not None, (
            "по истечении срока блокировки автоматика всё ещё отклоняется: срок "
            "не истекает без событий"
        )

    @pytest.mark.asyncio
    async def test_repeated_manual_action_restarts_countdown(self) -> None:
        """Повторное вмешательство продлевает отсчёт от него."""
        middleware, tracker = _middleware(lockout_minutes=30)

        await middleware.process(_intent("manual_command"))
        _expire_lockout(tracker, minutes=20)
        await middleware.process(_intent("manual_command", service="turn_off"))
        assert tracker.get_last_manual(DEVICE) is not None, (
            "повторное вмешательство не засчитано: продление нечего проверять"
        )

        _expire_lockout(tracker, minutes=20)
        allowed = await middleware.process(_intent("lighting"))

        assert allowed is None, (
            "повторное вмешательство человека не продлило блокировку: человек "
            "выключил свет ещё раз, а автоматика вернула его через 40 минут"
        )

    @pytest.mark.asyncio
    async def test_zero_lockout_disables_blocking(self) -> None:
        """Срок, равный нулю, — блокировка выключена, а не всегда активна."""
        middleware, _ = _middleware(lockout_minutes=0)

        await middleware.process(_intent("manual_command"))
        allowed = await middleware.process(_intent("lighting"))

        assert allowed is not None


class TestCommandReachesDevice:
    """Заблокированная команда не должна доходить до устройства.

    Проверка замкнута на диспетчере, а не на самой middleware: middleware
    возвращает отказ, но исполнить его должна цепочка целиком.
    """

    @pytest.mark.asyncio
    async def test_blocked_command_never_reaches_adapter(self) -> None:
        """До Home Assistant не доходит ни одна команда во время блокировки."""
        from core.commands.dispatcher import CommandDispatcher

        middleware, _ = _middleware(lockout_minutes=30)
        adapter = _RecordingAdapter()

        dispatcher = CommandDispatcher(ha_adapter=adapter, middlewares=[middleware])

        await dispatcher.submit(_intent("manual_command"))
        await dispatcher.submit(_intent("lighting"))

        assert adapter.call_count == 1, (
            "заблокированная команда дошла до Home Assistant: жилец выключил "
            "свет, а платформа всё равно отправила команду включения"
        )


class TestRawFrameFromLiveHome:
    """Сырой кадр живого Home Assistant доходит до записи ручного действия.

    Этот тест закрывает обрыв, который тесты #18 не видели: они собирали
    `message` с `context` **руками**, а продакшен передаёт в обработчик то,
    что собрал `_listen_loop` из сырых байтов сокета. Живая проверка
    2026-10-08 показала два обрыва этого конвейера, оба закрыты отдельно:

    - контейнер не инжектит middleware в адаптер
      (`tests/test_container.py::test_adapter_receives_manual_lockout_middleware`);
    - клиент отрезал конверт события до обработчика: в `_deliver` уходило
      только `event.data`, а `context` лежит рядом с `data`.

    Структура кадра снята с настоящего HA 2026-10-08 (см. докстринг
    `state_changed_event`): `msg = {type, id, event}` и
    `event = {event_type, data, context, origin, time_fired}`.
    """

    #: Кадр в форме, которую HA реально шлёт (снято живьём 2026-10-08).
    LIVE_FRAME = {
        "type": "event",
        "id": 1,
        "event": {
            "event_type": "state_changed",
            "data": {
                "entity_id": DEVICE,
                "old_state": {"entity_id": DEVICE, "state": "on", "attributes": {}},
                "new_state": {"entity_id": DEVICE, "state": "off", "attributes": {}},
            },
            "context": {
                "id": "01M4DSCD53X4XE9CAGRV1YYZ0C",
                "parent_id": None,
                "user_id": "user-42",
            },
            "origin": "local",
            "time_fired": "2026-10-08T14:00:00.000000+00:00",
        },
    }

    @pytest.mark.asyncio
    async def test_live_frame_records_manual_control_end_to_end(self) -> None:
        """Кадр сокета → listen loop → обработчик → трекер помнит человека.

        Ничего не подменяется: настоящий `_listen_loop` читает сырые JSON-байты
        из очереди сокета, настоящий обработчик адаптера разбирает их. Если
        конверт обрезается на любом участке, `user_id` не доходит до
        `record_manual_control`, и человек выключает свет, которого автоматика
        не запомнит.

        Обработчик ставится напрямую, минуя `subscribe()`: объект подписки здесь
        ни на что не влияет, а ожидание ответного `result` зависело бы от
        гонки регистрации обработчика с доставкой кадра. Механизм подписки
        проверен отдельно (B30, `tests/integration/test_websocket_disconnect_visible.py`).
        """
        from tests.test_ha_adapter import FakeHAWebSocket  # noqa: PLC0415

        middleware, tracker = _middleware()
        adapter = HAAdapter(
            mode="websocket",
            ws_url="ws://localhost:8123",
            token="test_token",
            manual_lockout_middleware=middleware,
        )

        ws = FakeHAWebSocket()
        client = SimpleHAWebSocketClient(url="ws://localhost:8123", token="test_token")
        client.ws = ws
        client.connected = True
        client._event_handler = adapter._handle_ws_state_change  # noqa: SLF001
        client._listen_task = asyncio.create_task(client._listen_loop())  # noqa: SLF001

        try:
            ws.push(self.LIVE_FRAME)
            for _ in range(200):
                if tracker.get_last_manual(DEVICE) is not None:
                    break
                await asyncio.sleep(0.01)
        finally:
            await client.close()

        assert tracker.get_last_manual(DEVICE) is not None, (
            "живой кадр Home Assistant не включил ручную блокировку: конверт "
            "события обрезан на пути до обработчика, user_id не дошёл до "
            "record_manual_control — человек выключил свет, а платформа это "
            "не заметила"
        )


def _expire_lockout(tracker: ControlTracker, minutes: float) -> None:
    """Отмотать время последнего ручного действия.

    Подмена вместо ожидания: срок блокировки задаётся минутами, и ждать их в
    проверке нельзя. Факт подменяется целиком, а не сдвигом системных часов, —
    иначе проверка проверяла бы подмену часов, а не истечение срока.

    Args:
        tracker: Трекер с записанным ручным действием.
        minutes: Сколько минут прошло.
    """
    last = tracker.get_last_manual(DEVICE)
    if last is None:
        return
    object.__setattr__(last, "timestamp", time.time() - minutes * 60)


class _RecordingAdapter:
    """Адаптер, считающий отправленные в Home Assistant команды.

    Обычная заглушка со счётчиком, а не `MagicMock`: у магической заглушки
    `call_count` увеличивается и при вызове, и внутри `side_effect`, то есть
    каждая команда засчитывалась бы дважды — и проверка «дошло одно вместо двух»
    прошла бы при обратном.
    """

    def __init__(self) -> None:
        """Создать заглушку с нулевым счётчиком."""
        self.call_count = 0

    async def call_service(self, **_kwargs: Any) -> bool:
        """Засчитать команду.

        Args:
            **_kwargs: Поля команды — на счёт не влияют.

        Returns:
            True, как отвечает настоящий адаптер.
        """
        self.call_count += 1
        return True
