import json
import uuid
import logging
import datetime
from typing import Dict, List, Optional, Tuple, Any
from PyQt6.QtCore import QObject, pyqtSignal
from config import DATA_FILE, MAX_HISTORY_ENTRIES

class DataManager(QObject):
    """
    Manages loading, saving, and manipulating application data.
    Handles Price History logic (pruning, updating).
    """
    profiles_changed = pyqtSignal()
    data_loaded = pyqtSignal()

    def __init__(self, parent: Optional[QObject] = None):
        super().__init__(parent)
        self.data: Dict[str, Any] = {}
        self.active_profile_name: str = ""
        self.load_data()

    def load_data(self) -> None:
        try:
            with open(DATA_FILE, 'r') as f:
                loaded_data = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            self._init_default_data()
            return

        if "profiles" in loaded_data and "active_profile" in loaded_data:
            self.data = loaded_data
            self.active_profile_name = loaded_data['active_profile']
            if self.active_profile_name not in self.data["profiles"]:
                if self.data["profiles"]:
                    self.active_profile_name = list(self.data["profiles"].keys())[0]
                else:
                    self._init_default_data()
                    return
        else:
            self._migrate_legacy_data(loaded_data)

        self._normalize_data()
        self.data_loaded.emit()

    def _init_default_data(self) -> None:
        self.data = {
            "profiles": {"Default Profile": {"components": [], "peripherals": []}},
            "active_profile": "Default Profile"
        }
        self.active_profile_name = "Default Profile"

    def _migrate_legacy_data(self, loaded_data: Any) -> None:
        components, peripherals = [], []
        if isinstance(loaded_data, list):
            components = loaded_data
        elif isinstance(loaded_data, dict):
            components = loaded_data.get("components", [])
            peripherals = loaded_data.get("peripherals", [])
        
        self.data = {
            "profiles": {"Default Profile": {"components": components, "peripherals": peripherals}},
            "active_profile": "Default Profile"
        }
        self.active_profile_name = "Default Profile"

    def _normalize_data(self) -> None:
        """Ensures all items have required keys, including price_history."""
        for profile_data in self.data["profiles"].values():
            for items in profile_data.values():
                for item in items:
                    item.setdefault('id', uuid.uuid4().hex)
                    item.setdefault('quantity', 1)
                    item.setdefault('image_url', '')
                    item.setdefault('price', 0)
                    item.setdefault('price_history', [])

    def save_data(self) -> None:
        self.data['active_profile'] = self.active_profile_name
        try:
            with open(DATA_FILE, 'w') as f:
                json.dump(self.data, f, indent=4)
        except IOError as e:
            logging.error(f"Failed to save data: {e}")

    # --- Profile Management ---
    def get_active_profile_data(self) -> Dict[str, List[Dict]]:
        return self.data['profiles'].get(self.active_profile_name, {"components": [], "peripherals": []})

    def get_profile_names(self) -> List[str]:
        return sorted(self.data['profiles'].keys())

    def switch_profile(self, new_name: str) -> bool:
        if new_name and new_name != self.active_profile_name and new_name in self.data['profiles']:
            self.active_profile_name = new_name
            self.save_data()
            return True
        return False

    def add_profile(self, name: str) -> Tuple[bool, str]:
        if name in self.data['profiles']:
            return False, "Profile already exists."
        self.data['profiles'][name] = {"components": [], "peripherals": []}
        self.active_profile_name = name
        self.save_data()
        self.profiles_changed.emit()
        return True, ""

    def rename_profile(self, old_name: str, new_name: str) -> Tuple[bool, str]:
        if new_name in self.data['profiles']:
            return False, "Profile already exists."
        if old_name not in self.data['profiles']:
            return False, "Old profile not found."
            
        self.data['profiles'][new_name] = self.data['profiles'].pop(old_name)
        self.active_profile_name = new_name
        self.save_data()
        self.profiles_changed.emit()
        return True, ""

    def delete_profile(self, name: str) -> Tuple[bool, str]:
        if len(self.data['profiles']) <= 1:
            return False, "Cannot delete the last profile."
        if name in self.data['profiles']:
            del self.data['profiles'][name]
            self.active_profile_name = list(self.data['profiles'].keys())[0]
            self.save_data()
            self.profiles_changed.emit()
            return True, ""
        return False, "Profile not found."

    # --- Item Management ---
    def add_item_to_profile(self, category: str, item_data: Dict) -> None:
        item_data.setdefault('price_history', [])
        # If adding manually with a price, initialize history
        if item_data.get('price', 0) > 0:
            today = datetime.date.today().isoformat()
            item_data['price_history'] = [{'date': today, 'price': item_data['price']}]
            
        self.get_active_profile_data()[category].append(item_data)
        self.save_data()

    def update_item_in_profile(self, category: str, index: int, item_data: Dict) -> None:
        # Preserve sensitive fields not handled by the simple dialog
        existing_item = self.get_active_profile_data()[category][index]
        item_data['id'] = existing_item['id']
        item_data['price'] = existing_item['price']
        item_data['image_url'] = existing_item['image_url']
        item_data['price_history'] = existing_item.get('price_history', [])
        
        self.get_active_profile_data()[category][index] = item_data
        self.save_data()

    def delete_items_from_profile(self, category: str, indices: List[int]) -> None:
        items = self.get_active_profile_data()[category]
        for index in sorted(indices, reverse=True):
            del items[index]
        self.save_data()

    def find_item(self, item_id: str) -> Tuple[Optional[Dict], Optional[str]]:
        for profile_data in self.data['profiles'].values():
            for category, items in profile_data.items():
                for item in items:
                    if item.get('id') == item_id:
                        return item, category
        return None, None

    # --- History Management ---
    def update_item_history(self, item_id: str, category: str, new_price: int) -> None:
        item, _ = self.find_item(item_id)
        if not item:
            return

        today = datetime.date.today().isoformat()
        history = item.setdefault('price_history', [])

        # Update main price
        item['price'] = new_price

        # Update History Logic
        if not history:
            history.append({'date': today, 'price': new_price})
        else:
            last_entry = history[-1]
            if last_entry['date'] == today:
                # Update today's entry
                last_entry['price'] = new_price
            else:
                # Append new day
                history.append({'date': today, 'price': new_price})

        # Prune History
        if len(history) > MAX_HISTORY_ENTRIES:
            # Remove oldest entries to keep list size at MAX
            item['price_history'] = history[-MAX_HISTORY_ENTRIES:]

        self.save_data()

    def reset_item_history(self, item_id: str, category: str) -> None:
        item, _ = self.find_item(item_id)
        if item:
            item['price_history'] = []
            # Keep current price as the only history entry to start fresh
            if item.get('price', 0) > 0:
                today = datetime.date.today().isoformat()
                item['price_history'] = [{'date': today, 'price': item['price']}]
            self.save_data()