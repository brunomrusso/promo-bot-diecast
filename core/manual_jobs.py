import hashlib
import json
import re
import logging
import math
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, unquote, urlencode, urljoin, urlparse, urlunparse
from zoneinfo import ZoneInfo

import requests as http_requests
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from bs4 import BeautifulSoup

from core import db, filters
from core.affiliate import is_monetized, to_affiliate_url
from core.notifier import format_whatsapp, send_deal, send_whatsapp_ready
from scrapers import get_scrapers
from scrapers.ml_coupons import _get_context, mark_ml_ready, mark_ml_verification, ml_available


def _number(value):
    if value is None:
        return 0
    if isinstance(value, (int, float)):
        return float(value)
    value = str(value).replace("R$", "").strip()
    if "," in value:
        value = value.replace(".", "").replace(",", ".")
    match = re.search(r"\d+(?:\.\d+)?", value)
    return float(match.group()) if match else 0


def _store(url):
    host = urlparse(url).netloc.lower()
    if "mercadolivre" in host or "meli.la" in host:
        return "Mercado Livre"
    if _is_amazon(host):
        return "Amazon"
    if "shopee" in host:
        return "Shopee"
    return "Lomadee"


def _is_amazon(host):
    return any(h in host for h in ("amazon", "amzn", "a.co"))


def _clean_url(url):
    """Remove tracking params and normalise the URL before extraction."""
    parsed = urlparse(url)
    host = parsed.netloc.lower()

    # Amazon shorteners: leave as-is for resolution in _extract_amazon_fast
    if any(h in host for h in ("link.amazon", "amzn.to", "amzn.com/", "a.co")):
        return url
    # Amazon full URLs: reduce to /dp/ASIN
    if _is_amazon(host):
        asin = _extract_asin(url)
        if asin:
            return f"{parsed.scheme}://{parsed.netloc}/dp/{asin}"
    # Mercado Livre: strip tracking params; if the pasted link is an
    # affiliate/social redirect, extract the embedded product URL first.
    if "mercadolivre" in host or "mercadolibre" in host or "meli.la" in host:
        if host == "meli.la" or parsed.path.lower().startswith("/social/"):
            return url
        for key in ("url", "link", "redirect", "adurl", "u"):
            candidate = parse_qs(parsed.query).get(key)
            if candidate:
                embedded = urlparse(unquote(candidate[0]))
                if "mercadolivre" in (embedded.hostname or "").lower():
                    return _clean_url(unquote(candidate[0]))
        params = parse_qs(parsed.query)
        selection = {key: params[key] for key in ("pdp_filters", "searchVariation", "variation_id")
                     if key in params}
        return urlunparse(parsed._replace(query=urlencode(selection, doseq=True), fragment=""))
    # Shopee: strip tracking params
    if "shopee" in host:
        return urlunparse(parsed._replace(query="", fragment=""))
    return url


_INTL_MARKERS = (
    "compra internacional", "envio internacional", "produto internacional",
    "import fees", "taxas de importação", "taxa de importação",
    "mercado livre global",
)


def _is_international(text):
    """Detect international-purchase markers in the page content."""
    lower = (text or "").lower()
    if any(marker in lower for marker in _INTL_MARKERS):
        return True
    # Amazon BR: domestic seller is "Amazon.com.br"; US seller shows "Amazon.com"
    if '"merchantName":"Amazon.com"' in text or \
            re.search(r"vendido\s+por:?\s*amazon\.com(?![.\w])", lower):
        return True
    return False


def _extract_asin(url):
    """Extract Amazon ASIN from various URL formats."""
    m = re.search(r'/dp/([A-Z0-9]{10})', url)
    if m:
        return m.group(1)
    m = re.search(r'/gp/product/([A-Z0-9]{10})', url)
    if m:
        return m.group(1)
    m = re.search(r'/product/([A-Z0-9]{10})', url)
    if m:
        return m.group(1)
    return None


_AMAZON_HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/125.0.0.0 Safari/537.36"),
    "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
}


def _resolve_short_link(url, max_hops=8):
    """Follow redirects manually (without downloading body) to find the final URL."""
    current = url
    for _ in range(max_hops):
        try:
            resp = http_requests.head(current, headers=_AMAZON_HEADERS, timeout=8,
                                       allow_redirects=False)
            if resp.status_code in (301, 302, 303, 307, 308) and resp.headers.get("Location"):
                current = resp.headers["Location"]
                continue
        except http_requests.RequestException:
            pass
        # HEAD may not give Location; try GET without downloading body
        try:
            resp = http_requests.get(current, headers=_AMAZON_HEADERS, timeout=10,
                                      allow_redirects=False, stream=True)
            if resp.status_code in (301, 302, 303, 307, 308) and resp.headers.get("Location"):
                current = resp.headers["Location"]
                resp.close()
                continue
            resp.close()
        except http_requests.RequestException:
            pass
        break
    return current


