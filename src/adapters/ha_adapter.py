"""
Home Assistant Adapter for Smart Home Platform.

This module provides an adapter for bidirectional communication with Home Assistant,
supporting both Pyscript mode (recommended for simplicity and hot-reload) and
WebSocket mode (for standalone execution outside HA).

Features:
- Dual-mode operation (Pyscript or WebSocket)
- End-to-end trace_id propagation for debugging
- Exponential backoff reconnection for WebSocket mode
- Graceful shutdown with timer cancellation
- Error isolation to prevent FSMEngine crashes
"""

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import time
import uuid
from collections.abc import Awaitable, Callable, Coroutine, Sequence
from typing import TYPE_CHECKING, Any, Protocol, cast, runtime_checkable

import aiohttp


# Use standard logging instead of loguru for consistency with logging_service
logger = logging.getLogger(__name__)


# Предел ожидания закрытия WebSocket. Закрытие идёт по рукопожатию, и на
# молчащем соединении оно может не прийти вовсе; ждать бесконечно означает
# остановить heartbeat и основной цикл адаптера (#70).
WS_CLOSE_TIMEOUT_SEC = 5.0

#: Сколько ждём ответа HA на подписку.
#:
#: Отдельно от закрытия: подписка не закрывает соединение, но без ответа на неё
#: события не придут, а узнать об этом можно только по отсутствию событий.
#: Константа, а не число в коде, чтобы проверки не ждали десять секунд каждая.
SUBSCRIPTION_TIMEOUT_SEC = 10.0


@runtime_checkable
class ActionGateProtocol(Protocol):
    """Разрешение на выполнение команд, выходящих в Home Assistant.

    Отдельный протокол, а не конкретный ``DeploymentManager``, потому что адаптер
    не должен зависеть от конкретного класса: запрет на выход — это свойство
    транспорта, а способ переключения режима — свойство политики (#77).
    """

    def should_execute_action(self) -> bool:
        """Вернуть True, если команды разрешено выполнять."""
        ...


class AlwaysExecuteGate:
    """Ворота, пропускающие всё.

    Значение по умолчанию, когда менеджер развёртывания не передан. Обратный
    вариант (блокировать всё) тихо отключил бы автоматику у того, кто забыл
    передать менеджер, и выглядел бы как «свет перестал включаться».
    """

    def should_execute_action(self) -> bool:
        """Всегда разрешать выполнение."""
        return True


