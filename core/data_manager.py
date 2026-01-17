import uuid
import logging
import datetime
import re
from typing import Dict, List, Optional, Tuple, Any
from PyQt6.QtCore import QObject, pyqtSignal
from sqlalchemy import select, delete, func

from config import MAX_HISTORY_ENTRIES
from core.database import SessionLocal, init_db
from core.models import Profile, Item, PriceHistory

logger = logging.getLogger(__name__)

class DataManager(QObject):
    """
    Manages application data using SQLite + SQLAlchemy.
    Exposes data as plain python dictionaries for UI compatibility.
    Handles sessions robustly using context managers.
    """
    profiles_changed = pyqtSignal()
    data_loaded = pyqtSignal()

    def __init__(self, parent: Optional[QObject] = None):
        super().__init__(parent)
        self.active_profile_name: str = ""
        
        # Ensure tables exist
        try:
            init_db()
        except Exception:
            pass
        
        # Load initial state
        self._init_active_profile()
        self.data_loaded.emit()

    def _init_active_profile(self) -> None:
        """Sets the active profile to the first available or creates a default."""
        with SessionLocal() as session:
            try:
                stmt = select(Profile.name).order_by(Profile.id).limit(1)
                result = session.execute(stmt).scalar()
                
                if result:
                    self.active_profile_name = result
                else:
                    # Create default profile if DB is empty
                    default_profile = Profile(name="Default Profile")
                    session.add(default_profile)
                    session.commit()
                    self.active_profile_name = "Default Profile"
            except Exception as e:
                logger.error(f"Failed to init profile: {e}")

    # --- Helpers for Robustness ---

    def _safe_int(self, value: Any, default: int = 0) -> int:
        """Safely converts any value to int, handling strings with non-numeric chars."""
        if isinstance(value, int):
            return value
        if isinstance(value, float):
            return int(value)
        if not value:
            return default
        try:
            # Remove non-digit characters (e.g., "Rp 5.000" -> "5000")
            clean_str = re.sub(r'[^\d]', '', str(value))
            return int(clean_str) if clean_str else default
        except (ValueError, TypeError):
            return default

    def _sanitize_str(self, value: Any, default: str = "") -> str:
        """Ensures value is a string and not None."""
        if value is None:
            return default
        return str(value).strip()

    # --- Profile Management ---

    def get_profile_names(self) -> List[str]:
        with SessionLocal() as session:
            try:
                stmt = select(Profile.name).order_by(Profile.name)
                return list(session.execute(stmt).scalars().all())
            except Exception as e:
                logger.error(f"Failed to fetch profile names: {e}")
                return []

    def get_active_profile_data(self) -> Dict[str, List[Dict]]:
        """
        Returns all items for the active profile, separated by category.
        Returns List of Dictionaries for UI consumption.
        """
        result = {"components": [], "peripherals": []}
        with SessionLocal() as session:
            try:
                profile = session.execute(
                    select(Profile).where(Profile.name == self.active_profile_name)
                ).scalar_one_or_none()

                if not profile:
                    return result

                # Fetch items ordered by index
                stmt = select(Item).where(Item.profile_id == profile.id).order_by(Item.order_index)
                items = session.execute(stmt).scalars().all()

                for item in items:
                    if item.category in result:
                        result[item.category].append(item.to_dict())
                
                return result
            except Exception as e:
                logger.error(f"Error fetching profile data: {e}")
                return result

    def switch_profile(self, new_name: str) -> bool:
        with SessionLocal() as session:
            try:
                exists = session.execute(
                    select(Profile.id).where(Profile.name == new_name)
                ).scalar_one_or_none()
                
                if exists:
                    self.active_profile_name = new_name
                    return True
                return False
            except Exception as e:
                logger.error(f"Error switching profile: {e}")
                return False

    def add_profile(self, name: str) -> Tuple[bool, str]:
        with SessionLocal() as session:
            try:
                if session.execute(select(Profile).where(Profile.name == name)).scalar_one_or_none():
                    return False, "Profile already exists."
                
                new_profile = Profile(name=name)
                session.add(new_profile)
                session.commit()
                self.active_profile_name = name
                self.profiles_changed.emit()
                return True, ""
            except Exception as e:
                session.rollback()
                return False, str(e)

    def rename_profile(self, old_name: str, new_name: str) -> Tuple[bool, str]:
        with SessionLocal() as session:
            try:
                # Check collision
                if session.execute(select(Profile).where(Profile.name == new_name)).scalar_one_or_none():
                    return False, "Profile name already exists."
                
                profile = session.execute(select(Profile).where(Profile.name == old_name)).scalar_one_or_none()
                if not profile:
                    return False, "Old profile not found."
                
                profile.name = new_name
                session.commit()
                self.active_profile_name = new_name
                self.profiles_changed.emit()
                return True, ""
            except Exception as e:
                session.rollback()
                return False, str(e)

    def delete_profile(self, name: str) -> Tuple[bool, str]:
        with SessionLocal() as session:
            try:
                count = session.execute(select(func.count(Profile.id))).scalar() or 0
                if count <= 1:
                    return False, "Cannot delete the last profile."
                
                profile = session.execute(select(Profile).where(Profile.name == name)).scalar_one_or_none()
                if not profile:
                    return False, "Profile not found."
                
                session.delete(profile)
                session.commit()
            except Exception as e:
                session.rollback()
                return False, str(e)

        # Update local state outside session
        self._init_active_profile()
        self.profiles_changed.emit()
        return True, ""

    def import_profile_data(self, profile_name: str, raw_data: Any) -> Tuple[bool, str]:
        """
        Robustly imports profile data.
        1. Generates FRESH IDs for everything (avoids UNIQUE constraint errors).
        2. Sanitizes input types (handles string-encoded prices, etc.).
        3. Handles legacy (list) vs new (dict) structures.
        """
        with SessionLocal() as session:
            try:
                # --- 1. Resolve Profile Name Collision ---
                target_name = self._sanitize_str(profile_name, "Imported Profile")
                counter = 1
                base_name = target_name
                while session.execute(select(Profile).where(Profile.name == target_name)).scalar_one_or_none():
                    target_name = f"{base_name} ({counter})"
                    counter += 1
                
                new_profile = Profile(name=target_name)
                session.add(new_profile)
                session.flush() # Flush to get new_profile.id

                # --- 2. Normalize Input Structure ---
                # Ensure data_map is {category: [items]}
                data_map = {}
                
                if isinstance(raw_data, list):
                    # Legacy: Root is a list of components
                    data_map = {"components": raw_data, "peripherals": []}
                elif isinstance(raw_data, dict):
                    # Standard: Check keys
                    if "components" in raw_data or "peripherals" in raw_data:
                        data_map = raw_data
                    else:
                        data_map = {
                            "components": raw_data.get("components", []),
                            "peripherals": raw_data.get("peripherals", [])
                        }
                else:
                    return False, "Invalid data format (must be JSON Object or Array)."

                # --- 3. Process Items ---
                valid_categories = ["components", "peripherals"]
                
                for cat in valid_categories:
                    items_list = data_map.get(cat)
                    if not isinstance(items_list, list):
                        continue

                    for idx, item_dict in enumerate(items_list):
                        if not isinstance(item_dict, dict):
                            continue

                        # Generate FRESH ID to prevent IntegrityError
                        new_item_id = uuid.uuid4().hex
                        
                        # Sanitize basic fields
                        name = self._sanitize_str(item_dict.get('name'), "Imported Item")
                        link = self._sanitize_str(item_dict.get('link'))
                        specs = self._sanitize_str(item_dict.get('specs'))
                        img_url = self._sanitize_str(item_dict.get('image_url'))
                        
                        qty = self._safe_int(item_dict.get('quantity'), 1)
                        current_price = self._safe_int(item_dict.get('price'), 0)
                        
                        # Handle History & Previous Price
                        raw_history = item_dict.get('price_history', [])
                        if not isinstance(raw_history, list):
                            raw_history = []
                            
                        # Determine prev price safely
                        prev_price = 0
                        if len(raw_history) >= 2:
                            prev_price = self._safe_int(raw_history[-2].get('price'), 0)
                        elif 'previous_price' in item_dict:
                            # Fallback if history missing but prev_price stored
                            prev_price = self._safe_int(item_dict['previous_price'], 0)

                        item_obj = Item(
                            id=new_item_id,
                            profile_id=new_profile.id,
                            category=cat,
                            name=name,
                            link=link,
                            specs=specs,
                            image_url=img_url,
                            quantity=qty,
                            current_price=current_price,
                            previous_price=prev_price,
                            order_index=idx
                        )
                        session.add(item_obj)

                        # Import History with FRESH ID
                        for h_entry in raw_history:
                            if not isinstance(h_entry, dict): 
                                continue
                            
                            h_date = self._sanitize_str(h_entry.get('date'), datetime.date.today().isoformat())
                            h_price = self._safe_int(h_entry.get('price'), 0)
                            
                            ph = PriceHistory(
                                item_id=new_item_id,
                                date=h_date,
                                price=h_price
                            )
                            session.add(ph)

                session.commit()
            
            except Exception as e:
                session.rollback()
                logger.error(f"Import failed critical: {e}", exc_info=True)
                return False, f"Database Error: {str(e)}"
        
        # Success: Update state
        self.active_profile_name = target_name
        self.profiles_changed.emit()
        return True, f"Successfully imported as '{target_name}'"

    # --- Item Management ---

    def add_item_to_profile(self, category: str, item_data: Dict) -> None:
        with SessionLocal() as session:
            try:
                profile = session.execute(
                    select(Profile).where(Profile.name == self.active_profile_name)
                ).scalar_one_or_none()
                
                if not profile:
                    return

                # Get next order index
                max_idx = session.execute(
                    select(func.max(Item.order_index))
                    .where(Item.profile_id == profile.id)
                    .where(Item.category == category)
                ).scalar()
                new_idx = (max_idx if max_idx is not None else -1) + 1

                # Prepare data
                price = self._safe_int(item_data.get('price'), 0)
                # Generate ID locally if not provided
                item_id = item_data.get('id') or uuid.uuid4().hex
                
                new_item = Item(
                    id=item_id,
                    profile_id=profile.id,
                    category=category,
                    name=self._sanitize_str(item_data.get('name'), 'New Item'),
                    link=self._sanitize_str(item_data.get('link')),
                    specs=self._sanitize_str(item_data.get('specs')),
                    image_url=self._sanitize_str(item_data.get('image_url')),
                    quantity=self._safe_int(item_data.get('quantity'), 1),
                    current_price=price,
                    order_index=new_idx
                )
                session.add(new_item)
                
                # Init history if price exists
                if price > 0:
                    today = datetime.date.today().isoformat()
                    hist = PriceHistory(item_id=item_id, date=today, price=price)
                    session.add(hist)
                
                session.commit()
            except Exception as e:
                logger.error(f"Failed to add item: {e}")
                session.rollback()

    def update_item_in_profile(self, category: str, index: int, item_data: Dict) -> None:
        target_id = item_data.get('id')
        if not target_id:
            logger.error("Cannot update item without ID")
            return

        with SessionLocal() as session:
            try:
                item = session.execute(select(Item).where(Item.id == target_id)).scalar_one_or_none()
                if not item:
                    return
                
                # Conditionally update fields if present in input dict
                if 'name' in item_data: item.name = self._sanitize_str(item_data['name'])
                if 'link' in item_data: item.link = self._sanitize_str(item_data['link'])
                if 'specs' in item_data: item.specs = self._sanitize_str(item_data['specs'])
                if 'quantity' in item_data: item.quantity = self._safe_int(item_data['quantity'])
                if 'image_url' in item_data: item.image_url = self._sanitize_str(item_data['image_url'])
                
                session.commit()
            except Exception as e:
                session.rollback()
                logger.error(f"Update failed: {e}")

    def reorder_items(self, category: str, src_index: int, dst_index: int) -> None:
        """
        Updates the order_index for items when drag-and-drop occurs.
        """
        with SessionLocal() as session:
            try:
                profile = session.execute(
                    select(Profile).where(Profile.name == self.active_profile_name)
                ).scalar_one()

                items = session.execute(
                    select(Item)
                    .where(Item.profile_id == profile.id, Item.category == category)
                    .order_by(Item.order_index)
                ).scalars().all()
                
                items_list = list(items)

                if not (0 <= src_index < len(items_list)) or not (0 <= dst_index < len(items_list)):
                    return

                moved_item = items_list.pop(src_index)
                items_list.insert(dst_index, moved_item)

                for idx, item in enumerate(items_list):
                    item.order_index = idx
                
                session.commit()
            except Exception as e:
                session.rollback()
                logger.error(f"Reorder failed: {e}")

    def delete_items_from_profile(self, category: str, indices: List[int]) -> None:
        with SessionLocal() as session:
            try:
                profile = session.execute(select(Profile).where(Profile.name == self.active_profile_name)).scalar_one()
                items = session.execute(
                    select(Item).where(Item.profile_id == profile.id, Item.category == category).order_by(Item.order_index)
                ).scalars().all()
                
                ids_to_delete = []
                for i in indices:
                    if 0 <= i < len(items):
                        ids_to_delete.append(items[i].id)
                
                if not ids_to_delete:
                    return

                session.execute(delete(Item).where(Item.id.in_(ids_to_delete)))
                session.commit()
            except Exception as e:
                session.rollback()
                logger.error(f"Delete failed: {e}")

    def find_item(self, item_id: str) -> Tuple[Optional[Dict], Optional[str]]:
        with SessionLocal() as session:
            try:
                item = session.execute(select(Item).where(Item.id == item_id)).scalar_one_or_none()
                if item:
                    return item.to_dict(), item.category
                return None, None
            except Exception as e:
                logger.error(f"Find item failed: {e}")
                return None, None
            
    def save_data(self) -> None:
        # No-op in SQL version, everything is committed immediately
        pass

    # --- History Management ---

    def get_item_history(self, item_id: str) -> List[Dict[str, Any]]:
        with SessionLocal() as session:
            try:
                stmt = select(PriceHistory).where(PriceHistory.item_id == item_id).order_by(PriceHistory.date)
                history = session.execute(stmt).scalars().all()
                return [h.to_dict() for h in history]
            except Exception as e:
                logger.error(f"Fetch history failed: {e}")
                return []

    def update_item_history(self, item_id: str, category: str, new_price: int) -> None:
        with SessionLocal() as session:
            try:
                item = session.execute(select(Item).where(Item.id == item_id)).scalar_one_or_none()
                if not item:
                    return

                today = datetime.date.today().isoformat()
                
                last_entry = session.execute(
                    select(PriceHistory)
                    .where(PriceHistory.item_id == item_id)
                    .order_by(PriceHistory.date.desc())
                    .limit(1)
                ).scalar_one_or_none()

                # Update item prices
                if item.current_price != new_price:
                    item.previous_price = item.current_price
                    item.current_price = new_price

                # Update History Table
                if last_entry and last_entry.date == today:
                    last_entry.price = new_price
                else:
                    new_hist = PriceHistory(item_id=item_id, date=today, price=new_price)
                    session.add(new_hist)

                # Pruning
                count = session.execute(
                    select(func.count(PriceHistory.id)).where(PriceHistory.item_id == item_id)
                ).scalar() or 0
                
                if count > MAX_HISTORY_ENTRIES:
                    subquery = (
                        select(PriceHistory.id)
                        .where(PriceHistory.item_id == item_id)
                        .order_by(PriceHistory.date.desc())
                        .limit(MAX_HISTORY_ENTRIES)
                    )
                    session.execute(
                        delete(PriceHistory)
                        .where(PriceHistory.item_id == item_id)
                        .where(PriceHistory.id.not_in(subquery))
                    )

                session.commit()
            except Exception as e:
                session.rollback()
                logger.error(f"Failed to update history: {e}")

    def reset_item_history(self, item_id: str, category: str) -> None:
        with SessionLocal() as session:
            try:
                session.execute(delete(PriceHistory).where(PriceHistory.item_id == item_id))
                
                item = session.execute(select(Item).where(Item.id == item_id)).scalar_one()
                today = datetime.date.today().isoformat()
                
                if item.current_price > 0:
                    ph = PriceHistory(item_id=item_id, date=today, price=item.current_price)
                    session.add(ph)
                
                item.previous_price = 0
                session.commit()
            except Exception as e:
                session.rollback()
                logger.error(f"Failed to reset history: {e}")