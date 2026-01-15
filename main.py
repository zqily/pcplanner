import sys
import traceback
import logging
from PyQt6.QtWidgets import QApplication
from config import ensure_dirs, setup_logging
from core.migrator import Migrator
from ui.main_window import PCPlanner

def excepthook(exc_type, exc_value, exc_tb):
    """Global exception handler to catch crashes."""
    tb = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
    logging.critical("Uncaught exception:\n" + tb)
    # Print to stderr as well for console visibility
    print("Critical Error! Check logs for details.", file=sys.stderr)
    sys.__excepthook__(exc_type, exc_value, exc_tb)

def main():
    sys.excepthook = excepthook
    
    # robust setup
    try:
        ensure_dirs()
        setup_logging()
    except Exception as e:
        print(f"Critical initialization failure: {e}", file=sys.stderr)
        sys.exit(1)
    
    # Run data migration if needed
    try:
        Migrator.run_migration()
    except Exception as e:
        logging.critical(f"Migration failed during startup: {e}", exc_info=True)
        # We continue startup; DataManager will initialize an empty DB if needed.

    try:
        app = QApplication(sys.argv)
        # Set app metadata
        app.setApplicationName("PC Planner")
        
        window = PCPlanner()
        window.show()
        
        sys.exit(app.exec())
    except Exception as e:
        logging.critical(f"Application crash: {e}", exc_info=True)
        raise

if __name__ == '__main__':
    main()