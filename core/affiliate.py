import re
from urllib.parse import parse_qs, urlparse

import config


def is_monetized(url: str, store: str) -> bool:
    """Confere se o link final realmente gera comissão."""
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if parsed.scheme != "https" or parsed.username or parsed.password:
        return False
    if host in {"meli.la", "lmdee.link"}:
        return True
    return bool(store == "Amazon" and config.AMAZON_TAG
                and (host == "amazon.com.br" or host.endswith(".amazon.com.br"))
                and config.AMAZON_TAG in parse_qs(parsed.query).get("tag", []))


def _clean_amazon_url(url: str) -> str:
    """Reduce an Amazon URL to https://www.amazon.com.br/dp/ASIN (no tracking junk)."""
    m = re.search(r'/dp/([A-Z0-9]{10})', url)
    if not m:
        m = re.search(r'/gp/product/([A-Z0-9]{10})', url)
    if not m:
        m = re.search(r'/product/([A-Z0-9]{10})', url)
    if m:
        parsed = urlparse(url)
        return f"{parsed.scheme}://{parsed.netloc}/dp/{m.group(1)}"
    return url


def amazon_site_link(asin: str) -> str:
    """Link da Amazon usado no SITE: ID de rastreamento próprio do site (relatório separado do WhatsApp)."""
    return f"https://www.amazon.com.br/dp/{asin}?tag={config.AMAZON_TAG_SITE}"


def _cache_store(store: str) -> str:
    """O cache de links do ML é separado por etiqueta (link de um canal não vai para outro)."""
    return f"{store}#{config.ML_TAG_BOT}" if store == "Mercado Livre" and config.ML_TAG_BOT else store


ML_LINK_FALHAS_KEY = "ml_site_link_falhas"
ML_LINK_FALHA_HORAS = 12  # o ML recusou (HTTP 400/409): não reabre o Gerador de Links (proxy) a cada ciclo


def _falha_recente(falhas, product_url, agora):
    from datetime import datetime, timedelta
    quando = falhas.get(product_url)
    try:
        return bool(quando) and agora - datetime.fromisoformat(quando) < timedelta(hours=ML_LINK_FALHA_HORAS)
    except ValueError:
        return False


def ml_site_link(product_url: str, generate: bool = True, insistir: bool = False) -> str:
    """meli.la do SITE (etiqueta do site). Sem etiqueta configurada, usa o link normal do bot.

    Se o ML recusou gerar o link deste anúncio, espera ML_LINK_FALHA_HORAS antes de tentar de novo
    (antes tentava a cada ciclo de 15 min, abrindo o Gerador de Links pelo proxy o dia todo).
    insistir=True (pedido feito no painel) tenta mesmo assim."""
    from datetime import datetime
    from core import db
    tag = config.ML_TAG_SITE
    if not tag:
        return to_affiliate_url({"store": "Mercado Livre", "url": product_url}) if generate else \
            cached_affiliate_url({"store": "Mercado Livre", "url": product_url})
    cached = db.cached_affiliate_link(f"Mercado Livre#{tag}", product_url)
    if cached:
        return cached
    if not generate or not product_url:
        return ""
    agora = datetime.now()
    falhas = db.get_setting(ML_LINK_FALHAS_KEY, {}) or {}
    if not insistir and _falha_recente(falhas, product_url, agora):
        return ""
    from scrapers.ml_coupons import ml_affiliate_link, ml_available
    link = ml_affiliate_link(product_url, tag, fallback=False)
    if is_monetized(link, "Mercado Livre"):
        if falhas.pop(product_url, None):
            db.set_setting(ML_LINK_FALHAS_KEY, falhas)
        return link
    if ml_available():  # só conta como recusa do ML se a sessão estava ok
        falhas = {u: q for u, q in falhas.items() if _falha_recente(falhas, u, agora)}
        falhas[product_url] = agora.isoformat(timespec="seconds")
        db.set_setting(ML_LINK_FALHAS_KEY, falhas)
        print(f"[ML-link] site: o ML recusou {product_url[:70]}; nova tentativa em {ML_LINK_FALHA_HORAS} h")
    return link


def cached_affiliate_url(deal: dict) -> str:
    from core import db

    store, url = deal["store"], deal["url"]
    link = db.cached_affiliate_link(_cache_store(store), url)
    if link and is_monetized(link, store):
        return link
    if is_monetized(url, store):
        return url
    if store == "Amazon":
        link = _generate_affiliate_url(deal)
        if is_monetized(link, store):
            db.cache_affiliate_link(store, url, link)
            return link
    return ""


def to_affiliate_url(deal: dict) -> str:
    from core import db

    cached = cached_affiliate_url(deal)
    if cached:
        return cached
    link = _generate_affiliate_url(deal)
    if is_monetized(link, deal["store"]):
        db.cache_affiliate_link(_cache_store(deal["store"]), deal["url"], link)
    return link


def _generate_affiliate_url(deal: dict) -> str:
    """Converte a URL do produto em link de afiliado, conforme credenciais
    configuradas no .env. Sem credencial, retorna a URL original."""
    url = deal["url"]
    if deal.get("affiliate_ready"):
        return url
    store = deal["store"]

    if store == "Amazon" and config.AMAZON_TAG:
        clean = _clean_amazon_url(url)
        return f"{clean}?tag={config.AMAZON_TAG}"

    if store == "Shopee":
        # 1) Lomadee (Shopee é marca aderida): gera lmdee.link com comissão
        if config.LOMADEE_APP_TOKEN:
            try:
                from scrapers.lomadee import get_brand_id, _shorten
                org = get_brand_id("shopee")
                if org:
                    link = _shorten(org, url)
                    if link != url:
                        return link
            except Exception:
                pass
        # 2) fallback: sub-id do programa de afiliados da Shopee
        if config.SHOPEE_AFFILIATE_ID:
            sep = "&" if "?" in url else "?"
            return f"{url}{sep}af_siteid={config.SHOPEE_AFFILIATE_ID}"

    if store == "Mercado Livre":
        # gera meli.la de afiliado via Gerador de Links (sessão logada)
        try:
            from scrapers.ml_coupons import ml_affiliate_link
            return ml_affiliate_link(url, config.ML_TAG_BOT or None)
        except Exception:
            return url

    return url
