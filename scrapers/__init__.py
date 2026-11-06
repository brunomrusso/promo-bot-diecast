import config

from .mercadolivre import ml_api_ready, search_mercadolivre as _search_ml_api
try:
    from .mercadolivre_pw import search_mercadolivre as _search_ml_pw
    from .ml_coupons import close_context as _close_ml_context
except ImportError:  # playwright não instalado
    _search_ml_pw = None
    def _close_ml_context(): pass


def navegador_ml_liberado():
    """Busca pelo navegador (usa o proxy, cobrado por GB) no máximo uma vez a cada N minutos
    (painel > Configurações > Tempos de busca). Dentro da mesma janela de 10 min, todas as buscas do ciclo passam."""
    import time
    from core import db
    janela = config.tempos()["ml_navegador_min"] * 60
    agora = time.time()
    inicio = float((db.get_system_state().get("ml_navegador_janela") or {}).get("value") or 0)
    if agora - inicio < 600:
        return True
    if agora - inicio >= janela - 30:
        db.set_system_state("ml_navegador_janela", agora)
        return True
    return False


def search_mercadolivre(keyword: str, min_discount: int):
    """Prefere a API oficial (token OAuth, sem proxy, a cada ciclo); navegador só como plano B e com limite de tempo."""
    if ml_api_ready():
        deals = _search_ml_api(keyword, min_discount)
        if deals is not None:
            return deals
        print(f"[ML] API falhou em '{keyword}'; usando o navegador")
    if _search_ml_pw:
        if not navegador_ml_liberado():
            print(f"[ML] '{keyword}': navegador fora da janela (economia de proxy); fica para a próxima")
            return []
        return _search_ml_pw(keyword, min_discount)
    raise RuntimeError("API do Mercado Livre indisponível e Playwright não instalado")
try:
    from .shopee_pw import search_shopee
except ImportError:
    from .shopee import search_shopee
try:
    from .amazon_pw import close_context as _close_amazon_context
    from .amazon_pw import search_amazon
except ImportError:
    from .amazon import search_amazon
    def _close_amazon_context(): pass


def close_browser():
    for close in (_close_ml_context, _close_amazon_context):
        try:
            close()
        except Exception:
            pass
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
