"""Tests for the plugin system.

This module tests the plugin loader and interfaces for the Smart Home Platform.
"""

from typing import Any
from unittest.mock import Mock, patch

import pytest
from src.core.plugin_loader import (
    PluginInfo,
    PluginLoader,
    PluginLoadResult,
)


class TestPluginInterfaces:
    """Test plugin interface protocols."""

    def test_behavior_plugin_protocol(self):
        """Test that BehaviorPlugin protocol is correctly defined."""

        class ValidBehavior:
            name = "test_behavior"
            description = "Test behavior"
            version = "1.0.0"

            def get_fsm_definition(self) -> dict[str, Any]:
                return {"states": {}, "transitions": [], "initial_state": "idle"}

            def get_guards(self) -> dict[str, Any]:
                return {}

            def get_actions(self) -> dict[str, Any]:
                return {}

        behavior = ValidBehavior()

        # Verify required attributes exist
        assert hasattr(behavior, "name")
        assert hasattr(behavior, "description")
        assert hasattr(behavior, "version")
        assert callable(behavior.get_fsm_definition)
        assert callable(behavior.get_guards)
        assert callable(behavior.get_actions)

    def test_middleware_plugin_protocol(self):
        """Test that MiddlewarePlugin protocol is correctly defined."""

        class ValidMiddleware:
            name = "test_middleware"
            description = "Test middleware"
            version = "1.0.0"
            priority = 10

            def process_command(self, command: dict[str, Any]) -> dict[str, Any] | None:
                return command

            def process_event(self, event: dict[str, Any]) -> dict[str, Any] | None:
                return event

        middleware = ValidMiddleware()

        # Verify required attributes exist
        assert hasattr(middleware, "name")
        assert hasattr(middleware, "description")
        assert hasattr(middleware, "version")
        assert hasattr(middleware, "priority")
        assert callable(middleware.process_command)
        assert callable(middleware.process_event)

    def test_adapter_plugin_protocol(self):
        """Test that AdapterPlugin protocol is correctly defined."""

        class ValidAdapter:
            name = "test_adapter"
            description = "Test adapter"
            version = "1.0.0"

            def connect(self) -> bool:
                return True

            def disconnect(self) -> None:
                pass

            def is_connected(self) -> bool:
                return True

            def send_command(self, device_id: str, command: str, params: dict[str, Any]) -> bool:
                return True

            def subscribe_events(self, callback: callable) -> bool:
                return True

        adapter = ValidAdapter()

        # Verify required methods exist
        assert callable(adapter.connect)
        assert callable(adapter.disconnect)
        assert callable(adapter.is_connected)
        assert callable(adapter.send_command)
        assert callable(adapter.subscribe_events)


class TestPluginInfo:
    """Test PluginInfo dataclass."""

    def test_plugin_info_default_values(self):
        """Test PluginInfo default values."""
        info = PluginInfo(
            name="test_plugin",
            module_path="test.module:TestClass",
            plugin_class=Mock,
        )

        assert info.name == "test_plugin"
        assert info.module_path == "test.module:TestClass"
        assert info.instance is None
        assert info.version == "unknown"
        assert info.error is None
        assert info.is_loaded is False

    def test_plugin_info_custom_values(self):
        """Test PluginInfo with custom values."""
        info = PluginInfo(
            name="custom_plugin",
            module_path="custom.module:CustomClass",
            plugin_class=Mock,
            instance=Mock(),
            version="2.0.0",
            is_loaded=True,
        )

        assert info.name == "custom_plugin"
        assert info.version == "2.0.0"
        assert info.is_loaded is True
        assert info.instance is not None


class TestPluginLoadResult:
    """Test PluginLoadResult dataclass."""

    def test_plugin_load_result_defaults(self):
        """Test PluginLoadResult default values."""
        result = PluginLoadResult(success=True)

        assert result.success is True
        assert result.loaded_count == 0
        assert result.failed_count == 0
        assert result.errors == []

    def test_plugin_load_result_with_data(self):
        """Test PluginLoadResult with data."""
        result = PluginLoadResult(
            success=False,
            loaded_count=5,
            failed_count=2,
            errors=["Error 1", "Error 2"],
        )

        assert result.success is False
        assert result.loaded_count == 5
        assert result.failed_count == 2
        assert len(result.errors) == 2