def _resolve_and_fetch_amazon(url):
    """Resolve shortened Amazon URLs and return (clean_url, html_text).

    For short links we follow redirects manually to discover the ASIN,
    then make a single clean GET to the /dp/ASIN page. This avoids the
    Amazon anti-bot block that happens when following redirect chains.
    """
    host = urlparse(url).netloc.lower()
    is_short = any(h in host for h in ("link.amazon", "amzn.to", "amzn.com", "a.co"))

    if is_short:
        resolved = _resolve_short_link(url)
        asin = _extract_asin(resolved)
        if asin:
            parsed = urlparse(resolved)
            domain = parsed.netloc or "www.amazon.com.br"
            scheme = parsed.scheme or "https"
            clean = f"{scheme}://{domain}/dp/{asin}"
        else:
            clean = resolved
    else:
        asin = _extract_asin(url)
        parsed = urlparse(url)
        domain = parsed.netloc or "www.amazon.com.br"
        scheme = parsed.scheme or "https"
        clean = f"{scheme}://{domain}/dp/{asin}" if asin else url

    # Single clean fetch of the product page
    import time as _time
    resp = http_requests.get(clean, headers=_AMAZON_HEADERS, timeout=20,
                              allow_redirects=True)
    # Amazon anti-bot returns a tiny page (<10KB); retry once after a pause
    if len(resp.text) < 10000:
        _time.sleep(3)
        resp = http_requests.get(clean, headers=_AMAZON_HEADERS, timeout=20,
                                  allow_redirects=True)
    return clean, resp.text


def _extract_amazon_fast(url):
    """Fast Amazon extraction using HTTP requests instead of Playwright."""
    clean, html_text = _resolve_and_fetch_amazon(url)

    title = ""
    image = ""
    price = 0
    original = 0

    # --- Title ---
    # 1) og:title
    m = re.search(r'<meta[^>]+property="og:title"[^>]+content="([^"]+)"', html_text)
    if m:
        title = m.group(1)
    # 2) <title> fallback
    if not title:
        m = re.search(r'<title[^>]*>([^<]+)</title>', html_text)
        if m:
            title = m.group(1).split("|")[0].split(":")[0].strip()
            title = re.sub(r'\s*-\s*Amazon.*$', '', title)

    # --- Image ---
    # 1) data-old-hires (high-res product image)
    m = re.search(r'data-old-hires="([^"]+)"', html_text)
    if m:
        image = m.group(1)
    # 2) og:image fallback
    if not image:
        m = re.search(r'<meta[^>]+property="og:image"[^>]+content="([^"]+)"', html_text)
        if m:
            image = m.group(1)
    # 3) landingImage data-a-dynamic-image fallback
    if not image:
        m = re.search(r'id="landingImage"[^>]+data-a-dynamic-image="\{([^}]+)\}', html_text)
        if m:
            img_match = re.search(r'https://[^"]+', m.group(1).replace("&quot;", '"'))
            if img_match:
                image = img_match.group()

    # --- Price: Buy Box only ---
    # Amazon pages have multiple prices (marketplace sellers, other offers).
    # The Buy Box price is the one customers see. We extract it specifically.

    # Strategy 1: find price near the Buy Box / apex area
    for buybox_marker in ["apex_desktop", "corePrice_desktop", "corePriceDisplay",
                          "price_inside_buybox", "newBuyBoxPrice",
                          "apex_offerDisplay_desktop", "buybox-tabular"]:
        idx = html_text.find(buybox_marker)
        if idx < 0:
            continue
        chunk = html_text[idx:idx+3000]
        for raw in re.findall(r'a-offscreen[^>]*>([^<]+)', chunk):
            val = _number(raw)
            if val > 0:
                price = val
                break
        if price:
            break

    # Strategy 2: first a-offscreen in the page (usually the main price)
    if not price:
        for raw in re.findall(r'a-offscreen[^>]*>([^<]+)', html_text):
            val = _number(raw)
            if val > 0:
                price = val
                break

    # Strategy 3: ld+json (may contain marketplace prices — use only as fallback)
    for m in re.finditer(r'<script[^>]+type="application/ld\+json"[^>]*>(.*?)</script>',
                         html_text, re.DOTALL):
        try:
            data = json.loads(m.group(1))
            product = next(_json_products(data), None)
            if not product:
                continue
            title = product.get("name") or title
            raw_img = product.get("image", "")
            if raw_img and not image:
                image = raw_img[0] if isinstance(raw_img, list) else raw_img
            if not price:
                offers = product.get("offers", {})
                if isinstance(offers, list):
                    offers = offers[0] if offers else {}
                price = _number(offers.get("price") or offers.get("lowPrice"))
            break
        except (ValueError, TypeError, StopIteration):
            continue

    # Strategy 4: a-price-whole
    if not price:
        for raw in re.findall(r'a-price-whole[^>]*>([^<]+)', html_text):
            val = _number(raw)
            if val > 0:
                fraction = ""
                mf = re.search(r'a-price-fraction[^>]*>([^<]+)', html_text)
                if mf:
                    fraction = mf.group(1).strip()
                price = _number(str(int(val)) + "," + fraction)
                break

    # --- Original/list price (strikethrough price) ---
    m = re.search(r'class="a-text-price"[^>]*><span[^>]*>([^<]+)', html_text)
    if m:
        original = _number(m.group(1))

    store = "Amazon"
    discount = round((1 - price / original) * 100) if original > price > 0 else 0

    return {
        "id": "manual-" + hashlib.sha1(clean.encode()).hexdigest()[:16],
        "store": store,
        "title": title,
        "price": price,
        "original_price": original or price,
        "discount": discount,
        "url": clean,
        "image": image,
        "international": _is_international(html_text),
        "_error": None,
    }


