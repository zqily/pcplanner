import hashlib
import os
import requests
import concurrent.futures
from typing import List, Dict, Optional
from PyQt6.QtCore import QObject, QThread, pyqtSignal

from config import HEADERS, CACHE_DIR, MAX_WORKERS, GITHUB_API_URL, APP_VERSION
from core.scraper import scrape_tokopedia

# --- Scraping Service ---

class ScrapeWorker(QObject):
    finished = pyqtSignal()
    item_scraped = pyqtSignal(str, str, dict, object) # id, category, updates_dict, img_bytes
    error = pyqtSignal(str, str)
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
        except Exception:
            return None

    def _task(self, link: str, session: requests.Session) -> tuple:
        price, img_url = scrape_tokopedia(link, session=session)
        img_bytes = self._get_image_bytes(img_url, session)
        return price, img_url, img_bytes

    def run(self) -> None:
        if not self.tasks:
            self.finished.emit()
            return

        self.scraping_started.emit(len(self.tasks))
        completed = 0

        with requests.Session() as session:
            session.headers.update(HEADERS)
            with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
                futures = {
                    executor.submit(self._task, t['link'], session): t 
                    for t in self.tasks
                }

                for future in concurrent.futures.as_completed(futures):
                    if not self.is_running:
                        break
                    
                    info = futures[future]
                    try:
                        price, img_url, img_bytes = future.result()
                        updates = {}
                        if price is not None: updates['price'] = price
                        if img_url is not None: updates['image_url'] = img_url
                        
                        if updates:
                            self.item_scraped.emit(info['id'], info['category'], updates, img_bytes)
                        else:
                            self.error.emit(info.get('name', 'Unknown'), "Scraping failed")
                    
                    except Exception as e:
                        self.error.emit(info.get('name', 'Unknown'), str(e))
                    finally:
                        completed += 1
                        self.progress_updated.emit(completed)
        
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
            resp = requests.get(GITHUB_API_URL, timeout=10)
            resp.raise_for_status()
            info = resp.json()
            latest = info.get("tag_name", "").lstrip('v')
            current = APP_VERSION.lstrip('v')
            
            if self._compare_versions(latest, current):
                self.update_available.emit(info)
        except Exception:
            pass
        finally:
            self.finished.emit()

    @staticmethod
    def _compare_versions(ver_a: str, ver_b: str) -> bool:
        try:
            return tuple(map(int, ver_a.split('.'))) > tuple(map(int, ver_b.split('.')))
        except ValueError:
            return False