class SimpleHAWebSocketClient:
    """Minimal WebSocket client implementing HA WebSocket API protocol.

    HA uses message-based auth:
      1. Client connects
      2. Server sends {"type": "auth_required", ...}
      3. Client sends {"type": "auth", "access_token": "..."}
      4. Server sends {"type": "auth_ok"} or {"type": "auth_invalid"}
    """

    def __init__(self, url: str, token: str, session: Any = None) -> None:
        self.url = url
        self.token = token
        self.session = session
        # Тип соединения определяется локальным импортом ``websockets`` внутри
        # connect(), поэтому имя типа здесь недоступно: атрибут помечается Any.
        # Без аннотации mypy выводил бы None из инициализатора и ругался на
        # каждый .recv()/.send()/.close() (attr-defined).
        self.ws: Any = None
        self.connected = False
        self._msg_id = 0
        self._handlers: dict[int, Callable[..., Any]] = {}
        self._event_handler: Callable[[dict[str, Any]], Awaitable[None]] | None = None
        self._listen_task: asyncio.Task[None] | None = None
        # Причина последнего разрыва. Нужна, чтобы отличить молчаливый уход HA
        # от собственной остановки: без неё оба случая выглядят одинаково.
        self._disconnect_reason: str | None = None
        # Подтверждена ли подписка ответом HA. Отправленное сообщение — ещё не
        # подписка: HA может отвергнуть её, и тогда события не придут никогда.
        self.subscription_confirmed: bool = False
        self.subscription_error: str | None = None
        # Сущности, ради которых подписывались. Фильтра на стороне HA нет
        # (проверено на живом HA 2026-10-08: `entity_ids` отвергается как
        # лишний ключ), поэтому ограничение применяется у нас.
        #
        # Список — замороженный снимок на момент subscribe(). Снимок слеп, если
        # манифест меняется после старта: устройство, добавленное через
        # /devices/apply, не получало бы собственных событий до рестарта
        # (Known Issue #83). Поэтому адаптер ставит сюда живой провайдер —
        # он важнее снимка и перечитывает манифест на каждом событии.
        self.filtered_entity_ids: tuple[str, ...] = ()
        self.entity_filter_provider: Callable[[], Sequence[str]] | None = None
        # Идентификатор подписки, ответ на который ещё ожидается. Инициализируется
        # перед вызовом _subscription_result().
        self._pending_subscription_id: int = 0
        # Сколько событий отброшено фильтром сущностей.
        self._filtered_out = 0
        # Размер фильтра при последнем наблюдении. Нужен, чтобы изменение
        # состава подписки было видно в журнале, а не только в памяти кода.
        self._filter_size_last_seen: int = 0

    @property
    def filtered_out_count(self) -> int:
        """Сколько событий отброшено фильтром сущностей.

        Returns:
            Счётчик отброшенных событий.
        """
        return self._filtered_out

    def _current_filter(self) -> Sequence[str]:
        """Список сущностей, ради которых стоит разбирать событие.

        Живой провайдер важнее снимка: провайдер перечитывает манифест
        адаптера, поэтому устройство, добавленное после старта, проходит
        фильтр сразу, без переподписки (Known Issue #83). Переподписка и не
        нужна — Home Assistant шлёт все события, ограничение чисто локальное.
        Пустой результат провайдера означает «фильтр выключен», как и пустой
        снимок: с пустым манифестом платформа обязана разбирать всё, а не
        молчать при зелёном /ready.

        Returns:
            Список `entity_id` для проверки; пустой, если фильтр не нужен.
        """
        if self.entity_filter_provider is None:
            return self.filtered_entity_ids
        current = self.entity_filter_provider()
        if len(current) != self._filter_size_last_seen:
            # WARNING: info в этом развёртывании не виден, а тихая смена
            # состава подписки — ровно то, что в бою (Known Issue #83)
            # обнаруживали только слепотой автоматики.
            logger.warning(
                f"HAAdapter: subscription filter changed: "
                f"{self._filter_size_last_seen} -> {len(current)} entities"
            )
            self._filter_size_last_seen = len(current)
        return current

    def _accepts(self, payload: dict[str, Any]) -> bool:
        """Относится ли событие к сущностям, ради которых подписались.

        Args:
            payload: Событие от HA.

        Returns:
            True, если событие стоит обрабатывать.
        """
        entity_ids = self._current_filter()
        if not entity_ids:
            return True
        entity_id = payload.get("entity_id")
        if not entity_id:
            return True
        return str(entity_id) in entity_ids

    def _record_filtered_event(self) -> None:
        """Отброшенное событие учитывается в метрике, а не только в памяти.

        Импорт метрик ленивый, как в ``_record_disconnect`` адаптера:
        импорт на уровне модуля создаёт цикл
        ``core.container → ha_adapter → src.core``.

        Returns:
            Ничего.
        """
        from core.metrics import get_metrics_collector

        get_metrics_collector().record_websocket_filtered_event()

    async def _deliver(self, payload: dict[str, Any]) -> None:
        """Передать событие обработчику, если оно проходит фильтр.

        Вынесено отдельно, чтобы доставка проверялась напрямую: события в бою
        приходят из сокета, и подмена пути скрыла бы, где именно теряется
        поток.

        Args:
            payload: Событие от HA.

        Returns:
            Ничего.
        """
        if not self._accepts(payload):
            self._filtered_out += 1
            self._record_filtered_event()
            return
        if self._event_handler is not None:
            await self._event_handler(payload)

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

            self.ws = await websockets.connect(self.url)
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
                        # Фильтр применяется здесь: ограничения на стороне HA
                        # нет. Отброшенные считаются, иначе «приходят все
                        # сущности дома» снова станет невидимым.
                        await self._deliver(payload)

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

    async def get_states(self) -> Any:
        if not self.ws or not self.connected:
            return []

        self._msg_id += 1
        msg_id = self._msg_id

        await self.ws.send(
            json.dumps(
                {
                    "id": msg_id,
                    "type": "get_states",
                }
            )
        )

        try:
            response = await asyncio.wait_for(self._request_result(msg_id), timeout=15)
            return response.get("result", [])
        except TimeoutError:
            return []

    async def call_service(
        self,
        domain: str,
        service: str,
        service_data: dict[str, Any] | None = None,
        return_response: bool = True,
    ) -> Any:
        if not self.ws or not self.connected:
            return None

        self._msg_id += 1
        msg_id = self._msg_id

        payload = {
            "id": msg_id,
            "type": "call_service",
            "domain": domain,
            "service": service,
            "service_data": service_data or {},
        }

        if return_response:
            loop = asyncio.get_event_loop()
            result_future: asyncio.Future[Any] = loop.create_future()

            def on_result(msg: dict[str, Any]) -> None:
                if not result_future.done():
                    result_future.set_result(msg)

            self._handlers[msg_id] = on_result
            await self.ws.send(json.dumps(payload))

            try:
                response = await asyncio.wait_for(result_future, timeout=15)
                return response.get("result")
            except TimeoutError:
                return None
        else:
            await self.ws.send(json.dumps(payload))
            return None


