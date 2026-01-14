import sys
import traceback
from PyQt6.QtWidgets import QApplication
from config import ensure_dirs, setup_logging
from ui.main_window import PCPlanner
import logging

def excepthook(exc_type, exc_value, exc_tb):
    """Global exception handler to catch crashes."""
    tb = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
    logging.critical("Uncaught exception:\n" + tb)
    print("Critical Error! Check logs for details.")
    # Optional: Show a crude native messagebox if Qt is still alive
    sys.__excepthook__(exc_type, exc_value, exc_tb)

def main():
    sys.excepthook = excepthook
    
    ensure_dirs()
    setup_logging()
    
    try:
        app = QApplication(sys.argv)
        window = PCPlanner()
        window.show()
        sys.exit(app.exec())
    except Exception as e:
        logging.critical(f"Application crash: {e}", exc_info=True)
        raise

if __name__ == '__main__':
    main()