def _json_products(value):
    if isinstance(value, list):
        for item in value:
            yield from _json_products(item)
    elif isinstance(value, dict):
        kind = value.get("@type")
        if kind == "Product" or (isinstance(kind, list) and "Product" in kind):
            yield value
        for item in value.get("@graph", []):
            yield from _json_products(item)


def _resolve_promotion_product(url):
    host = (urlparse(url).hostname or "").lower()
    if host not in {"uaidesconto.link", "www.uaidesconto.link"}:
        return url
    response = http_requests.get(
        url, headers={**_AMAZON_HEADERS, "Accept-Encoding": "gzip, deflate"},
        timeout=20, allow_redirects=False)
    response.raise_for_status()
    match = re.search(r'<script\b[^>]*\bid=[\"\']__NEXT_DATA__[\"\'][^>]*>(.*?)</script>',
                      response.text, re.DOTALL)
    if match:
        try:
            product = json.loads(match.group(1))["props"]["pageProps"]["product"]
            candidates = [product.get("originalValues", {}).get("url"),
                          product.get("initial_link")]
            for candidate in candidates:
                if not isinstance(candidate, str):
                    continue
                parsed = urlparse(candidate)
                hostname = (parsed.hostname or "").lower()
                if (parsed.scheme == "https" and not parsed.username
                        and not parsed.password
                        and (hostname == "mercadolivre.com.br"
                             or hostname.endswith(".mercadolivre.com.br"))
                        and re.search(r'/(?:up/MLBU\d+|p/MLB\d+)|/MLB-?\d+', parsed.path)):
                    return _clean_url(candidate)
        except (ValueError, KeyError, TypeError, AttributeError):
            pass
    raise ValueError("Não foi possível recuperar o produto desta página de divulgação. "
                     "Cole o link da página do produto, não o perfil do afiliado.")


def _social_product_url(page):
    links = page.get_by_role("link", name="Ir para produto", exact=True)
    try:
        links.first.wait_for(state="visible", timeout=8000)
    except PlaywrightTimeoutError:
        raise ValueError("O perfil abriu sem um produto compartilhado em destaque. "
                         "Nenhum item das recomendações foi selecionado.") from None
    candidates = set()
    for href in links.evaluate_all("els => els.map(e => e.href)"):
        parsed = urlparse(href)
        host = (parsed.hostname or "").lower()
        if (parsed.scheme == "https" and not parsed.username and not parsed.password
                and parsed.port in (None, 443)
                and (host == "mercadolivre.com.br" or host.endswith(".mercadolivre.com.br"))
                and re.search(r'/(?:up/MLBU\d+|p/MLB\d+)|/MLB-?\d+', parsed.path)):
            candidates.add(_clean_url(href))
    if len(candidates) != 1:
        raise ValueError("O compartilhamento não identificou um único produto com segurança.")
    return candidates.pop()


def _ml_product_url(url):
    """Resolve only the shared product, never profile recommendations."""
    for _ in range(5):
        parsed = urlparse(url)
        host = (parsed.hostname or "").lower()
        if (parsed.scheme != "https" or parsed.username or parsed.password
                or parsed.port not in (None, 443)
                or not (host == "meli.la" or host == "mercadolivre.com.br"
                        or host.endswith(".mercadolivre.com.br"))):
            return None
        if re.search(r'/p/MLB\d+', parsed.path):
            return _clean_url(url)
        if host != "meli.la" and not parsed.path.startswith("/social/"):
            return None
        response = http_requests.get(url, timeout=5, allow_redirects=False)
        if response.is_redirect:
            url = urljoin(url, response.headers.get("Location", ""))
            continue
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")
        targets = {urljoin(url, a["href"]) for a in soup.select("a[href]")
                   if " ".join(a.stripped_strings).casefold() == "ir para produto"}
        if len(targets) != 1:
            return None
        url = targets.pop()
    return None


