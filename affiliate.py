import re
from urllib.parse import urlparse

import config


def is_monetized(url: str, store: str) -> bool:
    """Confere se o link final realmente gera comissão."""
    if "meli.la" in url or "lmdee.link" in url:
        return True
    if store == "Amazon" and config.AMAZON_TAG \
            and f"tag={config.AMAZON_TAG}" in url:
        return True
    return False


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


def to_affiliate_url(deal: dict) -> str:
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
            return ml_affiliate_link(url)
        except Exception:
            return url

    return url
