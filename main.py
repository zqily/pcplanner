# main.py
import sys
import os
import json
import hashlib
import requests
import concurrent.futures
import uuid
import time
import webbrowser
from functools import partial

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QTableWidget, QTableWidgetItem,
    QPushButton, QVBoxLayout, QWidget, QHBoxLayout, QDialog,
    QLineEdit, QTextEdit, QFormLayout, QDialogButtonBox,
    QMessageBox, QLabel, QHeaderView, QAbstractItemView, QTabWidget,
    QSpinBox, QProgressBar, QComboBox, QInputDialog, QFileDialog
)
from PyQt6.QtGui import QPixmap, QDropEvent
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QObject

from scraper import scrape_tokopedia, HEADERS

# --- Configuration ---
DATA_FILE = 'data.json'
CACHE_DIR = 'image_cache'
WINDOW_WIDTH = 1200
WINDOW_HEIGHT = 800
IMAGE_COLUMN_WIDTH = 150
IMAGE_ROW_HEIGHT = 150
MAX_WORKERS = 10

# --- Update Configuration ---
APP_VERSION = "v1.2.0"
GITHUB_API_URL = "https://api.github.com/repos/zqily/pcplanner/releases/latest"


ID_ROLE = Qt.ItemDataRole.UserRole + 1

# --- DataManager Class ---
class DataManager(QObject):
    """
    Manages all data and profile-related logic for the application.
    """
    profiles_changed = pyqtSignal()
    data_loaded = pyqtSignal()

    def __init__(self, data_file, parent=None):
        super().__init__(parent)
        self.data_file = data_file
        self.data = {}
        self.active_profile_name = ""
        self.load_data()

    def load_data(self):
        try:
            with open(self.data_file, 'r') as f:
                loaded_data = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            self.data = {"profiles": {"Default Profile": {"components": [], "peripherals": []}}, "active_profile": "Default Profile"}
            self.active_profile_name = "Default Profile"
            return

        if "profiles" in loaded_data and "active_profile" in loaded_data:
            self.data = loaded_data
            self.active_profile_name = loaded_data['active_profile']
            if self.active_profile_name not in self.data["profiles"]:
                if self.data["profiles"]:
                    self.active_profile_name = list(self.data["profiles"].keys())[0]
                else:
                    self.data["profiles"]["Default Profile"] = {"components": [], "peripherals": []}
                    self.active_profile_name = "Default Profile"
                self.data["active_profile"] = self.active_profile_name
        else:
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

        for profile_data in self.data["profiles"].values():
            for items in profile_data.values():
                for item in items:
                    item.setdefault('id', uuid.uuid4().hex)
                    item.setdefault('quantity', 1)
                    item.setdefault('image_url', '')
                    item.setdefault('price', 0)
        self.data_loaded.emit()

    def save_data(self):
        self.data['active_profile'] = self.active_profile_name
        with open(self.data_file, 'w') as f:
            json.dump(self.data, f, indent=4)

    def get_active_profile_data(self):
        return self.data['profiles'].get(self.active_profile_name, {"components": [], "peripherals": []})

    def get_profile_names(self):
        return sorted(self.data['profiles'].keys())

    def switch_profile(self, new_profile_name):
        if new_profile_name and new_profile_name != self.active_profile_name and new_profile_name in self.data['profiles']:
            self.active_profile_name = new_profile_name
            self.save_data()
            return True
        return False

    def add_profile(self, name):
        if name in self.data['profiles']:
            return False, "A profile with this name already exists."
        self.data['profiles'][name] = {"components": [], "peripherals": []}
        self.active_profile_name = name
        self.save_data()
        self.profiles_changed.emit()
        return True, ""

    def rename_profile(self, old_name, new_name):
        if new_name in self.data['profiles']:
            return False, "A profile with this name already exists."
        self.data['profiles'][new_name] = self.data['profiles'].pop(old_name)
        self.active_profile_name = new_name
        self.save_data()
        self.profiles_changed.emit()
        return True, ""

    def delete_profile(self, name):
        if len(self.data['profiles']) <= 1:
            return False, "You cannot delete the last profile."
        del self.data['profiles'][name]
        self.active_profile_name = list(self.data['profiles'].keys())[0]
        self.save_data()
        self.profiles_changed.emit()
        return True, ""
    
    def add_item_to_profile(self, category, item_data):
        self.get_active_profile_data()[category].append(item_data)
        self.save_data()

    def update_item_in_profile(self, category, index, item_data):
        self.get_active_profile_data()[category][index].update(item_data)
        self.save_data()

    def delete_items_from_profile(self, category, indices):
        items = self.get_active_profile_data()[category]
        for index in sorted(indices, reverse=True):
            del items[index]
        self.save_data()

    def find_item(self, item_id):
        for profile_data in self.data['profiles'].values():
            for category, items in profile_data.items():
                for item in items:
                    if item.get('id') == item_id:
                        return item, category
        return None, None

