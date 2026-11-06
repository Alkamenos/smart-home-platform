"""Connection lifecycle for the Home Assistant WebSocket client (spec 018, T059).

Extracted from SimpleHAWebSocketClient: connecting, authenticating, listening,
closing and subscribing.
"""

# mypy: disable-error-code="attr-defined"

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from adapters.ha_constants import SUBSCRIPTION_TIMEOUT_SEC, WS_CLOSE_TIMEOUT_SEC


logger = logging.getLogger("adapters.ha_websocket")


class HaWsConnectionMixin:
    """Connect, listen, close and subscribe."""

    ws: Any
    connected: bool
    _msg_id: int
    _handlers: dict[int, Callable[..., Any]]
    _event_handler: Any
    _listen_task: asyncio.Task[None] | None
    _event_worker_task: asyncio.Task[None] | None
    _disconnect_reason: str | None
    subscription_confirmed: bool
    subscription_error: str | None
    filtered_entity_ids: tuple[str, ...]
    _pending_subscription_id: int
    _filter_size_last_seen: int

    async def connect(self) -> None:
        if self.ws is not None:
            await self.close()
            self.ws = None
        self._msg_id = 0
        self._handlers.clear()
        self._event_handler = None
        # Причина прошлого разрыва не должна пережить новое подключение: иначе
        # после успешного восстановления она продолжала бы объяснять то, что
        # давно починено.
        self._disconnect_reason = None
        try:
            import websockets

            # Предел размера сообщения поднят намеренно. По умолчанию библиотека
            # рвёт сообщения больше мегабайта, а реестр сущностей дома весит
            # 1.23 МБ (2107 сущностей, замер 2026-10-16): ответ молча не доходил,
            # и чистка мусора считала, что все вспомогательные элементы «откуда
            # бог весть», вместо «описан в YAML» или «создан через интерфейс».
            # 16 МБ — не «без предела»: безграничное чтение дало бы одному
            # сообщению съесть память платформы.
            self.ws = await websockets.connect(self.url, max_size=16 * 1024 * 1024)
            self.connected = True

            raw = await asyncio.wait_for(self.ws.recv(), timeout=15)
            msg = json.loads(raw)
            if msg.get("type") != "auth_required":
                self.connected = False
                raise ConnectionError(f"Expected auth_required, got: {msg}")

            await self.ws.send(
                json.dumps(
                    {
                        "type": "auth",
                        "access_token": self.token,
                    }
                )
            )

            raw = await asyncio.wait_for(self.ws.recv(), timeout=15)
            msg = json.loads(raw)
            if msg.get("type") == "auth_ok":
                logger.info("HAAdapter: WebSocket authenticated successfully")
            else:
                self.connected = False
                raise ConnectionError(f"Auth failed: {msg}")

            self._listen_task = asyncio.create_task(self._listen_loop())
            self._event_worker_task = asyncio.create_task(self._event_worker())

        except Exception as e:
            logger.warning(f"WebSocket connection failed: {e}")
            self.connected = False

    async def _listen_loop(self) -> None:
        """Читать события, пока соединение живо.

        Флаг ``connected`` сбрасывается в ``finally``, а не в ``except``.
        Home Assistant закрывает соединение штатно (``CLOSE 1001 going away``),
        и цикл чтения при этом доходит до конца **без исключения**: проверено
        на websockets 17.1 и 17.2. Прежний код трогал флаг только в ``except``,
        поэтому после штатного разрыва клиент оставался «подключённым» — и
        ``/ready`` отвечал ``home_assistant: ok``, хотя ни одного события
        больше не пришло бы. Наблюдалось в бою 2026-10-07 пять часов подряд.
        """
        try:
            async for raw in self.ws:
                try:
                    msg = json.loads(raw)
                    msg_type = msg.get("type")

                    if msg_type == "event" and self._event_handler:
                        event_data = msg.get("event", {})
                        payload = event_data.get("data", event_data)
                        # Контекст события лежит в конверте — рядом с `data`,
                        # а не внутри (снято с живого HA 2026-10-08:
                        # `event = {event_type, data, context, ...}`).
                        # Раньше в обработчик уходило только `data`, и
                        # `user_id` не доходил до record_manual_control:
                        # ручная блокировка не включалась ни одним путём из
                        # дома, хотя сами тесты #18 проходили — они собирали
                        # сообщение с контекстом руками.
                        if (
                            isinstance(payload, dict)
                            and "context" in event_data
                            and "context" not in payload
                        ):
                            payload = {**payload, "context": event_data["context"]}
                        # В очередь, а не сразу в обработчик: чтение сокета не
                        # должно ждать обработку события, иначе команда из
                        # обработчика блокирует чтение ответа на неё самой.
                        self._event_queue.put_nowait(payload)

                    elif msg_type == "result":
                        msg_id = msg.get("id")
                        if msg_id in self._handlers:
                            handler = self._handlers.pop(msg_id)
                            handler(msg)

                except Exception as e:
                    logger.warning(f"HAAdapter: error processing WS message: {e}")
        except Exception as e:
            self._disconnect_reason = f"{type(e).__name__}: {e}"
            logger.warning(f"HAAdapter: listen loop terminated: {e}")
        else:
            # Штатное закрытие: HA ушёл молча, без ошибки. Причина записывается
            # явно, иначе по журналу это неотличимо от «мы отключились сами».
            self._disconnect_reason = f"соединение закрыто сервером: {self.ws.close_code}"
        finally:
            self.connected = False
            logger.warning(f"HAAdapter: listen loop finished ({self._disconnect_reason})")

    async def close(self) -> None:
        # Инструментация #70: heartbeat входит в close() и не возвращается. Чтобы
        # сказать, на каком именно ожидании встали, нужна запись ДО и ПОСЛЕ каждого
        # шага, а не только вход и выход. Уровень WARNING — логи клиента наследуют
        # корневой обработчик, где INFO не виден (проверено: от этого модуля в
        # журнале не было ни одной строки).
        logger.warning(f"HAAdapter: close() start, listen_task={self._listen_task!r}")
        if self._listen_task:
            self._listen_task.cancel()
            logger.warning(f"HAAdapter: close() cancel sent, task done={self._listen_task.done()}")
            if self._event_worker_task:
                self._event_worker_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._listen_task
            logger.warning(
                f"HAAdapter: close() listen_task awaited, done={self._listen_task.done()}"
            )
        else:
            logger.warning("HAAdapter: close() no listen_task")
        if self.ws:
            logger.warning("HAAdapter: close() closing websocket")
            # Закрытие ограничено по времени (#70). Библиотека ждёт рукопожатия
            # закрытия, которого на молчащем соединении не приходит, и `close()`
            # не возвращался никогда: heartbeat застревал здесь, сокет оставался
            # открытым, переподключения не происходило, а /ready отвечал 200.
            # Известно живьём: второй вызов close() на том же сокете закрывал его
            # за 46 мс, а первый не возвращался совсем.
            try:
                await asyncio.wait_for(self.ws.close(), timeout=WS_CLOSE_TIMEOUT_SEC)
                logger.warning("HAAdapter: close() websocket closed")
            except TimeoutError:
                # Таймаут — не повод молчать: закрытие не завершилось, и это
                # единственный признак, по которому висяние видно в журнале.
                logger.warning(
                    f"HAAdapter: close() websocket close timed out after "
                    f"{WS_CLOSE_TIMEOUT_SEC}s, continuing anyway"
                )
            except Exception as error:  # noqa: BLE001 — закрытие не должно ронять heartbeat
                logger.warning(f"HAAdapter: close() websocket close failed: {error}")
        self.connected = False

    async def subscribe(
        self,
        handler: Callable[[dict[str, Any]], Awaitable[None]],
        filter_dict: dict[str, Any],
    ) -> None:
        """Подписаться на события Home Assistant.

        Args:
            handler: Обработчик входящего события.
            filter_dict: Фильтр подписки. Поле ``type`` обязательно, поле
                ``entity_ids`` ограничивает список присылаемых сущностей.
        """
        if self.ws and self.connected:
            self._msg_id += 1
            self._event_handler = handler
            sub_msg: dict[str, Any] = {
                "id": self._msg_id,
                "type": "subscribe_events",
                "event_type": filter_dict.get("type", ""),
            }
            # Списка сущностей в API Home Assistant нет. Проверено на живом HA
            # 2026-10-08 пятью вариантами подписки: принимаются `event_type`
            # и `event_id`, а `entity_ids` и даже `entity_id` отвергаются с
            # `extra keys not allowed`. Прежний код отправлял `entity_ids`,
            # HA отвергал подписку, а платформа писала в журнал «subscribed» и
            # ждала событий, которых не могло быть: `/ready` зелёный, доставки
            # нет. Тот же класс, что #9.
            #
            # Поэтому фильтр применяется у нас: подписка идёт на все события,
            # а лишние отбрасываются на входе. Отброшенные считаются — иначе
            # «приходят все 1502» снова станет невидимым.
            entity_ids = tuple(filter_dict.get("entity_ids") or ())
            self.filtered_entity_ids = entity_ids
            # Отсчёт для лога изменений фильтра начинается со снимка подписки:
            # первая смена состава манифеста будет видна как «N -> M», а не
            # как «0 -> M» с потерей исходной точки.
            self._filter_size_last_seen = len(entity_ids)

            self.subscription_confirmed = False
            self.subscription_error = None
            self._pending_subscription_id = self._msg_id

            await self.ws.send(json.dumps(sub_msg))

            try:
                await asyncio.wait_for(
                    self._subscription_result(),
                    timeout=SUBSCRIPTION_TIMEOUT_SEC,
                )
            except TimeoutError:
                self.subscription_error = (
                    f"HA не ответил на подписку за {SUBSCRIPTION_TIMEOUT_SEC:g} с"
                )
                logger.warning(
                    f"HAAdapter: подписка на {sub_msg['event_type']!r} не "
                    f"подтверждена ({self.subscription_error}) — события могут "
                    f"не приходить"
                )

    async def _subscription_result(self) -> None:
        """Дождаться ответа HA на подписку и запомнить, принял ли он её.

        Returns:
            Ничего.
        """
        message = await self._request_result(self._pending_subscription_id)
        if message.get("success") is True:
            self.subscription_confirmed = True
            logger.warning(
                f"HAAdapter: подписка на события подтверждена HA, "
                f"ограничение по сущностям применяется на нашей стороне "
                f"({len(self.filtered_entity_ids)} шт.)"
            )
            return

        error = message.get("error") or {}
        reason = f"{error.get('code', 'unknown')}: {error.get('message', 'без пояснения')}"
        self.subscription_error = reason
        logger.warning(f"HAAdapter: HA отверг подписку ({reason})")

    async def _request_result(self, msg_id: int) -> dict[str, Any]:
        """Дождаться ответа HA на запрос с указанным идентификатором.

        Args:
            msg_id: Идентификатор запроса.

        Returns:
            Ответ HA целиком: ``success``, ``result`` либо ``error``.
        """
        loop = asyncio.get_running_loop()
        result_future: asyncio.Future[Any] = loop.create_future()

        def on_result(msg: dict[str, Any]) -> None:
            if not result_future.done():
                result_future.set_result(msg)

        self._handlers[msg_id] = on_result
        try:
            response = await result_future
        finally:
            self._handlers.pop(msg_id, None)
        return response
