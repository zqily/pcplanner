import os
import sys
import logging
import shutil
from pathlib import Path
from datetime import datetime

# --- Application Metadata ---
APP_NAME = "PC Planner"
APP_VERSION = "v1.3.0"
GITHUB_API_URL = "https://api.github.com/repos/zqily/pcplanner/releases/latest"

# --- File Paths ---
BASE_DIR = Path(os.getcwd())
DATA_FILE = BASE_DIR / 'data.json'  # Kept for migration check
DB_FILE = BASE_DIR / 'data.sqlite'
CACHE_DIR = BASE_DIR / 'image_cache'
LOGS_DIR = BASE_DIR / 'logs'

# --- UI Constants ---
WINDOW_WIDTH = 1280
WINDOW_HEIGHT = 850
IMAGE_COLUMN_WIDTH = 120
IMAGE_ROW_HEIGHT = 120

# --- Data Constants ---
MAX_HISTORY_ENTRIES = 90

# --- Network Constants ---
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
    'Accept-Language': 'en-US,en;q=0.9',
}
MAX_WORKERS = 8
NETWORK_TIMEOUT = 15

def ensure_dirs() -> None:
    """Ensures necessary directories exist."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    LOGS_DIR.mkdir(parents=True, exist_ok=True)

def setup_logging() -> None:
    """
    Sets up a Minecraft-style logging system.
    1. Rotates 'latest.log' to 'YYYY-MM-DD-n.log'.
    2. Configures logging to write to 'latest.log' and Console.
    """
    ensure_dirs()
    
    log_file = LOGS_DIR / "latest.log"
    
    # --- Log Rotation Logic ---
    if log_file.exists():
        today_str = datetime.now().strftime("%Y-%m-%d")
        index = 1
        
        # Find the next available index for today's logs
        while True:
            archive_name = f"{today_str}-{index}.log"
            archive_path = LOGS_DIR / archive_name
            if not archive_path.exists():
                break
            index += 1
            
        try:
            shutil.move(str(log_file), str(LOGS_DIR / archive_name))
        except Exception as e:
            print(f"Failed to rotate logs: {e}")

    # --- Logger Configuration ---
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)
    
    # 1. File Handler (Detailed, includes file/line info)
    file_formatter = logging.Formatter(
        '[%(asctime)s] [%(threadName)s/%(levelname)s] [%(filename)s:%(lineno)d]: %(message)s',
        datefmt='%H:%M:%S'
    )
    file_handler = logging.FileHandler(log_file, encoding='utf-8')
    file_handler.setFormatter(file_formatter)
    root_logger.addHandler(file_handler)
    
    # 2. Console Handler (Cleaner output)
    console_formatter = logging.Formatter(
        '[%(asctime)s] [%(levelname)s]: %(message)s',
        datefmt='%H:%M:%S'
    )
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(console_formatter)
    root_logger.addHandler(console_handler)

    logging.info("Logging initialized. Previous log rotated.")
    logging.info(f"{APP_NAME} {APP_VERSION} starting up...")