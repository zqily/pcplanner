from PyQt6.QtWidgets import (
    QDialog, QLineEdit, QTextEdit, QSpinBox, QFormLayout, 
    QDialogButtonBox, QVBoxLayout
)
from typing import Dict, Optional, Any

class ComponentDialog(QDialog):
    def __init__(self, component: Optional[Dict[str, Any]] = None, parent: Optional[Any] = None):
        super().__init__(parent)
        self.setWindowTitle("Add/Edit Item")
        
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

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout()
        layout.addLayout(form)
        layout.addWidget(buttons)
        self.setLayout(layout)

    def get_data(self) -> Dict[str, Any]:
        return {
            "name": self.name_input.text(),
            "link": self.link_input.text(),
            "specs": self.specs_input.toPlainText(),
            "quantity": self.quantity_input.value()
        }