# Always use SimpleHAWebSocketClient (no external dependency)
HAS_WS_LIBRARY = True
# Псевдоним класса для читаемости аннотаций; присваивание само по себе
# корректно, поэтому подавлять здесь нечего (прежний ``# type: ignore`` был
# лишним — mypy сообщал unused-ignore).
HomeAssistantWS = SimpleHAWebSocketClient


if TYPE_CHECKING:
    from core.commands.middleware import ManualLockoutMiddleware
    from core.events.event_router import EventRouter


class HAAdapter:
    """
    Adapter for bidirectional communication with Home Assistant.

    Supports two modes of operation:
    1. Pyscript mode: Provides wrapper functions called from Pyscript files in HA.
    2. WebSocket mode: Uses aiohttp and homeassistant-websocket library for
       standalone execution outside HA.
    """

    def __init__(
        self,
        mode: str = "pyscript",
        engine: Any | None = None,
        hass: Any | None = None,
        ws_url: str | None = None,
        token: str | None = None,
        manual_lockout_middleware: ManualLockoutMiddleware | None = None,
        event_router: EventRouter | None = None,
        deployment: ActionGateProtocol | None = None,
    ) -> None:
        if mode not in ("pyscript", "websocket"):
            raise ValueError(f"Invalid mode: {mode}. Must be 'pyscript' or 'websocket'")

        self._mode = mode
        self._engine = engine
        self._hass = hass
        self._ws_url = ws_url
        self._token = token
        # Запрет на выход в Home Assistant. Передаётся из Container.build(),
        # иначе переменная SHADOW_MODE оставалась бы объявленной, но не
        # действующей (Known Issue #77).
        self._deployment: ActionGateProtocol = (
            deployment if deployment is not None else AlwaysExecuteGate()
        )

        self._manual_lockout_middleware = manual_lockout_middleware
        self._event_router = event_router
        self._ws_client: HomeAssistantWS | None = None
        self._session: aiohttp.ClientSession | None = None
        # Манифест для фильтра подписки. Не передаётся в __init__, чтобы не
        # менять его подпись: список сущностей нужен только при подписке, а
        # манифест меняется при hot-reload, и копия в адаптере разошлась бы с
        # реальной. Читается через getattr, поэтому адаптер, собранный без
        # манифеста (тесты, локальный запуск), работает как раньше.
        self._manifest: Any = None
        self._shutdown_event = asyncio.Event()
        self._reconnect_task: asyncio.Task[None] | None = None
        self._reconnect_attempt = 0
        self._connected_once = False
        self._trace_callbacks: list[
            Callable[[str, str, str, dict[str, Any]], Coroutine[Any, Any, None]]
        ] = []

        if mode == "pyscript" and hass is None:
            raise ValueError("hass instance is required for pyscript mode")
        if mode == "websocket":
            if ws_url is None:
                raise ValueError("ws_url is required for websocket mode")
            if token is None:
                raise ValueError("token is required for websocket mode")

        logger.info(f"HAAdapter initialized in '{mode}' mode")

    def set_fsm_engine(self, engine: Any) -> None:
        """Set the FSM engine reference (called by Container.build())."""
        self._fsm_engine = engine

    def _generate_trace_id(self) -> str:
        return str(uuid.uuid4())[:8]

    def _get_logger(self, trace_id: str) -> logging.LoggerAdapter[logging.Logger]:
        """Get a logger with trace_id context."""
        return logging.LoggerAdapter(logger, {"trace_id": trace_id})

    async def on_state_change(
        self,
        entity_id: str,
        new_state: str,
        old_state: str,
        context: dict[str, Any] | None = None,
    ) -> None:
        context = context or {}

        user_id = context.get("user_id")
        if user_id and self._manual_lockout_middleware:
            self._manual_lockout_middleware.record_manual_control(entity_id)

        trace_id = context.get("trace_id") or self._generate_trace_id()
        log = self._get_logger(trace_id)

        log.info(
            f"HAAdapter: state_change received for {entity_id}: '{old_state}' -> '{new_state}'"
        )

        payload = {
            "entity_id": entity_id,
            "new_state": new_state,
            "old_state": old_state,
            "context": {**context, "trace_id": trace_id},
        }

        # Доставка событий подписчикам идёт через шину платформы — ту же, что
        # использует движок (R-07). Раньше здесь стояло
        # `if hasattr(self._engine, "event_bus")`, и на настоящем `FSMEngine`
        # проверка давала False: шина называлась `_event_bus`, публичного
        # доступа к ней не было. Ветка публикации оказывалась мёртвой, а
        # работала запасная — `engine.trigger()` по идентификатору сущности
        # Home Assistant, который не является именем автомата, поэтому каждое
        # изменение состояния давало отказ `unknown_entity`, а состояние
        # устройства обновляла только ручная синхронизация (#9).
        #
        # Запасной ветки больше нет: подменять доставку вызовом движка нельзя,
        # а если шины нет, публиковать некуда и это не ошибка (тесты, локальный
        # запуск без шины).
        bus = getattr(self._engine, "event_bus", None)
        if bus is not None:
            try:
                await bus.publish(
                    event_type="state_change",
                    payload=payload,
                    trace_id=trace_id,
                )
            except Exception as e:
                log.error(f"HAAdapter: failed to publish event to EventBus: {e}")

        if self._event_router is not None:
            try:
                await self._event_router.route_state_change(
                    entity_id=entity_id,
                    new_state=new_state,
                    old_state=old_state,
                    context=context,
                )
            except Exception as e:
                log.error(f"HAAdapter: EventRouter.route_state_change failed for {entity_id}: {e}")

    async def call_service(
        self,
        domain: str,
        service: str,
        entity_id: str,
        data: dict[str, Any] | None = None,
        trace_id: str | None = None,
    ) -> bool:
        data = data or {}
        trace_id = trace_id or self._generate_trace_id()
        log = self._get_logger(trace_id)

        # Запрет на выход в Home Assistant. Стоит в единственной точке, откуда
        # платформа обращается к HA-сервисам: сюда попадают и команды автоматов
        # (через CommandDispatcher), и ручные команды из WebUI (через
        # DeviceService), причём разными способами вызова. Проверка на уровне
        # вызывающего кода обошла бы один из путей (Known Issue #77).
        if not self._deployment.should_execute_action():
            # WARNING, а не INFO: логи адаптера наследуют корневой обработчик,
            # где info не виден — на info проверка молчала бы и не доказала бы
            # ничего (урок #70). Уровень записей проверяется кодом.
            log.warning(
                f"[DRY RUN] Would execute: {domain}.{service}(entity_id={entity_id}, data={data})"
            )
            # Возвращается True намеренно: в режиме тени автомат продолжает
            # считать свои состояния, иначе нечего было бы наблюдать. Ответ,
            # которого на самом деле нет, и не должен выглядеть как отказ.
            return True

        log.info(f"HAAdapter: calling service {domain}.{service} for {entity_id}")

        try:
            if self._mode == "pyscript":
                return await self._call_service_pyscript(domain, service, entity_id, data, log)
            else:
                return await self._call_service_websocket(domain, service, entity_id, data, log)
        except Exception as e:
            log.error(f"HAAdapter: service call failed {domain}.{service} for {entity_id}: {e}")
            return False

    async def _call_service_pyscript(
        self,
        domain: str,
        service: str,
        entity_id: str,
        data: dict[str, Any],
        log: Any,
    ) -> bool:
        if self._hass is None:
            log.error("HAAdapter: hass instance not available in pyscript mode")
            return False

        service_data = {**data, "entity_id": entity_id}

        try:
            await self._hass.services.async_call(
                domain=domain,
                service=service,
                service_data=service_data,
            )
            return True
        except Exception as e:
            log.error(f"HAAdapter: pyscript service call error: {e}")
            return False

    async def _call_service_websocket(
        self,
        domain: str,
        service: str,
        entity_id: str,
        data: dict[str, Any],
        log: Any,
    ) -> bool:
        if self._ws_client is None:
            log.error("HAAdapter: WebSocket client not connected")
            return False

        service_data = {**data, "entity_id": entity_id}

        try:
            result = await self._ws_client.call_service(
                domain=domain,
                service=service,
                service_data=service_data,
                return_response=False,
            )
            return result is not None
        except Exception as e:
            log.error(f"HAAdapter: WebSocket service call error: {e}")
            return False

    async def start(self) -> None:
        """Start the adapter (WebSocket mode only).

        KEEPS: starts WebSocket connection as a BACKGROUND TASK so it does not
        block the caller. The caller can then poll ``is_connected`` to check
        progress.
        """
        if self._mode == "pyscript":
            logger.info("HAAdapter: start() is a no-op in pyscript mode")
            return

        if self._mode == "websocket":
            # Launch connection loop as a background task (non-blocking)
            self._reconnect_task = asyncio.create_task(self._connect_websocket())

    def _record_disconnect(self, reason: str, delay: float) -> None:
        """Зафиксировать потерю соединения: метрика + лог с номером попытки и задержкой.

        Инкрементирует ``websocket_disconnects_total`` и пишет WARNING только
        при реально установленном ранее соединении (``_connected_once``);
        неудачные попытки первичного подключения метрикой не считаются.
        Импорт метрик ленивый: импорт на уровне модуля создаёт цикл
        ``core.container → ha_adapter → src.core``.

        Args:
            reason: Причина обрыва (для лога).
            delay: Задержка перед следующей попыткой восстановления, сек.
        """
        from core.metrics import get_metrics_collector

        self._reconnect_attempt += 1
        if not self._connected_once:
            return
        self._connected_once = False
        get_metrics_collector().record_websocket_disconnect()
        logger.warning(
            f"HAAdapter: WebSocket lost ({reason}), "
            f"reconnecting (attempt {self._reconnect_attempt}, delay {delay:.1f}s)..."
        )

    async def _connect_websocket(self) -> None:
        """Establish WebSocket connection with exponential backoff."""
        reconnect_delay = 1.0
        max_reconnect_delay = 60.0

        while not self._shutdown_event.is_set():
            needs_backoff = False
            try:
                log = self._get_logger(self._generate_trace_id())
                # Инструментация #70: записи цикла переподключения печатаются на
                # уровне info либо через per-connection логгер, и в этом
                # развёртывании не видны ни те, ни другие. Поэтому по журналу
                # нельзя было отличить «цикл остановился» от «цикл работает
                # молча». Уровень WARNING — единственный, который здесь виден.
                logger.warning("🔌 HAAdapter: attempting WebSocket connection (iteration)")
                logger.info(f"🔌 HAAdapter: attempting WebSocket connection to {self._ws_url}")
                log.info(f"HAAdapter: connecting to WebSocket {self._ws_url}")

                # Отладочный лог
                log.info(f"HAAdapter: HomeAssistantWS class = {HomeAssistantWS}")
                log.info(f"HAAdapter: HAS_WS_LIBRARY = {HAS_WS_LIBRARY}")

                self._session = aiohttp.ClientSession()

                # Создаём клиент
                # cast, а не проверка: __init__ уже отвергает режим websocket
                # без ws_url/token, поэтому значения здесь заведомо не None.
                # Проверка в рантайме изменила бы поведение, а сужение через
                # атрибут mypy между методами не переносит.
                self._ws_client = HomeAssistantWS(
                    url=cast(str, self._ws_url),
                    token=cast(str, self._token),
                    session=self._session,
                )
                # Живой провайдер фильтра ставится до connect()/subscribe():
                # фильтр читает манифест в момент события, а не снимок на
                # момент подписки. Раньше список замораживался, и устройство,
                # добавленное через /devices/apply, оставалось слепым до
                # рестарта (Known Issue #83). Метод — bound method, поэтому
                # провайдер всегда видит актуальное self._manifest.
                self._ws_client.entity_filter_provider = self._subscribed_entities

                log.info(f"HAAdapter: ws_client created = {self._ws_client}")

                # Подключаемся
                await self._ws_client.connect()

                # КРИТИЧЕСКАЯ ПРОВЕРКА: реально ли подключились?
                if not getattr(self._ws_client, "connected", False):
                    raise ConnectionError("WebSocket connect() succeeded but connected=False")

                logger.info("✅ HAAdapter: WebSocket connected successfully!")

                # Подписываемся на события.
                #
                # Фильтра на стороне Home Assistant нет: API отвергает
                # `entity_ids` в subscribe_events (проверено на живом HA
                # 2026-10-08), поэтому подписка идёт на все события, а
                # ограничение применяется у нас, в _accepts. Здесь список
                # уходит только как снимок для лога и как отправная точка
                # для лога изменений фильтра.
                #
                # Пустой список означает подписку на всё: при пустом манифесте
                # лучше получать лишнее и отбивать у себя, чем не получать
                # ничего (тогда платформа выглядит исправной и молчит).
                subscribed = self._subscribed_entities()
                filter_dict: dict[str, Any] = {"type": "state_changed"}
                if subscribed:
                    filter_dict["entity_ids"] = subscribed

                await self._ws_client.subscribe(
                    self._handle_ws_state_change,
                    filter_dict,
                )
                # INFO-запись остаётся на месте: видимость покупается добавлением
                # WARNING, а не отказом от неё. Сторож на исходном тексте
                # (tests/unit/test_ha_adapter_reconnect_loop_observable.py) требует
                # и её присутствия, и это правильно: подписка — заметное событие,
                # и INFO для неё уместен.
                log.info("HAAdapter: subscribed to state_changed events")
                # Подписка считается успешной только после ответа HA. Раньше
                # запись делалась сразу после отправки, а HA отвергал её
                # неподдерживаемым ключом `entity_ids`: журнал врал, `/ready`
                # был зелёный, события не приходили никогда.
                if not self._ws_client.subscription_confirmed:
                    reason = self._ws_client.subscription_error or "причина неизвестна"
                    logger.warning(
                        f"🔔 HAAdapter: подписка на state_changed НЕ подтверждена "
                        f"({reason}); ограничение по {len(subscribed)} сущностям "
                        f"применяется на нашей стороне"
                    )
                elif subscribed:
                    # WARNING, а не INFO: логи адаптера наследуют корневой
                    # обработчик, где info не виден — проверка на info молчала бы
                    # и не доказала бы ничего (урок #70).
                    logger.warning(
                        f"🔔 HAAdapter: subscribed to state_changed for "
                        f"{len(subscribed)} entities from manifest "
                        f"(фильтр на нашей стороне: HA его не поддерживает)"
                    )
                else:
                    logger.warning(
                        "🔔 HAAdapter: manifest lists no entities — subscribed to "
                        "ALL state_changed events"
                    )
                logger.info("🔔 HAAdapter: listening for HA state changes...")

                reconnect_delay = 1.0
                self._reconnect_attempt = 0
                self._connected_once = True
                logger.info("✅ HAAdapter: WebSocket ready, backoff reset (delay=1.0s)")

                # 🆕 Инициализируем timestamp последнего события
                self._last_event_time = time.time()
                # Признак жизни соединения. Раньше порог «устаревшего» считался
                # от времени последнего события, а это время выставлялось только
                # здесь, при подключении, и нигде не обновлялось: обрыв
                # объявлялся ровно через 300 с после старта независимо от того,
                # как бурно шла жизнь дома. Тишина в доме и мёртвое соединение
                # были неразличимы.
                self._last_liveness_time = time.time()

                # 🆕 Запускаем heartbeat задачу для обнаружения мёртвых соединений
                heartbeat_task = asyncio.create_task(self._heartbeat_loop())

                try:
                    # Ждём сигнала остановки или завершения listen_task
                    listen_task = getattr(self._ws_client, "_listen_task", None)
                    if listen_task is not None and not listen_task.done():
                        tasks = [
                            asyncio.ensure_future(self._shutdown_event.wait()),
                            listen_task,
                        ]

                        done, pending = await asyncio.wait(
                            tasks,
                            return_when=asyncio.FIRST_COMPLETED,
                        )

                        reason = "listen task ended"
                        if listen_task in done:
                            reason = self._listen_task_reason(listen_task, log)
                    else:
                        # Задача чтения отсутствует или уже завершилась. Ждать
                        # дальше нечего: в ожидании остался бы только флаг
                        # остановки, который сам никогда не сработает. Прежний
                        # код именно так и уходил в ожидание forever — платформа
                        # навсегда переставала получать события, ни разу не
                        # написав об обрыве (Known Issue #70).
                        reason = "listen task missing or already done"

                    self._record_disconnect(reason, reconnect_delay)
                    needs_backoff = True
                finally:
                    # Останавливаем heartbeat при любом выходе
                    heartbeat_task.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await heartbeat_task

            except asyncio.CancelledError:
                # Ветка видна: она выходит из цикла, не делая ни паузы, ни
                # повторного подключения, и без записи выглядит как зависание.
                # Уровень WARNING — logger.info здесь не виден (#70).
                logger.warning("HAAdapter: reconnect loop cancelled - no retry will happen")
                break

            except Exception as e:
                trace_id = self._generate_trace_id()
                log = self._get_logger(trace_id)
                logger.error(f"❌ HAAdapter connection failed: {type(e).__name__}: {e}")
                if not isinstance(e, (ConnectionError, OSError, TimeoutError)):
                    logger.exception("HAAdapter: unexpected connection error")
                log.error(f"HAAdapter: connection error: {type(e).__name__}: {e}")

                # Логируем состояние для отладки
                log.error(f"HAAdapter: _ws_client is None = {self._ws_client is None}")
                if self._ws_client is not None:
                    log.error(
                        f"HAAdapter: _ws_client.connected = {getattr(self._ws_client, 'connected', 'N/A')}"
                    )
                    log.error(f"HAAdapter: _ws_client.ws = {getattr(self._ws_client, 'ws', 'N/A')}")

                self._record_disconnect(f"{type(e).__name__}: {e}", reconnect_delay)
                needs_backoff = True

            finally:
                await self._cleanup_websocket()

            if needs_backoff and not self._shutdown_event.is_set():
                logger.warning(f"🔄 HAAdapter: retrying in {reconnect_delay:.1f}s (visible)")
                await asyncio.sleep(reconnect_delay)
                reconnect_delay = min(reconnect_delay * 2, max_reconnect_delay)
            elif needs_backoff:
                # Ветка «нужна пауза, но система останавливается» раньше уходила
                # молча: цикл выходил из while по установленному _shutdown_event,
                # и в журнале не оставалось ни единой записи. Теперь видно.
                logger.warning("HAAdapter: backoff skipped, shutdown_event is set")

        logger.warning("HAAdapter: reconnect loop exited")

    @staticmethod
    def _listen_task_reason(listen_task: asyncio.Task[Any], log: Any) -> str:
        """Классифицирует завершение задачи чтения.

        Отдельный метод, а не три строки в цикле, потому что именно тут
        исходное исключение важно различать, а различение легко потерять:
        `CancelledError` не наследует `Exception`, поэтому `listen_task.result()`
        на отменённой задаче уходил в обработчик отмены самого цикла, цикл
        выходил, и переподключения не происходило никогда (#70).

        Отмена задачи чтения — ожидаемый исход при закрытии устаревшего
        соединения: так её останавливает heartbeat. Это обрыв, а не остановка
        платформы.

        Args:
            listen_task: Задача чтения.
            log: Журнал соединения.

        Returns:
            Причина завершения для `_record_disconnect`.
        """
        if listen_task.cancelled():
            return "listen task cancelled"
        try:
            listen_task.result()
        except Exception as error:
            log.warning(f"HAAdapter: listen_task ended unexpectedly: {error}")
            return f"listen task failed: {error}"
        return "listen task ended"

    async def _handle_ws_state_change(
        self,
        message: dict[str, Any],
        trace_id: str | None = None,
    ) -> None:
        trace_id = trace_id or self._generate_trace_id()
        log = self._get_logger(trace_id)
        self._last_liveness_time = time.time()

        try:
            entity_id = message.get("entity_id", "")
            old_state_obj = message.get("old_state", {})
            new_state_obj = message.get("new_state", {})

            old_state = old_state_obj.get("state", "unknown") if old_state_obj else "unknown"
            new_state = new_state_obj.get("state", "unknown") if new_state_obj else "unknown"

            logger.info(f"📡 HA STATE CHANGE: {entity_id}: '{old_state}' -> '{new_state}'")
            log.info(
                f"HAAdapter: WebSocket state_change for {entity_id}: '{old_state}' -> '{new_state}'"
            )

            # Указание пользователя лежит в конверте события, а не в его данных.
            # Раньше оно подставлялось заглушкой и терялось: без него платформа
            # не отличала «человек выключил свет» от «сработал сценарий», а
            # ручная блокировка не включалась ни одним путём. Именно поэтому
            # человек гасил свет, а автоматика включала его обратно.
            ha_context = message.get("context") or {}

            await self.on_state_change(
                entity_id=entity_id,
                new_state=new_state,
                old_state=old_state,
                context={
                    "trace_id": trace_id,
                    "source": "websocket",
                    "user_id": ha_context.get("user_id"),
                },
            )

        except Exception as e:
            log.error(f"HAAdapter: error handling WebSocket state change: {e}")

    async def _cleanup_websocket(self) -> None:
        if self._ws_client is not None:
            with contextlib.suppress(Exception):
                await self._ws_client.close()
            self._ws_client = None

        if self._session is not None:
            with contextlib.suppress(Exception):
                await self._session.close()
            self._session = None

    def _subscribed_entities(self) -> list[str]:
        """Сущности из манифеста, на которые подписан адаптер.

        Берутся из манифеста через тот же механизм, что и в `EventRouter`, чтобы
        источник истины был один: подписка и маршрутизация не должны
        расходиться, иначе платформа будет получать события, которые не
        маршрутизирует, либо не получать те, которые маршрутизирует.

        Returns:
            Список `entity_id`; пустой, если манифест недоступен или пуст.
        """
        manifest = getattr(self, "_manifest", None)
        if manifest is None:
            return []

        from core.events.event_router import collect_subscribed_entities

        return collect_subscribed_entities(manifest)

    async def _force_disconnect(self, reason: str) -> None:
        """Объявить соединение мёртвым и освободить сокет.

        Закрытие здесь — не гигиена, а условие переподключения. Цикл в
        `_connect_websocket` ждёт завершения задачи чтения, и при разрыве без
        чистого закрытия (отвал Wi-Fi, `docker network disconnect`) эта задача
        не завершается никогда: `recv()` ждёт данных, которых не будет. Пока сокет
        открыт и помечен лишь флагом, цикл остаётся в `asyncio.wait(...)`, а
        heartbeat со следующей итерации выходит по `if not connected: continue` —
        то есть выключает себя сам. Обрыв был обнаружен и записан, а
        переподключения не происходило никогда (#78).

        Args:
            reason: Причина обрыва — попадает в журнал.
        """
        client = self._ws_client
        if client is None:
            return

        client.connected = False
        try:
            await client.close()
        except Exception as error:  # noqa: BLE001 — обрыв не должен ронять heartbeat
            # Закрытие может не завершиться на мёртвом сокете; обрыв всё равно
            # объявлен, и следующая попытка подключения его разберёт.
            logger.warning(f"HAAdapter: close after '{reason}' failed: {error}")

    async def _heartbeat_loop(self) -> None:
        """Проверять живость соединения и переподключать мёртвое.

        Задача — находить мёртвые соединения, а не шумные дома. Поэтому порядок
        шагов важен: **сначала признак жизни, потом вывод**. Если сначала судить
        по тишине, а потом спрашивать сокет, то вывод всегда опережает проверку:
        при очередном пробуждении тишина уже «пять минут», и исправное соединение
        рвётся, не успев ни разу ответить на ping.

        Признак жизни обновляется тремя способами: при подключении, на каждом
        входящем событии и на каждом успешном ответе на ping. Ответ на ping —
        прямое доказательство, что соединение в порядке, даже если событий не
        было вовсе.

        Неотвечающий сокет приводит к обрыву, и обрыв обязан быть настоящим:
        соединение закрывается, а не только помечается флагом — иначе цикл
        переподключения не заметит обрыва никогда (#78).
        """
        try:
            while not self._shutdown_event.is_set():
                await asyncio.sleep(30)  # Check every 30 seconds

                if not (self._ws_client and getattr(self._ws_client, "connected", False)):
                    continue

                # Шаг 1: спросить у сокета, жив ли он.
                try:
                    ws = getattr(self._ws_client, "ws", None)
                    if ws and hasattr(ws, "ping"):
                        await asyncio.wait_for(ws.ping(), timeout=5)
                        # Ответ пришёл — соединение живо, даже если событий не было.
                        self._last_liveness_time = time.time()
                        logger.debug("HAAdapter: WebSocket ping sent")
                except Exception as e:
                    # Запись до закрытия: если `close()` не вернётся на мёртвом
                    # сокете, по журналу должно быть видно, что обрыв найден.
                    logger.warning(f"HAAdapter: ping failed ({e}), forcing reconnect")
                    await self._force_disconnect(f"ping failed: {e}")
                    return

                # Шаг 2: судить по признаку жизни, а не по тишине.
                last_liveness = getattr(self, "_last_liveness_time", None)
                if last_liveness is None:
                    last_liveness = getattr(self, "_last_event_time", None)
                if last_liveness is None:
                    continue
                time_since = time.time() - last_liveness
                if time_since > 300:  # 5 minutes without any sign of life
                    logger.warning(
                        f"HAAdapter: No sign of life for {time_since:.0f}s "
                        f"(no events, no ping reply), connection is stale - forcing reconnect"
                    )
                    logger.warning("HAAdapter: closing stale connection")
                    await self._force_disconnect("stale connection")
                    logger.warning("HAAdapter: stale connection closed, heartbeat will resume")
        except asyncio.CancelledError:
            pass

    async def stop(self) -> None:
        # ВИДИМО: единственное место в коде, где отменяется задача цикла
        # переподключения (#70). Пока запись шла на info, было невозможно отличить
        # «отменил stop()» от «отмена пришла изнутри» — обе выглядели одинаково.
        logger.warning(
            f"HAAdapter: stop() called, cancelling reconnect task (task={self._reconnect_task!r})"
        )
        logger.info("HAAdapter: initiating graceful shutdown")
        self._shutdown_event.set()

        if self._reconnect_task is not None and not self._reconnect_task.done():
            self._reconnect_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._reconnect_task
            self._reconnect_task = None

        if self._mode == "websocket":
            await self._cleanup_websocket()

        logger.info("HAAdapter: shutdown complete")

    def register_trace_callback(
        self,
        callback: Callable[[str, str, str, dict[str, Any]], Coroutine[Any, Any, None]],
    ) -> None:
        self._trace_callbacks.append(callback)

    @property
    def mode(self) -> str:
        return self._mode

    @property
    def is_connected(self) -> bool:
        """Есть ли живое соединение с Home Assistant.

        Returns:
            True, если соединение действительно есть.
        """
        if self._mode == "pyscript":
            return True
        return self._ws_client is not None and self._ws_client.connected

    @property
    def last_disconnect_reason(self) -> str | None:
        """Причина последнего разрыва соединения.

        Отдаётся наружу для `/ready`: оператор должен видеть не только факт
        отсутствия связи, но и то, кто её разорвал.

        Returns:
            Причина разрыва или ``None``, если разрывов не было.
        """
        if self._ws_client is None:
            return None
        return getattr(self._ws_client, "_disconnect_reason", None)


HomeAssistantAdapter = HAAdapter
