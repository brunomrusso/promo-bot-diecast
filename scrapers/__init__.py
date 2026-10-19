import config

try:
    from .mercadolivre_pw import search_mercadolivre
    from .ml_coupons import close_context as close_browser
except ImportError:  # playwright não instalado
    from .mercadolivre import search_mercadolivre
    def close_browser(): pass
try:
    from .shopee_pw import search_shopee
except ImportError:
    from .shopee import search_shopee
try:
    from .amazon_pw import search_amazon
except ImportError:
    from .amazon import search_amazon
from .lomadee import search_lomadee

_ALL = {
    "amazon": ("Amazon", search_amazon),
    "lomadee": ("Lomadee", search_lomadee),
    "mercadolivre": ("Mercado Livre", search_mercadolivre),
    "shopee": ("Shopee", search_shopee),
}

def get_scrapers():
    return [_ALL[key] for key in config.load_enabled_stores() if key in _ALL]


SCRAPERS = get_scrapers()
