from typing import Optional
from PyQt6.QtWidgets import QTableWidget, QAbstractItemView
from PyQt6.QtCore import pyqtSignal
from PyQt6.QtGui import QDropEvent

class DraggableTableWidget(QTableWidget):
    """
    A QTableWidget subclass that supports row drag-and-drop to reorder items.
    """
    rows_reordered = pyqtSignal(int, int)  # from_row, to_row

    def __init__(self, rows: int, columns: int):
        super().__init__(rows, columns)
        self.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setDragDropOverwriteMode(False)

    def dropEvent(self, event: Optional[QDropEvent]) -> None:
        if not event or not event.isAccepted():
            pass
        else:
             if event.source() != self:
                 return

        if event and event.source() == self:
            selection_model = self.selectionModel()
            if not selection_model:
                return

            current_idx = selection_model.currentIndex()
            if not current_idx.isValid():
                 return
            
            source_row = current_idx.row()
            dest_row = self.indexAt(event.position().toPoint()).row()

            if dest_row < 0:
                dest_row = self.rowCount() - 1
            
            super().dropEvent(event)
            self.rows_reordered.emit(source_row, dest_row)
            event.accept()