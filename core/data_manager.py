import uuid
import logging
import datetime
from typing import Dict, List, Optional, Tuple, Any
from PyQt6.QtCore import QObject, pyqtSignal
from sqlalchemy import select, delete, func
from sqlalchemy.orm import Session

from config import MAX_HISTORY_ENTRIES
from core.database import SessionLocal, init_db
from core.models import Profile, Item, PriceHistory

logger = logging.getLogger(__name__)

class DataManager(QObject):
    """
    Manages application data using SQLite + SQLAlchemy.
    Exposes data as plain python dictionaries for UI compatibility.
    """
    profiles_changed = pyqtSignal()
    data_loaded = pyqtSignal()

    def __init__(self, parent: Optional[QObject] = None):
        super().__init__(parent)
        self.active_profile_name: str = ""
        
        # Ensure tables exist
        init_db()
        
        # Load initial state
        self._init_active_profile()
        self.data_loaded.emit()

    def _init_active_profile(self) -> None:
        """Sets the active profile to the first available or creates a default."""
        session = SessionLocal()
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
        finally:
            session.close()

    # --- Profile Management ---

    def get_profile_names(self) -> List[str]:
        session = SessionLocal()
        try:
            stmt = select(Profile.name).order_by(Profile.name)
            return list(session.execute(stmt).scalars().all())
        finally:
            session.close()

    def get_active_profile_data(self) -> Dict[str, List[Dict]]:
        """
        Returns all items for the active profile, separated by category.
        Returns List of Dictionaries for UI consumption.
        """
        session = SessionLocal()
        result = {"components": [], "peripherals": []}
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
        finally:
            session.close()

    def switch_profile(self, new_name: str) -> bool:
        session = SessionLocal()
        try:
            exists = session.execute(
                select(Profile.id).where(Profile.name == new_name)
            ).scalar_one_or_none()
            
            if exists:
                self.active_profile_name = new_name
                return True
            return False
        finally:
            session.close()

    def add_profile(self, name: str) -> Tuple[bool, str]:
        session = SessionLocal()
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
        finally:
            session.close()

    def rename_profile(self, old_name: str, new_name: str) -> Tuple[bool, str]:
        session = SessionLocal()
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
        finally:
            session.close()

    def delete_profile(self, name: str) -> Tuple[bool, str]:
        session = SessionLocal()
        try:
            count = session.execute(select(func.count(Profile.id))).scalar() or 0
            if count <= 1:
                return False, "Cannot delete the last profile."
            
            profile = session.execute(select(Profile).where(Profile.name == name)).scalar_one_or_none()
            if not profile:
                return False, "Profile not found."
            
            session.delete(profile)
            session.commit()
            
            # Switch to another available profile
            self._init_active_profile()
            self.profiles_changed.emit()
            return True, ""
        except Exception as e:
            session.rollback()
            return False, str(e)
        finally:
            session.close()

    def import_profile_data(self, profile_name: str, data: Dict[str, Any]) -> Tuple[bool, str]:
        """
        Imports profile data from a dictionary structure (JSON export).
        Handles creation of items and history.
        """
        session = SessionLocal()
        try:
            # 1. Create or Find Profile (handle name collision by appending copy)
            target_name = profile_name
            counter = 1
            while session.execute(select(Profile).where(Profile.name == target_name)).scalar_one_or_none():
                target_name = f"{profile_name} ({counter})"
                counter += 1
            
            new_profile = Profile(name=target_name)
            session.add(new_profile)
            session.flush() # Get ID

            # 2. Parse Items
            categories = ["components", "peripherals"]
            if isinstance(data, list):
                # Legacy support: if root is list, assume components
                data = {"components": data, "peripherals": []}
            
            for cat in categories:
                items = data.get(cat, [])
                for idx, item_dict in enumerate(items):
                    item_id = item_dict.get('id') or uuid.uuid4().hex
                    current_price = item_dict.get('price', 0)
                    
                    # Determine previous price
                    raw_history = item_dict.get('price_history', [])
                    prev_price = 0
                    if len(raw_history) >= 2:
                        prev_price = raw_history[-2].get('price', 0)

                    item = Item(
                        id=item_id,
                        profile_id=new_profile.id,
                        category=cat,
                        name=item_dict.get('name', 'Imported Item'),
                        link=item_dict.get('link', ''),
                        specs=item_dict.get('specs', ''),
                        image_url=item_dict.get('image_url', ''),
                        quantity=item_dict.get('quantity', 1),
                        current_price=current_price,
                        previous_price=prev_price,
                        order_index=idx
                    )
                    session.add(item)

                    # 3. Parse History
                    for h in raw_history:
                        ph = PriceHistory(
                            item_id=item_id,
                            date=h.get('date', datetime.date.today().isoformat()),
                            price=h.get('price', 0)
                        )
                        session.add(ph)

            session.commit()
            self.active_profile_name = target_name
            self.profiles_changed.emit()
            return True, f"Imported as '{target_name}'"

        except Exception as e:
            session.rollback()
            logger.error(f"Import failed: {e}", exc_info=True)
            return False, str(e)
        finally:
            session.close()

    # --- Item Management ---

    def add_item_to_profile(self, category: str, item_data: Dict) -> None:
        session = SessionLocal()
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
            price = item_data.get('price', 0)
            item_id = item_data.get('id') or uuid.uuid4().hex
            
            new_item = Item(
                id=item_id,
                profile_id=profile.id,
                category=category,
                name=item_data.get('name', 'New Item'),
                link=item_data.get('link', ''),
                specs=item_data.get('specs', ''),
                image_url=item_data.get('image_url', ''),
                quantity=item_data.get('quantity', 1),
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
        finally:
            session.close()

    def update_item_in_profile(self, category: str, index: int, item_data: Dict) -> None:
        target_id = item_data.get('id')
        if not target_id:
            logger.error("Cannot update item without ID")
            return

        session = SessionLocal()
        try:
            item = session.execute(select(Item).where(Item.id == target_id)).scalar_one_or_none()
            if not item:
                return
            
            # Conditionally update fields if present in input dict
            if 'name' in item_data: item.name = item_data['name']
            if 'link' in item_data: item.link = item_data['link']
            if 'specs' in item_data: item.specs = item_data['specs']
            if 'quantity' in item_data: item.quantity = item_data['quantity']
            if 'image_url' in item_data: item.image_url = item_data['image_url']
            
            session.commit()
        except Exception as e:
            session.rollback()
            logger.error(f"Update failed: {e}")
        finally:
            session.close()

    def reorder_items(self, category: str, src_index: int, dst_index: int) -> None:
        """
        Updates the order_index for items when drag-and-drop occurs.
        Fetches items in current DB order, manipulates list, then writes back indices.
        """
        session = SessionLocal()
        try:
            profile = session.execute(
                select(Profile).where(Profile.name == self.active_profile_name)
            ).scalar_one()

            # 1. Fetch all items in current order
            items = session.execute(
                select(Item)
                .where(Item.profile_id == profile.id, Item.category == category)
                .order_by(Item.order_index)
            ).scalars().all()
            
            items_list = list(items)

            # 2. Validate indices
            if not (0 <= src_index < len(items_list)) or not (0 <= dst_index < len(items_list)):
                return

            # 3. Perform the move
            moved_item = items_list.pop(src_index)
            items_list.insert(dst_index, moved_item)

            # 4. Update order_index for all items
            for idx, item in enumerate(items_list):
                item.order_index = idx
            
            session.commit()
        except Exception as e:
            session.rollback()
            logger.error(f"Reorder failed: {e}")
        finally:
            session.close()

    def delete_items_from_profile(self, category: str, indices: List[int]) -> None:
        session = SessionLocal()
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
        finally:
            session.close()

    def find_item(self, item_id: str) -> Tuple[Optional[Dict], Optional[str]]:
        session = SessionLocal()
        try:
            item = session.execute(select(Item).where(Item.id == item_id)).scalar_one_or_none()
            if item:
                return item.to_dict(), item.category
            return None, None
        finally:
            session.close()
            
    def save_data(self) -> None:
        # No-op in SQL version
        pass

    # --- History Management ---

    def get_item_history(self, item_id: str) -> List[Dict[str, Any]]:
        session = SessionLocal()
        try:
            stmt = select(PriceHistory).where(PriceHistory.item_id == item_id).order_by(PriceHistory.date)
            history = session.execute(stmt).scalars().all()
            return [h.to_dict() for h in history]
        finally:
            session.close()

    def update_item_history(self, item_id: str, category: str, new_price: int) -> None:
        session = SessionLocal()
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
        finally:
            session.close()

    def reset_item_history(self, item_id: str, category: str) -> None:
        session = SessionLocal()
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
        finally:
            session.close()