def _extract_ml_api(url):
    from scrapers.mercadolivre import _api, ml_api_ready

    if not ml_api_ready():
        return None
    product_url = _ml_product_url(url)
    if not product_url:
        return None
    parsed = urlparse(product_url)
    catalog_id = re.search(r'/p/(MLB\d+)', parsed.path).group(1)
    # A catalog can contain hundreds of sellers. Never substitute the cheapest.
    selected = re.search(r'(?:^|;)item_id:(MLB\d+)(?:;|$)',
                         parse_qs(parsed.query).get("pdp_filters", [""])[0])
    if not selected:
        return None
    # Variation-specific links need the browser until variant matching is supported.
    if any(key in parse_qs(parsed.query) for key in ("variation_id", "searchVariation")):
        return None
    product = _api(f"/products/{catalog_id}")
    if not product:
        return None
    offers = _api(f"/products/{catalog_id}/items")
    if not offers:
        return None
    offer = next((item for item in offers.get("results", [])
                  if str(item.get("item_id", "")).replace("-", "") == selected.group(1)), None)
    if not offer or offer.get("currency_id") != "BRL":
        return None
    price = float(offer.get("price") or 0)
    pictures = product.get("pictures") or []
    image = pictures[0].get("url", "") if pictures else ""
    if not math.isfinite(price) or price <= 0 or not product.get("name") or not image:
        return None
    original = float(offer.get("original_price") or price)
    if not math.isfinite(original) or original < price:
        original = price
    return {
        "id": "manual-" + hashlib.sha1(product_url.encode()).hexdigest()[:16],
        "store": "Mercado Livre", "title": product["name"],
        "url": product_url, "price": price, "original_price": original,
        "discount": round((1 - price / original) * 100) if original > price else 0,
        "image": image, "international": False, "origin": "unknown",
        "_error": None,
    }


def extract_link(url):
    start = time.monotonic()
    source = url
    url = _clean_url(_resolve_promotion_product(url))
    deal = None
    method = "browser"
    if _store(url) == "Mercado Livre":
        try:
            deal = _extract_ml_api(url)
        except (http_requests.RequestException, ValueError, TypeError, KeyError):
            # API denial, missing data or timeout must keep the existing fallback.
            logging.getLogger(__name__).info("ML manual API unavailable; using browser")
        if deal:
            method = "ml_catalog_api"
    if deal is None:
        deal = _extract_link_browser(url)
        if deal["store"] == "Amazon":
            method = "amazon_http"
    # Keep the submitted affiliate link even when extraction used its destination.
    if (deal["store"] == "Mercado Livre" and not deal.get("_error")
            and (urlparse(source).hostname or "").lower() == "meli.la"
            and is_monetized(source, "Mercado Livre")):
        deal["affiliate_url"] = source
    deal["extraction_method"] = method
    deal["extraction_seconds"] = round(time.monotonic() - start, 3)
    logging.getLogger(__name__).info("Manual extraction method=%s seconds=%.3f",
                                   method, deal["extraction_seconds"])
    return deal