class TestPluginLoader:
    """Test PluginLoader class."""

    def test_plugin_loader_initialization(self):
        """Test PluginLoader initializes with empty plugin dictionaries."""
        loader = PluginLoader()

        assert loader.behavior_plugins == {}
        assert loader.middleware_plugins == {}
        assert loader.adapter_plugins == {}
        assert loader._discovered is False

    def test_discover_plugins_no_entry_points(self):
        """Test discover_plugins when no entry points are registered."""
        loader = PluginLoader()

        with patch("src.core.plugin_loader.entry_points", return_value=[]):
            loader.discover_plugins()

        assert loader._discovered is True
        assert loader.behavior_plugins == {}
        assert loader.middleware_plugins == {}
        assert loader.adapter_plugins == {}

    def test_discover_plugins_with_mocked_entry_points(self):
        """Test discover_plugins with mocked entry points."""
        loader = PluginLoader()

        # Create mock entry points
        mock_behavior_ep = Mock()
        mock_behavior_ep.name = "mock_behavior"
        mock_behavior_ep.value = "mock.module:MockBehavior"

        mock_middleware_ep = Mock()
        mock_middleware_ep.name = "mock_middleware"
        mock_middleware_ep.value = "mock.module:MockMiddleware"

        def mock_entry_points(group: str):
            if group == loader.BEHAVIOR_GROUP:
                return [mock_behavior_ep]
            elif group == loader.MIDDLEWARE_GROUP:
                return [mock_middleware_ep]
            return []

        with patch("src.core.plugin_loader.entry_points", side_effect=mock_entry_points):
            loader.discover_plugins()

        assert "mock_behavior" in loader.behavior_plugins
        assert "mock_middleware" in loader.middleware_plugins
        assert loader.adapter_plugins == {}

    def test_load_all_without_discovery(self):
        """Test load_all triggers discovery automatically."""
        loader = PluginLoader()

        with patch.object(loader, "discover_plugins") as mock_discover:
            with patch("src.core.plugin_loader.entry_points", return_value=[]):
                loader.load_all()

            mock_discover.assert_called_once()

    def test_get_behavior_plugins_empty(self):
        """Test get_behavior_plugins returns empty dict when no plugins loaded."""
        loader = PluginLoader()
        result = loader.get_behavior_plugins()
        assert result == {}

    def test_get_middleware_plugins_empty(self):
        """Test get_middleware_plugins returns empty dict when no plugins loaded."""
        loader = PluginLoader()
        result = loader.get_middleware_plugins()
        assert result == {}

    def test_get_adapter_plugins_empty(self):
        """Test get_adapter_plugins returns empty dict when no plugins loaded."""
        loader = PluginLoader()
        result = loader.get_adapter_plugins()
        assert result == {}

    def test_get_plugin_info_not_found(self):
        """Test get_plugin_info returns None for unknown plugin."""
        loader = PluginLoader()
        result = loader.get_plugin_info("unknown_plugin")
        assert result is None

    def test_unload_plugin_not_found(self):
        """Test unload_plugin returns False for unknown plugin."""
        loader = PluginLoader()
        result = loader.unload_plugin("unknown_plugin")
        assert result is False

    def test_unload_all_empty(self):
        """Test unload_all works with no loaded plugins."""
        loader = PluginLoader()
        # Should not raise any exceptions
        loader.unload_all()

    def test_load_single_plugin_invalid_module_path(self):
        """Test loading plugin with invalid module path format."""
        loader = PluginLoader()

        info = PluginInfo(
            name="bad_plugin",
            module_path="invalid_path_without_colon",
            plugin_class=None,
        )

        with pytest.raises(RuntimeError, match="Invalid module path format"):
            loader._load_single_plugin(info, "behavior")

    def test_load_single_plugin_module_not_found(self):
        """Test loading plugin when module doesn't exist."""
        loader = PluginLoader()

        info = PluginInfo(
            name="missing_module",
            module_path="nonexistent.module:NonExistentClass",
            plugin_class=None,
        )

        with pytest.raises(ModuleNotFoundError):
            loader._load_single_plugin(info, "behavior")

    def test_plugin_load_result_success_scenario(self):
        """Test PluginLoadResult indicates success correctly."""
        result = PluginLoadResult(
            success=True,
            loaded_count=10,
            failed_count=0,
            errors=[],
        )

        assert result.success is True
        assert result.loaded_count == 10
        assert result.failed_count == 0
        assert len(result.errors) == 0

    def test_plugin_load_result_failure_scenario(self):
        """Test PluginLoadResult indicates failure correctly."""
        result = PluginLoadResult(
            success=False,
            loaded_count=5,
            failed_count=3,
            errors=["Error 1", "Error 2", "Error 3"],
        )

        assert result.success is False
        assert result.loaded_count == 5
        assert result.failed_count == 3
        assert len(result.errors) == 3


