"""Plugin loader for Smart Home Platform.

This module provides automatic discovery and loading of plugins via
Python's entry_points mechanism (importlib.metadata).

Plugins are discovered from installed packages that register entry points
under the 'smart_home.behaviors', 'smart_home.middleware', or
'smart_home.adapters' groups.

Example usage::

    loader = PluginLoader()
    loader.discover_plugins()

    # Load all discovered plugins
    loader.load_all()

    # Access loaded plugins
    behaviors = loader.get_behavior_plugins()
    middlewares = loader.get_middleware_plugins()

Example plugin registration in pyproject.toml::

    [project.entry-points."smart_home.behaviors"]
    party_mode = "my_party_plugin.behavior:PartyModeBehavior"

    [project.entry-points."smart_home.middleware"]
    geo_fence = "my_geo_plugin.middleware:GeoFenceMiddleware"
"""

import logging
from dataclasses import dataclass, field
from importlib.metadata import entry_points
from typing import Any


logger = logging.getLogger(__name__)


@dataclass
class PluginInfo:
    """Information about a loaded plugin."""

    name: str
    """Plugin name from entry point."""

    module_path: str
    """Full module path (e.g., 'my_plugin.module:ClassName')."""

    plugin_class: type
    """The plugin class type."""

    instance: Any | None = None
    """Loaded plugin instance (None if not yet instantiated)."""

    version: str = "unknown"
    """Plugin version."""

    error: str | None = None
    """Error message if loading failed."""

    is_loaded: bool = False
    """Whether the plugin was successfully loaded."""


@dataclass
class PluginLoadResult:
    """Result of plugin loading operation."""

    success: bool
    """Whether loading was successful."""

    loaded_count: int = 0
    """Number of plugins successfully loaded."""

    failed_count: int = 0
    """Number of plugins that failed to load."""

    errors: list[str] = field(default_factory=list)
    """List of error messages."""