def _extract_link_browser(url):
    url = _clean_url(url)
    store = _store(url)
    # Amazon: fast HTTP extraction (no Playwright needed)
    if store == "Amazon":
        return _extract_amazon_fast(url)
    ctx = _get_context()
    page = ctx.new_page()
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(1500)
        final_url = page.url
        if (_store(final_url) == "Mercado Livre"
                and urlparse(final_url).path.lower().startswith("/social/")):
            product_url = _social_product_url(page)
            page.goto(product_url, wait_until="domcontentloaded", timeout=30000)
            page.wait_for_timeout(1500)
            final_url = page.url
            if urlparse(final_url).path.lower().startswith("/social/"):
                raise ValueError("O Mercado Livre não abriu a página do produto compartilhado.")
        body_text = page.inner_text("body")
        body_lower = body_text[:4000].lower()
        title = ""
        image = ""
        price = 0
        original = 0
        for script in page.query_selector_all('script[type="application/ld+json"]'):
            try:
                data = json.loads(script.inner_text())
                product = next(_json_products(data), None)
                if not product:
                    continue
                title = product.get("name", title)
                raw_image = product.get("image", image)
                image = raw_image[0] if isinstance(raw_image, list) else raw_image
                offers = product.get("offers", {})
                if isinstance(offers, list):
                    offers = offers[0] if offers else {}
                price = _number(offers.get("price") or offers.get("lowPrice"))
                break
            except (ValueError, TypeError, StopIteration):
                continue
        title = title or page.title().split("|")[0].strip()
        if not image:
            meta = page.query_selector('meta[property="og:image"]')
            image = meta.get_attribute("content") if meta else ""
        if not price:
            selectors = [
                ".andes-money-amount__fraction",
                ".a-price .a-offscreen",
                "[itemprop='price']",
            ]
            for selector in selectors:
                element = page.query_selector(selector)
                if element:
                    price = _number(element.get_attribute("content") or element.inner_text())
                    if price:
                        break
        original_selectors = [
            ".andes-money-amount--previous .andes-money-amount__fraction",
            ".a-price.a-text-price .a-offscreen",
        ]
        for selector in original_selectors:
            element = page.query_selector(selector)
            if element:
                original = _number(element.inner_text())
                if original:
                    break
        store = _store(final_url)
        product_url = _clean_url(final_url)
        discount = round((1 - price / original) * 100) if original > price > 0 else 0
        is_captcha = (
            "captcha" in final_url
            or "wall/logged" in final_url
            or "segurança" in title.lower()
            or "verificação" in body_lower
            or "captcha" in body_lower
        )
        if store == "Mercado Livre":
            mark_ml_verification(final_url) if is_captcha else mark_ml_ready()
        return {
            "id": "manual-" + hashlib.sha1(product_url.encode()).hexdigest()[:16],
            "store": store,
            "title": title,
            "price": price,
            "original_price": original or price,
            "discount": discount,
            "url": product_url,
            "image": image,
            "international": _is_international(body_text),
            "_error": "Mercado Livre exige verificação de segurança. Recarregue a sessão." if is_captcha else None,
        }
    finally:
        page.close()


def normalize_manual_coupon(deal):
    """Cupom do anúncio: nenhum campo é obrigatório.
    - só o código: o texto mostra o cupom, sem "preço com cupom";
    - desconto (com ou sem código): calcula o preço final (ou usa o final que você confirmou);
    - só o preço final: mostra "com cupom" sem código (cupom para ativar na página do produto).
    Regras informadas que não batem (compra mínima maior que o preço, final >= preço) continuam bloqueando."""
    code = str(deal.get("manual_coupon_code", "") or "").strip().upper()
    value = float(deal.get("manual_coupon_value") or 0)
    final_in = float(deal.get("manual_coupon_final_price") or 0)
    if not code and value <= 0 and final_in <= 0:
        for key in list(deal):
            if key.startswith("manual_coupon_"):
                deal.pop(key, None)
        return deal
    price = float(deal.get("price") or 0)
    kind = deal.get("manual_coupon_type", "fixed") or "fixed"
    minimum = float(deal.get("manual_coupon_min_purchase") or 0)
    cap = float(deal.get("manual_coupon_max_discount") or 0)
    final = 0.0
    if value > 0 or final_in > 0:
        if price <= 0:
            raise ValueError("Informe o preço do produto para calcular o cupom")
        if minimum and price < minimum:
            raise ValueError("O produto não atinge a compra mínima do cupom")
        if value > 0:
            discount = price * value / 100 if kind == "percent" else value
            if cap:
                discount = min(discount, cap)
            final = final_in or max(0, price - discount)
        else:
            final = final_in
        if final <= 0 or final >= price:
            raise ValueError("O preço final com cupom deve ser menor que o preço atual")
    deal.update({
        "manual_coupon_code": code,
        "manual_coupon_type": kind,
        "manual_coupon_value": value,
        "manual_coupon_min_purchase": minimum,
        "manual_coupon_max_discount": cap,
        "manual_coupon_final_price": round(final, 2),
    })
    return deal


def publish_deal(deal):
    deal = normalize_manual_coupon(deal)
    rule = db.match_brand_rule(deal["title"])
    if rule and not db.brand_limit_available(rule):
        raise ValueError(f"Limite diário de {rule['name']} atingido")
    link = deal.pop("affiliate_url", "") or to_affiliate_url(deal)
    if not is_monetized(link, deal["store"]):
        raise ValueError("O link não está monetizado")
    if not send_deal(deal, link):
        raise ValueError("O Telegram recusou a publicação")
    if deal.get("_pending_id"):
        db.set_status(deal["_pending_id"], "posted",
                      rule["id"] if rule else None, rule["name"] if rule else "")
    else:
        db.mark_posted(deal["id"], deal["store"], deal["title"],
                       deal.get("price", 0), url=deal["url"], image=deal.get("image", ""),
                       original_price=deal.get("original_price", 0),
                       discount=deal.get("discount", 0),
                       brand_rule_id=rule["id"] if rule else None,
                       brand_name=rule["name"] if rule else "")
    db.record_publication_details(deal.get("_pending_id") or deal["id"], deal, link)
    db.record_product_price(deal, "approved")
    db.supersede_pending([s["product_id"] for s in db.similar_pending(
        deal["title"], exclude_id=deal.get("_pending_id") or deal["id"])])
    return {"published": True, "whatsapp": format_whatsapp(deal, link),
            "affiliate_url": link}


