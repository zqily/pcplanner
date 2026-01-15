import os
import sys
import json
import logging
import shutil
import tempfile
from pathlib import Path
from datetime import datetime
from typing import Dict, Any

# --- File Paths ---
BASE_DIR = Path(os.getcwd())
DATA_FILE = BASE_DIR / 'data.json'  # Kept for migration check
DB_FILE = BASE_DIR / 'data.sqlite'
CACHE_DIR = BASE_DIR / 'image_cache'
LOGS_DIR = BASE_DIR / 'logs'
CONFIG_FILE = BASE_DIR / 'config.json'

# --- Default Configuration ---
DEFAULT_CONFIG = {
    "app_info": {
        "name": "PC Planner",
        "version": "v1.3.0",
        "github_api_url": "https://api.github.com/repos/zqily/pcplanner/releases/latest"
    },
    "window": {
        "width": 1280,
        "height": 850,
        "image_column_width": 120,
        "image_row_height": 120
    },
    "data": {
        "max_history_entries": 90
    },
    "network": {
        "max_workers": 8,
        "timeout": 15,
        "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:147.0) Gecko/20100101 Firefox/147.0"
    }
}

def deep_update(base_dict: Dict, update_dict: Dict) -> Dict:
    """Recursively updates the base dictionary with values from the update dictionary."""
    for key, value in update_dict.items():
        if isinstance(value, dict):
            base_dict_value = base_dict.get(key)
            if isinstance(base_dict_value, dict):
                deep_update(base_dict_value, value)
            else:
                base_dict[key] = value
        else:
            base_dict[key] = value
    return base_dict

def load_config() -> Dict[str, Any]:
    """
    Loads config.json. 
    Handles missing file, corruption, and partial updates robustly.
    """
    config = DEFAULT_CONFIG.copy()

    # 1. Check if file exists
    if not CONFIG_FILE.exists():
        try:
            # Atomic write for initial config
            with tempfile.NamedTemporaryFile('w', dir=str(BASE_DIR), delete=False) as tf:
                json.dump(DEFAULT_CONFIG, tf, indent=4)
                tf.flush()
                os.fsync(tf.fileno())
                temp_name = tf.name
            os.replace(temp_name, CONFIG_FILE)
            print(f"Generated default configuration at {CONFIG_FILE}")
        except Exception as e:
            print(f"Error creating config file: {e}")
        return config

    # 2. Try to load and parse
    try:
        with open(CONFIG_FILE, 'r') as f:
            user_config = json.load(f)
        
        # Merge user config into defaults
        config = deep_update(config, user_config)

    except json.JSONDecodeError:
        # 3. Handle corruption
        print("CRITICAL: config.json is invalid/corrupted.")
        backup_path = CONFIG_FILE.with_suffix('.json.old')
        try:
            shutil.move(str(CONFIG_FILE), str(backup_path))
            print(f"Backed up corrupted config to {backup_path.name}")
            
            with tempfile.NamedTemporaryFile('w', dir=str(BASE_DIR), delete=False) as tf:
                json.dump(DEFAULT_CONFIG, tf, indent=4)
                tf.flush()
                os.fsync(tf.fileno())
                temp_name = tf.name
            os.replace(temp_name, CONFIG_FILE)
            print("Regenerated clean config.json")
        except Exception as e:
            print(f"Failed to recover config: {e}")

    except Exception as e:
        print(f"Unexpected error loading config: {e}")

    return config

# --- Load Configuration ---
_cfg = load_config()

# --- Expose Constants ---
APP_NAME = _cfg['app_info']['name']
APP_VERSION = _cfg['app_info']['version']
GITHUB_API_URL = _cfg['app_info']['github_api_url']

WINDOW_WIDTH = _cfg['window']['width']
WINDOW_HEIGHT = _cfg['window']['height']
IMAGE_COLUMN_WIDTH = _cfg['window']['image_column_width']
IMAGE_ROW_HEIGHT = _cfg['window']['image_row_height']

MAX_HISTORY_ENTRIES = _cfg['data']['max_history_entries']

MAX_WORKERS = _cfg['network']['max_workers']
NETWORK_TIMEOUT = _cfg['network']['timeout']

HEADERS = {
    'User-Agent': _cfg['network']['user_agent'],
    'Accept-Language': 'en-US,en;q=0.9',
}

# --- Helper Functions ---

def ensure_dirs() -> None:
    """Ensures necessary directories exist."""
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        LOGS_DIR.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        print(f"Fatal: Could not create necessary directories: {e}")
        sys.exit(1)

def setup_logging() -> None:
    """
    Sets up logging. Rotates 'latest.log' to 'YYYY-MM-DD-n.log'.
    """
    ensure_dirs()
    
    log_file = LOGS_DIR / "latest.log"
    
    # --- Log Rotation Logic ---
    if log_file.exists():
        today_str = datetime.now().strftime("%Y-%m-%d")
        index = 1
        
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
    
    # 1. File Handler
    try:
        file_formatter = logging.Formatter(
            '[%(asctime)s] [%(threadName)s/%(levelname)s] [%(filename)s:%(lineno)d]: %(message)s',
            datefmt='%H:%M:%S'
        )
        file_handler = logging.FileHandler(log_file, encoding='utf-8')
        file_handler.setFormatter(file_formatter)
        root_logger.addHandler(file_handler)
    except IOError as e:
        print(f"Failed to setup file logging: {e}")

    # 2. Console Handler
    console_formatter = logging.Formatter(
        '[%(asctime)s] [%(levelname)s]: %(message)s',
        datefmt='%H:%M:%S'
    )
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(console_formatter)
    root_logger.addHandler(console_handler)

    logging.info("Logging initialized.")
    logging.info(f"{APP_NAME} {APP_VERSION} initialized with config from {CONFIG_FILE.name}")