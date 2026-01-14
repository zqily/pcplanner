import logging
from datetime import datetime
from typing import List, Dict, Any, Optional

from PyQt6.QtWidgets import QDialog, QVBoxLayout, QWidget, QMessageBox
from PyQt6.QtCore import Qt

import matplotlib
import matplotlib.ticker
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.backends.backend_qt import NavigationToolbar2QT as NavigationToolbar
from matplotlib.figure import Figure
import matplotlib.dates as mdates

# Ensure we use the QtAgg backend
matplotlib.use('QtAgg')

class PriceHistoryWindow(QDialog):
    """
    A dialog window that displays an interactive price history graph
    using Matplotlib embedded in PyQt6.
    """

    def __init__(self, item_name: str, history_data: List[Dict[str, Any]], parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setWindowTitle(f"Price History: {item_name}")
        self.resize(800, 600)
        self.item_name = item_name
        self.history_data = history_data
        
        self._init_ui()
        self._plot_data()

    def _init_ui(self) -> None:
        """Sets up the Matplotlib canvas and toolbar."""
        layout = QVBoxLayout()
        
        # Create Figure and Canvas
        self.figure = Figure(figsize=(8, 6), dpi=100)
        self.canvas = FigureCanvas(self.figure)
        
        # Add Navigation Toolbar (Zoom, Pan, Save)
        self.toolbar = NavigationToolbar(self.canvas, self)
        
        layout.addWidget(self.toolbar)
        layout.addWidget(self.canvas)
        self.setLayout(layout)

    def _plot_data(self) -> None:
        """Parses data and renders the plot."""
        if not self.history_data:
            self._show_empty_message()
            return

        try:
            # Sort history by date just in case
            sorted_history = sorted(self.history_data, key=lambda x: x['date'])
            
            dates = []
            prices = []
            
            for entry in sorted_history:
                try:
                    dt = datetime.fromisoformat(entry['date'])
                    dates.append(dt)
                    prices.append(entry['price'])
                except (ValueError, KeyError) as e:
                    logging.warning(f"Skipping invalid history entry: {entry} - {e}")
                    continue

            if not dates:
                self._show_empty_message()
                return

            # Clear existing axes
            self.figure.clear()
            ax = self.figure.add_subplot(111)

            # Plot styling
            ax.plot(dates, prices, marker='o', linestyle='-', linewidth=2, markersize=6, color='#2980b9')
            ax.grid(True, linestyle='--', alpha=0.7)
            
            # Formatting
            ax.set_title(f"Price Trend: {self.item_name}", fontsize=12, fontweight='bold', pad=15)
            ax.set_ylabel("Price (IDR)", fontsize=10)
            ax.set_xlabel("Date", fontsize=10)
            
            # Y-Axis Currency Formatting
            ax.yaxis.set_major_formatter(matplotlib.ticker.StrMethodFormatter('Rp {x:,.0f}'))
            
            # X-Axis Date Formatting
            ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m-%d'))
            ax.xaxis.set_major_locator(mdates.AutoDateLocator())
            self.figure.autofmt_xdate(rotation=45)

            # Refresh canvas
            self.canvas.draw()

        except Exception as e:
            logging.error(f"Failed to plot graph: {e}", exc_info=True)
            QMessageBox.critical(self, "Plot Error", f"Could not generate graph: {str(e)}")

    def _show_empty_message(self) -> None:
        """Displays a message on the canvas if no data exists."""
        self.figure.clear()
        ax = self.figure.add_subplot(111)
        ax.text(0.5, 0.5, 'No Price History Available', 
                horizontalalignment='center', 
                verticalalignment='center',
                transform=ax.transAxes,
                fontsize=14, color='gray')
        ax.axis('off')
        self.canvas.draw()