class TestPluginLoaderIntegration:
    """Integration tests for plugin loader with real scenarios."""

    def test_loader_discovers_and_reports_count(self):
        """Test that loader correctly counts discovered plugins."""
        loader = PluginLoader()

        mock_eps = {
            loader.BEHAVIOR_GROUP: [
                Mock(name="behavior1", value="mod1:Class1"),
                Mock(name="behavior2", value="mod2:Class2"),
            ],
            loader.MIDDLEWARE_GROUP: [
                Mock(name="middleware1", value="mod3:Class3"),
            ],
            loader.ADAPTER_GROUP: [],
        }

        def mock_entry_points(group: str):
            return mock_eps.get(group, [])

        with patch("src.core.plugin_loader.entry_points", side_effect=mock_entry_points):
            loader.discover_plugins()

        assert len(loader.behavior_plugins) == 2
        assert len(loader.middleware_plugins) == 1
        assert len(loader.adapter_plugins) == 0


class SampleBehavior:
    """Sample behavior for testing."""

    name = "sample"
    description = "Sample behavior"
    version = "1.0.0"

    def get_fsm_definition(self) -> dict[str, Any]:
        return {}

    def get_guards(self) -> dict[str, Any]:
        return {}

    def get_actions(self) -> dict[str, Any]:
        return {}


class SampleMiddleware:
    """Sample middleware for testing."""

    name = "sample_mw"
    description = "Sample middleware"
    version = "1.0.0"
    priority = 5

    def process_command(self, command: dict[str, Any]) -> dict[str, Any] | None:
        return command

    def process_event(self, event: dict[str, Any]) -> dict[str, Any] | None:
        return event


class TestPluginLoadingWithMocks:
    """Test plugin loading with mocked imports."""

    def test_load_behavior_plugin_success(self):
        """Test successful loading of a behavior plugin."""
        loader = PluginLoader()

        # Create mock module with plugin class
        mock_module = Mock()
        mock_module.SampleBehavior = SampleBehavior

        info = PluginInfo(
            name="sample_behavior",
            module_path="test.module:SampleBehavior",
            plugin_class=None,
        )

        with patch.dict("sys.modules", {"test.module": mock_module}):
            loader._load_single_plugin(info, "behavior")

        assert info.is_loaded is True
        assert info.instance is not None
        assert info.plugin_class == SampleBehavior

    def test_load_middleware_plugin_success(self):
        """Test successful loading of a middleware plugin."""
        loader = PluginLoader()

        mock_module = Mock()
        mock_module.SampleMiddleware = SampleMiddleware

        info = PluginInfo(
            name="sample_middleware",
            module_path="test.module:SampleMiddleware",
            plugin_class=None,
        )

        with patch.dict("sys.modules", {"test.module": mock_module}):
            loader._load_single_plugin(info, "middleware")

        assert info.is_loaded is True
        assert info.instance is not None
