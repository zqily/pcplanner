import json
import uuid
import logging
import shutil
from datetime import datetime
from sqlalchemy.orm import Session
from config import DATA_FILE, DB_FILE
from core.database import SessionLocal, init_db
from core.models import Profile, Item, PriceHistory

logger = logging.getLogger(__name__)

class Migrator:
    """Handles migration from JSON file to SQLite database."""
    
    @staticmethod
    def run_migration() -> None:
        if not DATA_FILE.exists():
            return
            
        if DB_FILE.exists():
            # If DB exists, we assume migration happened or it's a fresh DB install.
            # We won't re-import json unless DB is size 0.
            if DB_FILE.stat().st_size > 0:
                return

        logger.info("Starting migration from JSON to SQLite...")
        
        # Initialize tables
        init_db()
        
        try:
            with open(DATA_FILE, 'r') as f:
                data = json.load(f)
        except (json.JSONDecodeError, IOError) as e:
            logger.error(f"Failed to read legacy data file: {e}")
            return

        session: Session = SessionLocal()
        
        try:
            # 1. Handle Profiles
            profiles_data = data.get("profiles", {})
            active_profile_name = data.get("active_profile", "Default Profile")
            
            # Ensure "Default Profile" exists if dict is empty/malformed
            if not profiles_data:
                profiles_data = {"Default Profile": {"components": [], "peripherals": []}}

            for p_name, p_content in profiles_data.items():
                profile = Profile(name=p_name)
                session.add(profile)
                session.flush() # Flush to get profile.id
                
                # 2. Handle Items
                for category in ["components", "peripherals"]:
                    items_list = p_content.get(category, [])
                    for idx, item_dict in enumerate(items_list):
                        # Basic fields
                        item_id = item_dict.get('id', uuid.uuid4().hex)
                        current_price = item_dict.get('price', 0)
                        
                        # History Logic
                        raw_history = item_dict.get('price_history', [])
                        
                        # Calculate previous price from history if available
                        prev_price = 0
                        if len(raw_history) >= 2:
                            prev_price = raw_history[-2].get('price', 0)
                        
                        item = Item(
                            id=item_id,
                            profile_id=profile.id,
                            category=category,
                            name=item_dict.get('name', 'Unknown'),
                            link=item_dict.get('link', ''),
                            specs=item_dict.get('specs', ''),
                            image_url=item_dict.get('image_url', ''),
                            quantity=item_dict.get('quantity', 1),
                            current_price=current_price,
                            previous_price=prev_price,
                            order_index=idx
                        )
                        session.add(item)
                        
                        # 3. Handle History
                        for h_entry in raw_history:
                            ph = PriceHistory(
                                item_id=item_id,
                                date=h_entry.get('date', datetime.now().date().isoformat()),
                                price=h_entry.get('price', 0)
                            )
                            session.add(ph)

            session.commit()
            logger.info("Migration completed successfully.")
            
            # Backup old file
            backup_path = DATA_FILE.with_suffix('.json.bak')
            shutil.move(str(DATA_FILE), str(backup_path))
            logger.info(f"Renamed legacy data file to {backup_path.name}")

        except Exception as e:
            session.rollback()
            logger.error(f"Migration failed: {e}", exc_info=True)
            # Delete the potentially corrupted DB file
            if DB_FILE.exists():
                DB_FILE.unlink()
        finally:
            session.close()