# --- ScrapeManager Class ---
class ScrapeManager(QObject):
    """
    Manages the creation, execution, and cancellation of scraping threads.
    """
    scraping_started = pyqtSignal(int)
    scraping_finished = pyqtSignal(bool) # bool for was_cancelled
    item_scraped = pyqtSignal(str, str, dict, object)
    progress_updated = pyqtSignal(int)
    error_occurred = pyqtSignal(str, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.thread = None
        self.worker = None

    def is_running(self):
        return self.thread is not None and self.thread.isRunning()

    def start(self, tasks):
        if self.is_running() or not tasks:
            if not tasks: self.scraping_finished.emit(False)
            return

        self.thread = QThread()
        self.worker = ScrapeWorker(tasks)
        self.worker.moveToThread(self.thread)

        # Connect worker signals to manager signals
        self.worker.finished.connect(self.on_worker_finished)
        self.worker.item_scraped.connect(self.item_scraped)
        self.worker.error.connect(self.error_occurred)
        self.worker.scraping_started.connect(self.scraping_started)
        self.worker.progress_updated.connect(self.progress_updated)

        self.thread.started.connect(self.worker.run)
        self.thread.start()

    def cancel(self):
        if self.worker:
            self.worker.stop()

    def on_worker_finished(self):
        was_cancelled = not (self.worker and self.worker.is_running)
        self.scraping_finished.emit(was_cancelled)

        if self.thread:
            self.thread.quit()
            self.thread.wait()

        self.worker = None
        self.thread = None

# --- Update Helper Function ---
def is_new_version_available(latest_version_str, current_version_str):
    def parse(v_str):
        if isinstance(v_str, str) and v_str.startswith('v'):
            v_str = v_str[1:]
        try:
            return tuple(map(int, v_str.split('.')))
        except (ValueError, TypeError, AttributeError):
            return (0,)
    latest_tuple = parse(latest_version_str)
    current_tuple = parse(current_version_str)
    return latest_tuple > current_tuple


# --- Worker for Update Checking ---
class UpdateCheckWorker(QObject):
    update_available = pyqtSignal(dict)
    finished = pyqtSignal()

    def get_latest_release_info(self):
        try:
            response = requests.get(GITHUB_API_URL, timeout=10)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            print(f"Error fetching release information: {e}")
            return None

    def run(self):
        release_info = self.get_latest_release_info()
        if release_info:
            latest_version = release_info.get("tag_name")
            if is_new_version_available(latest_version, APP_VERSION):
                self.update_available.emit(release_info)
        self.finished.emit()


# --- Worker for Threading ---
class ScrapeWorker(QObject):
    finished = pyqtSignal()
    item_scraped = pyqtSignal(str, str, dict, object)
    error = pyqtSignal(str, str)
    scraping_started = pyqtSignal(int)
    progress_updated = pyqtSignal(int)

    def __init__(self, tasks):
        super().__init__()
        self.tasks = tasks
        self.is_running = True

    def _get_cache_path(self, url):
        if not url: return None
        hashed_url = hashlib.sha256(url.encode('utf-8')).hexdigest()
        return os.path.join(CACHE_DIR, f"{hashed_url}.jpg")

    def _get_image_bytes(self, image_url, session):
        if not image_url or not self.is_running: return None
        cache_path = self._get_cache_path(image_url)
        if os.path.exists(cache_path):
            try:
                with open(cache_path, 'rb') as f:
                    return f.read()
            except IOError as e:
                print(f"Error reading from cache {cache_path}: {e}")

        max_retries = 3
        retry_delay = 2
        img_resp = None
        for attempt in range(max_retries):
            if not self.is_running: return None
            try:
                img_resp = session.get(image_url, timeout=10)
                img_resp.raise_for_status()
                break
            except requests.exceptions.RequestException as e:
                print(f"Failed to download image {image_url} on attempt {attempt + 1}/{max_retries}: {e}")
                if attempt < max_retries - 1:
                    time.sleep(retry_delay)
                else:
                    return None
        if not img_resp: return None
        image_bytes = img_resp.content
        try:
            with open(cache_path, 'wb') as f:
                f.write(image_bytes)
        except IOError as e:
            print(f"Error writing to cache {cache_path}: {e}")
        return image_bytes

    def _task(self, link, session):
        price, new_image_url = scrape_tokopedia(link, session=session)
        image_bytes = self._get_image_bytes(new_image_url, session)
        return price, new_image_url, image_bytes

    def run(self):
        if not self.tasks:
            self.finished.emit()
            return
        self.scraping_started.emit(len(self.tasks))
        completed_count = 0
        with requests.Session() as session:
            session.headers.update(HEADERS)
            with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
                future_to_info = {executor.submit(self._task, task['link'], session): task for task in self.tasks}
                for future in concurrent.futures.as_completed(future_to_info):
                    if not self.is_running:
                        for f in future_to_info: f.cancel()
                        break
                    info = future_to_info[future]
                    item_id = info['id']
                    category = info['category']
                    item_name = info.get('name', 'Unknown')
                    try:
                        price, image_url, image_bytes = future.result()
                        updated_data = {}
                        if price is not None: updated_data['price'] = price
                        if image_url is not None: updated_data['image_url'] = image_url
                        if not updated_data: self.error.emit(item_name, f"Failed to scrape data for link: {info.get('link')}")
                        self.item_scraped.emit(item_id, category, updated_data, image_bytes)
                    except concurrent.futures.CancelledError:
                        print("A scrape task was cancelled.")
                    except Exception as e:
                        self.error.emit(item_name, f"An error occurred: {e}")
                    finally:
                        completed_count += 1
                        self.progress_updated.emit(completed_count)
        self.finished.emit()

    def stop(self):
        self.is_running = False

# --- Add/Edit Component Dialog ---
class ComponentDialog(QDialog):
    def __init__(self, component=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Add/Edit Item")
        self.name_input = QLineEdit()
        self.link_input = QLineEdit()
        self.specs_input = QTextEdit()
        self.quantity_input = QSpinBox()
        self.quantity_input.setMinimum(1)
        self.quantity_input.setMaximum(999)
        if component:
            self.name_input.setText(component.get('name', ''))
            self.link_input.setText(component.get('link', ''))
            self.specs_input.setText(component.get('specs', ''))
            self.quantity_input.setValue(component.get('quantity', 1))
        else:
            self.quantity_input.setValue(1)
        form_layout = QFormLayout()
        form_layout.addRow("Name:", self.name_input)
        form_layout.addRow("Quantity:", self.quantity_input)
        form_layout.addRow("Tokopedia Link:", self.link_input)
        form_layout.addRow("Specs:", self.specs_input)
        self.button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.button_box.accepted.connect(self.accept)
        self.button_box.rejected.connect(self.reject)
        main_layout = QVBoxLayout()
        main_layout.addLayout(form_layout)
        main_layout.addWidget(self.button_box)
        self.setLayout(main_layout)

    def get_data(self):
        return {
            "name": self.name_input.text(),
            "link": self.link_input.text(),
            "specs": self.specs_input.toPlainText(),
            "quantity": self.quantity_input.value()
        }

# --- Draggable Table for Reordering ---
class DraggableTableWidget(QTableWidget):
    """A QTableWidget subclass that supports row drag-and-drop to reorder items."""
    rows_reordered = pyqtSignal(int, int)  # from_row, to_row

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setDragDropOverwriteMode(False)

    def dropEvent(self, event: QDropEvent):
        if not event.isAccepted() and event.source() == self:
            source_row = self.selectionModel().currentIndex().row()
            dest_row = self.indexAt(event.position().toPoint()).row()

            if dest_row < 0:
                dest_row = self.rowCount() -1
            
            # Allow the default drop event to visually move the row
            super().dropEvent(event)
            
            # After the visual move, the original source_row might be at a new index.
            # We need to find the item that was originally at source_row and see where it landed.
            # However, emitting the original and destination indices before the move is simpler.
            self.rows_reordered.emit(source_row, dest_row)
            event.accept()

# --- Main Application Window ---
class PCPlanner(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"PC Planner")
        self.setGeometry(100, 100, WINDOW_WIDTH, WINDOW_HEIGHT)
        
        self.data_manager = DataManager(DATA_FILE)
        self.scrape_manager = ScrapeManager()
        
        self.category_keys = ["components", "peripherals"]
        self.update_thread = None
        self._ensure_cache_dir()

        # This map will hold {'category': {'item_id': row_index}}
        self.item_id_to_row_map = {}
        
        self.initUI()
        self.connect_signals()

        self.populate_profile_combo()
        self.populate_tables()
        self.check_for_updates()

    def _ensure_cache_dir(self):
        if not os.path.exists(CACHE_DIR):
            os.makedirs(CACHE_DIR)

    def _get_cache_path(self, url):
        if not url: return None
        hashed_url = hashlib.sha256(url.encode('utf-8')).hexdigest()
        return os.path.join(CACHE_DIR, f"{hashed_url}.jpg")

    def initUI(self):
        self.tab_widget = QTabWidget()
        self.tables = {}
        self.total_labels = {}
        category_titles = {"components": "PC Components", "peripherals": "Peripherals"}
        for key in self.category_keys:
            title = category_titles.get(key, key.capitalize())
            # Use the new DraggableTableWidget
            table = DraggableTableWidget(0, 6)
            table.setHorizontalHeaderLabels(["Image", "Name", "Price (IDR)", "Qty", "Link", "Specs"])
            
            # Other properties remain the same
            table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
            table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
            table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
            table.setColumnWidth(0, IMAGE_COLUMN_WIDTH)
            table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
            table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
            table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeMode.Stretch)
            table.verticalHeader().setDefaultSectionSize(IMAGE_ROW_HEIGHT)
            self.tables[key] = table
            
            total_label = QLabel("Total Price: Rp 0")
            total_label.setStyleSheet("font-size: 16px; font-weight: bold;")
            self.total_labels[key] = total_label
            
            tab_layout = QVBoxLayout()
            tab_layout.addWidget(table)
            tab_layout.addWidget(total_label, alignment=Qt.AlignmentFlag.AlignRight)
            tab_container = QWidget()
            tab_container.setLayout(tab_layout)
            self.tab_widget.addTab(tab_container, title)

        self.add_button = QPushButton("Add Item")
        self.edit_button = QPushButton("Edit Item")
        self.delete_button = QPushButton("Delete Item")
        self.refresh_all_button = QPushButton("Refresh All")
        self.refresh_selected_button = QPushButton("Refresh Selected")
        self.cancel_button = QPushButton("Cancel Refresh")
        self.cancel_button.setVisible(False)
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        self.progress_bar.setTextVisible(True)
        self.grand_total_label = QLabel("Grand Total: Rp 0")
        self.grand_total_label.setStyleSheet("font-size: 20px; font-weight: bold; padding: 10px;")
        self.grand_total_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.profile_combo = QComboBox()
        self.new_profile_button = QPushButton("New")
        self.rename_profile_button = QPushButton("Rename")
        self.delete_profile_button = QPushButton("Delete")
        self.import_profile_button = QPushButton("Import")
        self.export_profile_button = QPushButton("Export")
        
        profile_layout = QHBoxLayout()
        profile_layout.addWidget(QLabel("Profile:"))
        profile_layout.addWidget(self.profile_combo, 1)
        profile_layout.addWidget(self.new_profile_button)
        profile_layout.addWidget(self.rename_profile_button)
        profile_layout.addWidget(self.delete_profile_button)
        profile_layout.addStretch()
        profile_layout.addWidget(self.import_profile_button)
        profile_layout.addWidget(self.export_profile_button)
        
        button_layout = QHBoxLayout()
        button_layout.addWidget(self.add_button)
        button_layout.addWidget(self.edit_button)
        button_layout.addWidget(self.delete_button)
        button_layout.addStretch()
        button_layout.addWidget(self.refresh_selected_button)
        button_layout.addWidget(self.refresh_all_button)
        button_layout.addWidget(self.cancel_button)
        
        main_layout = QVBoxLayout()
        main_layout.addLayout(profile_layout)
        main_layout.addLayout(button_layout)
        main_layout.addWidget(self.progress_bar)
        main_layout.addWidget(self.tab_widget)
        main_layout.addWidget(self.grand_total_label)
        
        container = QWidget()
        container.setLayout(main_layout)
        self.setCentralWidget(container)

    def connect_signals(self):
        self.add_button.clicked.connect(self.add_item)
        self.edit_button.clicked.connect(self.edit_item)
        self.delete_button.clicked.connect(self.delete_item)
        self.refresh_all_button.clicked.connect(self.refresh_all)
        self.refresh_selected_button.clicked.connect(self.refresh_selected)
        self.cancel_button.clicked.connect(self.scrape_manager.cancel)
        self.profile_combo.activated.connect(self.switch_profile)
        self.new_profile_button.clicked.connect(self.add_profile)
        self.rename_profile_button.clicked.connect(self.rename_profile)
        self.delete_profile_button.clicked.connect(self.delete_profile)
        self.import_profile_button.clicked.connect(self.import_profile)
        self.export_profile_button.clicked.connect(self.export_profile)
        self.data_manager.profiles_changed.connect(self.handle_profiles_changed)
        self.scrape_manager.scraping_started.connect(self.on_scraping_started)
        self.scrape_manager.progress_updated.connect(self.on_progress_updated)
        self.scrape_manager.item_scraped.connect(self.on_item_scraped)
        self.scrape_manager.error_occurred.connect(self.show_scrape_error)
        self.scrape_manager.scraping_finished.connect(self.on_refresh_finished)

        # Connect the custom signal for each table
        for category, table in self.tables.items():
            table.rows_reordered.connect(partial(self.handle_row_reorder, category))

    def handle_row_reorder(self, category, source_row, dest_row):
        """Update the data model when rows are reordered in the UI."""
        # Get the list of items for the specific category
        items = self.data_manager.get_active_profile_data()[category]
        
        # Move the item in the list
        moved_item = items.pop(source_row)
        if dest_row > source_row:
             items.insert(dest_row, moved_item)
        else:
             items.insert(dest_row, moved_item)

        # Save the new order and refresh the table to ensure data integrity
        self.data_manager.save_data()
        self.populate_tables()

    def set_scraping_state(self, is_scraping):
        self.refresh_all_button.setVisible(not is_scraping)
        self.refresh_selected_button.setVisible(not is_scraping)
        self.cancel_button.setVisible(is_scraping)
        self.progress_bar.setVisible(is_scraping)
        if not is_scraping:
            self.progress_bar.setValue(0)

    def handle_profiles_changed(self):
        self.populate_profile_combo()
        self.populate_tables()

    def populate_profile_combo(self):
        self.profile_combo.blockSignals(True)
        self.profile_combo.clear()
        profiles = self.data_manager.get_profile_names()
        self.profile_combo.addItems(profiles)
        if self.data_manager.active_profile_name in profiles:
            self.profile_combo.setCurrentText(self.data_manager.active_profile_name)
        self.profile_combo.blockSignals(False)
        self.delete_profile_button.setEnabled(len(profiles) > 1)
    
    def switch_profile(self):
        new_profile_name = self.profile_combo.currentText()
        if self.data_manager.switch_profile(new_profile_name):
            self.populate_tables()
            
    def add_profile(self):
        text, ok = QInputDialog.getText(self, 'New Profile', 'Enter new profile name:')
        if ok and text:
            success, message = self.data_manager.add_profile(text)
            if not success:
                QMessageBox.warning(self, "Error", message)

    def rename_profile(self):
        old_name = self.data_manager.active_profile_name
        if not old_name: return
        text, ok = QInputDialog.getText(self, 'Rename Profile', 'Enter new name:', text=old_name)
        if ok and text and text != old_name:
            success, message = self.data_manager.rename_profile(old_name, text)
            if not success:
                QMessageBox.warning(self, "Error", message)

    def delete_profile(self):
        profile_to_delete = self.data_manager.active_profile_name
        reply = QMessageBox.question(self, "Confirm Delete", f"Are you sure you want to delete '{profile_to_delete}'?",
                                     QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
        if reply == QMessageBox.StandardButton.Yes:
            success, message = self.data_manager.delete_profile(profile_to_delete)
            if not success:
                QMessageBox.warning(self, "Cannot Delete", message)

    def export_profile(self):
        profile_name = self.data_manager.active_profile_name
        if not profile_name:
            QMessageBox.warning(self, "Export Error", "No active profile.")
            return

        export_payload = {"profile_name": profile_name, "data": self.data_manager.get_active_profile_data()}
        suggested_filename = f"profile_{profile_name.replace(' ', '_')}.json"
        filePath, _ = QFileDialog.getSaveFileName(self, "Export Profile", suggested_filename, "JSON Files (*.json)")

        if filePath:
            try:
                with open(filePath, 'w') as f:
                    json.dump(export_payload, f, indent=4)
                QMessageBox.information(self, "Export Successful", f"Profile '{profile_name}' exported.")
            except Exception as e:
                QMessageBox.critical(self, "Export Error", f"Error exporting: {e}")

    def import_profile(self):
        filePath, _ = QFileDialog.getOpenFileName(self, "Import Profile", "", "JSON Files (*.json)")
        if not filePath: return

        try:
            with open(filePath, 'r') as f: imported_content = json.load(f)
        except Exception as e:
            QMessageBox.critical(self, "Import Error", f"Error reading file: {e}")
            return

        if not isinstance(imported_content, dict) or 'profile_name' not in imported_content or 'data' not in imported_content:
            QMessageBox.warning(self, "Import Failed", "Invalid JSON structure.")
            return
        
        base_name = imported_content.get('profile_name', 'Imported_Profile')
        profile_data = imported_content['data']

        for category in ['components', 'peripherals']:
            for item in profile_data.get(category, []):
                item['id'] = uuid.uuid4().hex
                item.setdefault('quantity', 1)
        
        success, message = self.data_manager.add_profile(base_name)
        if success:
            self.data_manager.data['profiles'][base_name] = profile_data
            self.data_manager.switch_profile(base_name)
            self.data_manager.save_data()
            self.handle_profiles_changed()
            QMessageBox.information(self, "Import Successful", f"Profile '{base_name}' imported.")
        else:
             QMessageBox.warning(self, "Import Failed", message)

    def populate_tables(self):
        # Reset the map before repopulating
        self.item_id_to_row_map = {key: {} for key in self.category_keys}
        
        active_profile_data = self.data_manager.get_active_profile_data()
        for category, items in active_profile_data.items():
            table = self.tables.get(category)
            if not table: continue
            
            table.setRowCount(0)
            for item in items:
                row_position = table.rowCount()
                table.insertRow(row_position)
                
                # Add the new item's ID and row to the map
                item_id = item.get('id')
                if item_id:
                    self.item_id_to_row_map[category][item_id] = row_position

                price, quantity = item.get('price', 0), item.get('quantity', 1)
                
                self._update_row_image(category, row_position, item.get('image_url'))
                
                name_item = QTableWidgetItem(item.get('name', 'N/A'))
                name_item.setData(ID_ROLE, item_id)
                table.setItem(row_position, 1, name_item)

                price_str = f"{price:,.0f}"
                if quantity > 1:
                    price_str += f"\n({(price * quantity):,.0f})"
                
                price_item = QTableWidgetItem(price_str)
                price_item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                table.setItem(row_position, 2, price_item)
                
                qty_item = QTableWidgetItem(str(quantity))
                qty_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                table.setItem(row_position, 3, qty_item)

                # --- CLICKABLE LINK IMPLEMENTATION ---
                link = item.get('link', '')
                link_label = QLabel()
                link_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
                if "tokopedia.com" in link:
                    link_label.setText(f"<a href='{link}'>View on Tokopedia</a>")
                    link_label.setOpenExternalLinks(True)
                else:
                    link_label.setText("N/A")
                table.setCellWidget(row_position, 4, link_label)
                # --- END OF CHANGE ---

                table.setItem(row_position, 5, QTableWidgetItem(item.get('specs', '')))
        self.update_totals()


    def _update_row_image(self, category, row, image_url=None, image_bytes=None):
        table = self.tables.get(category)
        if not table or row >= table.rowCount(): return
        img_label = QLabel("No Image")
        img_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        pixmap = QPixmap()
        loaded = False
        if image_bytes and pixmap.loadFromData(image_bytes):
            loaded = True
        elif image_url:
            cache_path = self._get_cache_path(image_url)
            if cache_path and os.path.exists(cache_path) and pixmap.load(cache_path):
                loaded = True
        if loaded and not pixmap.isNull():
            img_label.setPixmap(pixmap.scaled(IMAGE_COLUMN_WIDTH, IMAGE_ROW_HEIGHT, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        table.setCellWidget(row, 0, img_label)

    def update_totals(self):
        grand_total = 0
        for category, items in self.data_manager.get_active_profile_data().items():
            category_total = sum(c.get('price', 0) * c.get('quantity', 1) for c in items)
            grand_total += category_total
            if category in self.total_labels:
                self.total_labels[category].setText(f"Total Price: Rp {category_total:,.0f}")
        self.grand_total_label.setText(f"Grand Total: Rp {grand_total:,.0f}")

    def get_current_category_info(self):
        category_key = self.category_keys[self.tab_widget.currentIndex()]
        return category_key, self.tables[category_key]

    def add_item(self):
        if self.scrape_manager.is_running():
            QMessageBox.warning(self, "Busy", "Wait for the current refresh to finish.")
            return

        category_key, _ = self.get_current_category_info()
        dialog = ComponentDialog(parent=self)
        if dialog.exec():
            new_data = dialog.get_data()
            if "tokopedia.com" not in new_data['link']:
                QMessageBox.warning(self, "Invalid Link", "Please provide a valid Tokopedia link.")
                return
            
            new_data['id'] = uuid.uuid4().hex
            self.data_manager.add_item_to_profile(category_key, new_data)
            self.populate_tables()
            
            self.start_refresh(items_to_process=[{'item': new_data, 'category': category_key}])

    def edit_item(self):
        category_key, active_table = self.get_current_category_info()
        selected_rows = active_table.selectionModel().selectedRows()
        if not selected_rows:
            QMessageBox.warning(self, "Selection Error", "Please select an item to edit.")
            return
        
        row_index = selected_rows[0].row()
        item_to_edit = self.data_manager.get_active_profile_data()[category_key][row_index]
        dialog = ComponentDialog(component=item_to_edit, parent=self)
        if dialog.exec():
            self.data_manager.update_item_in_profile(category_key, row_index, dialog.get_data())
            self.populate_tables()

    def delete_item(self):
        category_key, active_table = self.get_current_category_info()
        selected_rows = active_table.selectionModel().selectedRows()
        if not selected_rows:
            QMessageBox.warning(self, "Selection Error", "Please select item(s) to delete.")
            return
        
        rows_to_delete = sorted([index.row() for index in selected_rows], reverse=True)
        reply = QMessageBox.question(self, "Confirm Delete", f"Are you sure you want to delete {len(rows_to_delete)} item(s)?",
                                     QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)

        if reply == QMessageBox.StandardButton.Yes:
            self.data_manager.delete_items_from_profile(category_key, rows_to_delete)
            self.populate_tables()
    
    def refresh_all(self):
        self.start_refresh()

    def refresh_selected(self):
        category_key, active_table = self.get_current_category_info()
        selected_rows = {index.row() for index in active_table.selectionModel().selectedRows()}
        if not selected_rows:
            QMessageBox.warning(self, "Selection Error", "Please select item(s) to refresh.")
            return
        
        items_to_process = []
        for row_index in sorted(list(selected_rows)):
            item = self.data_manager.get_active_profile_data()[category_key][row_index]
            items_to_process.append({'item': item, 'category': category_key})
        
        self.start_refresh(items_to_process)

    def start_refresh(self, items_to_process=None):
        if self.scrape_manager.is_running(): return

        tasks = []
        if items_to_process is not None:
            items_scope = items_to_process
        else:
            items_scope = [
                {'item': item, 'category': category}
                for category, item_list in self.data_manager.get_active_profile_data().items()
                for item in item_list
            ]

        for info in items_scope:
            link = info['item'].get('link', '')
            if "tokopedia.com" in link:
                tasks.append({'id': info['item']['id'], 'category': info['category'], 'link': link, 'name': info['item'].get('name', 'Unknown')})

        self.scrape_manager.start(tasks)

    def on_scraping_started(self, total):
        self.set_scraping_state(True)
        self.progress_bar.setMaximum(total)
        self.progress_bar.setFormat(f"Scraping... %p% ({total} items)")

    def on_progress_updated(self, count):
        self.progress_bar.setValue(count)

    def on_item_scraped(self, item_id, category, updated_data, image_bytes):
        target_item, _ = self.data_manager.find_item(item_id)
        if not target_item: return
        target_item.update(updated_data)

        table = self.tables.get(category)
        if not table: return

        # Use the map for a direct lookup instead of looping
        row = self.item_id_to_row_map.get(category, {}).get(item_id)

        if row is not None:
            price, quantity = target_item.get('price', 0), target_item.get('quantity', 1)
            price_str = f"{price:,.0f}"
            if quantity > 1:
                price_str += f"\n({(price * quantity):,.0f})"
            
            # Ensure a QTableWidgetItem exists before setting text
            price_item = table.item(row, 2)
            if price_item:
                price_item.setText(price_str)
            else:
                new_price_item = QTableWidgetItem(price_str)
                new_price_item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                table.setItem(row, 2, new_price_item)

            self._update_row_image(category, row, image_bytes=image_bytes)

        self.update_totals()


    def show_scrape_error(self, name, message):
        QMessageBox.warning(self, f"Scraping Error: {name}", message)

    def on_refresh_finished(self, was_cancelled):
        self.set_scraping_state(False)
        self.data_manager.save_data()

    def check_for_updates(self):
        self.update_thread = QThread()
        self.update_worker = UpdateCheckWorker()
        self.update_worker.moveToThread(self.update_thread)
        self.update_worker.update_available.connect(self.show_update_dialog)
        self.update_worker.finished.connect(self.update_thread.quit)
        self.update_worker.finished.connect(self.update_worker.deleteLater)
        self.update_thread.finished.connect(self.update_thread.deleteLater)
        self.update_thread.started.connect(self.update_worker.run)
        self.update_thread.start()

    def show_update_dialog(self, release_info):
        latest_version = release_info.get("tag_name", "N/A")
        release_url = release_info.get("html_url")
        if not release_url: return

        message = (f"A new version is available!\n\n"
                   f"Current: {APP_VERSION}\n"
                   f"Latest: {latest_version}\n\n"
                   f"Open download page?")
        
        reply = QMessageBox.information(self, "Update Available", message, 
                                        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                        QMessageBox.StandardButton.Yes)

        if reply == QMessageBox.StandardButton.Yes:
            webbrowser.open(release_url)

    def closeEvent(self, event):
        if self.scrape_manager.is_running():
            self.scrape_manager.cancel()
            if self.scrape_manager.thread and self.scrape_manager.thread.isRunning():
                self.scrape_manager.thread.wait(1000)
        event.accept()

if __name__ == '__main__':
    app = QApplication(sys.argv)
    window = PCPlanner()
    window.show()
    sys.exit(app.exec())
