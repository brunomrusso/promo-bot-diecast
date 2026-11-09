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

AMAZON_TAG = os.getenv("AMAZON_TAG", "")  # links enviados pelo bot (WhatsApp/Telegram)
AMAZON_TAG_SITE = os.getenv("AMAZON_TAG_SITE", "") or AMAZON_TAG  # links do site (russodiecast.com.br)
ML_TAG_BOT = os.getenv("ML_TAG_BOT", "")    # etiqueta do ML nos links do bot (WhatsApp/Telegram); vazio = etiqueta em uso
ML_TAG_SITE = os.getenv("ML_TAG_SITE", "")  # etiqueta do ML nos links do site
DASHBOARD_URL = os.getenv("DASHBOARD_URL", "")  # e.g. https://meubot.example.com
SHOPEE_AFFILIATE_ID = os.getenv("SHOPEE_AFFILIATE_ID", "")
ML_AFFILIATE_PREFIX = os.getenv("ML_AFFILIATE_PREFIX", "")
ML_PROXY_URL = os.getenv("ML_PROXY_URL", "")  # http://user:pass@host:port

CHECK_INTERVAL_MINUTES = _env_int("CHECK_INTERVAL_MINUTES", 15)

# Site russodiecast.com.br: achadinhos gerados pelas minis com "Mostrar no site".
# Use uma conta de FTP do cPanel restrita à pasta do site (não a conta principal).
SITE_URL = os.getenv("SITE_URL", "https://russodiecast.com.br").strip()
SITE_FTP_HOST = os.getenv("SITE_FTP_HOST", "").strip()
SITE_FTP_USER = os.getenv("SITE_FTP_USER", "").strip()
SITE_FTP_PASSWORD = os.getenv("SITE_FTP_PASSWORD", "").strip()
SITE_FTP_DIR = os.getenv("SITE_FTP_DIR", "").strip()  # vazio = raiz da conta FTP


def ml_playwright_proxy():
    """Dict de proxy para Playwright a partir de ML_PROXY_URL, ou None."""
    if not ML_PROXY_URL:
        return None
    from urllib.parse import urlparse
    parsed = urlparse(ML_PROXY_URL)
    proxy = {"server": f"{parsed.scheme}://{parsed.hostname}:{parsed.port}"}
    # Desligado por padrão: buscar o CDN (mlstatic) direto pela VPS e a página pelo proxy mistura dois IPs,
    # e o anti-bot do ML pediu verificação logo depois (06/11). Para testar de novo: ML_PROXY_BYPASS=*.mlstatic.com
    if os.getenv("ML_PROXY_BYPASS"):
        proxy["bypass"] = os.getenv("ML_PROXY_BYPASS")
    if parsed.username:
        proxy["username"] = parsed.username
        proxy["password"] = parsed.password or ""
    return proxy


TEMPOS_PADRAO = {"ciclo_min": 15, "termos_por_ciclo": 3, "ml_navegador_min": 60, "congelar_horas": 24}
TEMPOS_LIMITES = {"ciclo_min": (5, 120), "termos_por_ciclo": (1, 20), "ml_navegador_min": (15, 1440),
                  "congelar_horas": (0, 720)}


def tempos():
    """Tempos de busca (painel > Configurações > Tempos de busca). Valores fora dos limites voltam ao limite."""
    salvo = _dynamic("tempos_busca", {}) or {}
    base = dict(TEMPOS_PADRAO, ciclo_min=CHECK_INTERVAL_MINUTES,
                ml_navegador_min=_env_int("ML_INTERVALO_MIN", TEMPOS_PADRAO["ml_navegador_min"]))
    out = {}
    for k, padrao in base.items():
        try:
            v = int(salvo[k]) if salvo.get(k) not in (None, "") else padrao  # 0 é valor válido (desliga)
        except (TypeError, ValueError):
            v = padrao
        lo, hi = TEMPOS_LIMITES[k]
        out[k] = min(hi, max(lo, v))
    return out


def load_enabled_stores():
    fallback = [item.strip() for item in
                os.getenv("ENABLED_STORES", "amazon,mercadolivre,shopee").split(",")
                if item.strip()]
    return _dynamic("enabled_stores", fallback)