def run_coupon_blitz(payload: dict) -> dict:
    """Varredura de cupom relâmpago: busca preço atual por mini, aplica o
    cupom e enfileira pendentes para aprovação."""
    from scrapers import _ALL
    from scrapers.lomadee import coupon_status
    from scrapers.mercadolivre import ml_coupon_status
    code = str(payload.get("code", "")).strip().upper()
    store = payload.get("store") or "Mercado Livre"
    scraper = dict(get_scrapers() or _ALL.values()).get(store)
    verification = (ml_coupon_status(code) if store == "Mercado Livre"
                    else coupon_status(code))
    if verification == "unverifiable":
        verification = coupon_status(code)
    summary = {"code": code, "store": store, "verification": verification,
               "queued": 0, "skipped": [], "errors": []}
    if not scraper:
        summary["errors"].append(f"Loja {store} não está habilitada")
        return summary
    notified = 0
    for item_id in payload.get("item_ids", []):
        item = db.get_monitored_item(item_id)
        if not item:
            summary["skipped"].append(f"mini #{item_id}: não encontrada")
            continue
        offers, seen = [], set()
        for query in filters.search_queries(item["search_terms"]) or [item["search_terms"]]:
            try:
                offers.extend(scraper(query, 0))
            except Exception as exc:
                summary["errors"].append(f"{item['name']}: {str(exc)[:120]}")
        matches = []
        for deal in offers:
            if deal["id"] in seen or not deal.get("price"):
                continue
            seen.add(deal["id"])
            if filters.monitored_match_diagnostic(deal, item)["matches"]:
                matches.append(deal)
        candidates = [d for d in matches if d.get("origin") != "international"] or matches
        if not candidates:
            summary["skipped"].append(f"{item['name']}: sem oferta correspondente")
            continue
        best = min(candidates, key=lambda d: d["price"])
        deal = dict(best, manual_coupon_code=code,
                    manual_coupon_type=payload.get("kind", "percent"),
                    manual_coupon_value=payload.get("value", 0),
                    manual_coupon_min_purchase=payload.get("min_purchase", 0),
                    manual_coupon_max_discount=payload.get("cap", 0),
                    manual_coupon_final_price="")
        try:
            deal = normalize_manual_coupon(deal)
        except ValueError as exc:
            summary["skipped"].append(f"{item['name']}: {exc}")
            continue
        verification_label = {"verified": "verificado no feed Lomadee",
                              "not_found": "não consta no feed — confirme no checkout",
                              "unverifiable": "verificação indisponível"}[summary["verification"]]
        note = (f"Cupom {code} · R$ {best['price']:.2f} → R$ "
                f"{deal['manual_coupon_final_price']:.2f} · {verification_label}")
        if db.enqueue_coupon_deal(item_id, deal, deal, note):
            summary["queued"] += 1
            if notified < 10:
                try:
                    if send_approval_ping(deal, summary["verification"]):
                        notified += 1
                except Exception:
                    pass
    return summary


def send_approval_ping(deal: dict, verification: str) -> bool:
    """Notifica o admin no Telegram com os botões de aprovação."""
    from core.notifier import send_for_approval
    verify_label = {"verified": "✅ verificado", "not_found": "⚠️ confirme no checkout",
                    "unverifiable": "⚠️ não verificável"}[verification]
    heading = (f"🎟️ <b>CUPOM {deal['manual_coupon_code']}</b> ({verify_label})\n"
               f"Final estimado: R$ {deal['manual_coupon_final_price']:.2f}\n\n")
    return send_for_approval(deal, "", heading=heading)


