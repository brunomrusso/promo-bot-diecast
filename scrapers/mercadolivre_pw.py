import re
from urllib.parse import quote, parse_qs, urlparse, urlencode, urlunparse
from core import db, filters

from .ml_coupons import (
    _get_context, is_ml_verification, mark_ml_ready, mark_ml_verification,
    ml_available,
)


def _to_float(text: str):
    nums = re.sub(r"[^\d]", "", text)
    try:
        return float(nums) / 100 if "," in text else float(nums)
    except (ValueError, TypeError):
        return None


_origin_checks_remaining = 2


def reset_comparison_budget():
    global _origin_checks_remaining
    _origin_checks_remaining = 2


def _verify_market_origins(page, deals):
    global _origin_checks_remaining
    authorized = db.active_monitored_items()
    candidates = [d for d in deals if d["origin"] == "unknown"
                  and any(filters.identifies_monitored(d, item) for item in authorized)]
    for deal in sorted(candidates, key=lambda d: d["price"])[:_origin_checks_remaining]:
        _origin_checks_remaining -= 1
        try:
            page.goto(deal["url"], wait_until="domcontentloaded", timeout=30000)
            if is_ml_verification(page):
                mark_ml_verification(page.url)
                break
            shipping = page.locator(".ui-pdp-container--column-right").all_inner_texts()
            text = " ".join(shipping).lower()
            title = page.locator("h1.ui-pdp-title").inner_text(timeout=5000)
            price_el = page.query_selector(".ui-pdp-price__second-line .andes-money-amount__fraction")
            cents_el = page.query_selector(".ui-pdp-price__second-line .andes-money-amount__cents")
            if not price_el or not db.comparable_product(deal["title"], title):
                continue
            price = _to_float(price_el.inner_text())
            if price and cents_el:
                price += int(cents_el.inner_text()) / 100
            if not price:
                continue
            deal["price"] = price
            if any(t in text for t in ("internacional", "importação", "china")):
                deal["origin"] = "international"
            elif "estoque disponível" in text and any(t in text for t in ("chegará", "retire grátis")):
                deal["origin"] = "national"
        except Exception as exc:
            print(f"[ML] comparação inconclusiva: {str(exc)[:300]}")
    return deals


def search_mercadolivre(keyword: str, min_discount: int):
    """Scraping da busca do ML usando a sessão logada persistente
    (chrome_profile_ml) — passa pelo anti-bot."""
    slug = quote(keyword.replace(" ", "-"))
    url = f"https://lista.mercadolivre.com.br/{slug}"
    deals = []
    seen = set()
    if not ml_available():
        return deals
    try:
        ctx = _get_context()
        page = ctx.new_page()
        try:
            resp = page.goto(url, timeout=45000)
            if resp is not None and resp.status >= 400:
                mark_ml_verification(page.url)
                print(f"[ML] bloqueio HTTP {resp.status} em '{keyword}'")
                page.close()
                return []
            if is_ml_verification(page):
                mark_ml_verification(page.url)
                print(f"[ML] captcha/verificação em '{keyword}'")
                page.close()
                return []
            page.wait_for_selector(
                "li.ui-search-layout__item, div.poly-card", timeout=25000
            )
            page.wait_for_timeout(2000)
            mark_ml_ready()
        except Exception:
            verification = is_ml_verification(page)
            if verification:
                mark_ml_verification(page.url)
                print(f"[ML] captcha/verificação em '{keyword}'")
            else:
                print(f"[ML] timeout/erro em '{keyword}'")
            page.close()
            return []

        cards = page.query_selector_all(
            "li.ui-search-layout__item, div.poly-card"
        )
        for card in cards[:48]:
            link_el = (card.query_selector("a.poly-component__title")
                       or card.query_selector("h3 a")
                       or card.query_selector("h2 a")
                       or card.query_selector("a"))
            price_el = card.query_selector(
                ".poly-price__current .andes-money-amount__fraction"
            ) or card.query_selector(".andes-money-amount__fraction")
            orig_el = card.query_selector(
                ".andes-money-amount--previous .andes-money-amount__fraction"
            ) or card.query_selector("s .andes-money-amount__fraction")
            img_el = card.query_selector("img")
            if not (link_el and price_el):
                continue
            card_text = card.inner_text().lower()
            if "internacional" in card_text or "china" in card_text:
                continue  # importado: preço final muda com taxa
            href = link_el.get_attribute("href") or ""
            if not href.startswith("http") or "mclics/clicks" in href:
                continue
            title_el = link_el
            price = _to_float(price_el.inner_text())
            cents_el = card.query_selector(".poly-price__current .andes-money-amount__cents")
            if price and cents_el:
                price += int(cents_el.inner_text()) / 100
            original = _to_float(orig_el.inner_text()) if orig_el else None
            if not price:
                continue
            discount = (
                round((1 - price / original) * 100)
                if original and original > price else 0
            )
            m = re.search(r"/p/([A-Z0-9]+)|MLB-?(\d+)", href)
            parsed = urlparse(href)
            params = parse_qs(parsed.query)
            selected_item = re.search(r"item_id:(MLB\d+)", params.get("pdp_filters", [""])[0])
            pid = selected_item[1] if selected_item else (m.group(0) if m else href.split("?")[0][:80])
            selection = {key: params[key] for key in ("pdp_filters", "searchVariation", "variation_id") if key in params}
            clean_url = urlunparse(parsed._replace(query=urlencode(selection, doseq=True), fragment=""))
            if pid in seen:
                continue
            seen.add(pid)
            deals.append(
                {
                    "id": f"ml-{pid}",
                    "store": "Mercado Livre",
                    "origin": "national" if any(t in card_text for t in ("chegará", "chega amanhã", "retire grátis")) else "unknown",
                    "title": title_el.inner_text().strip(),
                    "price": price,
                    "original_price": original or price,
                    "discount": discount,
                    "url": clean_url,
                    "image": (img_el.get_attribute("src")
                              or img_el.get_attribute("data-src") or "")
                              if img_el else "",
                }
            )
        _verify_market_origins(page, deals)
        page.close()
    except Exception as e:
        print(f"[ML] erro '{keyword}': {e}")
    return deals
