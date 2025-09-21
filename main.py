# main.py
import sys
import os
import json
import hashlib
import requests
import concurrent.futures
import uuid
import time

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QTableWidget, QTableWidgetItem,
    QPushButton, QVBoxLayout, QWidget, QHBoxLayout, QDialog,
    QLineEdit, QTextEdit, QFormLayout, QDialogButtonBox,
    QMessageBox, QLabel, QHeaderView, QAbstractItemView, QTabWidget,
    QSpinBox, QProgressBar, QComboBox, QInputDialog
)
from PyQt6.QtGui import QPixmap
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

ID_ROLE = Qt.ItemDataRole.UserRole + 1

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

        # Add retry logic for image download
        max_retries = 3
        retry_delay = 2  # seconds
        img_resp = None

        for attempt in range(max_retries):
            if not self.is_running: return None  # Check for cancellation within the loop
            try:
                img_resp = session.get(image_url, timeout=10)
                img_resp.raise_for_status()
                break  # Success
            except requests.exceptions.RequestException as e:
                print(f"Failed to download image {image_url} on attempt {attempt + 1}/{max_retries}: {e}")
                if attempt < max_retries - 1:
                    time.sleep(retry_delay)
                else:
                    print(f"All retries failed for image {image_url}.")
                    return None

        if not img_resp:
            return None  # Safeguard

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
                future_to_info = {
                    executor.submit(self._task, task['link'], session): task
                    for task in self.tasks
                }
                for future in concurrent.futures.as_completed(future_to_info):
                    if not self.is_running:
                        for f in future_to_info:
                            f.cancel()
                        break
                    info = future_to_info[future]
                    item_id = info['id']
                    category = info['category']
                    item_name = info.get('name', 'Unknown')
                    try:
                        price, image_url, image_bytes = future.result()
                        updated_data = {}
                        if price is not None:
                            updated_data['price'] = price
                        if image_url is not None:
                            updated_data['image_url'] = image_url
                        if not updated_data:
                            self.error.emit(item_name, f"Failed to scrape data for link: {info.get('link')}")
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
        print("Stopping scrape worker...")
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

