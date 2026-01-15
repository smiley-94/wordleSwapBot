import os
import json

# --- TELEGRAM CONFIG ---
TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
TELEGRAM_ADMIN_ID = int(os.environ["TELEGRAM_ADMIN_ID"]) if os.environ["TELEGRAM_ADMIN_ID"].isdigit() else None
TELEGRAM_ALLOWED_USERS = json.loads(os.environ.get("TELEGRAM_ALLOWED_USERS", "[]"))

# --- APP SETTINGS ---
APP_LOG_LEVEL = os.environ.get("APP_LOG_LEVEL", "INFO")
APP_DB_PATH = os.environ.get("APP_DB_PATH", "/data/wordle_bot.db")

# --- IMAGE PROCESSING ---
IMAGE_MAX_WIDTH = int(os.environ.get("IMAGE_MAX_WIDTH", "1280"))
IMAGE_MAX_BYTES = int(os.environ.get("IMAGE_MAX_BYTES", "1048576"))

# --- WORDLE ANALYZER ---
ANALYZER_BASE_URL = os.environ.get("ANALYZER_BASE_URL", "")
ANALYZER_LINK_LABEL = os.environ.get("ANALYZER_LINK_LABEL", "Wordle Analyzer")

# --- OLLAMA OCR CONFIG ---
OLLAMA_API_KEY = os.environ.get("OLLAMA_API_KEY", "")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "ministral-3:8b-cloud")
OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "https://ollama.com")
