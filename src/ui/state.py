import json
import logging
from pathlib import Path
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)

class StateManager:
    """
    Manages persistent user state (e.g., 'Done' status of items).
    Stores data in data/user_state.json.
    """
    def __init__(self, state_path: str = "data/user_state.json"):
        self.state_path = Path(state_path)
        self.data = self._load_state()

    def _load_state(self) -> Dict[str, Any]:
        if not self.state_path.exists():
            return {"done_items": {}, "settings": {}}
        try:
            with open(self.state_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Failed to load user state: {e}")
            return {"done_items": {}, "settings": {}}

    def _save_state(self):
        try:
            with open(self.state_path, "w", encoding="utf-8") as f:
                json.dump(self.data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"Failed to save user state: {e}")

    def is_done(self, item_id: str) -> bool:
        """Check if an item is marked as done."""
        return self.data.get("done_items", {}).get(str(item_id), False)

    def set_done(self, item_id: str, is_done: bool):
        """Update done status and save."""
        if "done_items" not in self.data:
            self.data["done_items"] = {}
        
        self.data["done_items"][str(item_id)] = is_done
        self._save_state()

    def toggle_done(self, item_id: str) -> bool:
        current = self.is_done(item_id)
        self.set_done(item_id, not current)
        return not current
