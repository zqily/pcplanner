import logging
from datetime import datetime
from typing import List, Dict, Any, Optional

from PyQt6.QtWidgets import QDialog, QVBoxLayout, QWidget, QMessageBox, QLabel
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
        self.resize(800, 620) # Slightly taller to accommodate the note
        self.item_name = item_name
        self.history_data = history_data
        
        # Navigation state for Middle-Click Pan
        self._middle_pressed = False
        self._last_mouse_x = None
        self._last_mouse_y = None
        
        self._init_ui()
        self._connect_navigation_events()
        self._plot_data()

    def _init_ui(self) -> None:
        """Sets up the Matplotlib canvas, toolbar, and instruction label."""
        layout = QVBoxLayout()
        
        # 1. Figure & Canvas
        self.figure = Figure(figsize=(8, 6), dpi=100)
        self.figure.patch.set_facecolor('#f0f0f0')
        self.canvas = FigureCanvas(self.figure)
        
        # 2. Standard Toolbar
        self.toolbar = NavigationToolbar(self.canvas, self)
        
        # 3. Instruction Note
        self.note_label = QLabel("<b>Navigation:</b> Middle Click + Drag to Pan | Scroll Wheel to Zoom")
        self.note_label.setStyleSheet("color: #555; font-size: 11px; margin-bottom: 5px;")
        self.note_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        # Assemble Layout
        layout.addWidget(self.toolbar)
        layout.addWidget(self.canvas)
        layout.addWidget(self.note_label)
        self.setLayout(layout)

    def _connect_navigation_events(self) -> None:
        """Binds mouse events for custom navigation."""
        # Scroll to Zoom
        self.canvas.mpl_connect('scroll_event', self._on_scroll_zoom)
        
        # Middle Click to Pan
        self.canvas.mpl_connect('button_press_event', self._on_mouse_press)
        self.canvas.mpl_connect('button_release_event', self._on_mouse_release)
        self.canvas.mpl_connect('motion_notify_event', self._on_mouse_move)

    def _plot_data(self) -> None:
        """Parses data and renders the plot with auto-fitting."""
        if not self.history_data:
            self._show_empty_message()
            return

        try:
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

            self.figure.clear()
            self.ax = self.figure.add_subplot(111)

            # --- Plot Data ---
            self.ax.plot(dates, prices, marker='o', linestyle='-', linewidth=2, 
                         markersize=6, color='#2980b9', label='Price')
            self.ax.fill_between(dates, prices, alpha=0.1, color='#2980b9')

            # --- Styling ---
            self.ax.grid(True, which='major', linestyle='--', linewidth=0.7, alpha=0.7)
            self.ax.grid(True, which='minor', linestyle=':', linewidth=0.5, alpha=0.4)
            self.ax.minorticks_on()
            
            self.ax.set_title(f"Price Trend: {self.item_name}", fontsize=12, fontweight='bold', pad=15)
            self.ax.set_ylabel("Price (IDR)", fontsize=10, fontweight='bold')
            self.ax.set_xlabel("Date", fontsize=10, fontweight='bold')
            
            self.ax.yaxis.set_major_formatter(matplotlib.ticker.StrMethodFormatter('Rp {x:,.0f}'))
            self.ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m-%d'))
            self.ax.xaxis.set_major_locator(mdates.AutoDateLocator())
            self.figure.autofmt_xdate(rotation=45)

            # --- Auto-Zoom / Initial Fitting ---
            self.ax.autoscale(enable=True, axis='x', tight=True)

            if len(prices) > 0:
                min_p = min(prices)
                max_p = max(prices)

                if min_p == max_p:
                    buffer = max(min_p * 0.05, 1000)
                    self.ax.set_ylim(min_p - buffer, max_p + buffer)
                else:
                    price_range = max_p - min_p
                    pad = price_range * 0.1
                    self.ax.set_ylim(min_p - pad, max_p + pad)

                # Annotation for latest price
                last_date = dates[-1]
                last_price = prices[-1]
                self.ax.annotate(f'Rp {last_price:,.0f}', 
                            xy=(last_date, last_price), 
                            xytext=(0, 10), 
                            textcoords='offset points',
                            ha='center', va='bottom',
                            bbox=dict(boxstyle='round,pad=0.3', fc='yellow', alpha=0.6),
                            fontsize=9, fontweight='bold')

            self.figure.tight_layout()
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

    # --- Navigation Logic ---

    def _on_scroll_zoom(self, event):
        """Zooms in/out centered on the mouse cursor using the scroll wheel."""
        if event.inaxes is None: return

        ax = event.inaxes
        base_scale = 1.25
        scale_factor = 1 / base_scale if event.button == 'up' else base_scale

        cur_xlim = ax.get_xlim()
        cur_ylim = ax.get_ylim()
        
        xdata = event.xdata
        ydata = event.ydata

        if xdata is None or ydata is None: return

        # Calculate new X limits
        x_left = xdata - (xdata - cur_xlim[0]) * scale_factor
        x_right = xdata + (cur_xlim[1] - xdata) * scale_factor

        # Calculate new Y limits
        y_bottom = ydata - (ydata - cur_ylim[0]) * scale_factor
        y_top = ydata + (cur_ylim[1] - ydata) * scale_factor

        ax.set_xlim([x_left, x_right])
        ax.set_ylim([y_bottom, y_top])
        
        self.canvas.draw_idle()

    def _on_mouse_press(self, event):
        """Handle Middle Click start for panning."""
        if event.button == 2: # Middle Mouse Button
            self._middle_pressed = True
            self._last_mouse_x = event.x
            self._last_mouse_y = event.y

    def _on_mouse_release(self, event):
        """Handle Middle Click end."""
        if event.button == 2:
            self._middle_pressed = False

    def _on_mouse_move(self, event):
        """Handle Middle Click drag logic (Manual Panning)."""
        if not self._middle_pressed or event.inaxes is None:
            return

        ax = event.inaxes
        
        dx_pix = event.x - self._last_mouse_x
        dy_pix = event.y - self._last_mouse_y
        
        self._last_mouse_x = event.x
        self._last_mouse_y = event.y

        xlim = ax.get_xlim()
        ylim = ax.get_ylim()
        
        bbox = ax.bbox
        scale_x = (xlim[1] - xlim[0]) / bbox.width
        scale_y = (ylim[1] - ylim[0]) / bbox.height

        ax.set_xlim(xlim[0] - dx_pix * scale_x, xlim[1] - dx_pix * scale_x)
        ax.set_ylim(ylim[0] - dy_pix * scale_y, ylim[1] - dy_pix * scale_y)
        
        self.canvas.draw_idle()