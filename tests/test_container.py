"""Tests for the Dependency Injection Container."""

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0

import os
from unittest.mock import MagicMock, patch

import pytest

from core.container import Container, PlatformContext
from core.models.manifest import Manifest


class TestContainerInitialization:
    """Test container initialization scenarios."""

    def test_init_with_manifest_path(self):
        """Test container initialization with manifest path."""
        container = Container(manifest_path="instances/leonids_house/manifest.yaml")
        assert container._manifest_path == "instances/leonids_house/manifest.yaml"
        assert container._manifest is None
        assert container._event_bus is None
        assert container._fsm is None

    def test_init_with_preloaded_manifest(self):
        """Test container initialization with pre-loaded manifest."""
        mock_manifest = MagicMock(spec=Manifest)
        container = Container(manifest=mock_manifest)
        assert container._manifest is mock_manifest
        assert container._manifest_path is None

    def test_init_with_config_overrides(self):
        """Test container initialization with config overrides."""
        overrides = {"test_key": "test_value"}
        container = Container(manifest_path="test.yaml", config_overrides=overrides)
        assert container._config_overrides == overrides


class TestLazyInitialization:
    """Test lazy initialization of components."""

    def test_event_bus_lazy_init(self):
        """Test EventBus is created on first access."""
        container = Container(manifest_path="instances/leonids_house/manifest.yaml")
        assert container._event_bus is None

        event_bus = container.event_bus
        assert event_bus is not None
        assert container._event_bus is event_bus

        # Second access returns same instance
        assert container.event_bus is event_bus

    def test_fsm_lazy_init(self):
        """Test FSMEngine is created on first access."""
        container = Container(manifest_path="instances/leonids_house/manifest.yaml")
        assert container._fsm is None

        fsm = container.fsm
        assert fsm is not None
        assert container._fsm is fsm

    def test_control_tracker_lazy_init(self):
        """Test ControlTracker is created on first access."""
        container = Container(manifest_path="instances/leonids_house/manifest.yaml")
        assert container._control_tracker is None

        tracker = container.control_tracker
        assert tracker is not None
        assert container._control_tracker is tracker

    def test_manifest_lazy_load(self):
        """Test manifest is loaded on first access."""
        container = Container(manifest_path="instances/leonids_house/manifest.yaml")
        assert container._manifest is None

        manifest = container.manifest
        assert manifest is not None
        assert container._manifest is manifest


class TestComponentDependencies:
    """Test that components are created with correct dependencies."""

    def test_event_router_depends_on_manifest_and_fsm(self):
        """Test EventRouter receives manifest and fsm."""
        container = Container(manifest_path="instances/leonids_house/manifest.yaml")

        # Access event_router (should trigger creation of manifest and fsm)
        event_router = container.event_router
        assert event_router is not None
        assert container._manifest is not None
        assert container._fsm is not None

    def test_adapter_with_mock_token(self):
        """Test adapter creation with mock token (uses MockAdapter)."""
        container = Container(manifest_path="instances/leonids_house/manifest.yaml")

        # Ensure no HA_TOKEN is set
        original_token = os.environ.pop("HA_TOKEN", None)

        try:
            adapter = container.adapter
            assert adapter is not None
            from adapters.mock_adapter import MockAdapter

            assert isinstance(adapter, MockAdapter)
        finally:
            if original_token:
                os.environ["HA_TOKEN"] = original_token

    @patch.dict(os.environ, {"HA_TOKEN": "test_token"})
    def test_adapter_with_real_token(self):
        """Test adapter creation with real token (uses HAAdapter)."""
        container = Container(manifest_path="instances/leonids_house/manifest.yaml")

        adapter = container.adapter
        assert adapter is not None
        from adapters.ha_adapter import HAAdapter

        assert isinstance(adapter, HAAdapter)

    def test_dispatcher_depends_on_adapter(self):
        """Test CommandDispatcher receives adapter."""
        container = Container(manifest_path="instances/leonids_house/manifest.yaml")

        # Remove HA_TOKEN to use MockAdapter
        os.environ.pop("HA_TOKEN", None)

        dispatcher = container.dispatcher
        assert dispatcher is not None
        assert container._adapter is not None

    def test_middleware_depends_on_manifest_and_tracker(self):
        """Test ManualLockoutMiddleware receives automation_rules and control_tracker."""
        container = Container(manifest_path="instances/leonids_house/manifest.yaml")

        middleware = container.middleware
        assert middleware is not None
        assert container._control_tracker is not None


