"""Plugin system interfaces for Smart Home Platform.

This module defines the protocols (interfaces) that plugins must implement.
Plugins are discovered automatically via entry_points and loaded at runtime.
"""

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class BehaviorPlugin(Protocol):
    """Interface for behavior plugins.

    Behavior plugins add new automation behaviors to the system without
    modifying the core codebase.
    """

    name: str
    """Unique identifier for this behavior."""

    description: str
    """Human-readable description of what this behavior does."""

    version: str
    """Plugin version following semver (e.g., '1.0.0')."""

    def get_fsm_definition(self) -> dict[str, Any]:
        """Return FSM definition for this behavior.

        Returns:
            Dictionary containing states, transitions, and initial state.
        """
        ...

    def get_guards(self) -> dict[str, Any]:
        """Return guard functions registry for this behavior.

        Returns:
            Dictionary mapping guard names to callable functions.
        """
        ...

    def get_actions(self) -> dict[str, Any]:
        """Return action functions registry for this behavior.

        Returns:
            Dictionary mapping action names to callable functions.
        """
        ...


@runtime_checkable
class MiddlewarePlugin(Protocol):
    """Interface for middleware plugins.

    Middleware plugins intercept and modify commands/events in the pipeline.
    """

    name: str
    """Unique identifier for this middleware."""

    description: str
    """Human-readable description of what this middleware does."""

    version: str
    """Plugin version following semver."""

    priority: int
    """Execution priority (lower = earlier execution)."""

    def process_command(self, command: dict[str, Any]) -> dict[str, Any] | None:
        """Process a command before it reaches the dispatcher.

        Args:
            command: The command dictionary to process.

        Returns:
            Modified command dictionary, or None to drop the command.
        """
        ...

    def process_event(self, event: dict[str, Any]) -> dict[str, Any] | None:
        """Process an event before it reaches the router.

        Args:
            event: The event dictionary to process.

        Returns:
            Modified event dictionary, or None to drop the event.
        """
        ...


@runtime_checkable
class AdapterPlugin(Protocol):
    """Interface for adapter plugins.

    Adapter plugins provide connectivity to external systems
    (e.g., different home automation platforms, IoT protocols).
    """

    name: str
    """Unique identifier for this adapter."""

    description: str
    """Human-readable description of what this adapter connects to."""

    version: str
    """Plugin version following semver."""

    def connect(self) -> bool:
        """Establish connection to the external system.

        Returns:
            True if connection successful, False otherwise.
        """
        ...

    def disconnect(self) -> None:
        """Close connection to the external system."""
        ...

    def is_connected(self) -> bool:
        """Check if connection is active.

        Returns:
            True if connected, False otherwise.
        """
        ...

    def send_command(self, device_id: str, command: str, params: dict[str, Any]) -> bool:
        """Send a command to an external device.

        Args:
            device_id: Target device identifier.
            command: Command to execute.
            params: Command parameters.

        Returns:
            True if command sent successfully, False otherwise.
        """
        ...

    def subscribe_events(self, callback: callable) -> bool:
        """Subscribe to events from the external system.

        Args:
            callback: Function to call when events arrive.

        Returns:
            True if subscription successful, False otherwise.
        """
        ...


@runtime_checkable
class PluginMetadata(Protocol):
    """Interface for plugin metadata providers.

    Plugins can optionally implement this to provide rich metadata.
    """

    def get_metadata(self) -> dict[str, Any]:
        """Return comprehensive plugin metadata.

        Returns:
            Dictionary containing:
            - name: Plugin name
            - version: Plugin version
            - author: Plugin author
            - license: License type
            - dependencies: List of required plugins/packages
            - compatible_versions: Supported platform versions
        """
        ...
