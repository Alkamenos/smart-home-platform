"""
Dependency Injection Container for Smart Home Platform.

This module provides a lightweight DI container with lazy initialization
for better modularity and testability.
"""

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

from adapters.ha_adapter import HAAdapter
from adapters.mock_adapter import MockAdapter
from core.action_handlers import register_all_actions
from core.commands.dispatcher import CommandDispatcher
from core.commands.middleware import ManualLockoutMiddleware
from core.control_tracker import ControlTracker
from core.events.event_bus import EventBus
from core.events.event_router import EventRouter
from core.fsm.engine import FSMEngine
from core.fsm.factory import FSMFactory
from core.models.manifest import Manifest, load_manifest
from core.registry import Registry


@dataclass
class PlatformContext:
    """
    Container for all platform components.

    Attributes:
        manifest: Loaded manifest with automation rules.
        event_bus: EventBus for publishing/subscribing to events.
        fsm: FSMEngine for state machine management.
        control_tracker: ControlTracker for tracking manual interventions.
        adapter: HAAdapter or MockAdapter for calling services.
        dispatcher: CommandDispatcher with middleware chain.
        event_router: EventRouter for routing sensor events to FSMs.
    """

    manifest: Manifest
    event_bus: EventBus
    fsm: FSMEngine
    control_tracker: ControlTracker
    adapter: Any  # HAAdapter or MockAdapter
    dispatcher: CommandDispatcher
    event_router: EventRouter


class Container:
    """
    Lightweight Dependency Injection Container with lazy initialization.

    This container creates and manages platform components, ensuring
    proper dependency ordering and enabling easy mocking for tests.

    Example usage:
        ```python
        container = Container(manifest_path="instances/leonids_house/manifest.yaml")
        context = container.build()

        # Or access components individually:
        engine = container.engine
        adapter = container.adapter
        ```
    """

    def __init__(
        self,
        manifest_path: str | None = None,
        manifest: Manifest | None = None,
        config_overrides: dict[str, Any] | None = None,
    ):
        """
        Initialize the DI container.

        Args:
            manifest_path: Path to the manifest YAML file.
            manifest: Pre-loaded manifest (alternative to manifest_path).
            config_overrides: Optional configuration overrides.
        """
        self._manifest_path = manifest_path
        self._manifest = manifest
        self._config_overrides = config_overrides or {}

        # Lazy-initialized components
        self._event_bus: EventBus | None = None
        self._fsm: FSMEngine | None = None
        self._control_tracker: ControlTracker | None = None
        self._event_router: EventRouter | None = None
        self._adapter: HAAdapter | MockAdapter | None = None
        self._dispatcher: CommandDispatcher | None = None
        self._middleware: ManualLockoutMiddleware | None = None
        self._registry: Registry | None = None
        self._factory: FSMFactory | None = None

    @property
    def manifest(self) -> Manifest:
        """Load and return the manifest (cached)."""
        if self._manifest is None:
            if self._manifest_path is None:
                msg = "Manifest path not provided"
                raise RuntimeError(msg)
            self._manifest = load_manifest(self._manifest_path)
        return self._manifest

    @property
    def event_bus(self) -> EventBus:
        """Get or create EventBus instance."""
        if self._event_bus is None:
            self._event_bus = EventBus()
        return self._event_bus

    @property
    def fsm(self) -> FSMEngine:
        """Get or create FSMEngine instance."""
        if self._fsm is None:
            self._fsm = FSMEngine()
        return self._fsm

    @property
    def control_tracker(self) -> ControlTracker:
        """Get or create ControlTracker instance."""
        if self._control_tracker is None:
            self._control_tracker = ControlTracker(history_size=100)
        return self._control_tracker

    @property
    def event_router(self) -> EventRouter:
        """Get or create EventRouter instance (depends on manifest and fsm)."""
        if self._event_router is None:
            self._event_router = EventRouter(manifest=self.manifest, engine=self.fsm)
        return self._event_router

    @property
    def adapter(self) -> HAAdapter | MockAdapter:
        """Get or create adapter instance (depends on fsm and event_router)."""
        if self._adapter is None:
            ws_url = os.environ.get("HA_WEBSOCKET_URL", "ws://localhost:8123/api/websocket")
            ha_token = os.environ.get("HA_TOKEN")

            if ha_token:
                self._adapter = HAAdapter(
                    mode="websocket",
                    engine=self.fsm,
                    event_router=self.event_router,
                    ws_url=ws_url,
                    token=ha_token,
                )
            else:
                self._adapter = MockAdapter(engine=self.fsm)
                self._adapter.set_event_router(self.event_router)
        return self._adapter

    @property
    def dispatcher(self) -> CommandDispatcher:
        """Get or create CommandDispatcher instance (depends on adapter)."""
        if self._dispatcher is None:
            self._dispatcher = CommandDispatcher(ha_adapter=self.adapter, middlewares=[])
            # Add middleware if available
            self._dispatcher.add_middleware(self.middleware)
        return self._dispatcher

    @property
    def middleware(self) -> ManualLockoutMiddleware:
        """Get or create ManualLockoutMiddleware instance."""
        if self._middleware is None:
            self._middleware = ManualLockoutMiddleware(
                automation_rules=self.manifest.automation_rules,
                control_tracker=self.control_tracker,
            )
        return self._middleware

    @property
    def registry(self) -> Registry:
        """Get or create Registry instance."""
        if self._registry is None:
            self._registry = Registry()
            register_all_actions(self._registry)
        return self._registry

    @property
    def factory(self) -> FSMFactory:
        """Get or create FSMFactory instance (depends on fsm, registry, event_bus)."""
        if self._factory is None:
            self._factory = FSMFactory(
                engine=self.fsm, registry=self.registry, event_bus=self.event_bus
            )
        return self._factory

    def build(self) -> PlatformContext:
        """
        Build and return the complete platform context.

        This triggers lazy initialization of all components in the correct order.

        Returns:
            PlatformContext with all initialized components.
        """
        # Access properties in dependency order to ensure proper initialization
        _ = self.event_bus  # No dependencies
        _ = self.fsm  # No dependencies
        _ = self.control_tracker  # No dependencies
        _ = self.event_router  # Depends on manifest, fsm
        _ = self.adapter  # Depends on fsm, event_router
        _ = self.dispatcher  # Depends on adapter, middleware
        _ = self.factory  # Depends on fsm, registry, event_bus

        # Create and register FSMs from manifest
        self.factory.create_and_register(self.manifest)

        # Link adapter to FSM engine
        self.adapter.set_fsm_engine(self.fsm)

        return PlatformContext(
            manifest=self.manifest,
            event_bus=self.event_bus,
            fsm=self.fsm,
            control_tracker=self.control_tracker,
            adapter=self.adapter,
            dispatcher=self.dispatcher,
            event_router=self.event_router,
        )

    def reset(self) -> None:
        """Reset all cached instances for testing purposes."""
        self._event_bus = None
        self._fsm = None
        self._control_tracker = None
        self._event_router = None
        self._adapter = None
        self._dispatcher = None
        self._middleware = None
        self._registry = None
        self._factory = None
        # Don't reset manifest as it's expensive to reload
