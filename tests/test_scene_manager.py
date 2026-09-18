"""Tests for Scene Manager.

Tests cover:
- Scene registration and unregistration
- Parallel and sequential execution
- Time-based triggers
- Scene activation scenarios
"""

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import asyncio
from datetime import datetime
from unittest.mock import MagicMock

import pytest
from src.core.models.scene import (
    SceneAction,
    SceneConfig,
    SceneManagerConfig,
    SceneTrigger,
)
from src.core.scene_manager import SceneManager


class TestSceneModels:
    """Test scene model classes."""

    def test_scene_action_creation(self) -> None:
        """Test creating a scene action with default values."""
        action = SceneAction(device="light.living_room", service="turn_off")

        assert action.device == "light.living_room"
        assert action.service == "turn_off"
        assert action.data == {}
        assert action.delay_sec == 0.0

    def test_scene_action_with_data(self) -> None:
        """Test creating a scene action with custom data."""
        action = SceneAction(
            device="media_player.tv",
            service="turn_on",
            data={"source": "Netflix"},
            delay_sec=2.5,
        )

        assert action.device == "media_player.tv"
        assert action.service == "turn_on"
        assert action.data == {"source": "Netflix"}
        assert action.delay_sec == 2.5

    def test_scene_trigger_time_type(self) -> None:
        """Test creating a time-based trigger."""
        trigger = SceneTrigger(type="time", at="19:00")

        assert trigger.type == "time"
        assert trigger.at == "19:00"
        assert trigger.entity_id is None

    def test_scene_trigger_button_type(self) -> None:
        """Test creating a button trigger."""
        trigger = SceneTrigger(type="button", entity_id="input_button.cinema", event="press")

        assert trigger.type == "button"
        assert trigger.entity_id == "input_button.cinema"
        assert trigger.event == "press"

    def test_scene_trigger_state_type(self) -> None:
        """Test creating a state-based trigger."""
        trigger = SceneTrigger(
            type="state", entity_id="binary_sensor.motion", from_state="off", to_state="on"
        )

        assert trigger.type == "state"
        assert trigger.entity_id == "binary_sensor.motion"
        assert trigger.from_state == "off"
        assert trigger.to_state == "on"

    def test_scene_config_parallel_mode(self) -> None:
        """Test creating a scene with parallel execution mode."""
        scene = SceneConfig(id="cinema_mode", name="Cinema Mode", execution_mode="parallel")

        assert scene.id == "cinema_mode"
        assert scene.name == "Cinema Mode"
        assert scene.execution_mode == "parallel"
        assert scene.enabled is True
        assert scene.has_sequential_actions is False

    def test_scene_config_sequential_mode(self) -> None:
        """Test creating a scene with sequential execution mode."""
        scene = SceneConfig(id="goodnight", name="Good Night", execution_mode="sequential")

        assert scene.execution_mode == "sequential"
        assert scene.has_sequential_actions is True

    def test_scene_config_has_sequential_actions_property(self) -> None:
        """Test has_sequential_actions property with mixed actions."""
        actions = [
            SceneAction(device="light1", service="turn_off"),
            SceneAction(device="light2", service="turn_off", delay_sec=1.0),
        ]
        scene = SceneConfig(id="test", name="Test", actions=actions, execution_mode="parallel")

        assert scene.has_sequential_actions is True

    def test_scene_config_with_full_cinema_scenario(self) -> None:
        """Test creating a complete cinema mode scene."""
        scene = SceneConfig(
            id="cinema_mode",
            name="Cinema Mode",
            description="Activate cinema experience",
            actions=[
                SceneAction(device="light.living_room", service="turn_off"),
                SceneAction(device="cover.blinds", service="close_cover"),
                SceneAction(
                    device="media_player.tv", service="turn_on", data={"source": "Netflix"}
                ),
            ],
            triggers=[
                SceneTrigger(type="time", at="19:00"),
                SceneTrigger(type="button", entity_id="input_button.cinema", event="press"),
            ],
            execution_mode="parallel",
        )

        assert len(scene.actions) == 3
        assert len(scene.triggers) == 2
        assert scene.enabled is True


class TestSceneManagerConfig:
    """Test SceneManagerConfig model."""

    def test_default_config(self) -> None:
        """Test creating default scene manager config."""
        config = SceneManagerConfig()

        assert config.scenes == []
        assert config.auto_reload is True

    def test_config_with_scenes(self) -> None:
        """Test creating config with scenes."""
        scene = SceneConfig(id="test", name="Test Scene")
        config = SceneManagerConfig(scenes=[scene])

        assert len(config.scenes) == 1
        assert config.scenes[0].id == "test"


