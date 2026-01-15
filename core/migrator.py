import json
import logging
import uuid
import os
from datetime import datetime

from config import DATA_FILE
from core.database import SessionLocal, init_db
from core.models import Profile, Item, PriceHistory

logger = logging.getLogger(__name__)

class Migrator:
    @staticmethod
    def run_migration():
        """
        Checks if the legacy data.json exists and migrates it to SQLite 
        if the database is currently empty.
        """
        if not DATA_FILE.exists():
            return

        logger.info("Legacy data.json found. Initializing migration...")
        
        # Ensure DB tables exist
        init_db()

        with SessionLocal() as session:
            # Check if we already have data to prevent duplicate migration
            existing_profiles = session.query(Profile).count()
            if existing_profiles > 0:
                logger.info("Database already contains data. Skipping migration to avoid duplicates.")
                return

            try:
                with open(DATA_FILE, 'r', encoding='utf-8') as f:
                    legacy_data = json.load(f)

                # The old format was likely a Dict[profile_name, Dict[category, List[items]]]
                for profile_name, categories in legacy_data.items():
                    logger.info(f"Migrating profile: {profile_name}")
                    
                    new_profile = Profile(name=profile_name)
                    session.add(new_profile)
                    session.flush() # Get the profile ID

                    for cat_name, items in categories.items():
                        if cat_name not in ["components", "peripherals"]:
                            continue

                        for idx, item_data in enumerate(items):
                            # Generate a unique ID if the old one doesn't exist
                            item_id = item_data.get('id') or uuid.uuid4().hex
                            
                            # Create Item
                            new_item = Item(
                                id=item_id,
                                profile_id=new_profile.id,
                                category=cat_name,
                                name=item_data.get('name', 'Unknown Item'),
                                link=item_data.get('link', ''),
                                specs=item_data.get('specs', ''),
                                image_url=item_data.get('image_url', ''),
                                quantity=item_data.get('quantity', 1),
                                current_price=item_data.get('price', 0),
                                previous_price=0,
                                order_index=idx
                            )
                            session.add(new_item)

                            # Migrate History
                            history = item_data.get('price_history', [])
                            for h_entry in history:
                                # Old format usually: {"date": "YYYY-MM-DD", "price": 100}
                                ph = PriceHistory(
                                    item_id=item_id,
                                    date=h_entry.get('date', datetime.now().strftime("%Y-%m-%d")),
                                    price=h_entry.get('price', 0)
                                )
                                session.add(ph)
                            
                            # Set previous price for UI delta if history exists
                            if len(history) >= 2:
                                new_item.previous_price = history[-2].get('price', 0)

                session.commit()
                logger.info("Migration successful.")

                # Rename old file to prevent re-migration
                backup_path = DATA_FILE.with_suffix('.json.bak')
                try:
                    os.rename(DATA_FILE, backup_path)
                    logger.info(f"Legacy data file renamed to {backup_path.name}")
                except OSError as e:
                    logger.warning(f"Could not rename legacy file: {e}")

            except Exception as e:
                session.rollback()
                logger.error(f"Migration failed: {e}", exc_info=True)
                raise