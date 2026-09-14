"""
ConfigWatcher - Hot reload service for YAML configuration files.

This module uses watchdog to monitor changes in instances/ and features/ directories,
and automatically reloads FSM definitions when YAML files are modified.

Usage:
    watcher = ConfigWatcher(loader, factory, engine)
    watcher.start()
    
    # Or via CLI:
    python cli.py watch
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional

from loguru import logger
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler, FileModifiedEvent, FileCreatedEvent, FileDeletedEvent

if TYPE_CHECKING:
    from smart_home.core.loader import Loader
    from smart_home.core.fsm_factory import FSMFactory
    from smart_home.core.fsm import FSMEngine, FSMDefinition
    from smart_home.core.models.manifest import Manifest


class YAMLFileHandler(FileSystemEventHandler):
    """Handler for YAML file system events."""
    
    def __init__(self, callback: callable):
        self._callback = callback
        self._debounce_sec: float = 0.5
        self._last_modified: dict[str, float] = {}
    
    def _should_process(self, path: str) -> bool:
        """Check if the event should be processed (debounce)."""
        now = time.time()
        last = self._last_modified.get(path, 0)
        if now - last < self._debounce_sec:
            return False
        self._last_modified[path] = now
        return True
    
    def on_modified(self, event):
        """Handle file modification events."""
        if isinstance(event, FileModifiedEvent) and event.src_path.endswith(('.yaml', '.yml')):
            if self._should_process(event.src_path):
                logger.info(f"YAML file modified: {event.src_path}")
                self._callback(event.src_path)
    
    def on_created(self, event):
        """Handle file creation events."""
        if isinstance(event, FileCreatedEvent) and event.src_path.endswith(('.yaml', '.yml')):
            if self._should_process(event.src_path):
                logger.info(f"YAML file created: {event.src_path}")
                self._callback(event.src_path)
    
    def on_deleted(self, event):
        """Handle file deletion events."""
        if isinstance(event, FileDeletedEvent) and event.src_path.endswith(('.yaml', '.yml')):
            if self._should_process(event.src_path):
                logger.info(f"YAML file deleted: {event.src_path}")
                self._callback(event.src_path)


class ConfigWatcher:
    """
    Service for monitoring YAML configuration files and hot-reloading FSM definitions.
    
    This class uses watchdog to monitor changes in:
    - instances/*/manifest.yaml - Instance manifests
    - features/*.yaml - Feature templates
    
    When a change is detected:
    1. Reload the manifest or feature template
    2. Determine which FSMs are affected
    3. Stop old FSMs
    4. Create and register new FSMs
    
    Attributes:
        loader: Loader instance for loading YAML files
        factory: FSMFactory instance for creating FSM definitions
        engine: FSMEngine instance for managing FSM state
        observer: Watchdog Observer instance
    """
    
    def __init__(
        self,
        loader: 'Loader',
        factory: 'FSMFactory',
        engine: 'FSMEngine',
        manifest_path: str = "instances/leonids_house/manifest.yaml",
        features_dir: str = "features",
        instances_dir: str = "instances",
    ) -> None:
        """
        Initialize the ConfigWatcher.
        
        Args:
            loader: Loader instance for loading YAML files
            factory: FSMFactory instance for creating FSM definitions
            engine: FSMEngine instance for managing FSM state
            manifest_path: Path to the main manifest file
            features_dir: Path to the features directory
            instances_dir: Path to the instances directory
        """
        self._loader = loader
        self._factory = factory
        self._engine = engine
        self._manifest_path = Path(manifest_path)
        self._features_dir = Path(features_dir)
        self._instances_dir = Path(instances_dir)
        self._current_manifest: Optional['Manifest'] = None
        
        self._observer = Observer()
        self._running = False
        
        # Setup handlers
        self._setup_handlers()
    
    def _setup_handlers(self) -> None:
        """Setup watchdog handlers for monitored directories."""
        # Handler for features directory
        features_handler = YAMLFileHandler(self._on_yaml_changed)
        self._observer.schedule(features_handler, str(self._features_dir), recursive=False)
        logger.info(f"Watching features directory: {self._features_dir}")
        
        # Handler for instances directory
        instances_handler = YAMLFileHandler(self._on_yaml_changed)
        self._observer.schedule(instances_handler, str(self._instances_dir), recursive=True)
        logger.info(f"Watching instances directory: {self._instances_dir}")
    
    def start(self) -> None:
        """Start the watchdog observer."""
        if self._running:
            logger.warning("ConfigWatcher already running")
            return
        
        self._running = True
        self._observer.start()
        logger.info("ConfigWatcher started")
    
    def stop(self) -> None:
        """Stop the watchdog observer."""
        self._running = False
        self._observer.stop()
        self._observer.join()
        logger.info("ConfigWatcher stopped")
    
    def _on_yaml_changed(self, path: str) -> None:
        """
        Handle YAML file changes.
        
        When a YAML file is modified:
        1. Reload the manifest if it's a manifest file
        2. Determine which FSMs are affected
        3. Stop old FSMs
        4. Create and register new FSMs
        
        Args:
            path: Path to the modified YAML file
        """
        logger.info(f"Processing YAML change: {path}")
        
        try:
            path_obj = Path(path)
            
            # Check if it's a manifest file
            if self._is_manifest_file(path_obj):
                self._reload_manifest(path_obj)
            elif self._is_feature_file(path_obj):
                self._reload_feature(path_obj)
            else:
                logger.debug(f"Ignoring non-config YAML file: {path}")
                
        except Exception as e:
            logger.error(f"Error processing YAML change: {e}")
    
    def _is_manifest_file(self, path: Path) -> bool:
        """Check if the path is a manifest file."""
        # Manifest files are in instances/*/manifest.yaml
        return (
            path.parent.name != "" and 
            path.parent.parent == self._instances_dir and
            path.name == "manifest.yaml"
        ) or (
            self._manifest_path.resolve() == path.resolve()
        )
    
    def _is_feature_file(self, path: Path) -> bool:
        """Check if the path is a feature template file."""
        return path.parent.resolve() == self._features_dir.resolve() and path.suffix in ('.yaml', '.yml')
    
    def _reload_manifest(self, path: Path) -> None:
        """
        Reload manifest and update FSMs.
        
        Args:
            path: Path to the manifest file
        """
        logger.info(f"Reloading manifest: {path}")
        
        try:
            # Load new manifest
            from smart_home.core.models.manifest import load_manifest
            new_manifest = load_manifest(str(path))
            
            # Store reference
            self._current_manifest = new_manifest
            
            # Get list of device IDs from new manifest
            new_device_ids = {device.id for device in new_manifest.devices}
            
            # Get list of current FSM entity IDs
            current_fsm_ids = set(self._engine.get_all_states().keys())
            
            # Find FSMs that need to be removed (devices no longer in manifest)
            # This is a simplified approach - in production you'd want more sophisticated tracking
            fsm_defs_to_remove = []
            for fsm_id in current_fsm_ids:
                # Check if this FSM belongs to a device still in the manifest
                belongs_to_valid_device = any(
                    fsm_id.startswith(device_id) for device_id in new_device_ids
                )
                if not belongs_to_valid_device:
                    fsm_defs_to_remove.append(fsm_id)
            
            # Remove old FSMs that are no longer needed
            for fsm_id in fsm_defs_to_remove:
                logger.info(f"Unregistering FSM: {fsm_id}")
                self._engine.unregister(fsm_id)
            
            # Recreate all FSMs from the new manifest
            # In production, you'd want to be more selective about which FSMs to recreate
            logger.info("Recreating FSMs from updated manifest...")
            
            # Clear template cache to force reload
            self._factory._template_cache.clear()
            
            # Create new FSM definitions
            new_definitions = self._factory.create_from_manifest(new_manifest)
            
            # Register new FSMs
            for definition in new_definitions:
                logger.info(f"Registering FSM: {definition.entity_id}")
                self._engine.register_definition(definition, restore_state=False)
            
            logger.info(f"Manifest reloaded successfully. Created {len(new_definitions)} FSMs")
            
        except Exception as e:
            logger.error(f"Failed to reload manifest: {e}")
            raise
    
    def _reload_feature(self, path: Path) -> None:
        """
        Reload feature template and update affected FSMs.
        
        Args:
            path: Path to the feature YAML file
        """
        feature_name = path.stem  # filename without extension
        logger.info(f"Reloading feature template: {feature_name}")
        
        try:
            # Clear the template from cache
            if feature_name in self._factory._template_cache:
                del self._factory._template_cache[feature_name]
                logger.info(f"Cleared template cache for: {feature_name}")
            
            # If we have a manifest, recreate FSMs that use this template
            if self._current_manifest is not None:
                logger.info("Recreating FSMs that use updated template...")
                
                # Find devices using this template
                affected_devices = []
                for device in self._current_manifest.devices:
                    for behavior in device.behaviors:
                        if behavior.template == feature_name:
                            affected_devices.append((device.id, behavior))
                
                if affected_devices:
                    logger.info(f"Found {len(affected_devices)} behaviors using template '{feature_name}'")
                    
                    # Recreate FSMs for affected devices
                    for device_id, behavior in affected_devices:
                        try:
                            # First, unregister old FSMs for this device/behavior
                            # Find existing FSM entity IDs that match this device
                            current_fsm_ids = set(self._engine.get_all_states().keys())
                            for fsm_id in current_fsm_ids:
                                if fsm_id.startswith(device_id):
                                    logger.info(f"Unregistering old FSM: {fsm_id}")
                                    self._engine.unregister(fsm_id)
                            
                            # Create and register new FSMs
                            definitions = self._factory.create_from_behavior(device_id, behavior)
                            for definition in definitions:
                                logger.info(f"Re-registering FSM: {definition.entity_id}")
                                self._engine.register_definition(definition, restore_state=False)
                        except Exception as e:
                            logger.error(f"Failed to recreate FSM for {device_id}: {e}")
                else:
                    logger.debug(f"No devices currently using template '{feature_name}'")
            
            logger.info(f"Feature template '{feature_name}' reloaded successfully")
            
        except Exception as e:
            logger.error(f"Failed to reload feature template: {e}")
            raise
    
    @property
    def is_running(self) -> bool:
        """Check if the watcher is running."""
        return self._running


def create_watcher(
    loader: 'Loader',
    factory: 'FSMFactory',
    engine: 'FSMEngine',
    manifest_path: str = "instances/leonids_house/manifest.yaml",
    features_dir: str = "features",
    instances_dir: str = "instances",
) -> 'ConfigWatcher':
    """
    Create and return a ConfigWatcher instance.
    
    Args:
        loader: Loader instance
        factory: FSMFactory instance
        engine: FSMEngine instance
        manifest_path: Path to manifest file
        features_dir: Path to features directory
        instances_dir: Path to instances directory
    
    Returns:
        ConfigWatcher instance
    """
    return ConfigWatcher(
        loader=loader,
        factory=factory,
        engine=engine,
        manifest_path=manifest_path,
        features_dir=features_dir,
        instances_dir=instances_dir,
    )