def process_scheduled():
    for blitz in db.due_blitzes():
        db.set_blitz_status(blitz["id"], "running")
        try:
            db.set_blitz_status(blitz["id"], "done", run_coupon_blitz(blitz["payload"]))
        except Exception as exc:
            db.set_blitz_status(blitz["id"], "error", error=str(exc))
    settings = db.get_setting("schedule", {
        "quiet_start": "23:00", "quiet_end": "08:00",
        "min_interval": 10, "timezone": "America/Sao_Paulo"})
    zone = ZoneInfo(settings.get("timezone", "America/Sao_Paulo"))
    now_utc = datetime.now(timezone.utc)
    now_local = now_utc.astimezone(zone)
    start = datetime.strptime(settings["quiet_start"], "%H:%M").time()
    end = datetime.strptime(settings["quiet_end"], "%H:%M").time()
    quiet = (now_local.time() >= start or now_local.time() < end) if start > end \
        else start <= now_local.time() < end
    for item in db.due_scheduled_posts():
        if quiet:
            end_local = datetime.combine(now_local.date(), end, zone)
            if now_local.time() >= start:
                end_local += timedelta(days=1)
            db.reschedule_post(item["id"], end_local.astimezone(timezone.utc)
                               .replace(tzinfo=None).isoformat(sep=" ", timespec="seconds"))
            continue
        last = db.last_scheduled_publication()
        if last:
            last_time = datetime.fromisoformat(last).replace(tzinfo=timezone.utc)
            allowed = last_time + timedelta(minutes=int(settings.get("min_interval", 10)))
            if now_utc < allowed:
                db.reschedule_post(item["id"], allowed.replace(tzinfo=None)
                                   .isoformat(sep=" ", timespec="seconds"))
                continue
        try:
            publish_deal(item["deal"])
            db.set_scheduled_status(item["id"], "published")
        except Exception as exc:
            db.set_scheduled_status(item["id"], "error", str(exc))