# --- Main Application Window ---
class PCPlanner(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("PC Build Planner")
        self.setGeometry(100, 100, WINDOW_WIDTH, WINDOW_HEIGHT)
        self.data = {}
        self.active_profile_name = ""
        self.category_keys = ["components", "peripherals"]
        self.is_refreshing = False
        self.worker = None
        self.thread = None
        self._ensure_cache_dir()
        self.load_data()
        self.initUI()

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
            table = QTableWidget()
            table.setColumnCount(6)
            table.setHorizontalHeaderLabels(["Image", "Name", "Price (IDR)", "Qty", "Link", "Specs"])
            table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
            table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
            table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
            table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
            table.setColumnWidth(0, IMAGE_COLUMN_WIDTH)
            table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
            table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
            table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
            table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
            table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeMode.Stretch)
            table.verticalHeader().setDefaultSectionSize(IMAGE_ROW_HEIGHT)
            total_label = QLabel("Total Price: Rp 0")
            total_label.setStyleSheet("font-size: 16px; font-weight: bold;")
            self.tables[key] = table
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

        # --- Profile Management ---
        self.profile_combo = QComboBox()
        self.new_profile_button = QPushButton("New")
        self.rename_profile_button = QPushButton("Rename")
        self.delete_profile_button = QPushButton("Delete")

        profile_layout = QHBoxLayout()
        profile_layout.addWidget(QLabel("Profile:"))
        profile_layout.addWidget(self.profile_combo, 1)
        profile_layout.addWidget(self.new_profile_button)
        profile_layout.addWidget(self.rename_profile_button)
        profile_layout.addWidget(self.delete_profile_button)

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

        self.add_button.clicked.connect(self.add_item)
        self.edit_button.clicked.connect(self.edit_item)
        self.delete_button.clicked.connect(self.delete_item)
        self.refresh_all_button.clicked.connect(self.refresh_all)
        self.refresh_selected_button.clicked.connect(self.refresh_selected)
        self.cancel_button.clicked.connect(self.cancel_refresh)
        
        # Profile connections
        self.profile_combo.activated.connect(self.switch_profile)
        self.new_profile_button.clicked.connect(self.add_profile)
        self.rename_profile_button.clicked.connect(self.rename_profile)
        self.delete_profile_button.clicked.connect(self.delete_profile)
        
        self.populate_profile_combo()
        self.populate_tables()

    def set_scraping_state(self, is_scraping):
        self.is_refreshing = is_scraping
        self.refresh_all_button.setVisible(not is_scraping)
        self.refresh_selected_button.setVisible(not is_scraping)
        self.cancel_button.setVisible(is_scraping)
        self.progress_bar.setVisible(is_scraping)
        if not is_scraping:
            self.progress_bar.setValue(0)

    def load_data(self):
        try:
            with open(DATA_FILE, 'r') as f:
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
            # Migrate from old format
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

        # Sanitize data for all profiles
        for profile_data in self.data["profiles"].values():
            for items in profile_data.values():
                for item in items:
                    item.setdefault('id', uuid.uuid4().hex)
                    item.setdefault('quantity', 1)
                    item.setdefault('image_url', '')
                    item.setdefault('price', 0)

    def save_data(self):
        self.data['active_profile'] = self.active_profile_name
        with open(DATA_FILE, 'w') as f:
            json.dump(self.data, f, indent=4)

    def get_active_profile_data(self):
        return self.data['profiles'].get(self.active_profile_name, {"components": [], "peripherals": []})

    def populate_profile_combo(self):
        self.profile_combo.blockSignals(True)
        self.profile_combo.clear()
        profiles = sorted(self.data['profiles'].keys())
        self.profile_combo.addItems(profiles)
        if self.active_profile_name in profiles:
            self.profile_combo.setCurrentText(self.active_profile_name)
        self.profile_combo.blockSignals(False)
        self.delete_profile_button.setEnabled(len(profiles) > 1)
    
    def switch_profile(self):
        new_profile_name = self.profile_combo.currentText()
        if new_profile_name and new_profile_name != self.active_profile_name:
            self.active_profile_name = new_profile_name
            self.save_data()
            self.populate_tables()
            
    def add_profile(self):
        text, ok = QInputDialog.getText(self, 'New Profile', 'Enter new profile name:')
        if ok and text:
            if text in self.data['profiles']:
                QMessageBox.warning(self, "Error", "A profile with this name already exists.")
                return
            self.data['profiles'][text] = {"components": [], "peripherals": []}
            self.active_profile_name = text
            self.populate_profile_combo()
            self.populate_tables()
            self.save_data()

    def rename_profile(self):
        old_name = self.active_profile_name
        if not old_name: return
        text, ok = QInputDialog.getText(self, 'Rename Profile', 'Enter new name for profile:', text=old_name)
        if ok and text and text != old_name:
            if text in self.data['profiles']:
                QMessageBox.warning(self, "Error", "A profile with this name already exists.")
                return
            self.data['profiles'][text] = self.data['profiles'].pop(old_name)
            self.active_profile_name = text
            self.populate_profile_combo()
            self.save_data()

    def delete_profile(self):
        if len(self.data['profiles']) <= 1:
            QMessageBox.warning(self, "Cannot Delete", "You cannot delete the last profile.")
            return
        profile_to_delete = self.active_profile_name
        reply = QMessageBox.question(self, "Confirm Delete", f"Are you sure you want to delete the profile '{profile_to_delete}'?",
                                     QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                     QMessageBox.StandardButton.No)
        if reply == QMessageBox.StandardButton.Yes:
            del self.data['profiles'][profile_to_delete]
            self.active_profile_name = list(self.data['profiles'].keys())[0]
            self.populate_profile_combo()
            self.populate_tables()
            self.save_data()
            
    def populate_tables(self):
        active_profile_data = self.get_active_profile_data()
        for category, items in active_profile_data.items():
            table = self.tables.get(category)
            if not table: continue
            table.setRowCount(0)
            for item in items:
                row_position = table.rowCount()
                table.insertRow(row_position)
                price = item.get('price', 0)
                quantity = item.get('quantity', 1)
                self._update_row_image(category, row_position, item.get('image_url'))
                name_item = QTableWidgetItem(item.get('name', 'N/A'))
                name_item.setData(ID_ROLE, item.get('id'))
                table.setItem(row_position, 1, name_item)
                price_str = f"{price:,.0f}"
                if quantity > 1:
                    total_price = price * quantity
                    total_price_str = f"({total_price:,.0f})"
                    combined_price_text = f"{price_str}\n{total_price_str}"
                else:
                    combined_price_text = price_str
                price_item = QTableWidgetItem(combined_price_text)
                price_item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                table.setItem(row_position, 2, price_item)
                quantity_item = QTableWidgetItem(str(quantity))
                quantity_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                table.setItem(row_position, 3, quantity_item)
                table.setItem(row_position, 4, QTableWidgetItem(item.get('link', 'N/A')))
                table.setItem(row_position, 5, QTableWidgetItem(item.get('specs', '')))
        self.update_totals()

    def _update_row_image(self, category, row, image_url=None, image_bytes=None):
        table = self.tables.get(category)
        if not table or row >= table.rowCount(): return
        img_label = QLabel()
        img_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        pixmap_loaded = False
        if image_bytes:
            pixmap = QPixmap()
            pixmap.loadFromData(image_bytes)
            if not pixmap.isNull():
                img_label.setPixmap(pixmap.scaled(IMAGE_COLUMN_WIDTH, IMAGE_ROW_HEIGHT, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
                pixmap_loaded = True
        elif image_url:
            cache_path = self._get_cache_path(image_url)
            if cache_path and os.path.exists(cache_path):
                pixmap = QPixmap(cache_path)
                if not pixmap.isNull():
                    img_label.setPixmap(pixmap.scaled(IMAGE_COLUMN_WIDTH, IMAGE_ROW_HEIGHT, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
                    pixmap_loaded = True
        if not pixmap_loaded:
            img_label.setText("No Image")
        table.setCellWidget(row, 0, img_label)

    def update_totals(self):
        grand_total = 0
        active_profile_data = self.get_active_profile_data()
        for category, items in active_profile_data.items():
            category_total = sum(c.get('price', 0) * c.get('quantity', 1) for c in items)
            grand_total += category_total
            if category in self.total_labels:
                self.total_labels[category].setText(f"Total Price: Rp {category_total:,.0f}")
        self.grand_total_label.setText(f"Grand Total: Rp {grand_total:,.0f}")

    def get_current_category_info(self):
        current_index = self.tab_widget.currentIndex()
        category_key = self.category_keys[current_index]
        active_table = self.tables[category_key]
        return category_key, active_table

    def add_item(self):
        if self.is_refreshing:
            QMessageBox.warning(self, "Busy", "Please wait for the current refresh operation to finish.")
            return

        category_key, _ = self.get_current_category_info()
        dialog = ComponentDialog(parent=self)
        if dialog.exec():
            new_data = dialog.get_data()
            if "tokopedia.com" not in new_data['link']:
                 if "shopee" in new_data['link']:
                     QMessageBox.warning(self, "Unsupported Link", "Shopee links are not supported.")
                 else:
                    QMessageBox.warning(self, "Invalid Link", "Please provide a valid Tokopedia link.")
                 return
            
            new_data['id'] = uuid.uuid4().hex
            self.get_active_profile_data()[category_key].append(new_data)
            self.save_data()
            self.populate_tables()
            
            new_item_info = {'item': new_data, 'category': category_key}
            self.start_refresh(items_to_process=[new_item_info])

    def edit_item(self):
        category_key, active_table = self.get_current_category_info()
        selected_rows = active_table.selectionModel().selectedRows()
        if not selected_rows:
            QMessageBox.warning(self, "Selection Error", "Please select an item to edit.")
            return
        row_index = selected_rows[0].row()
        item_to_edit = self.get_active_profile_data()[category_key][row_index]
        dialog = ComponentDialog(component=item_to_edit, parent=self)
        if dialog.exec():
            updated_data = dialog.get_data()
            item_to_edit.update(updated_data)
            self.save_data()
            self.populate_tables()

    def delete_item(self):
        category_key, active_table = self.get_current_category_info()
        selected_rows = active_table.selectionModel().selectedRows()
        if not selected_rows:
            QMessageBox.warning(self, "Selection Error", "Please select an item to delete.")
            return
        
        # Correctly handle multi-selection deletion from bottom to top
        rows_to_delete = sorted([index.row() for index in selected_rows], reverse=True)
        
        if len(rows_to_delete) > 1:
            reply = QMessageBox.question(self, "Confirm Delete", f"Are you sure you want to delete {len(rows_to_delete)} items?",
                                         QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
        else:
            item_name = self.get_active_profile_data()[category_key][rows_to_delete[0]].get('name', 'this item')
            reply = QMessageBox.question(self, "Confirm Delete", f"Are you sure you want to delete '{item_name}'?",
                                         QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)

        if reply == QMessageBox.StandardButton.Yes:
            for row_index in rows_to_delete:
                del self.get_active_profile_data()[category_key][row_index]
            self.save_data()
            self.populate_tables()
    
    def refresh_all(self):
        if self.is_refreshing: return
        self.start_refresh()

    def refresh_selected(self):
        if self.is_refreshing: return
        category_key, active_table = self.get_current_category_info()
        selected_rows = active_table.selectionModel().selectedRows()

        if not selected_rows:
            QMessageBox.warning(self, "Selection Error", "Please select one or more items to refresh.")
            return

        items_to_process = []
        unique_row_indices = {index.row() for index in selected_rows}
        
        active_profile_data = self.get_active_profile_data()
        for row_index in sorted(list(unique_row_indices)):
            item_to_refresh = active_profile_data[category_key][row_index]
            items_to_process.append({'item': item_to_refresh, 'category': category_key})
        
        if items_to_process:
            self.start_refresh(items_to_process=items_to_process)

    def start_refresh(self, items_to_process=None):
        self.set_scraping_state(True)
        
        items = []
        if items_to_process is not None:
            items = items_to_process
        else:
            active_profile_data = self.get_active_profile_data()
            items = [
                {'item': component, 'category': category}
                for category, item_list in active_profile_data.items()
                for component in item_list
            ]

        tasks_to_run = []
        for info in items:
            component = info['item']
            category = info['category']
            link = component.get('link', '')
            if "tokopedia.com" in link:
                tasks_to_run.append({
                    'id': component['id'],
                    'category': category,
                    'link': link,
                    'name': component.get('name', 'Unknown')
                })
            elif "shopee" in link:
                self.show_scrape_error(component.get('name', 'Unknown'), "Shopee links are not supported.")
        
        if not tasks_to_run:
            self.on_refresh_finished(was_cancelled=False)
            return

        self.thread = QThread()
        self.worker = ScrapeWorker(tasks_to_run)
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run)
        self.worker.finished.connect(self.on_worker_finished)
        self.worker.item_scraped.connect(self.on_item_scraped)
        self.worker.error.connect(self.show_scrape_error)
        self.worker.scraping_started.connect(self.on_scraping_started)
        self.worker.progress_updated.connect(self.on_progress_updated)
        self.thread.start()

    def cancel_refresh(self):
        if self.worker:
            self.worker.stop()

    def on_worker_finished(self):
        was_cancelled = not (self.worker and self.worker.is_running)
        self.on_refresh_finished(was_cancelled)

        if self.thread:
            self.thread.quit()
            self.thread.wait()
        self.worker = None
        self.thread = None

    def on_scraping_started(self, total):
        self.progress_bar.setMaximum(total)
        self.progress_bar.setFormat(f"Scraping... %p% ({total} items)")

    def on_progress_updated(self, count):
        self.progress_bar.setValue(count)

    def on_item_scraped(self, item_id, category, updated_data, image_bytes):
        target_item = None
        active_profile_items = self.get_active_profile_data().get(category, [])
        for item in active_profile_items:
            if item.get('id') == item_id:
                target_item = item
                break
        if not target_item: return
        target_item.update(updated_data)
        table = self.tables.get(category)
        if not table: return
        found_row = -1
        for row in range(table.rowCount()):
            name_item = table.item(row, 1)
            if name_item and name_item.data(ID_ROLE) == item_id:
                found_row = row
                break
        if found_row == -1: return
        price = target_item.get('price', 0)
        quantity = target_item.get('quantity', 1)
        price_str = f"{price:,.0f}"
        if quantity > 1:
            total_price = price * quantity
            total_price_str = f"({total_price:,.0f})"
            combined_price_text = f"{price_str}\n{total_price_str}"
        else:
            combined_price_text = price_str
        table.item(found_row, 2).setText(combined_price_text)
        self._update_row_image(category, found_row, image_bytes=image_bytes)
        self.update_totals()

    def show_scrape_error(self, name, message):
        QMessageBox.warning(self, f"Scraping Error: {name}", message)

    def on_refresh_finished(self, was_cancelled):
        # The progress bar disappearing is sufficient notification.
        # No popup is needed.
        self.set_scraping_state(False)
        self.save_data()

    def closeEvent(self, event):
        if self.is_refreshing:
            self.cancel_refresh()
            if self.thread and self.thread.isRunning():
                self.thread.wait(1000)
        event.accept()

if __name__ == '__main__':
    app = QApplication(sys.argv)
    window = PCPlanner()
    window.show()
    sys.exit(app.exec())
