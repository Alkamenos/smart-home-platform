"""Scene Manager for Smart Home Platform.

Manages complex multi-device scenarios with support for:
- Parallel and sequential action execution
- Time-based, button, and state triggers
- Integration with EventBus for event-driven activation
"""

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import TYPE_CHECKING, Any

from loguru import logger

from core.models.scene import SceneAction, SceneConfig, SceneManagerConfig


if TYPE_CHECKING:
    from ..event_bus import EventBus


class SceneManager:
    """Manages scenes and their execution.

    A scene is a collection of actions that can be triggered by various events.
    Scenes support both parallel and sequential execution modes.

    Attributes:
        config: Scene manager configuration.
        event_bus: Event bus for subscribing to triggers.
        _scenes: Dictionary mapping scene IDs to configurations.
    """

    def __init__(
        self, config: SceneManagerConfig | None = None, event_bus: EventBus | None = None
    ) -> None:
        """Initialize Scene Manager.

        Args:
            config: Optional scene manager configuration.
            event_bus: Optional event bus for trigger subscriptions.
        """
        self.config = config or SceneManagerConfig()
        self.event_bus = event_bus
        self._scenes: dict[str, SceneConfig] = {}

        # Load scenes from config
        for scene_config in self.config.scenes:
            self.register_scene(scene_config)

        # Subscribe to triggers if event bus is available
        if self.event_bus:
            self._subscribe_to_triggers()

        logger.info(f"Scene Manager initialized with {len(self._scenes)} scenes")

    def register_scene(self, scene_config: SceneConfig) -> None:
        """Register a scene.

        Args:
            scene_config: Scene configuration to register.
        """
        if not scene_config.enabled:
            logger.debug(f"Skipping disabled scene: {scene_config.id}")
            return

        self._scenes[scene_config.id] = scene_config
        logger.info(f"Registered scene: {scene_config.id} ({scene_config.name})")

        # Subscribe to triggers for this scene
        if self.event_bus:
            self._subscribe_scene_triggers(scene_config)

    def unregister_scene(self, scene_id: str) -> None:
        """Unregister a scene.

        Args:
            scene_id: ID of the scene to unregister.
        """
        if scene_id in self._scenes:
            del self._scenes[scene_id]
            logger.info(f"Unregistered scene: {scene_id}")

    def get_scene(self, scene_id: str) -> SceneConfig | None:
        """Get a scene by ID.

        Args:
            scene_id: ID of the scene to retrieve.

        Returns:
            Scene configuration if found, None otherwise.
        """
        return self._scenes.get(scene_id)

    def list_scenes(self) -> list[str]:
        """List all registered scene IDs.

        Returns:
            List of scene IDs.
        """
        return list(self._scenes.keys())

    async def activate_scene(self, scene_id: str, context: dict[str, Any] | None = None) -> bool:
        """Activate a scene by executing its actions.

        Args:
            scene_id: ID of the scene to activate.
            context: Optional context dictionary passed to action handlers.

        Returns:
            True if scene was activated successfully, False otherwise.
        """
        scene = self.get_scene(scene_id)
        if not scene:
            logger.error(f"Scene not found: {scene_id}")
            return False

        if not scene.enabled:
            logger.warning(f"Scene is disabled: {scene_id}")
            return False

        logger.info(f"Activating scene: {scene_id} ({scene.name})")

        try:
            if scene.execution_mode == "sequential" or scene.has_sequential_actions:
                await self._execute_sequential(scene, context)
            else:
                await self._execute_parallel(scene, context)

            logger.info(f"Scene activated successfully: {scene_id}")
            return True

        except Exception as e:
            logger.error(f"Failed to activate scene {scene_id}: {e}")
            return False

    async def _execute_parallel(
        self, scene: SceneConfig, context: dict[str, Any] | None = None
    ) -> None:
        """Execute all actions in parallel.

        Args:
            scene: Scene configuration.
            context: Optional context dictionary.
        """
        tasks = [self._execute_action(action, context) for action in scene.actions]
        await asyncio.gather(*tasks)

    async def _execute_sequential(
        self, scene: SceneConfig, context: dict[str, Any] | None = None
    ) -> None:
        """Execute actions sequentially with delays.

        Args:
            scene: Scene configuration.
            context: Optional context dictionary.
        """
        for action in scene.actions:
            await self._execute_action(action, context)

            # Apply delay if specified
            if action.delay_sec > 0:
                logger.debug(f"Waiting {action.delay_sec}s before next action in scene")
                await asyncio.sleep(action.delay_sec)

    async def _execute_action(
        self, action: SceneAction, context: dict[str, Any] | None = None
    ) -> None:
        """Execute a single scene action.

        Args:
            action: Action to execute.
            context: Optional context dictionary.
        """
        logger.debug(f"Executing action: {action.service} on {action.device}")

        # TODO: Integrate with actual device control layer
        # For now, just log the action
        # In production, this would call Home Assistant API or similar

        if context is None:
            context = {}

        # Placeholder for actual device control
        # Example: await ha_adapter.call_service(domain, service, action.device, action.data)

    def _subscribe_to_triggers(self) -> None:
        """Subscribe to all scene triggers."""
        for scene in self._scenes.values():
            self._subscribe_scene_triggers(scene)

    def _subscribe_scene_triggers(self, scene: SceneConfig) -> None:
        """Subscribe to triggers for a specific scene.

        Args:
            scene: Scene configuration.
        """
        if not self.event_bus:
            return

        for trigger in scene.triggers:
            if trigger.type == "button" and trigger.entity_id:
                # Subscribe to button press events
                pass  # TODO: Implement event subscription

            elif trigger.type == "state" and trigger.entity_id:
                # Subscribe to state change events
                pass  # TODO: Implement event subscription

    def check_time_triggers(self) -> list[str]:
        """Check and return scenes with time-based triggers that should fire now.

        Returns:
            List of scene IDs that should be activated based on time triggers.
        """
        now = datetime.now()
        current_time = now.strftime("%H:%M")

        triggered_scenes: list[str] = []

        for scene_id, scene in self._scenes.items():
            for trigger in scene.triggers:
                if trigger.type == "time" and trigger.at == current_time:
                    triggered_scenes.append(scene_id)
                    logger.debug(f"Time trigger matched for scene {scene_id} at {current_time}")

        return triggered_scenes

    async def process_time_triggers(self) -> None:
        """Process all time-based triggers and activate matching scenes."""
        triggered = self.check_time_triggers()
        for scene_id in triggered:
            await self.activate_scene(scene_id)

    def reload_scenes(self, new_config: SceneManagerConfig) -> None:
        """Reload scenes from new configuration.

        Args:
            new_config: New scene manager configuration.
        """
        logger.info("Reloading scenes from new configuration")

        # Unregister all scenes
        self._scenes.clear()

        # Update config and reload
        self.config = new_config
        for scene_config in self.config.scenes:
            self.register_scene(scene_config)

        logger.info(f"Reloaded {len(self._scenes)} scenes")