def process_jobs(urgent_only=False):
    for row in db.claim_jobs(urgent_only=urgent_only):
        try:
            payload = json.loads(row["payload"])
            if row["action"] == "restart_bot":
                db.finish_job(row["id"], {"restarting": True})
                raise SystemExit(0)
            if row["action"] == "extract":
                deal = extract_link(payload["url"])
                if deal.get("_error"):
                    raise ValueError(deal["_error"])
                if payload.get("only_data"):  # cadastro de mini pelo link: só os dados, sem gerar link de afiliado
                    db.finish_job(row["id"], deal)
                    continue
                stage_start = time.monotonic()
                link = deal.get("affiliate_url") or to_affiliate_url(deal)
                deal["monetization_seconds"] = round(time.monotonic() - stage_start, 3)
                deal["affiliate_url"] = link
                deal["monetized"] = is_monetized(link, deal["store"])
                stage_start = time.monotonic()
                deal["whatsapp"] = format_whatsapp(deal, link)
                deal["formatting_seconds"] = round(time.monotonic() - stage_start, 3)
                db.finish_job(row["id"], deal)
            elif row["action"] == "scan_monitored":
                item = db.get_monitored_item(payload["item_id"])
                if not item:
                    raise ValueError("Mini monitorada não encontrada")
                results = []
                seen = set()
                diagnostics = []
                scrapers = get_scrapers()
                for idx, (store_name, scraper) in enumerate(scrapers, 1):
                    db.set_system_state("scan_progress", {
                        "item_id": item["id"], "store": store_name,
                        "index": idx, "total": len(scrapers)})
                    report = {"store": store_name, "received": 0, "matched": 0,
                              "discarded": 0, "duplicates": 0, "missing_terms": {},
                              "samples": [], "status": "ok"}
                    diagnostics.append(report)
                    offers = []
                    query_errors = []
                    for query in filters.search_queries(item["search_terms"]) or [item["search_terms"]]:
                        try:
                            offers.extend(scraper(query, 0))
                        except Exception as exc:
                            query_errors.append(f"{query}: {exc}"[:200])
                    if not offers and query_errors:
                        report.update(status="error", error="; ".join(query_errors))
                        continue
                    report["received"] = len(offers)
                    if not offers:
                        report["status"] = "empty"
                        if store_name == "Mercado Livre" and not ml_available():
                            report.update(status="error", error="Mercado Livre requer verificação manual da sessão")
                    for deal in offers:
                        if deal["id"] in seen:
                            report["duplicates"] += 1
                            continue
                        match = filters.monitored_match_diagnostic(deal, item)
                        if not match["matches"]:
                            report["discarded"] += 1
                            for term in match["missing_terms"]:
                                report["missing_terms"][term] = report["missing_terms"].get(term, 0) + 1
                            if len(report["samples"]) < 5:
                                report["samples"].append({"title": deal["title"], "reasons": match["reasons"]})
                            continue
                        report["matched"] += 1
                        seen.add(deal["id"])
                        db.record_price(item["id"], deal)
                        db.record_product_price(deal)
                        deal["previously_posted"] = db.already_posted(deal["id"])
                        deal["fair_price"] = deal["price"] <= item["max_price"]
                        deal["quality"] = db.deal_price_quality(
                            deal["title"], deal["price"], item["id"])
                        results.append(deal)
                    process_jobs(urgent_only=True)
                results.sort(key=lambda deal: deal["price"])
                if results:
                    minimum = results[0]["price"]
                    stores = len(set(deal["store"] for deal in results))
                    for deal in results:
                        deal["comparison"] = {
                            "count": len(results), "stores": stores,
                            "min_price": minimum, "best": deal["price"] == minimum,
                        }
                scan_result = {
                    "item": item, "results": results[:30], "matches_total": len(results),
                    "stores_searched": len(scrapers), "diagnostics": diagnostics,
                    "completed_at": datetime.utcnow().isoformat(timespec="seconds"),
                }
                db.set_setting(f"monitored_scan_{item['id']}", scan_result)
                db.set_system_state("scan_progress", {})
                db.finish_job(row["id"], scan_result)
            elif row["action"] == "share_monitored":
                if not db.get_monitored_item(payload["item_id"]):
                    raise ValueError("Mini monitorada não encontrada")
                deal = normalize_manual_coupon(payload["deal"])
                link = to_affiliate_url(deal)
                if not is_monetized(link, deal["store"]):
                    raise ValueError("Não foi possível gerar um link monetizado para compartilhar")
                db.finish_job(row["id"], {"whatsapp": format_whatsapp(deal, link),
                                          "affiliate_url": link})
            elif row["action"] == "share_pending":
                pending = db.get_pending(payload["product_id"])
                if not pending:
                    raise ValueError("Oferta já foi decidida ou não existe")
                store, title, price, url, image, original, discount = pending
                deal = {"id": payload["product_id"], "store": store, "title": title,
                        "price": price, "url": url, "image": image,
                        "original_price": original, "discount": discount}
                link = to_affiliate_url(deal)
                if not is_monetized(link, store):
                    raise ValueError("Não foi possível gerar um link monetizado para compartilhar")
                db.finish_job(row["id"], {"whatsapp": format_whatsapp(deal, link),
                                          "affiliate_url": link})
            elif row["action"] == "approve_pending":
                pending = db.get_pending(payload["product_id"])
                if not pending:
                    raise ValueError("Oferta já foi decidida ou não existe")
                store, title, price, url, image, original, discount = pending
                fresh = extract_link(url)
                if not fresh.get("price"):
                    db.set_status(payload["product_id"], "expired")
                    raise ValueError("A oferta não está mais disponível")
                title, price = fresh["title"] or title, fresh["price"]
                image = fresh.get("image") or image
                original = fresh.get("original_price") or price
                discount = fresh.get("discount", 0)
                deal = normalize_manual_coupon({
                    "id": payload["product_id"], "store": store, "title": title,
                    "price": price, "url": url, "image": image,
                    "original_price": original, "discount": discount,
                    **(payload.get("coupon") or db.pending_coupon_fields(payload["product_id"])),
                })
                rule = db.match_brand_rule(deal["title"])
                if rule and not db.brand_limit_available(rule):
                    raise ValueError(f"Limite diário de {rule['name']} atingido")
                link = to_affiliate_url(deal)
                if not is_monetized(link, deal["store"]):
                    raise ValueError("O link não está monetizado")
                if not send_deal(deal, link):
                    raise ValueError("O Telegram recusou a publicação")
                db.set_status(deal["id"], "posted",
                              rule["id"] if rule else None,
                              rule["name"] if rule else "")
                db.record_publication_details(deal["id"], deal, link)
                db.record_product_price(deal, "approved")
                db.supersede_pending([s["product_id"] for s in db.similar_pending(
                    deal["title"], exclude_id=deal["id"])])
                send_whatsapp_ready(deal, link)
                db.finish_job(row["id"], {
                    "published": True,
                    "whatsapp": format_whatsapp(deal, link),
                    "affiliate_url": link,
                })
            elif row["action"] == "publish":
                db.finish_job(row["id"], publish_deal(payload["deal"]))
            elif row["action"] == "site_achadinho_add":
                from core import site_achadinhos
                db.finish_job(row["id"], site_achadinhos.add(payload.get("url", ""), payload.get("preco_alvo"),
                                                             payload.get("categoria")))
            elif row["action"] == "site_ranking_publish_preview":
                from core import site_ranking
                db.finish_job(row["id"], site_ranking.publish_preview())
            elif row["action"] == "site_ranking":
                from core import site_ranking
                result = site_ranking.run(publish=bool(payload.get("publish")), origem="painel",
                                          escopo=payload.get("escopo"))
                if result.get("status") == "erro":
                    raise RuntimeError(result.get("erro"))
                db.finish_job(row["id"], result)
        except Exception as exc:
            db.finish_job(row["id"], error=str(exc))
