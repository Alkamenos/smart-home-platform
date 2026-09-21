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
import time
import uuid
from collections.abc import Callable, Coroutine
from typing import TYPE_CHECKING, Any

import aiohttp
from loguru import logger


class SimpleHAWebSocketClient:
    """Minimal WebSocket client implementing HA WebSocket API protocol.

    HA uses message-based auth:
      1. Client connects
      2. Server sends {"type": "auth_required", ...}
      3. Client sends {"type": "auth", "access_token": "..."}
      4. Server sends {"type": "auth_ok"} or {"type": "auth_invalid"}
    """

    def __init__(self, url: str, token: str, session=None):
        self.url = url
        self.token = token
        self.session = session
        self.ws = None
        self.connected = False
        self._msg_id = 0
        self._handlers: dict[int, Callable] = {}
        self._event_handler: Callable | None = None
        self._listen_task = None

    async def connect(self):
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

    async def _listen_loop(self):
        try:
            async for raw in self.ws:
                try:
                    msg = json.loads(raw)
                    msg_type = msg.get("type")

                    if msg_type == "event" and self._event_handler:
                        event_data = msg.get("event", {})
                        payload = event_data.get("data", event_data)
                        await self._event_handler(payload)

                    elif msg_type == "result":
                        msg_id = msg.get("id")
                        if msg_id in self._handlers:
                            handler = self._handlers.pop(msg_id)
                            handler(msg)

                except Exception:
                    pass
        except Exception:
            self.connected = False

    async def close(self):
        if self._listen_task:
            self._listen_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._listen_task
        if self.ws:
            await self.ws.close()
        self.connected = False

    async def subscribe(self, handler, filter_dict):
        if self.ws and self.connected:
            self._msg_id += 1
            self._event_handler = handler
            sub_msg = {
                "id": self._msg_id,
                "type": "subscribe_events",
                "event_type": filter_dict.get("type", ""),
            }
            await self.ws.send(json.dumps(sub_msg))

    async def get_states(self):
        if not self.ws or not self.connected:
            return []

        self._msg_id += 1
        msg_id = self._msg_id
        loop = asyncio.get_event_loop()
        result_future: asyncio.Future = loop.create_future()

        def on_result(msg):
            if not result_future.done():
                result_future.set_result(msg)

        self._handlers[msg_id] = on_result

        await self.ws.send(
            json.dumps(
                {
                    "id": msg_id,
                    "type": "get_states",
                }
            )
        )

        try:
            response = await asyncio.wait_for(result_future, timeout=15)
            return response.get("result", [])
        except TimeoutError:
            return []

    async def call_service(self, domain, service, service_data=None, return_response=True):
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
            result_future: asyncio.Future = loop.create_future()

            def on_result(msg):
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
HomeAssistantWS = SimpleHAWebSocketClient  # type: ignore


