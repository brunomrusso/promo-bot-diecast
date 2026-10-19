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
# desconto >= isso posta direto; abaixo vai pra aprovação manual
AUTO_APPROVE_MIN = _env_int("AUTO_APPROVE_MIN", 40)

ML_CLIENT_ID = os.getenv("ML_CLIENT_ID", "")
ML_CLIENT_SECRET = os.getenv("ML_CLIENT_SECRET", "")

LOMADEE_APP_TOKEN = os.getenv("LOMADEE_APP_TOKEN", "")
LOMADEE_SOURCE_ID = os.getenv("LOMADEE_SOURCE_ID", "")

AMAZON_TAG = os.getenv("AMAZON_TAG", "")
DASHBOARD_URL = os.getenv("DASHBOARD_URL", "")  # e.g. https://meubot.example.com
SHOPEE_AFFILIATE_ID = os.getenv("SHOPEE_AFFILIATE_ID", "")
ML_AFFILIATE_PREFIX = os.getenv("ML_AFFILIATE_PREFIX", "")

MIN_DISCOUNT = _env_int("MIN_DISCOUNT", 30)
CHECK_INTERVAL_MINUTES = _env_int("CHECK_INTERVAL_MINUTES", 15)

# Termos de busca enviados às lojas
KEYWORDS = [
    "hot wheels premium",
    "hot wheels car culture",
    "hot wheels boulevard",
    "hot wheels elite 64",
    "hot wheels",
    "disney cars diecast",
    "carros disney pixar miniatura",
    "mini gt",
    "kaido house",
    "matchbox",
    "tomica miniatura carro",
    "majorette carro",
    "greenlight 1:64",
    "m2 machines diecast",
    "miniatura 1:64",
    "lego speed champions",
    "lego technic",
]

# Lê keywords.txt a cada chamada: edite o arquivo e o próximo ciclo
# já usa os novos termos, sem reiniciar o bot.
def load_keywords():
    configured = _dynamic("keywords", None)
    if configured:
        return configured
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "keywords.txt")
    if not os.path.exists(path):
        return KEYWORDS
    with open(path, encoding="utf-8") as f:
        keywords = [line.strip() for line in f
                    if line.strip() and not line.startswith("#")]
    return keywords or KEYWORDS

# O título precisa conter pelo menos UM destes termos (relevância)
RELEVANT_TERMS = [
    "hot wheels", "matchbox", "mini gt", "minigt", "kaido", "tomica",
    "majorette", "greenlight", "m2 machines", "johnny lightning",
    "disney cars", "carros disney", "pixar", "diecast", "die cast",
    "1:64", "1/64", "escala 1", "miniatura",
    "lego speed champions", "lego technic", "lego city",
]

# Mesmo contendo termo relevante, descarta se tiver estes (não é diecast)
BLOCKLIST = [
    "walkie", "talkie", "ioiô", "ioio", "tinta", "placa", "camiseta",
    "vestido", "blusa", "boné", "mochila", "lancheira", "garrafa",
    "copo", "prato", "balão", "bexiga", "festa", "adesivo",
    "quebra-cabeça", "livro", "caderno", "pelúcia", "fantasia",
    "bicicleta", "patins", "skate", "colchonete", "tapete", "jogo de cama",
    "feminina", "masculina adulto", "tênis", "sandália", "chinelo",
    "mochila", "bolsa", "nvme", "ssd", "m.2", "dock", "adaptador",
    "expansão", "pcie", "memória", "polaina", "cordão",
]

# LEGO é secundário: desconto mínimo maior e limite por ciclo
LEGO_TERMS = ["lego"]
# LEGO precisa ser de carro/veículo pra passar
LEGO_CAR_TERMS = [
    "speed champions", "technic", "carro", "car ", "f1", "formula",
    "ferrari", "porsche", "mclaren", "lamborghini", "bmw", "mercedes",
    "aston martin", "audi", "nissan", "toyota", "supra", "mustang",
    "camaro", "dodge", "ford", "bugatti", "koenigsegg", "pagani",
    "rally", "corrida", "race", "veículo", "senna", "bronco",
]
LEGO_MIN_DISCOUNT = 35
LEGO_MAX_PER_CYCLE = 2

# Cupons por ciclo (evita spam)
MAX_COUPONS_PER_CYCLE = 5


def load_relevant_terms():
    return _dynamic("relevant_terms", RELEVANT_TERMS)


def load_blocklist_terms():
    return _dynamic("blocklist_terms", BLOCKLIST)


def load_lego_car_terms():
    return _dynamic("lego_car_terms", LEGO_CAR_TERMS)


def load_enabled_stores():
    fallback = [item.strip() for item in
                os.getenv("ENABLED_STORES", "amazon,mercadolivre,shopee").split(",")
                if item.strip()]
    return _dynamic("enabled_stores", fallback)
