"""
State Persistence Module for Smart Home Platform.

This module provides state persistence for FSMs, allowing states to be
saved to a JSON file and restored on platform restart.
"""

import json
import sys
from pathlib import Path
from typing import Optional, Tuple

# Platform-specific file locking imports
if sys.platform == "win32":
    import msvcrt
else:
    import fcntl


class StatePersistence:
    """
    Persists FSM states to a JSON file.
    
    This class handles saving and loading FSM states to/from a JSON file,
    enabling state recovery after platform restarts.
    
    Attributes:
        storage_path: Path to the JSON file where states are stored.
    """
    
    def __init__(self, storage_path: str = "state.json") -> None:
        """
        Initialize the state persistence manager.
        
        Args:
            storage_path: Path to the JSON file for storing states.
        """
        self.storage_path = Path(storage_path)
        self._ensure_storage_dir()
    
    def _ensure_storage_dir(self) -> None:
        """Ensure the directory for the storage file exists."""
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
    
    def _acquire_lock(self, f):
        """
        Acquire an exclusive lock on the file.
        
        Args:
            f: File object to lock.
        """
        if sys.platform == "win32":
            # Windows: use msvcrt.locking()
            # Lock a large region to cover the entire file
            msvcrt.locking(f.fileno(), msvcrt.LK_LOCK, 1024 * 1024)
        else:
            # Linux/Unix: use fcntl.flock()
            fcntl.flock(f.fileno(), fcntl.LOCK_EX)
    
    def _release_lock(self, f):
        """
        Release the lock on the file.
        
        Args:
            f: File object to unlock.
        """
        if sys.platform == "win32":
            msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1024 * 1024)
        else:
            fcntl.flock(f.fileno(), fcntl.LOCK_UN)
    
    def _load_data(self, lock_file=None) -> dict:
        """
        Load existing data from the JSON file.
        
        Args:
            lock_file: Optional file object that is already locked.
        
        Returns:
            dict: The current data in the storage file, or empty dict if not exists.
        """
        if not self.storage_path.exists():
            return {}
        
        try:
            with open(self.storage_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                return data if isinstance(data, dict) else {}
        except (json.JSONDecodeError, IOError):
            return {}
    
    def _save_data(self, data: dict) -> None:
        """
        Save data to the JSON file using atomic write with file locking.
        
        Uses atomic write pattern: write to temp file, then rename.
        Also uses file locking to prevent race conditions.
        
        Args:
            data: The data dictionary to save.
        """
        self._ensure_storage_dir()
        
        # Use a unique temp file name based on PID and timestamp to avoid conflicts
        import os
        import time
        temp_path = self.storage_path.with_suffix(
            self.storage_path.suffix + f'.tmp.{os.getpid()}.{int(time.time() * 1000000)}'
        )
        
        # Open the main file for locking
        with open(self.storage_path, 'a', encoding='utf-8') as lock_file:
            try:
                # Acquire exclusive lock
                self._acquire_lock(lock_file)
                
                # Write to temporary file first
                with open(temp_path, 'w', encoding='utf-8') as f:
                    json.dump(data, f, indent=2, ensure_ascii=False)
                    f.flush()
                    os.fsync(f.fileno())  # Ensure data is written to disk
                
                # Atomic rename (os.rename is atomic on POSIX systems)
                # On Windows, os.replace is needed if target exists
                if sys.platform == "win32":
                    os.replace(temp_path, self.storage_path)
                else:
                    os.rename(temp_path, self.storage_path)
            finally:
                # Release lock
                self._release_lock(lock_file)
            
            # Clean up temp file if it still exists (in case of error)
            if temp_path.exists():
                try:
                    temp_path.unlink()
                except OSError:
                    pass
    
    def save_state(self, entity_id: str, state: str, context: dict) -> None:
        """
        Save the FSM state to the storage file.
        
        This method acquires an exclusive lock before reading the current state
        and writing the new state to prevent race conditions.
        
        Args:
            entity_id: The unique identifier of the FSM entity.
            state: The current state name to save.
            context: The context dictionary associated with the state.
        """
        import os
        
        self._ensure_storage_dir()
        
        # Use a unique temp file name based on PID and timestamp to avoid conflicts
        temp_path = self.storage_path.with_suffix(
            self.storage_path.suffix + f'.tmp.{os.getpid()}.{int(__import__("time").time() * 1000000)}'
        )
        
        # Open the main file for locking - this lock covers both read and write
        with open(self.storage_path, 'a+', encoding='utf-8') as lock_file:
            try:
                # Acquire exclusive lock BEFORE reading
                self._acquire_lock(lock_file)
                
                # Read current data while holding the lock
                lock_file.seek(0)
                try:
                    content = lock_file.read()
                    if content:
                        data = json.loads(content)
                        if not isinstance(data, dict):
                            data = {}
                    else:
                        data = {}
                except (json.JSONDecodeError, IOError):
                    data = {}
                
                # Update data with new state
                data[entity_id] = {
                    "state": state,
                    "context": context
                }
                
                # Write to temporary file first
                with open(temp_path, 'w', encoding='utf-8') as f:
                    json.dump(data, f, indent=2, ensure_ascii=False)
                    f.flush()
                    os.fsync(f.fileno())  # Ensure data is written to disk
                
                # Atomic rename
                if sys.platform == "win32":
                    os.replace(temp_path, self.storage_path)
                else:
                    os.rename(temp_path, self.storage_path)
            finally:
                # Release lock
                self._release_lock(lock_file)
            
            # Clean up temp file if it still exists (in case of error)
            if temp_path.exists():
                try:
                    temp_path.unlink()
                except OSError:
                    pass
    
    def load_state(self, entity_id: str) -> Optional[Tuple[str, dict]]:
        """
        Load a saved FSM state from the storage file.
        
        Args:
            entity_id: The unique identifier of the FSM entity.
            
        Returns:
            Optional[Tuple[str, dict]]: A tuple of (state, context) if found,
                                        None if no saved state exists.
        """
        data = self._load_data()
        if entity_id not in data:
            return None
        
        entry = data[entity_id]
        state = entry.get("state")
        context = entry.get("context", {})
        
        if state is None:
            return None
        
        return (state, context)
    
    def clear_state(self, entity_id: str) -> None:
        """
        Clear the saved state for an entity.
        
        Args:
            entity_id: The unique identifier of the FSM entity.
        """
        data = self._load_data()
        if entity_id in data:
            del data[entity_id]
            self._save_data(data)
    
    def clear_all(self) -> None:
        """Clear all saved states."""
        if self.storage_path.exists():
            self.storage_path.unlink()
    
    def save_all(self, states: dict) -> None:
        """
        Save all FSM states to the storage file at once.
        
        This method is useful for graceful shutdown when you need to persist
        all current states in a single operation.
        
        Args:
            states: Dictionary mapping entity_id to (state, context) tuples.
        """
        data = {}
        for entity_id, (state, context) in states.items():
            data[entity_id] = {
                "state": state,
                "context": context
            }
        self._save_data(data)
