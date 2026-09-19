"""Tests for DeploymentManager."""

from datetime import datetime
from pathlib import Path

import pytest
from src.core.deployment_manager import (
    DeploymentManager,
    DeploymentMode,
    DeploymentState,
)


class TestDeploymentMode:
    """Test DeploymentMode enum."""

    def test_modes_exist(self):
        """Test that all required modes exist."""
        assert DeploymentMode.SHADOW.value == "shadow"
        assert DeploymentMode.ACTIVE.value == "active"
        assert DeploymentMode.HYBRID.value == "hybrid"
        assert DeploymentMode.DISABLED.value == "disabled"


class TestDeploymentState:
    """Test DeploymentState dataclass."""

    def test_default_values(self):
        """Test default state values."""
        state = DeploymentState()

        assert state.mode == DeploymentMode.SHADOW
        assert state.backup_created is False
        assert state.backup_path is None
        assert state.health_status == "unknown"
        assert state.error_count == 0
        assert state.warning_count == 0
        assert isinstance(state.started_at, datetime)
        assert isinstance(state.last_mode_change, datetime)

    def test_to_dict(self):
        """Test serialization to dictionary."""
        state = DeploymentState(
            mode=DeploymentMode.ACTIVE,
            backup_created=True,
            backup_path=Path("/backup"),
            health_status="healthy",
            error_count=5,
            warning_count=2,
        )

        result = state.to_dict()

        assert result["mode"] == "active"
        assert result["backup_created"] is True
        assert result["backup_path"] == "/backup"
        assert result["health_status"] == "healthy"
        assert result["error_count"] == 5
        assert result["warning_count"] == 2


class TestDeploymentManager:
    """Test DeploymentManager class."""

    @pytest.fixture
    def manager(self, tmp_path):
        """Create a DeploymentManager instance."""
        config_path = tmp_path / "deployment.yaml"
        return DeploymentManager(config_path=config_path)

    def test_initialization(self, manager):
        """Test successful initialization."""
        result = manager.initialize()

        assert result is True
        assert manager.get_mode() == DeploymentMode.SHADOW
        assert manager.state.health_status == "healthy"

    def test_initialization_without_config(self, manager):
        """Test initialization without existing config file."""
        # Config file doesn't exist yet - should still work
        result = manager.initialize()

        assert result is True
        assert manager.get_mode() == DeploymentMode.SHADOW

    def test_set_mode_shadow_to_active(self, manager, tmp_path):
        """Test mode change from shadow to active."""
        manager.initialize()

        # Must create backup first
        backup_path = tmp_path / "backup.yaml"
        manager.set_backup_created(backup_path)

        # Now can switch to active
        result = manager.set_mode(DeploymentMode.ACTIVE)

        assert result is True
        assert manager.get_mode() == DeploymentMode.ACTIVE

    def test_set_mode_requires_backup(self, manager):
        """Test that active mode requires backup."""
        manager.initialize()

        # Try to switch to active without backup
        result = manager.set_mode(DeploymentMode.ACTIVE)

        assert result is False
        assert manager.get_mode() == DeploymentMode.SHADOW

    def test_set_mode_disabled_to_active_blocked(self, manager, tmp_path):
        """Test that disabled -> active transition is blocked."""
        manager.initialize()
        manager.set_mode(DeploymentMode.DISABLED, force=True)

        # Try to go directly to active
        result = manager.set_mode(DeploymentMode.ACTIVE)

        assert result is False
        assert manager.get_mode() == DeploymentMode.DISABLED

    def test_should_execute_action_active(self, manager, tmp_path):
        """Test action execution in active mode."""
        manager.initialize()
        manager.set_backup_created(tmp_path / "backup.yaml")
        manager.set_mode(DeploymentMode.ACTIVE)

        assert manager.should_execute_action() is True

    def test_should_execute_action_shadow(self, manager):
        """Test action execution in shadow mode."""
        manager.initialize()

        assert manager.should_execute_action() is False

    def test_should_execute_action_disabled(self, manager):
        """Test action execution in disabled mode."""
        manager.initialize()
        manager.set_mode(DeploymentMode.DISABLED, force=True)

        assert manager.should_execute_action() is False

    def test_should_execute_action_hybrid(self, manager, tmp_path):
        """Test action execution in hybrid mode."""
        manager.initialize()
        manager.set_backup_created(tmp_path / "backup.yaml")
        manager.set_mode(DeploymentMode.HYBRID)

        assert manager.should_execute_action() is True

    def test_log_dry_run_action(self, manager, caplog):
        """Test dry run action logging."""
        import logging

        caplog.set_level(logging.INFO)

        manager.initialize()
        manager.log_dry_run_action("light.turn_on", "light.kitchen", {"brightness": 200})

        assert "[DRY RUN]" in caplog.text
        assert "light.turn_on" in caplog.text
        assert "light.kitchen" in caplog.text

    def test_record_error_triggers_fallback(self, manager):
        """Test that error threshold triggers fallback."""
        manager.initialize()

        # Record errors up to threshold
        for i in range(10):
            manager.record_error(RuntimeError(f"Error {i}"))

        # Should have triggered fallback
        assert manager.get_mode() == DeploymentMode.DISABLED
        assert manager.state.health_status == "fallback_triggered"

    def test_record_warning(self, manager, caplog):
        """Test warning recording."""
        import logging

        caplog.set_level(logging.WARNING)

        manager.initialize()
        manager.record_warning("Test warning")

        assert manager.state.warning_count == 1
        assert "Test warning" in caplog.text

    def test_reset_counters(self, manager):
        """Test counter reset."""
        manager.initialize()

        # Add some errors and warnings
        manager.record_error(RuntimeError("Test"))
        manager.record_warning("Test")

        # Reset
        manager.reset_counters()

        assert manager.state.error_count == 0
        assert manager.state.warning_count == 0

    def test_health_check_healthy(self, manager):
        """Test health check when healthy."""
        manager.initialize()

        result = manager.health_check()

        assert result is True
        assert manager.state.health_status == "healthy"

    def test_health_check_not_initialized(self, manager):
        """Test health check before initialization."""
        result = manager.health_check()

        assert result is False
        assert manager.state.health_status == "not_initialized"

    def test_health_check_unhealthy(self, manager):
        """Test health check when unhealthy."""
        manager.initialize()

        # Add many errors
        for i in range(15):
            manager.record_error(RuntimeError(f"Error {i}"))

        result = manager.health_check()

        assert result is False
        assert manager.state.health_status == "unhealthy"

    def test_force_mode_change(self, manager):
        """Test forced mode change bypasses validation."""
        manager.initialize()

        # Force change to active without backup
        result = manager.set_mode(DeploymentMode.ACTIVE, force=True)

        assert result is True
        assert manager.get_mode() == DeploymentMode.ACTIVE

    def test_get_state(self, manager):
        """Test getting deployment state."""
        manager.initialize()

        state = manager.get_state()

        assert isinstance(state, DeploymentState)
        assert state.mode == DeploymentMode.SHADOW
        assert state.health_status == "healthy"