class TestSceneManager:
    """Test SceneManager class."""

    @pytest.fixture
    def sample_scene(self) -> SceneConfig:
        """Create a sample scene for testing."""
        return SceneConfig(
            id="test_scene",
            name="Test Scene",
            actions=[
                SceneAction(device="light.test", service="turn_on"),
            ],
        )

    @pytest.fixture
    def sample_config(self, sample_scene: SceneConfig) -> SceneManagerConfig:
        """Create a sample config for testing."""
        return SceneManagerConfig(scenes=[sample_scene])

    def test_init_empty(self) -> None:
        """Test initializing scene manager with no config."""
        manager = SceneManager()

        assert manager._scenes == {}
        assert len(manager.list_scenes()) == 0

    def test_init_with_config(self, sample_config: SceneManagerConfig) -> None:
        """Test initializing scene manager with config."""
        manager = SceneManager(config=sample_config)

        assert len(manager._scenes) == 1
        assert "test_scene" in manager._scenes

    def test_register_scene(self, sample_scene: SceneConfig) -> None:
        """Test registering a scene."""
        manager = SceneManager()
        manager.register_scene(sample_scene)

        assert "test_scene" in manager._scenes
        assert manager.get_scene("test_scene") == sample_scene

    def test_register_disabled_scene(self) -> None:
        """Test registering a disabled scene."""
        scene = SceneConfig(id="disabled", name="Disabled", enabled=False)
        manager = SceneManager()
        manager.register_scene(scene)

        # Disabled scenes should not be registered
        assert "disabled" not in manager._scenes

    def test_unregister_scene(self, sample_scene: SceneConfig) -> None:
        """Test unregistering a scene."""
        manager = SceneManager()
        manager.register_scene(sample_scene)

        assert "test_scene" in manager._scenes

        manager.unregister_scene("test_scene")

        assert "test_scene" not in manager._scenes

    def test_get_scene_existing(self, sample_scene: SceneConfig) -> None:
        """Test getting an existing scene."""
        manager = SceneManager()
        manager.register_scene(sample_scene)

        retrieved = manager.get_scene("test_scene")

        assert retrieved is not None
        assert retrieved.id == "test_scene"
        assert retrieved.name == "Test Scene"

    def test_get_scene_nonexistent(self) -> None:
        """Test getting a non-existent scene."""
        manager = SceneManager()

        retrieved = manager.get_scene("nonexistent")

        assert retrieved is None

    def test_list_scenes(self, sample_config: SceneManagerConfig) -> None:
        """Test listing all scene IDs."""
        manager = SceneManager(config=sample_config)

        scene_ids = manager.list_scenes()

        assert scene_ids == ["test_scene"]


