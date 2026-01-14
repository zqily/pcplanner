import hashlib
import os
import requests
import concurrent.futures
import logging
from typing import List, Dict, Optional
from PyQt6.QtCore import QObject, QThread, pyqtSignal

from config import HEADERS, CACHE_DIR, MAX_WORKERS, GITHUB_API_URL, APP_VERSION
from core.scraper import scrape_tokopedia

# Get module logger
logger = logging.getLogger(__name__)

# --- Scraping Service ---

class ScrapeWorker(QObject):
    finished = pyqtSignal()
    item_scraped = pyqtSignal(str, str, dict, object) # id, category, updates_dict, img_bytes
    error = pyqtSignal(str, str) # Item Name, Error Message
    scraping_started = pyqtSignal(int)
    progress_updated = pyqtSignal(int)

    def __init__(self, tasks: List[Dict]):
        super().__init__()
        self.tasks = tasks
        self.is_running = True

    def _get_cache_path(self, url: str) -> str:
        hashed = hashlib.sha256(url.encode('utf-8')).hexdigest()
        return str(CACHE_DIR / f"{hashed}.jpg")

    def _get_image_bytes(self, image_url: Optional[str], session: requests.Session) -> Optional[bytes]:
        if not image_url or not self.is_running:
            return None
        
        cache_path = self._get_cache_path(image_url)
        if os.path.exists(cache_path):
            try:
                with open(cache_path, 'rb') as f:
                    return f.read()
            except IOError:
                pass

        try:
            resp = session.get(image_url, timeout=10)
            resp.raise_for_status()
            data = resp.content
            with open(cache_path, 'wb') as f:
                f.write(data)
            return data
        except Exception as e:
            logger.warning(f"Failed to download image from {image_url}: {e}")
            return None

    def _task(self, link: str, session: requests.Session) -> tuple:
        # This runs inside the thread pool
        try:
            price, img_url = scrape_tokopedia(link, session=session)
            img_bytes = self._get_image_bytes(img_url, session)
            return price, img_url, img_bytes
        except Exception:
            # Re-raise to be caught in run() via future.result()
            raise

    def run(self) -> None:
        if not self.tasks:
            self.finished.emit()
            return

        logger.info(f"Starting batch scrape for {len(self.tasks)} items.")
        self.scraping_started.emit(len(self.tasks))
        completed = 0

        with requests.Session() as session:
            session.headers.update(HEADERS)
            with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
                # Map future to task info
                futures = {
                    executor.submit(self._task, t['link'], session): t 
                    for t in self.tasks
                }

                for future in concurrent.futures.as_completed(futures):
                    if not self.is_running:
                        logger.info("Scraping cancelled by user.")
                        break
                    
                    info = futures[future]
                    item_name = info.get('name', 'Unknown Item')
                    
                    try:
                        price, img_url, img_bytes = future.result()
                        
                        updates = {}
                        if price is not None: updates['price'] = price
                        if img_url is not None: updates['image_url'] = img_url
                        
                        if updates:
                            logger.info(f"Successfully scraped '{item_name}' (ID: {info['id']})")
                            self.item_scraped.emit(info['id'], info['category'], updates, img_bytes)
                        else:
                            # Scraping ran but returned no data (parsers failed)
                            msg = "Parser returned no data. Website structure may have changed."
                            logger.warning(f"Partial failure for '{item_name}': {msg}")
                            self.error.emit(item_name, msg)
                    
                    except Exception as e:
                        # Catch network errors or crashes in _task
                        logger.error(f"Critical error scraping '{item_name}': {e}", exc_info=True)
                        self.error.emit(item_name, str(e))
                    finally:
                        completed += 1
                        self.progress_updated.emit(completed)
        
        logger.info("Batch scrape finished.")
        self.finished.emit()

    def stop(self) -> None:
        self.is_running = False


class ScrapeManager(QObject):
    scraping_started = pyqtSignal(int)
    scraping_finished = pyqtSignal(bool)
    item_scraped = pyqtSignal(str, str, dict, object)
    progress_updated = pyqtSignal(int)
    error_occurred = pyqtSignal(str, str)

    def __init__(self, parent: Optional[QObject] = None):
        super().__init__(parent)
        self.worker_thread: Optional[QThread] = None
        self.worker: Optional[ScrapeWorker] = None

    def is_running(self) -> bool:
        return self.worker_thread is not None and self.worker_thread.isRunning()

    def start(self, tasks: List[Dict]) -> None:
        if self.is_running(): return

        self.worker_thread = QThread()
        self.worker = ScrapeWorker(tasks)
        self.worker.moveToThread(self.worker_thread)

        self.worker.finished.connect(self._on_finished)
        self.worker.item_scraped.connect(self.item_scraped)
        self.worker.error.connect(self.error_occurred)
        self.worker.scraping_started.connect(self.scraping_started)
        self.worker.progress_updated.connect(self.progress_updated)
        
        self.worker_thread.started.connect(self.worker.run)
        self.worker_thread.start()

    def cancel(self) -> None:
        if self.worker:
            self.worker.stop()

    def _on_finished(self) -> None:
        was_cancelled = False
        if self.worker:
            was_cancelled = not self.worker.is_running
        
        self.scraping_finished.emit(was_cancelled)
        if self.worker_thread:
            self.worker_thread.quit()
            self.worker_thread.wait()
        self.worker = None
        self.worker_thread = None

# --- Update Service ---

class UpdateCheckWorker(QObject):
    update_available = pyqtSignal(dict)
    finished = pyqtSignal()

    def run(self) -> None:
        try:
            logger.info("Checking for updates...")
            resp = requests.get(GITHUB_API_URL, timeout=10)
            resp.raise_for_status()
            info = resp.json()
            latest = info.get("tag_name", "").lstrip('v')
            current = APP_VERSION.lstrip('v')
            
            if self._compare_versions(latest, current):
                logger.info(f"Update available: {latest}")
                self.update_available.emit(info)
            else:
                logger.info("App is up to date.")
        except Exception as e:
            logger.warning(f"Update check failed: {e}")
        finally:
            self.finished.emit()

    @staticmethod
    def _compare_versions(ver_a: str, ver_b: str) -> bool:
        try:
            return tuple(map(int, ver_a.split('.'))) > tuple(map(int, ver_b.split('.')))
        except ValueError:
            return False