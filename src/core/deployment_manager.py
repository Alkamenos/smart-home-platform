"""
Deployment Manager for Safe Home Assistant Integration.

Provides shadow mode, graceful fallback, and deployment state management.
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path


logger = logging.getLogger(__name__)


class DeploymentMode(Enum):
    """Deployment modes for the platform."""

    SHADOW = "shadow"
    """Platform computes actions but doesn't execute them (dry-run)."""

    ACTIVE = "active"
    """Platform executes actions normally."""

    HYBRID = "hybrid"
    """Platform executes actions but keeps HA automations as fallback."""

    DISABLED = "disabled"
    """Platform is completely disabled, HA automations handle everything."""


@dataclass
class DeploymentState:
    """Current state of the deployment."""

    mode: DeploymentMode = DeploymentMode.SHADOW
    started_at: datetime = field(default_factory=datetime.now)
    last_mode_change: datetime = field(default_factory=datetime.now)
    backup_created: bool = False
    backup_path: Path | None = None
    health_status: str = "unknown"
    error_count: int = 0
    warning_count: int = 0

    def to_dict(self) -> dict:
        """Convert state to dictionary for serialization."""
        return {
            "mode": self.mode.value,
            "started_at": self.started_at.isoformat(),
            "last_mode_change": self.last_mode_change.isoformat(),
            "backup_created": self.backup_created,
            "backup_path": str(self.backup_path) if self.backup_path else None,
            "health_status": self.health_status,
            "error_count": self.error_count,
            "warning_count": self.warning_count,
        }


class DeploymentManager:
    """
    Manages safe deployment strategies for Home Assistant integration.

    Features:
    - Shadow mode for safe testing
    - Graceful fallback on errors
    - Deployment state tracking
    - Mode switching with validation
    """

    def __init__(self, config_path: Path | None = None):
        """
        Initialize the deployment manager.

        Args:
            config_path: Path to deployment configuration file.
        """
        self.config_path = config_path or Path("deployment.yaml")
        self.state = DeploymentState()
        self._error_threshold = 10  # Max errors before fallback
        self._initialized = False

    def initialize(self) -> bool:
        """
        Initialize the deployment manager.

        Returns:
            True if initialization successful, False otherwise.
        """
        try:
            logger.info("Initializing DeploymentManager...")

            # Load configuration if exists
            if self.config_path.exists():
                self._load_config()

            # Start in shadow mode by default for safety
            self.state.mode = DeploymentMode.SHADOW
            self.state.started_at = datetime.now()
            self.state.health_status = "healthy"

            self._initialized = True
            logger.info(f"DeploymentManager initialized in {self.state.mode.value} mode")
            return True

        except Exception as e:
            logger.error(f"Failed to initialize DeploymentManager: {e}")
            self.state.health_status = "unhealthy"
            return False

    def _load_config(self) -> None:
        """Load deployment configuration from file."""
        # TODO: Implement YAML config loading
        logger.debug(f"Loading config from {self.config_path}")

    def get_mode(self) -> DeploymentMode:
        """Get current deployment mode."""
        return self.state.mode

    def set_mode(self, mode: DeploymentMode, force: bool = False) -> bool:
        """
        Change deployment mode.

        Args:
            mode: New deployment mode.
            force: If True, skip validation checks.

        Returns:
            True if mode changed successfully.
        """
        if not self._initialized:
            logger.error("DeploymentManager not initialized")
            return False

        old_mode = self.state.mode

        # Validation (unless forced)
        if not force and not self._validate_mode_change(old_mode, mode):
            logger.warning(
                f"Mode change from {old_mode.value} to {mode.value} blocked by validation"
            )
            return False

        # Apply mode change
        self.state.mode = mode
        self.state.last_mode_change = datetime.now()

        logger.info(f"Deployment mode changed: {old_mode.value} → {mode.value}")

        # Log special transitions
        if mode == DeploymentMode.SHADOW:
            logger.info("Now in DRY RUN mode - actions will be logged but not executed")
        elif mode == DeploymentMode.ACTIVE:
            logger.info("Now in ACTIVE mode - actions will be executed")

        return True

    def _validate_mode_change(self, from_mode: DeploymentMode, to_mode: DeploymentMode) -> bool:
        """
        Validate mode transition.

        Args:
            from_mode: Current mode.
            to_mode: Target mode.

        Returns:
            True if transition is valid.
        """
        # Cannot go directly from DISABLED to ACTIVE
        if from_mode == DeploymentMode.DISABLED and to_mode == DeploymentMode.ACTIVE:
            logger.warning("Must enable SHADOW mode before ACTIVE mode")
            return False

        # Must have backup before going ACTIVE
        if to_mode == DeploymentMode.ACTIVE and not self.state.backup_created:
            logger.warning("Cannot activate without backup. Create backup first.")
            return False

        return True

    def should_execute_action(self) -> bool:
        """
        Check if actions should be executed.

        Returns:
            True if platform should execute actions, False for shadow/disabled modes.
        """
        return self.state.mode in (DeploymentMode.ACTIVE, DeploymentMode.HYBRID)

    def log_dry_run_action(self, action_type: str, entity_id: str, data: dict) -> None:
        """
        Log an action that would be executed in shadow mode.

        Args:
            action_type: Type of action (e.g., 'light.turn_on').
            entity_id: Target entity ID.
            data: Action data/parameters.
        """
        if self.state.mode != DeploymentMode.SHADOW:
            return

        logger.info(f"[DRY RUN] Would execute: {action_type}(entity_id={entity_id}, data={data})")

    def record_error(self, error: Exception) -> None:
        """
        Record an error and check if fallback is needed.

        Args:
            error: The exception that occurred.
        """
        self.state.error_count += 1
        logger.error(f"Deployment error #{self.state.error_count}: {error}")

        # Check if we need to trigger fallback
        if self.state.error_count >= self._error_threshold:
            self._trigger_fallback(error)

    def _trigger_fallback(self, error: Exception) -> None:
        """
        Trigger graceful fallback to HA automations.

        Args:
            error: The error that triggered fallback.
        """
        logger.critical(
            f"Error threshold reached ({self._error_threshold}). "
            f"Triggering graceful fallback. Last error: {error}"
        )

        # Switch to disabled mode
        self.set_mode(DeploymentMode.DISABLED, force=True)
        self.state.health_status = "fallback_triggered"

        # TODO: Send notification to admin
        logger.warning("Platform disabled. HA automations are now in control.")

    def record_warning(self, message: str) -> None:
        """Record a warning."""
        self.state.warning_count += 1
        logger.warning(f"Deployment warning #{self.state.warning_count}: {message}")

    def set_backup_created(self, backup_path: Path) -> None:
        """
        Mark backup as created.

        Args:
            backup_path: Path to the backup file.
        """
        self.state.backup_created = True
        self.state.backup_path = backup_path
        logger.info(f"Backup created at: {backup_path}")

    def get_state(self) -> DeploymentState:
        """Get current deployment state."""
        return self.state

    def reset_counters(self) -> None:
        """Reset error and warning counters."""
        self.state.error_count = 0
        self.state.warning_count = 0
        logger.debug("Deployment counters reset")

    def health_check(self) -> bool:
        """
        Perform health check.

        Returns:
            True if platform is healthy.
        """
        # Basic health checks
        if not self._initialized:
            self.state.health_status = "not_initialized"
            return False

        if self.state.error_count > self._error_threshold:
            self.state.health_status = "unhealthy"
            return False

        self.state.health_status = "healthy"
        return True