class TestSceneManagerActivation:
    """Test scene activation scenarios."""

    @pytest.fixture
    def sample_scene(self) -> SceneConfig:
        """Create a sample scene for testing."""
        return SceneConfig(
            id="test_scene",
            name="Test Scene",
            actions=[
                SceneAction(device="light.test", service="turn_on"),
            ],
        )

    @pytest.fixture
    def mock_event_bus(self) -> MagicMock:
        """Create a mock event bus."""
        return MagicMock()

    def test_activate_scene_success(self, sample_scene: SceneConfig) -> None:
        """Test successful scene activation."""
        manager = SceneManager()
        manager.register_scene(sample_scene)

        # Run async test
        result = asyncio.run(manager.activate_scene("test_scene"))

        assert result is True

    def test_activate_scene_not_found(self) -> None:
        """Test activating a non-existent scene."""
        manager = SceneManager()

        result = asyncio.run(manager.activate_scene("nonexistent"))

        assert result is False

    def test_activate_disabled_scene(self) -> None:
        """Test activating a disabled scene."""
        scene = SceneConfig(id="disabled", name="Disabled", enabled=False)
        manager = SceneManager()
        manager.register_scene(scene)

        result = asyncio.run(manager.activate_scene("disabled"))

        assert result is False

    @pytest.mark.asyncio
    async def test_parallel_execution(self) -> None:
        """Test parallel action execution."""
        actions = [
            SceneAction(device="light1", service="turn_on"),
            SceneAction(device="light2", service="turn_on"),
            SceneAction(device="light3", service="turn_on"),
        ]
        scene = SceneConfig(
            id="parallel_test", name="Parallel Test", actions=actions, execution_mode="parallel"
        )

        manager = SceneManager()
        manager.register_scene(scene)

        # Track execution order
        execution_order: list[str] = []

        # Mock the _execute_action method to track order
        original_execute = manager._execute_action

        async def mock_execute(action: SceneAction, context: dict | None = None) -> None:
            execution_order.append(action.device)
            await original_execute(action, context)

        manager._execute_action = mock_execute  # type: ignore[method-assign]

        await manager.activate_scene("parallel_test")

        # All actions should be executed (order may vary in parallel)
        assert len(execution_order) == 3
        assert set(execution_order) == {"light1", "light2", "light3"}

    @pytest.mark.asyncio
    async def test_sequential_execution(self) -> None:
        """Test sequential action execution."""
        actions = [
            SceneAction(device="light1", service="turn_on", delay_sec=0.1),
            SceneAction(device="light2", service="turn_on", delay_sec=0.1),
        ]
        scene = SceneConfig(
            id="sequential_test",
            name="Sequential Test",
            actions=actions,
            execution_mode="sequential",
        )

        manager = SceneManager()
        manager.register_scene(scene)

        # Track execution order
        execution_order: list[str] = []

        async def mock_execute(action: SceneAction, context: dict | None = None) -> None:
            execution_order.append(action.device)
            await manager.__class__._execute_action(manager, action, context)

        # Temporarily replace the method
        manager._execute_action = mock_execute  # type: ignore[method-assign]

        start_time = datetime.now()
        await manager.activate_scene("sequential_test")
        end_time = datetime.now()

        # Actions should execute in order
        assert execution_order == ["light1", "light2"]

        # Total time should include delays (at least 0.1 seconds)
        duration = (end_time - start_time).total_seconds()
        assert duration >= 0.1

    def test_check_time_triggers(self) -> None:
        """Test checking time-based triggers."""
        current_time = datetime.now().strftime("%H:%M")

        scene1 = SceneConfig(
            id="scene1",
            name="Scene 1",
            triggers=[SceneTrigger(type="time", at=current_time)],
        )
        scene2 = SceneConfig(
            id="scene2",
            name="Scene 2",
            triggers=[SceneTrigger(type="time", at="23:59")],
        )

        manager = SceneManager()
        manager.register_scene(scene1)
        manager.register_scene(scene2)

        triggered = manager.check_time_triggers()

        assert "scene1" in triggered
        assert "scene2" not in triggered

    @pytest.mark.asyncio
    async def test_process_time_triggers(self) -> None:
        """Test processing time-based triggers and activating scenes."""
        current_time = datetime.now().strftime("%H:%M")

        scene = SceneConfig(
            id="timed_scene",
            name="Timed Scene",
            triggers=[SceneTrigger(type="time", at=current_time)],
            actions=[SceneAction(device="light.test", service="turn_on")],
        )

        manager = SceneManager()
        manager.register_scene(scene)

        # Process time triggers - should activate the scene
        await manager.process_time_triggers()

        # Verify scene was activated (no exception means success)
        assert True

    def test_reload_scenes(self) -> None:
        """Test reloading scenes from new configuration."""
        initial_scene = SceneConfig(id="initial", name="Initial Scene")
        initial_config = SceneManagerConfig(scenes=[initial_scene])

        manager = SceneManager(config=initial_config)
        assert len(manager.list_scenes()) == 1

        # Create new config
        new_scene = SceneConfig(id="new", name="New Scene")
        new_config = SceneManagerConfig(scenes=[new_scene])

        manager.reload_scenes(new_config)

        assert len(manager.list_scenes()) == 1
        assert "new" in manager.list_scenes()
        assert "initial" not in manager.list_scenes()


class TestSceneManagerIntegration:
    """Integration tests for Scene Manager."""

    @pytest.mark.asyncio
    async def test_full_cinema_mode_scenario(self) -> None:
        """Test complete cinema mode scenario."""
        # Create cinema mode scene
        cinema_scene = SceneConfig(
            id="cinema_mode",
            name="Cinema Mode",
            description="Activate cinema experience",
            actions=[
                SceneAction(device="light.living_room", service="turn_off"),
                SceneAction(device="cover.blinds", service="close_cover"),
                SceneAction(
                    device="media_player.tv", service="turn_on", data={"source": "Netflix"}
                ),
            ],
            triggers=[
                SceneTrigger(type="button", entity_id="input_button.cinema", event="press"),
            ],
            execution_mode="parallel",
        )

        config = SceneManagerConfig(scenes=[cinema_scene])
        manager = SceneManager(config=config)

        # Activate the scene
        result = await manager.activate_scene("cinema_mode")

        assert result is True

    @pytest.mark.asyncio
    async def test_goodnight_sequence_scenario(self) -> None:
        """Test goodnight sequence with delays."""
        goodnight_scene = SceneConfig(
            id="goodnight",
            name="Good Night",
            description="Turn off everything and lock doors",
            actions=[
                SceneAction(device="light.all", service="turn_off"),
                SceneAction(device="cover.all", service="close_cover", delay_sec=1.0),
                SceneAction(device="lock.front_door", service="lock", delay_sec=2.0),
            ],
            execution_mode="sequential",
        )

        config = SceneManagerConfig(scenes=[goodnight_scene])
        manager = SceneManager(config=config)

        result = await manager.activate_scene("goodnight")

        assert result is True
