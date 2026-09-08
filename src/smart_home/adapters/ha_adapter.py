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

from __future__ import annotations

import asyncio
import uuid
from typing import Any, Callable, Coroutine, Optional

import aiohttp
from loguru import logger

# Try to import homeassistant_websocket for WebSocket mode
try:
    from homeassistant_websocket import HomeAssistantWS  # type: ignore
    HAS_WS_LIBRARY = True
except ImportError:
    HAS_WS_LIBRARY = False
    HomeAssistantWS = None  # type: ignore


class HAAdapter:
    """
    Adapter for bidirectional communication with Home Assistant.
    
    Supports two modes of operation:
    1. Pyscript mode: Provides wrapper functions called from Pyscript files in HA.
    2. WebSocket mode: Uses aiohttp and homeassistant-websocket library for 
       standalone execution outside HA.
    
    Attributes:
        _mode: Operation mode ("pyscript" or "websocket").
        _engine: Reference to FSMEngine for event processing.
        _hass: Home Assistant instance (Pyscript mode only).
        _ws_client: WebSocket client instance (WebSocket mode only).
        _trace_callbacks: Registered callbacks for trace_id propagation.
        _shutdown_event: Event for graceful shutdown signaling.
        _reconnect_task: Task handling WebSocket reconnection logic.
    
    Usage (Pyscript mode):
        adapter = HAAdapter(mode="pyscript", engine=engine, hass=hass)
        await adapter.on_state_change("binary_sensor.kitchen_motion", "on", "off", {})
        await adapter.call_service("light", "turn_on", "light.kitchen", {}, "a1b2c3d4")
    
    Usage (WebSocket mode):
        adapter = HAAdapter(
            mode="websocket",
            engine=engine,
            ws_url="ws://localhost:8123/api/websocket",
            token="your_long_lived_token"
        )
        await adapter.start()
        # ... run until shutdown ...
        await adapter.stop()
    """
    
    def __init__(
        self,
        mode: str = "pyscript",
        engine: Any | None = None,
        hass: Any | None = None,
        ws_url: str | None = None,
        token: str | None = None,
    ) -> None:
        """
        Initialize HAAdapter.
        
        Args:
            mode: Operation mode - "pyscript" or "websocket".
            engine: FSMEngine instance for event processing.
            hass: Home Assistant instance (required for pyscript mode).
            ws_url: WebSocket URL for HA (required for websocket mode).
            token: Long-lived access token for HA (required for websocket mode).
        
        Raises:
            ValueError: If required parameters are missing for the selected mode.
        """
        if mode not in ("pyscript", "websocket"):
            raise ValueError(f"Invalid mode: {mode}. Must be 'pyscript' or 'websocket'")
        
        self._mode = mode
        self._engine = engine
        self._hass = hass
        self._ws_url = ws_url
        self._token = token
        
        self._ws_client: HomeAssistantWS | None = None
        self._session: aiohttp.ClientSession | None = None
        self._shutdown_event = asyncio.Event()
        self._reconnect_task: asyncio.Task | None = None
        self._trace_callbacks: list[Callable[[str, str, str, dict[str, Any]], Coroutine[Any, Any, None]]] = []
        
        # Validate required parameters based on mode
        if mode == "pyscript" and hass is None:
            raise ValueError("hass instance is required for pyscript mode")
        if mode == "websocket":
            if ws_url is None:
                raise ValueError("ws_url is required for websocket mode")
            if token is None:
                raise ValueError("token is required for websocket mode")
            if not HAS_WS_LIBRARY:
                logger.warning(
                    "homeassistant-websocket library not installed. "
                    "WebSocket mode will not work. Install with: pip install homeassistant-websocket"
                )
        
        logger.info(f"HAAdapter initialized in '{mode}' mode")
    
    def _generate_trace_id(self) -> str:
        """
        Generate a short trace ID for logging correlation.
        
        Returns:
            First 8 characters of a UUID4 string.
        """
        return str(uuid.uuid4())[:8]
    
    def _get_logger(self, trace_id: str) -> Any:
        """
        Get a logger instance bound with trace_id.
        
        Args:
            trace_id: Trace ID to bind to the logger.
        
        Returns:
            Logger instance with trace_id context.
        """
        return logger.bind(trace_id=trace_id)
    
    async def on_state_change(
        self,
        entity_id: str,
        new_state: str,
        old_state: str,
        context: dict[str, Any] | None = None,
    ) -> None:
        """
        Handle state change event from Home Assistant.
        
        This method is called by Pyscript when a monitored entity changes state.
        It generates a trace_id if not provided and publishes the event to EventBus.
        
        Args:
            entity_id: ID of the entity that changed state.
            new_state: New state value of the entity.
            old_state: Previous state value of the entity.
            context: Optional context dictionary that may contain trace_id.
        
        Example:
            @state_trigger("binary_sensor.kitchen_motion")
            def kitchen_motion_changed(value=None, old_value=None):
                adapter.on_state_change(
                    "binary_sensor.kitchen_motion",
                    str(value),
                    str(old_value),
                    {}
                )
        """
        context = context or {}
        
        # Extract or generate trace_id
        trace_id = context.get("trace_id") or self._generate_trace_id()
        log = self._get_logger(trace_id)
        
        log.info(
            f"HAAdapter: state_change received for {entity_id}: "
            f"'{old_state}' -> '{new_state}'"
        )
        
        # Prepare payload
        payload = {
            "entity_id": entity_id,
            "new_state": new_state,
            "old_state": old_state,
            "context": {**context, "trace_id": trace_id},
        }
        
        # Publish to EventBus if engine is available
        if self._engine is not None and hasattr(self._engine, "event_bus"):
            try:
                await self._engine.event_bus.publish(
                    event_type="state_change",
                    payload=payload,
                    trace_id=trace_id,
                )
                log.debug(f"HAAdapter: event published to EventBus for {entity_id}")
            except Exception as e:
                log.error(f"HAAdapter: failed to publish event to EventBus: {e}")
        elif self._engine is not None:
            # Direct trigger if no event_bus attribute
            try:
                trigger_name = f"{entity_id}_changed"
                await self._engine.trigger(
                    entity_id=entity_id,
                    event=trigger_name,
                    external_ctx={"new_state": new_state, "old_state": old_state, "trace_id": trace_id},
                )
                log.debug(f"HAAdapter: direct trigger called for {entity_id}")
            except Exception as e:
                log.error(f"HAAdapter: failed to trigger FSM: {e}")
        else:
            log.warning("HAAdapter: No engine attached, event not processed")
    
    async def call_service(
        self,
        domain: str,
        service: str,
        entity_id: str,
        data: dict[str, Any] | None = None,
        trace_id: str | None = None,
    ) -> bool:
        """
        Call a Home Assistant service.
        
        This method is used by FSM actions to control devices in HA.
        It handles errors gracefully to prevent FSMEngine crashes.
        
        Args:
            domain: Service domain (e.g., "light", "switch", "climate").
            service: Service name (e.g., "turn_on", "turn_off", "set_temperature").
            entity_id: Target entity ID.
            data: Additional service data.
            trace_id: Optional trace ID for logging correlation.
        
        Returns:
            True if service call succeeded, False otherwise.
        
        Example:
            await adapter.call_service(
                domain="light",
                service="turn_on",
                entity_id="light.kitchen",
                data={"brightness": 255},
                trace_id="a1b2c3d4"
            )
        """
        data = data or {}
        trace_id = trace_id or self._generate_trace_id()
        log = self._get_logger(trace_id)
        
        log.info(
            f"HAAdapter: calling service {domain}.{service} for {entity_id}"
        )
        
        try:
            if self._mode == "pyscript":
                return await self._call_service_pyscript(
                    domain, service, entity_id, data, log
                )
            else:  # websocket mode
                return await self._call_service_websocket(
                    domain, service, entity_id, data, log
                )
        except Exception as e:
            log.error(
                f"HAAdapter: service call failed {domain}.{service} "
                f"for {entity_id}: {e}"
            )
            return False
    
    async def _call_service_pyscript(
        self,
        domain: str,
        service: str,
        entity_id: str,
        data: dict[str, Any],
        log: Any,
    ) -> bool:
        """
        Call service using Pyscript's hass.services.async_call.
        
        Args:
            domain: Service domain.
            service: Service name.
            entity_id: Target entity ID.
            data: Service data.
            log: Logger instance with trace_id bound.
        
        Returns:
            True if successful, False otherwise.
        """
        if self._hass is None:
            log.error("HAAdapter: hass instance not available in pyscript mode")
            return False
        
        # Add entity_id to service data
        service_data = {**data, "entity_id": entity_id}
        
        try:
            await self._hass.services.async_call(
                domain=domain,
                service=service,
                service_data=service_data,
            )
            log.debug(
                f"HAAdapter: service {domain}.{service} called successfully"
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
        """
        Call service using WebSocket connection.
        
        Args:
            domain: Service domain.
            service: Service name.
            entity_id: Target entity ID.
            data: Service data.
            log: Logger instance with trace_id bound.
        
        Returns:
            True if successful, False otherwise.
        """
        if self._ws_client is None:
            log.error("HAAdapter: WebSocket client not connected")
            return False
        
        # Add entity_id to service data
        service_data = {**data, "entity_id": entity_id}
        
        try:
            result = await self._ws_client.call_service(
                domain=domain,
                service=service,
                service_data=service_data,
                return_response=False,
            )
            log.debug(
                f"HAAdapter: WebSocket service {domain}.{service} called successfully"
            )
            return result is not None
        except Exception as e:
            log.error(f"HAAdapter: WebSocket service call error: {e}")
            return False
    
    async def start(self) -> None:
        """
        Start the adapter (WebSocket mode only).
        
        In WebSocket mode, this establishes the connection and subscribes
        to state_changed events. In Pyscript mode, this is a no-op.
        
        Raises:
            RuntimeError: If called in pyscript mode.
        """
        if self._mode == "pyscript":
            logger.info("HAAdapter: start() is a no-op in pyscript mode")
            return
        
        if self._mode == "websocket":
            await self._connect_websocket()
    
    async def _connect_websocket(self) -> None:
        """
        Establish WebSocket connection with exponential backoff.
        
        Implements exponential backoff strategy for reconnection attempts:
        - Initial delay: 1 second
        - Maximum delay: 60 seconds
        - Multiplier: 2x per attempt
        """
        if not HAS_WS_LIBRARY or HomeAssistantWS is None:
            logger.error(
                "HAAdapter: homeassistant-websocket library not available"
            )
            return
        
        reconnect_delay = 1.0
        max_reconnect_delay = 60.0
        
        while not self._shutdown_event.is_set():
            try:
                log = self._get_logger(self._generate_trace_id())
                log.info(f"HAAdapter: connecting to WebSocket {self._ws_url}")
                
                self._session = aiohttp.ClientSession()
                self._ws_client = HomeAssistantWS(
                    url=self._ws_url,
                    token=self._token,
                    session=self._session,
                )
                
                await self._ws_client.connect()
                log.info("HAAdapter: WebSocket connected")
                
                # Subscribe to state_changed events
                await self._ws_client.subscribe(
                    self._handle_ws_state_change,
                    {"type": "state_changed"},
                )
                log.info("HAAdapter: subscribed to state_changed events")
                
                # Reset reconnect delay on successful connection
                reconnect_delay = 1.0
                
                # Wait for shutdown signal or disconnection
                await self._shutdown_event.wait()
                
            except asyncio.CancelledError:
                logger.info("HAAdapter: WebSocket connection cancelled")
                break
            except Exception as e:
                trace_id = self._generate_trace_id()
                log = self._get_logger(trace_id)
                log.error(f"HAAdapter: WebSocket error: {e}")
                
                if not self._shutdown_event.is_set():
                    log.info(
                        f"HAAdapter: reconnecting in {reconnect_delay:.1f}s "
                        f"(exponential backoff)"
                    )
                    await asyncio.sleep(reconnect_delay)
                    reconnect_delay = min(reconnect_delay * 2, max_reconnect_delay)
            
            finally:
                await self._cleanup_websocket()
    
    async def _handle_ws_state_change(
        self,
        message: dict[str, Any],
        trace_id: str | None = None,
    ) -> None:
        """
        Handle state change message from WebSocket.
        
        Args:
            message: State change message from HA.
            trace_id: Optional trace ID from the message context.
        """
        trace_id = trace_id or self._generate_trace_id()
        log = self._get_logger(trace_id)
        
        try:
            # Parse WebSocket state change message
            # Format: {"entity_id": "...", "old_state": {...}, "new_state": {...}}
            entity_id = message.get("entity_id", "")
            old_state_obj = message.get("old_state", {})
            new_state_obj = message.get("new_state", {})
            
            old_state = old_state_obj.get("state", "unknown") if old_state_obj else "unknown"
            new_state = new_state_obj.get("state", "unknown") if new_state_obj else "unknown"
            
            log.info(
                f"HAAdapter: WebSocket state_change for {entity_id}: "
                f"'{old_state}' -> '{new_state}'"
            )
            
            # Forward to on_state_change for unified processing
            await self.on_state_change(
                entity_id=entity_id,
                new_state=new_state,
                old_state=old_state,
                context={"trace_id": trace_id, "source": "websocket"},
            )
            
        except Exception as e:
            log.error(f"HAAdapter: error handling WebSocket state change: {e}")
    
    async def _cleanup_websocket(self) -> None:
        """Clean up WebSocket resources."""
        if self._ws_client is not None:
            try:
                await self._ws_client.close()
            except Exception:
                pass
            self._ws_client = None
        
        if self._session is not None:
            try:
                await self._session.close()
            except Exception:
                pass
            self._session = None
        
        logger.debug("HAAdapter: WebSocket resources cleaned up")
    
    async def stop(self) -> None:
        """
        Stop the adapter and clean up resources.
        
        This method:
        - Signals shutdown to all background tasks
        - Cancels the reconnection task (if running)
        - Closes WebSocket connection (if applicable)
        - Cleans up aiohttp session
        
        Should be called during graceful shutdown of the application.
        """
        logger.info("HAAdapter: initiating graceful shutdown")
        
        # Signal shutdown
        self._shutdown_event.set()
        
        # Cancel reconnect task
        if self._reconnect_task is not None and not self._reconnect_task.done():
            self._reconnect_task.cancel()
            try:
                await self._reconnect_task
            except asyncio.CancelledError:
                pass
            self._reconnect_task = None
        
        # Clean up WebSocket resources
        if self._mode == "websocket":
            await self._cleanup_websocket()
        
        logger.info("HAAdapter: shutdown complete")
    
    def register_trace_callback(
        self,
        callback: Callable[[str, str, str, dict[str, Any]], Coroutine[Any, Any, None]],
    ) -> None:
        """
        Register a callback for trace_id propagation.
        
        Callbacks are invoked on every state change event with the trace_id.
        
        Args:
            callback: Async callback function receiving 
                     (entity_id, new_state, old_state, context).
        """
        self._trace_callbacks.append(callback)
        logger.debug(f"HAAdapter: registered trace callback {callback.__name__}")
    
    @property
    def mode(self) -> str:
        """Get the current operation mode."""
        return self._mode
    
    @property
    def is_connected(self) -> bool:
        """
        Check if the adapter is connected.
        
        Returns:
            True if connected (always True for pyscript mode),
            False if WebSocket is disconnected.
        """
        if self._mode == "pyscript":
            return True
        return self._ws_client is not None
