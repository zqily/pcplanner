import sys
from PyQt6.QtWidgets import QApplication
from config import ensure_dirs
from ui.main_window import PCPlanner

def main():
    ensure_dirs()
    app = QApplication(sys.argv)
    window = PCPlanner()
    window.show()
    sys.exit(app.exec())

if __name__ == '__main__':
    main()