class PluginLoader:
    """Discovers and loads plugins via entry_points.

    This loader automatically discovers plugins registered under:
    - 'smart_home.behaviors' - Behavior plugins
    - 'smart_home.middleware' - Middleware plugins
    - 'smart_home.adapters' - Adapter plugins

    Attributes:
        behavior_plugins: Discovered behavior plugin info.
        middleware_plugins: Discovered middleware plugin info.
        adapter_plugins: Discovered adapter plugin info.
    """

    BEHAVIOR_GROUP = "smart_home.behaviors"
    MIDDLEWARE_GROUP = "smart_home.middleware"
    ADAPTER_GROUP = "smart_home.adapters"

    def __init__(self) -> None:
        """Initialize the plugin loader."""
        self.behavior_plugins: dict[str, PluginInfo] = {}
        self.middleware_plugins: dict[str, PluginInfo] = {}
        self.adapter_plugins: dict[str, PluginInfo] = {}
        self._discovered = False

    def discover_plugins(self) -> None:
        """Discover all available plugins via entry_points.

        This method scans registered entry points and collects information
        about available plugins. Plugins are not loaded until load_all()
        or specific load_* methods are called.
        """
        logger.info("Discovering plugins...")

        self._discover_group(self.BEHAVIOR_GROUP, self.behavior_plugins, "behavior")
        self._discover_group(self.MIDDLEWARE_GROUP, self.middleware_plugins, "middleware")
        self._discover_group(self.ADAPTER_GROUP, self.adapter_plugins, "adapter")

        self._discovered = True

        total = (
            len(self.behavior_plugins) + len(self.middleware_plugins) + len(self.adapter_plugins)
        )
        logger.info(
            f"Discovered {total} plugins: "
            f"{len(self.behavior_plugins)} behaviors, "
            f"{len(self.middleware_plugins)} middlewares, "
            f"{len(self.adapter_plugins)} adapters"
        )

    def _discover_group(
        self, group: str, target_dict: dict[str, PluginInfo], plugin_type: str
    ) -> None:
        """Discover plugins from a specific entry point group.

        Args:
            group: Entry point group name.
            target_dict: Dictionary to store discovered plugins.
            plugin_type: Human-readable plugin type for logging.
        """
        try:
            eps = entry_points(group=group)
            for ep in eps:
                plugin_info = PluginInfo(
                    name=ep.name,
                    module_path=f"{ep.value}",
                    plugin_class=None,  # Will be set during load
                )
                target_dict[ep.name] = plugin_info
                logger.debug(f"Found {plugin_type} plugin: {ep.name}")
        except Exception as e:
            logger.warning(f"Failed to discover {plugin_type} plugins: {e}")

    def load_all(self) -> PluginLoadResult:
        """Load all discovered plugins.

        Returns:
            PluginLoadResult with statistics about the loading process.
        """
        if not self._discovered:
            self.discover_plugins()

        result = PluginLoadResult(success=True)

        # Load each plugin type
        result.loaded_count += self._load_plugins(self.behavior_plugins, "behavior")
        result.failed_count += len(self.behavior_plugins) - sum(
            1 for p in self.behavior_plugins.values() if p.is_loaded
        )

        result.loaded_count += self._load_plugins(self.middleware_plugins, "middleware")
        result.failed_count += len(self.middleware_plugins) - sum(
            1 for p in self.middleware_plugins.values() if p.is_loaded
        )

        result.loaded_count += self._load_plugins(self.adapter_plugins, "adapter")
        result.failed_count += len(self.adapter_plugins) - sum(
            1 for p in self.adapter_plugins.values() if p.is_loaded
        )

        # Collect errors
        all_plugins = [
            *self.behavior_plugins.values(),
            *self.middleware_plugins.values(),
            *self.adapter_plugins.values(),
        ]
        result.errors = [f"{p.name}: {p.error}" for p in all_plugins if p.error]

        if result.failed_count > 0:
            result.success = False
            logger.warning(f"Plugin loading completed with {result.failed_count} failures")
        else:
            logger.info(f"Successfully loaded {result.loaded_count} plugins")

        return result

    def _load_plugins(self, plugins: dict[str, PluginInfo], plugin_type: str) -> int:
        """Load plugins from a dictionary.

        Args:
            plugins: Dictionary of PluginInfo objects.
            plugin_type: Human-readable type for logging.

        Returns:
            Number of successfully loaded plugins.
        """
        loaded = 0
        for name, info in plugins.items():
            try:
                self._load_single_plugin(info, plugin_type)
                if info.is_loaded:
                    loaded += 1
            except Exception as e:
                info.error = str(e)
                info.is_loaded = False
                logger.error(f"Failed to load {plugin_type} plugin '{name}': {e}")

        return loaded

    def _load_single_plugin(self, info: PluginInfo, plugin_type: str) -> None:
        """Load a single plugin.

        Args:
            info: PluginInfo object to populate.
            plugin_type: Type of plugin for validation.
        """
        module_path = info.module_path

        # Parse module path (format: "module.path:ClassName")
        try:
            module_name, class_name = module_path.rsplit(":", 1)
        except ValueError as e:
            raise RuntimeError(
                f"Invalid module path format: {module_path}. Expected 'module.path:ClassName'"
            ) from e

        # Import module and get class
        module = __import__(module_name, fromlist=[class_name])
        plugin_class = getattr(module, class_name)

        info.plugin_class = plugin_class

        # Validate plugin interface
        if plugin_type == "behavior":
            if not isinstance(plugin_class, type) or not issubclass(plugin_class, type):
                # For protocols, we check at runtime
                pass
        elif plugin_type == "middleware" or plugin_type == "adapter":
            pass  # Validation happens at runtime

        # Instantiate the plugin
        try:
            instance = plugin_class()
            info.instance = instance
            info.is_loaded = True

            # Extract version if available
            if hasattr(instance, "version"):
                info.version = instance.version

            logger.info(f"Loaded {plugin_type} plugin '{info.name}' v{info.version}")
        except Exception as e:
            raise RuntimeError(f"Failed to instantiate plugin: {e}") from e

    def get_behavior_plugins(self) -> dict[str, Any]:
        """Get loaded behavior plugin instances.

        Returns:
            Dictionary mapping plugin names to instances.
        """
        return {
            name: info.instance
            for name, info in self.behavior_plugins.items()
            if info.is_loaded and info.instance is not None
        }

    def get_middleware_plugins(self) -> dict[str, Any]:
        """Get loaded middleware plugin instances.

        Returns:
            Dictionary mapping plugin names to instances.
        """
        return {
            name: info.instance
            for name, info in self.middleware_plugins.items()
            if info.is_loaded and info.instance is not None
        }

    def get_adapter_plugins(self) -> dict[str, Any]:
        """Get loaded adapter plugin instances.

        Returns:
            Dictionary mapping plugin names to instances.
        """
        return {
            name: info.instance
            for name, info in self.adapter_plugins.items()
            if info.is_loaded and info.instance is not None
        }

    def get_plugin_info(self, name: str) -> PluginInfo | None:
        """Get information about a specific plugin.

        Args:
            name: Plugin name.

        Returns:
            PluginInfo if found, None otherwise.
        """
        for plugins in [
            self.behavior_plugins,
            self.middleware_plugins,
            self.adapter_plugins,
        ]:
            if name in plugins:
                return plugins[name]
        return None

    def unload_plugin(self, name: str) -> bool:
        """Unload a specific plugin.

        Args:
            name: Plugin name to unload.

        Returns:
            True if plugin was unloaded, False if not found.
        """
        for plugins in [
            self.behavior_plugins,
            self.middleware_plugins,
            self.adapter_plugins,
        ]:
            if name in plugins:
                info = plugins[name]
                if info.instance and hasattr(info.instance, "disconnect"):
                    try:
                        info.instance.disconnect()
                    except Exception as e:
                        logger.warning(f"Error disconnecting plugin: {e}")

                info.instance = None
                info.is_loaded = False
                logger.info(f"Unloaded plugin '{name}'")
                return True

        return False

    def unload_all(self) -> None:
        """Unload all loaded plugins."""
        all_plugins = [
            *self.behavior_plugins.values(),
            *self.middleware_plugins.values(),
            *self.adapter_plugins.values(),
        ]

        for info in all_plugins:
            if info.instance and hasattr(info.instance, "disconnect"):
                try:
                    info.instance.disconnect()
                except Exception as e:
                    logger.warning(f"Error disconnecting plugin '{info.name}': {e}")

            info.instance = None
            info.is_loaded = False

        logger.info("All plugins unloaded")
