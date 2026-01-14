import os
import logging
from pathlib import Path

# --- Application Metadata ---
APP_NAME = "PC Planner"
APP_VERSION = "v1.2.0"
GITHUB_API_URL = "https://api.github.com/repos/zqily/pcplanner/releases/latest"

# --- File Paths ---
BASE_DIR = Path(os.getcwd())
DATA_FILE = BASE_DIR / 'data.json'
CACHE_DIR = BASE_DIR / 'image_cache'

# --- UI Constants ---
WINDOW_WIDTH = 1200
WINDOW_HEIGHT = 800
IMAGE_COLUMN_WIDTH = 150
IMAGE_ROW_HEIGHT = 150

# --- Network Constants ---
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
    'Accept-Language': 'en-US,en;q=0.9',
}
MAX_WORKERS = 10
NETWORK_TIMEOUT = 15

# --- Logging Setup ---
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler()]
)

def ensure_dirs() -> None:
    """Ensures necessary directories exist."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)