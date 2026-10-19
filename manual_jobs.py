import hashlib
import json
import re
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse
from zoneinfo import ZoneInfo

import requests as http_requests

import db
import filters
from affiliate import is_monetized, to_affiliate_url
from notifier import format_whatsapp, send_deal, send_whatsapp_ready
from scrapers import get_scrapers
from scrapers.ml_coupons import _get_context, mark_ml_ready, mark_ml_verification


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
    # Mercado Livre: strip tracking params
    if "mercadolivre" in host or "mercadolibre" in host:
        return urlunparse(parsed._replace(query=urlencode({}), fragment=""))
    # Shopee: strip tracking params
    if "shopee" in host:
        return urlunparse(parsed._replace(query="", fragment=""))
    return url


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


def extract_link(url):
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
        body_lower = page.inner_text("body")[:4000].lower()
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
            "id": "manual-" + hashlib.sha1(final_url.encode()).hexdigest()[:16],
            "store": store,
            "title": title,
            "price": price,
            "original_price": original or price,
            "discount": discount,
            "url": final_url,
            "image": image,
            "_error": "Mercado Livre exige verificação de segurança. Recarregue a sessão." if is_captcha else None,
        }
    finally:
        page.close()


def normalize_manual_coupon(deal):
    code = str(deal.get("manual_coupon_code", "")).strip().upper()
    if not code:
        for key in list(deal):
            if key.startswith("manual_coupon_"):
                deal.pop(key, None)
        return deal
    price = float(deal.get("price") or 0)
    kind = deal.get("manual_coupon_type", "fixed")
    value = float(deal.get("manual_coupon_value") or 0)
    minimum = float(deal.get("manual_coupon_min_purchase") or 0)
    cap = float(deal.get("manual_coupon_max_discount") or 0)
    if price <= 0 or value <= 0:
        raise ValueError("Cupom informado sem preço ou desconto válido")
    if minimum and price < minimum:
        raise ValueError("O produto não atinge a compra mínima do cupom")
    discount = price * value / 100 if kind == "percent" else value
    if cap:
        discount = min(discount, cap)
    suggested = max(0, price - discount)
    final = float(deal.get("manual_coupon_final_price") or suggested)
    if final <= 0 or final >= price:
        raise ValueError("O preço final com cupom deve ser menor que o preço atual")
    deal.update({
        "manual_coupon_code": code,
        "manual_coupon_type": kind,
        "manual_coupon_value": value,
        "manual_coupon_min_purchase": minimum,
        "manual_coupon_max_discount": cap,
        "manual_coupon_final_price": final,
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
    return {"published": True, "whatsapp": format_whatsapp(deal, link),
            "affiliate_url": link}


def process_scheduled():
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


def process_jobs():
    for row in db.claim_jobs():
        try:
            payload = json.loads(row["payload"])
            if row["action"] == "restart_bot":
                db.finish_job(row["id"], {"restarting": True})
                raise SystemExit(0)
            if row["action"] == "extract":
                deal = extract_link(payload["url"])
                if deal.get("_error"):
                    raise ValueError(deal["_error"])
                link = to_affiliate_url(deal)
                deal["affiliate_url"] = link
                deal["monetized"] = is_monetized(link, deal["store"])
                deal["whatsapp"] = format_whatsapp(deal, link)
                db.finish_job(row["id"], deal)
            elif row["action"] == "scan_monitored":
                item = db.get_monitored_item(payload["item_id"])
                if not item:
                    raise ValueError("Mini monitorada não encontrada")
                results = []
                seen = set()
                scrapers = get_scrapers()
                for store_name, scraper in scrapers:
                    for deal in scraper(item["search_terms"], 0):
                        if deal["id"] in seen or not filters.identifies_monitored(deal, item):
                            continue
                        seen.add(deal["id"])
                        db.record_price(item["id"], deal)
                        deal["previously_posted"] = db.already_posted(deal["id"])
                        deal["fair_price"] = deal["price"] <= item["max_price"]
                        deal["quality"] = db.deal_price_quality(
                            deal["title"], deal["price"], item["id"])
                        results.append(deal)
                results.sort(key=lambda deal: deal["price"])
                if results:
                    minimum = results[0]["price"]
                    stores = len(set(deal["store"] for deal in results))
                    for deal in results:
                        deal["comparison"] = {
                            "count": len(results), "stores": stores,
                            "min_price": minimum, "best": deal["price"] == minimum,
                        }
                db.finish_job(row["id"], {
                    "item": item,
                    "results": results[:30],
                    "stores_searched": len(scrapers),
                })
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
                    **payload.get("coupon", {}),
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
                send_whatsapp_ready(deal, link)
                db.finish_job(row["id"], {
                    "published": True,
                    "whatsapp": format_whatsapp(deal, link),
                    "affiliate_url": link,
                })
            elif row["action"] == "publish":
                db.finish_job(row["id"], publish_deal(payload["deal"]))
        except Exception as exc:
            db.finish_job(row["id"], error=str(exc))
