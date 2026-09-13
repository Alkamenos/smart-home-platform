"""
State Persistence Module for Smart Home Platform.

This module provides state persistence for FSMs, allowing states to be
saved to a JSON file and restored on platform restart.
"""

import json
from pathlib import Path
from typing import Optional, Tuple


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
    
    def _load_data(self) -> dict:
        """
        Load existing data from the JSON file.
        
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
        Save data to the JSON file.
        
        Args:
            data: The data dictionary to save.
        """
        self._ensure_storage_dir()
        with open(self.storage_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    
    def save_state(self, entity_id: str, state: str, context: dict) -> None:
        """
        Save the FSM state to the storage file.
        
        Args:
            entity_id: The unique identifier of the FSM entity.
            state: The current state name to save.
            context: The context dictionary associated with the state.
        """
        data = self._load_data()
        data[entity_id] = {
            "state": state,
            "context": context
        }
        self._save_data(data)
    
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
