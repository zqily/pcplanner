import hashlib
import uuid
import json
import webbrowser
from functools import partial
from typing import Dict, Optional

from PyQt6.QtWidgets import (
    QMainWindow, QTableWidgetItem, QPushButton, QVBoxLayout, 
    QWidget, QHBoxLayout, QMessageBox, QLabel, QHeaderView, 
    QAbstractItemView, QTabWidget, QProgressBar, QComboBox, 
    QInputDialog, QFileDialog
)
from PyQt6.QtGui import QPixmap, QCloseEvent, QColor
from PyQt6.QtCore import Qt, QThread

from config import (
    WINDOW_WIDTH, WINDOW_HEIGHT, IMAGE_COLUMN_WIDTH, IMAGE_ROW_HEIGHT, 
    CACHE_DIR, APP_NAME, APP_VERSION
)
from core.data_manager import DataManager
from services.workers import ScrapeManager, UpdateCheckWorker
from ui.widgets import DraggableTableWidget
from ui.dialogs import ComponentDialog
from ui.graph_window import PriceHistoryWindow

ID_ROLE = Qt.ItemDataRole.UserRole + 1

class PCPlanner(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"{APP_NAME} {APP_VERSION}")
        self.resize(WINDOW_WIDTH, WINDOW_HEIGHT)
        
        self.data_manager = DataManager()
        self.scrape_manager = ScrapeManager()
        
        self.category_keys = ["components", "peripherals"]
        self.item_id_to_row_map: Dict[str, Dict[str, int]] = {}
        self.tables: Dict[str, DraggableTableWidget] = {}
        self.total_labels: Dict[str, QLabel] = {}

        self.update_thread: Optional[QThread] = None

        self._init_ui()
        self._connect_signals()

        self.populate_profile_combo()
        self.populate_tables()
        self._check_for_updates()

    def _init_ui(self) -> None:
        # Tabs
        self.tab_widget = QTabWidget()
        labels = {"components": "PC Components", "peripherals": "Peripherals"}
        
        for key in self.category_keys:
            table = DraggableTableWidget(0, 6)
            table.setHorizontalHeaderLabels(["Image", "Name", "Price History (IDR)", "Qty", "Link", "Specs"])
            table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
            table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
            
            h_header = table.horizontalHeader()
            if h_header:
                h_header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
                h_header.setSectionResizeMode(5, QHeaderView.ResizeMode.Stretch)
                h_header.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
                h_header.setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
                h_header.setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
                h_header.setSectionResizeMode(4, QHeaderView.ResizeMode.Fixed)
            
            table.setColumnWidth(0, IMAGE_COLUMN_WIDTH)
            table.setColumnWidth(2, 180) # Increased for Price History
            table.setColumnWidth(3, 60)
            table.setColumnWidth(4, 60)
            
            v_header = table.verticalHeader()
            if v_header:
                v_header.setDefaultSectionSize(IMAGE_ROW_HEIGHT)
                v_header.setMinimumSectionSize(IMAGE_ROW_HEIGHT)
            
            self.tables[key] = table
            
            self.total_labels[key] = QLabel("Total Price: Rp 0")
            self.total_labels[key].setStyleSheet("font-size: 16px; font-weight: bold;")
            
            layout = QVBoxLayout()
            layout.addWidget(table)
            layout.addWidget(self.total_labels[key], alignment=Qt.AlignmentFlag.AlignRight)
            container = QWidget()
            container.setLayout(layout)
            self.tab_widget.addTab(container, labels.get(key, key))

        # Controls
        self.add_btn = QPushButton("Add Item")
        self.edit_btn = QPushButton("Edit Item")
        self.del_btn = QPushButton("Delete Item")
        self.graph_btn = QPushButton("Show History")  # New Button
        self.refresh_btn = QPushButton("Refresh All")
        self.refresh_sel_btn = QPushButton("Refresh Selected")
        self.cancel_btn = QPushButton("Cancel Refresh")
        self.cancel_btn.setVisible(False)
        
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        
        self.grand_total_lbl = QLabel("Grand Total: Rp 0")
        self.grand_total_lbl.setStyleSheet("font-size: 20px; font-weight: bold; padding: 10px;")

        # Profile Controls
        self.profile_combo = QComboBox()
        self.new_prof_btn = QPushButton("New")
        self.ren_prof_btn = QPushButton("Rename")
        self.del_prof_btn = QPushButton("Delete")
        self.imp_prof_btn = QPushButton("Import")
        self.exp_prof_btn = QPushButton("Export")

        # Layouts
        prof_layout = QHBoxLayout()
        prof_layout.addWidget(QLabel("Profile:"))
        prof_layout.addWidget(self.profile_combo, 1)
        prof_layout.addWidget(self.new_prof_btn)
        prof_layout.addWidget(self.ren_prof_btn)
        prof_layout.addWidget(self.del_prof_btn)
        prof_layout.addStretch()
        prof_layout.addWidget(self.imp_prof_btn)
        prof_layout.addWidget(self.exp_prof_btn)

        btn_layout = QHBoxLayout()
        btn_layout.addWidget(self.add_btn)
        btn_layout.addWidget(self.edit_btn)
        btn_layout.addWidget(self.del_btn)
        btn_layout.addWidget(self.graph_btn) # Added here
        btn_layout.addStretch()
        btn_layout.addWidget(self.refresh_sel_btn)
        btn_layout.addWidget(self.refresh_btn)
        btn_layout.addWidget(self.cancel_btn)

        main_layout = QVBoxLayout()
        main_layout.addLayout(prof_layout)
        main_layout.addLayout(btn_layout)
        main_layout.addWidget(self.progress_bar)
        main_layout.addWidget(self.tab_widget)
        main_layout.addWidget(self.grand_total_lbl, alignment=Qt.AlignmentFlag.AlignRight)

        widget = QWidget()
        widget.setLayout(main_layout)
        self.setCentralWidget(widget)

    def _connect_signals(self) -> None:
        self.add_btn.clicked.connect(self.add_item)
        self.edit_btn.clicked.connect(self.edit_item)
        self.del_btn.clicked.connect(self.delete_item)
        self.graph_btn.clicked.connect(self.show_item_history) # Connect new button
        self.refresh_btn.clicked.connect(self.refresh_all)
        self.refresh_sel_btn.clicked.connect(self.refresh_selected)
        self.cancel_btn.clicked.connect(self.scrape_manager.cancel)
        
        self.profile_combo.activated.connect(self.switch_profile)
        self.new_prof_btn.clicked.connect(self.add_profile)
        self.ren_prof_btn.clicked.connect(self.rename_profile)
        self.del_prof_btn.clicked.connect(self.delete_profile)
        self.imp_prof_btn.clicked.connect(self.import_profile)
        self.exp_prof_btn.clicked.connect(self.export_profile)

        self.data_manager.profiles_changed.connect(self.handle_profiles_changed)
        
        self.scrape_manager.scraping_started.connect(self._on_scraping_start)
        self.scrape_manager.progress_updated.connect(self.progress_bar.setValue)
        self.scrape_manager.item_scraped.connect(self._on_item_scraped)
        self.scrape_manager.error_occurred.connect(lambda n, m: print(f"Error {n}: {m}")) 
        self.scrape_manager.scraping_finished.connect(self._on_scraping_end)

        for cat, table in self.tables.items():
            table.rows_reordered.connect(partial(self.handle_row_reorder, cat))
            # Changed from edit_item to show_item_history for double click
            table.doubleClicked.connect(self.show_item_history)

    # --- Profile Logic ---
    def populate_profile_combo(self) -> None:
        self.profile_combo.blockSignals(True)
        self.profile_combo.clear()
        profiles = self.data_manager.get_profile_names()
        self.profile_combo.addItems(profiles)
        self.profile_combo.setCurrentText(self.data_manager.active_profile_name)
        self.profile_combo.blockSignals(False)
        self.del_prof_btn.setEnabled(len(profiles) > 1)

    def switch_profile(self) -> None:
        if self.data_manager.switch_profile(self.profile_combo.currentText()):
            self.populate_tables()

    def add_profile(self) -> None:
        name, ok = QInputDialog.getText(self, 'New Profile', 'Name:')
        if ok and name:
            success, msg = self.data_manager.add_profile(name)
            if not success: QMessageBox.warning(self, "Error", msg)

    def rename_profile(self) -> None:
        old = self.data_manager.active_profile_name
        name, ok = QInputDialog.getText(self, 'Rename', 'New Name:', text=old)
        if ok and name and name != old:
            success, msg = self.data_manager.rename_profile(old, name)
            if not success: QMessageBox.warning(self, "Error", msg)

    def delete_profile(self) -> None:
        name = self.data_manager.active_profile_name
        if QMessageBox.question(self, "Delete", f"Delete '{name}'?") == QMessageBox.StandardButton.Yes:
            self.data_manager.delete_profile(name)

    def handle_profiles_changed(self) -> None:
        self.populate_profile_combo()
        self.populate_tables()

    def import_profile(self):
        fpath, _ = QFileDialog.getOpenFileName(self, "Import", "", "JSON (*.json)")
        if not fpath: return
        try:
            with open(fpath, 'r') as f: data = json.load(f)
            name = data.get('profile_name', 'Imported')
            if self.data_manager.add_profile(name)[0]:
                self.data_manager.data['profiles'][name] = data.get('data', {})
                self.data_manager.switch_profile(name)
                self.handle_profiles_changed()
        except Exception as e:
            QMessageBox.critical(self, "Error", str(e))

    def export_profile(self):
        name = self.data_manager.active_profile_name
        data = {"profile_name": name, "data": self.data_manager.get_active_profile_data()}
        fpath, _ = QFileDialog.getSaveFileName(self, "Export", f"{name}.json", "JSON (*.json)")
        if fpath:
            with open(fpath, 'w') as f: json.dump(data, f, indent=4)

    # --- Table/Item Logic ---
    def populate_tables(self) -> None:
        self.item_id_to_row_map = {k: {} for k in self.category_keys}
        profile_data = self.data_manager.get_active_profile_data()

        for cat, items in profile_data.items():
            table = self.tables.get(cat)
            if not table: continue
            table.setRowCount(0)
            
            for i, item in enumerate(items):
                table.insertRow(i)
                table.setRowHeight(i, IMAGE_ROW_HEIGHT)
                item_id = item.get('id')
                if item_id: self.item_id_to_row_map[cat][item_id] = i
                self._update_row_visuals(table, i, item)

        self._update_totals()

    def _update_row_visuals(self, table: DraggableTableWidget, row: int, item: Dict, img_bytes: bytes = None) -> None:
        # Image
        lbl = QLabel()
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl.setStyleSheet("border: 0px; padding: 0px;")
        
        pix = QPixmap()
        if img_bytes:
            pix.loadFromData(img_bytes)
        elif item.get('image_url'):
            hashed = hashlib.sha256(item['image_url'].encode()).hexdigest()
            path = CACHE_DIR / f"{hashed}.jpg"
            if path.exists(): pix.load(str(path))
        
        if not pix.isNull():
            scaled_pix = pix.scaled(
                IMAGE_COLUMN_WIDTH, 
                IMAGE_ROW_HEIGHT, 
                Qt.AspectRatioMode.KeepAspectRatio, 
                Qt.TransformationMode.SmoothTransformation
            )
            lbl.setPixmap(scaled_pix)
        else:
            lbl.setText("No Image")
            
        table.setCellWidget(row, 0, lbl)

        # Name
        name_item = QTableWidgetItem(item.get('name', 'N/A'))
        name_item.setData(ID_ROLE, item.get('id'))
        table.setItem(row, 1, name_item)

        # Price & History
        price = item.get('price', 0)
        qty = item.get('quantity', 1)
        history = item.get('price_history', [])
        
        delta_str = ""
        delta_color = None
        
        if len(history) >= 2:
            prev_price = history[-2]['price']
            diff = price - prev_price
            if diff < 0:
                delta_str = f"▼ Rp {abs(diff):,.0f}"
                delta_color = QColor("green")
            elif diff > 0:
                delta_str = f"▲ Rp {abs(diff):,.0f}"
                delta_color = QColor("red")
        
        price_txt = f"Rp {price:,.0f}"
        if delta_str:
            price_txt += f"\n({delta_str})"
        
        if qty > 1:
            price_txt += f"\nTotal: Rp {price*qty:,.0f}"

        price_item = QTableWidgetItem(price_txt)
        price_item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        
        if delta_color:
            color_hex = delta_color.name()
            rich_text = f"""
            <div style='text-align: right;'>
                <b>Rp {price:,.0f}</b><br>
                <span style='color: {color_hex};'>{delta_str}</span>
                {f"<br><small>Total: Rp {price*qty:,.0f}</small>" if qty > 1 else ""}
            </div>
            """
            price_lbl = QLabel(rich_text)
            price_lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            table.setCellWidget(row, 2, price_lbl)
        else:
            table.removeCellWidget(row, 2)
            table.setItem(row, 2, price_item)

        # Qty
        qty_item = QTableWidgetItem(str(qty))
        qty_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        table.setItem(row, 3, qty_item)

        # Link
        link = item.get('link', '')
        link_lbl = QLabel(f"<a href='{link}'>View</a>" if "http" in link else "N/A")
        link_lbl.setOpenExternalLinks(True)
        link_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        table.setCellWidget(row, 4, link_lbl)

        # Specs
        table.setItem(row, 5, QTableWidgetItem(item.get('specs', '')))

    def _update_totals(self) -> None:
        grand = 0
        data = self.data_manager.get_active_profile_data()
        for cat, items in data.items():
            sub = sum(i.get('price', 0) * i.get('quantity', 1) for i in items)
            grand += sub
            self.total_labels[cat].setText(f"Total: Rp {sub:,.0f}")
        self.grand_total_lbl.setText(f"Grand Total: Rp {grand:,.0f}")

    def handle_row_reorder(self, category: str, src: int, dst: int) -> None:
        items = self.data_manager.get_active_profile_data()[category]
        items.insert(dst, items.pop(src))
        self.data_manager.save_data()
        self.populate_tables()

    def add_item(self) -> None:
        cat = self.category_keys[self.tab_widget.currentIndex()]
        dlg = ComponentDialog(parent=self)
        if dlg.exec():
            data = dlg.get_data()
            data['id'] = uuid.uuid4().hex
            self.data_manager.add_item_to_profile(cat, data)
            self.populate_tables()
            if "tokopedia.com" in data['link']:
                self.scrape_manager.start([{'id': data['id'], 'category': cat, 'link': data['link']}])

    def edit_item(self) -> None:
        cat = self.category_keys[self.tab_widget.currentIndex()]
        table = self.tables[cat]
        sel_model = table.selectionModel()
        if not sel_model: return

        rows = sel_model.selectedRows()
        if not rows: return
        idx = rows[0].row()
        item = self.data_manager.get_active_profile_data()[cat][idx]
        
        def reset_history():
            self.data_manager.reset_item_history(item['id'], cat)
            
        dlg = ComponentDialog(item, self, reset_callback=reset_history)
        if dlg.exec():
            self.data_manager.update_item_in_profile(cat, idx, dlg.get_data())
            self.populate_tables()

    def delete_item(self) -> None:
        cat = self.category_keys[self.tab_widget.currentIndex()]
        table = self.tables[cat]
        sel_model = table.selectionModel()
        if not sel_model: return

        rows = sorted([r.row() for r in sel_model.selectedRows()], reverse=True)
        if rows and QMessageBox.question(self, "Delete", "Confirm delete?") == QMessageBox.StandardButton.Yes:
            self.data_manager.delete_items_from_profile(cat, rows)
            self.populate_tables()

    def show_item_history(self) -> None:
        cat = self.category_keys[self.tab_widget.currentIndex()]
        table = self.tables[cat]
        sel_model = table.selectionModel()
        
        if not sel_model or not sel_model.hasSelection():
            # If triggered by button with no selection
            return

        rows = sel_model.selectedRows()
        if not rows: return
        
        idx = rows[0].row()
        item = self.data_manager.get_active_profile_data()[cat][idx]
        
        history = item.get('price_history', [])
        
        # Open the Graph Window
        graph_win = PriceHistoryWindow(item.get('name', 'Unknown Item'), history, parent=self)
        graph_win.exec()

    # --- Scraping & Updates ---
    def refresh_all(self) -> None:
        self._start_scrape()

    def refresh_selected(self) -> None:
        cat = self.category_keys[self.tab_widget.currentIndex()]
        table = self.tables[cat]
        sel_model = table.selectionModel()
        if not sel_model: return
        
        rows = [r.row() for r in sel_model.selectedRows()]
        items = [self.data_manager.get_active_profile_data()[cat][i] for i in rows]
        self._start_scrape([{'item': i, 'category': cat} for i in items])

    def _start_scrape(self, specific_items=None) -> None:
        if self.scrape_manager.is_running(): return
        tasks = []
        scope = specific_items or [
            {'item': i, 'category': c} 
            for c, lst in self.data_manager.get_active_profile_data().items() for i in lst
        ]
        
        for info in scope:
            link = info['item'].get('link', '')
            if "tokopedia.com" in link:
                tasks.append({'id': info['item']['id'], 'category': info['category'], 'link': link, 'name': info['item'].get('name')})
        
        self.scrape_manager.start(tasks)

    def _on_scraping_start(self, total: int) -> None:
        self.refresh_btn.setVisible(False)
        self.refresh_sel_btn.setVisible(False)
        self.cancel_btn.setVisible(True)
        self.progress_bar.setVisible(True)
        self.progress_bar.setMaximum(total)
        self.progress_bar.setFormat(f"Scraping... %p% ({total} items)")

    def _on_scraping_end(self, cancelled: bool) -> None:
        self.refresh_btn.setVisible(True)
        self.refresh_sel_btn.setVisible(True)
        self.cancel_btn.setVisible(False)
        self.progress_bar.setVisible(False)
        self.data_manager.save_data()

    def _on_item_scraped(self, iid: str, cat: str, data: Dict, img_bytes: bytes) -> None:
        if 'price' in data:
            self.data_manager.update_item_history(iid, cat, data['price'])
        
        item, _ = self.data_manager.find_item(iid)
        if item:
            if 'image_url' in data:
                item['image_url'] = data['image_url']
            
            row = self.item_id_to_row_map.get(cat, {}).get(iid)
            if row is not None:
                self._update_row_visuals(self.tables[cat], row, item, img_bytes)
            self._update_totals()

    def _check_for_updates(self) -> None:
        self.update_thread = QThread()
        self.u_worker = UpdateCheckWorker()
        self.u_worker.moveToThread(self.update_thread)
        self.u_worker.update_available.connect(lambda r: webbrowser.open(r.get("html_url")) if QMessageBox.information(self, "Update", f"New version {r.get('tag_name')} available.", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No) == QMessageBox.StandardButton.Yes else None)
        self.u_worker.finished.connect(self.update_thread.quit)
        self.update_thread.started.connect(self.u_worker.run)
        self.update_thread.start()

    def closeEvent(self, event: Optional[QCloseEvent]) -> None:
        if self.scrape_manager.is_running():
            self.scrape_manager.cancel()
            if self.scrape_manager.worker_thread:
                self.scrape_manager.worker_thread.wait(1000)
        if event:
            event.accept()