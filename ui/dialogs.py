from PyQt6.QtWidgets import (
    QDialog, QLineEdit, QTextEdit, QSpinBox, QFormLayout, 
    QDialogButtonBox, QVBoxLayout, QPushButton, QMessageBox, QHBoxLayout
)
from typing import Dict, Optional, Any, Callable

class ComponentDialog(QDialog):
    def __init__(self, 
                 component: Optional[Dict[str, Any]] = None, 
                 parent: Optional[Any] = None,
                 reset_callback: Optional[Callable[[], None]] = None):
        super().__init__(parent)
        self.setWindowTitle("Add/Edit Item")
        
        self.component = component
        self.reset_callback = reset_callback

        self.name_input = QLineEdit()
        self.link_input = QLineEdit()
        self.specs_input = QTextEdit()
        self.quantity_input = QSpinBox()
        self.quantity_input.setRange(1, 999)

        if component:
            self.name_input.setText(component.get('name', ''))
            self.link_input.setText(component.get('link', ''))
            self.specs_input.setText(component.get('specs', ''))
            self.quantity_input.setValue(component.get('quantity', 1))
        
        self._setup_ui()

    def _setup_ui(self) -> None:
        form = QFormLayout()
        form.addRow("Name:", self.name_input)
        form.addRow("Quantity:", self.quantity_input)
        form.addRow("Tokopedia Link:", self.link_input)
        form.addRow("Specs:", self.specs_input)

        # Standard Dialog Buttons
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        # Main Layout
        layout = QVBoxLayout()
        layout.addLayout(form)
        
        # Reset History Button (Only in Edit Mode)
        if self.component and self.reset_callback:
            reset_btn = QPushButton("Reset Price History")
            reset_btn.setStyleSheet("background-color: #d9534f; color: white; font-weight: bold;")
            reset_btn.clicked.connect(self._handle_reset)
            layout.addWidget(reset_btn)

        layout.addWidget(buttons)
        self.setLayout(layout)

    def _handle_reset(self) -> None:
        if QMessageBox.warning(
            self, 
            "Confirm Reset", 
            "Are you sure you want to delete all price history for this item? This cannot be undone.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        ) == QMessageBox.StandardButton.Yes:
            if self.reset_callback:
                self.reset_callback()
                QMessageBox.information(self, "Success", "Price history reset.")

    def get_data(self) -> Dict[str, Any]:
        return {
            "name": self.name_input.text(),
            "link": self.link_input.text(),
            "specs": self.specs_input.toPlainText(),
            "quantity": self.quantity_input.value()
        }