class TestBuildMethod:
    """Test the build() method creates complete platform context."""

    def test_build_returns_platform_context(self):
        """Test build() returns PlatformContext with all components."""
        container = Container(manifest_path="instances/leonids_house/manifest.yaml")

        # Remove HA_TOKEN to use MockAdapter
        os.environ.pop("HA_TOKEN", None)

        context = container.build()

        assert isinstance(context, PlatformContext)
        assert context.manifest is not None
        assert context.event_bus is not None
        assert context.fsm is not None
        assert context.control_tracker is not None
        assert context.adapter is not None
        assert context.dispatcher is not None
        assert context.event_router is not None

    def test_build_initializes_components_in_order(self):
        """Test build() initializes components in correct dependency order."""
        container = Container(manifest_path="instances/leonids_house/manifest.yaml")

        # Remove HA_TOKEN to use MockAdapter
        os.environ.pop("HA_TOKEN", None)

        # Before build, most components should be None
        assert container._event_bus is None
        assert container._fsm is None

        container.build()

        # After build, all components should be initialized
        assert container._event_bus is not None
        assert container._fsm is not None
        assert container._event_router is not None
        assert container._adapter is not None
        assert container._dispatcher is not None

    def test_build_links_adapter_to_fsm(self):
        """Test build() links adapter to FSM engine."""
        container = Container(manifest_path="instances/leonids_house/manifest.yaml")

        # Remove HA_TOKEN to use MockAdapter
        os.environ.pop("HA_TOKEN", None)

        context = container.build()

        # Verify adapter has reference to FSM
        from adapters.mock_adapter import MockAdapter

        assert isinstance(context.adapter, MockAdapter)
        assert context.adapter._fsm_engine is context.fsm


class TestResetMethod:
    """Test the reset() method for testing purposes."""

    def test_reset_clears_cached_instances(self):
        """Test reset() clears all cached component instances."""
        container = Container(manifest_path="instances/leonids_house/manifest.yaml")

        # Initialize some components including manifest
        _ = container.manifest  # Load manifest
        _ = container.event_bus
        _ = container.fsm
        _ = container.control_tracker

        assert container._manifest is not None
        assert container._event_bus is not None
        assert container._fsm is not None
        assert container._control_tracker is not None

        # Reset
        container.reset()

        # All should be cleared (except manifest)
        assert container._event_bus is None
        assert container._fsm is None
        assert container._control_tracker is None
        assert container._manifest is not None  # Manifest is preserved

    def test_reset_allows_rebuild(self):
        """Test components can be rebuilt after reset."""
        container = Container(manifest_path="instances/leonids_house/manifest.yaml")

        # Remove HA_TOKEN to use MockAdapter
        os.environ.pop("HA_TOKEN", None)

        # Build once
        context1 = container.build()
        original_event_bus = context1.event_bus

        # Reset and rebuild
        container.reset()
        context2 = container.build()

        # Should get new instances
        assert context2.event_bus is not original_event_bus


class TestContainerWithMocks:
    """Test using container with mocked components for testing."""

    def test_can_override_components(self):
        """Test that components can be overridden for testing."""
        container = Container(manifest_path="instances/leonids_house/manifest.yaml")

        # Pre-set a mock event bus
        mock_event_bus = MagicMock()
        container._event_bus = mock_event_bus

        assert container.event_bus is mock_event_bus

    def test_factory_uses_injected_dependencies(self):
        """Test FSMFactory uses injected dependencies."""
        container = Container(manifest_path="instances/leonids_house/manifest.yaml")

        factory = container.factory
        assert factory is not None
        assert factory._engine is container.fsm
        assert factory._registry is container.registry
        assert factory._event_bus is container.event_bus


class TestErrorHandling:
    """Test error handling in container."""

    def test_manifest_property_raises_without_path_or_manifest(self):
        """Test manifest property raises RuntimeError if no path or manifest provided."""
        container = Container()

        with pytest.raises(RuntimeError, match="Manifest path not provided"):
            _ = container.manifest

    def test_manifest_with_preloaded_manifest(self):
        """Test manifest property works with pre-loaded manifest."""
        mock_manifest = MagicMock(spec=Manifest)
        container = Container(manifest=mock_manifest)

        assert container.manifest is mock_manifest
