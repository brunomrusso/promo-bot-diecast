import os
import time
from dotenv import load_dotenv

from core import db

load_dotenv()

_cache = {}


def _dynamic(key, default):
    cached = _cache.get(key)
    if cached and time.time() - cached[0] < 10:
        return cached[1]
    value = db.get_setting(key, default)
    _cache[key] = (time.time(), value)
    return value


def clear_dynamic_cache():
    _cache.clear()


def _env_int(name, default):
    raw = os.getenv(name, str(default)).split("#", 1)[0].strip().split()[0]
    try:
        return int(raw)
    except (ValueError, IndexError):
        return int(default)


TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
TELEGRAM_ADMIN_CHAT_ID = os.getenv("TELEGRAM_ADMIN_CHAT_ID", "")
ML_CLIENT_ID = os.getenv("ML_CLIENT_ID", "")
ML_CLIENT_SECRET = os.getenv("ML_CLIENT_SECRET", "")

LOMADEE_APP_TOKEN = os.getenv("LOMADEE_APP_TOKEN", "")
LOMADEE_SOURCE_ID = os.getenv("LOMADEE_SOURCE_ID", "")

AMAZON_TAG = os.getenv("AMAZON_TAG", "")
DASHBOARD_URL = os.getenv("DASHBOARD_URL", "")  # e.g. https://meubot.example.com
SHOPEE_AFFILIATE_ID = os.getenv("SHOPEE_AFFILIATE_ID", "")
ML_AFFILIATE_PREFIX = os.getenv("ML_AFFILIATE_PREFIX", "")
ML_PROXY_URL = os.getenv("ML_PROXY_URL", "")  # http://user:pass@host:port

CHECK_INTERVAL_MINUTES = _env_int("CHECK_INTERVAL_MINUTES", 15)


def ml_playwright_proxy():
    """Dict de proxy para Playwright a partir de ML_PROXY_URL, ou None."""
    if not ML_PROXY_URL:
        return None
    from urllib.parse import urlparse
    parsed = urlparse(ML_PROXY_URL)
    proxy = {"server": f"{parsed.scheme}://{parsed.hostname}:{parsed.port}"}
    if parsed.username:
        proxy["username"] = parsed.username
        proxy["password"] = parsed.password or ""
    return proxy


def load_enabled_stores():
    fallback = [item.strip() for item in
                os.getenv("ENABLED_STORES", "amazon,mercadolivre,shopee").split(",")
                if item.strip()]
    return _dynamic("enabled_stores", fallback)