if TYPE_CHECKING:
    from src.core.event_router import EventRouter
    from src.core.middleware import ManualLockoutMiddleware


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
    ) -> None:
        if mode not in ("pyscript", "websocket"):
            raise ValueError(f"Invalid mode: {mode}. Must be 'pyscript' or 'websocket'")

        self._mode = mode
        self._engine = engine
        self._hass = hass
        self._ws_url = ws_url
        self._token = token

        self._manual_lockout_middleware = manual_lockout_middleware
        self._event_router = event_router
        self._ws_client: HomeAssistantWS | None = None
        self._session: aiohttp.ClientSession | None = None
        self._shutdown_event = asyncio.Event()
        self._reconnect_task: asyncio.Task | None = None
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

    def set_fsm_engine(self, engine) -> None:
        """Set the FSM engine reference (called by Container.build())."""
        self._fsm_engine = engine

    def _generate_trace_id(self) -> str:
        return str(uuid.uuid4())[:8]

    def _get_logger(self, trace_id: str) -> Any:
        return logger.bind(trace_id=trace_id)

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

        if self._engine is not None and hasattr(self._engine, "event_bus"):
            try:
                await self._engine.event_bus.publish(
                    event_type="state_change",
                    payload=payload,
                    trace_id=trace_id,
                )
            except Exception as e:
                log.error(f"HAAdapter: failed to publish event to EventBus: {e}")
        elif self._engine is not None:
            try:
                trigger_name = f"{entity_id}_changed"
                await self._engine.trigger(
                    entity_id=entity_id,
                    event=trigger_name,
                    external_ctx={
                        "new_state": new_state,
                        "old_state": old_state,
                        "trace_id": trace_id,
                    },
                )
            except Exception as e:
                log.error(f"HAAdapter: failed to trigger FSM: {e}")

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

    async def _connect_websocket(self) -> None:
        """Establish WebSocket connection with exponential backoff."""
        reconnect_delay = 1.0
        max_reconnect_delay = 60.0

        while not self._shutdown_event.is_set():
            try:
                log = self._get_logger(self._generate_trace_id())
                log.info(f"HAAdapter: connecting to WebSocket {self._ws_url}")

                # Отладочный лог
                log.info(f"HAAdapter: HomeAssistantWS class = {HomeAssistantWS}")
                log.info(f"HAAdapter: HAS_WS_LIBRARY = {HAS_WS_LIBRARY}")

                self._session = aiohttp.ClientSession()

                # Создаём клиент
                self._ws_client = HomeAssistantWS(
                    url=self._ws_url,
                    token=self._token,
                    session=self._session,
                )

                log.info(f"HAAdapter: ws_client created = {self._ws_client}")

                # Подключаемся
                await self._ws_client.connect()

                # КРИТИЧЕСКАЯ ПРОВЕРКА: реально ли подключились?
                if not getattr(self._ws_client, "connected", False):
                    raise ConnectionError("WebSocket connect() succeeded but connected=False")

                log.info("HAAdapter: WebSocket connected successfully")

                # Подписываемся на события
                await self._ws_client.subscribe(
                    self._handle_ws_state_change,
                    {"type": "state_changed"},
                )
                log.info("HAAdapter: subscribed to state_changed events")

                reconnect_delay = 1.0

                # 🆕 Инициализируем timestamp последнего события
                self._last_event_time = time.time()

                # 🆕 Запускаем heartbeat задачу для обнаружения мёртвых соединений
                heartbeat_task = asyncio.create_task(self._heartbeat_loop())

                try:
                    # Ждём сигнала остановки или завершения listen_task (если есть)
                    listen_task = getattr(self._ws_client, "_listen_task", None)
                    tasks = [asyncio.ensure_future(self._shutdown_event.wait())]
                    if listen_task and not listen_task.done():
                        tasks.append(listen_task)

                    done, pending = await asyncio.wait(
                        tasks,
                        return_when=asyncio.FIRST_COMPLETED,
                    )

                    # Если listen_task завершился — соединение разорвано извне
                    if listen_task and listen_task in done:
                        try:
                            listen_task.result()
                        except Exception as e:
                            log.warning(f"HAAdapter: listen_task ended unexpectedly: {e}")
                        # Выходим из try блока, чтобы сработал reconnect
                finally:
                    # Останавливаем heartbeat при любом выходе
                    heartbeat_task.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await heartbeat_task

            except asyncio.CancelledError:
                logger.info("HAAdapter: WebSocket connection cancelled")
                break

            except Exception as e:
                trace_id = self._generate_trace_id()
                log = self._get_logger(trace_id)
                log.error(f"HAAdapter: connection error: {type(e).__name__}: {e}")

                # Логируем состояние для отладки
                log.error(f"HAAdapter: _ws_client is None = {self._ws_client is None}")
                if self._ws_client is not None:
                    log.error(
                        f"HAAdapter: _ws_client.connected = {getattr(self._ws_client, 'connected', 'N/A')}"
                    )
                    log.error(f"HAAdapter: _ws_client.ws = {getattr(self._ws_client, 'ws', 'N/A')}")

                if not self._shutdown_event.is_set():
                    log.info(f"HAAdapter: reconnecting in {reconnect_delay:.1f}s")
                    await asyncio.sleep(reconnect_delay)
                    reconnect_delay = min(reconnect_delay * 2, max_reconnect_delay)

            finally:
                await self._cleanup_websocket()

    async def _handle_ws_state_change(
        self,
        message: dict[str, Any],
        trace_id: str | None = None,
    ) -> None:
        trace_id = trace_id or self._generate_trace_id()
        log = self._get_logger(trace_id)

        try:
            entity_id = message.get("entity_id", "")
            old_state_obj = message.get("old_state", {})
            new_state_obj = message.get("new_state", {})

            old_state = old_state_obj.get("state", "unknown") if old_state_obj else "unknown"
            new_state = new_state_obj.get("state", "unknown") if new_state_obj else "unknown"

            log.info(
                f"HAAdapter: WebSocket state_change for {entity_id}: '{old_state}' -> '{new_state}'"
            )

            await self.on_state_change(
                entity_id=entity_id,
                new_state=new_state,
                old_state=old_state,
                context={"trace_id": trace_id, "source": "websocket"},
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

    async def _heartbeat_loop(self) -> None:
        """Send periodic pings to detect dead WebSocket connections.

        Without this, silent TCP disconnections (e.g., NAT timeout on router)
        will leave the connection stuck forever - no events, no errors.
        The heartbeat detects stale connections and forces a reconnect.
        """
        try:
            while not self._shutdown_event.is_set():
                await asyncio.sleep(30)  # Check every 30 seconds

                if not (self._ws_client and getattr(self._ws_client, "connected", False)):
                    continue

                # Check time since last event - if too long, connection is stale
                last_event = getattr(self, "_last_event_time", None)
                if last_event is not None:
                    time_since = time.time() - last_event
                    if time_since > 300:  # 5 minutes without events = stale
                        logger.warning(
                            f"HAAdapter: No events for {time_since:.0f}s, connection is stale - forcing reconnect"
                        )
                        if self._ws_client:
                            self._ws_client.connected = False
                            with contextlib.suppress(Exception):
                                await self._ws_client.close()
                        continue

                # Send ping to keep connection alive
                try:
                    ws = getattr(self._ws_client, "ws", None)
                    if ws and hasattr(ws, "ping"):
                        await asyncio.wait_for(ws.ping(), timeout=5)
                        logger.debug("HAAdapter: WebSocket ping sent")
                except (TimeoutError, Exception) as e:
                    logger.warning(f"HAAdapter: ping failed ({e}), forcing reconnect")
                    if self._ws_client:
                        self._ws_client.connected = False
        except asyncio.CancelledError:
            pass

    async def stop(self) -> None:
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
        if self._mode == "pyscript":
            return True
        return self._ws_client is not None and self._ws_client.connected


HomeAssistantAdapter = HAAdapter
