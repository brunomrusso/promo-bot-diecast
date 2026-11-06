import re
import time
from urllib.parse import quote

from . import pw_shared
from .ml_coupons import _args

_ctx = None
_browser = None
_pw = None


def _get_context():
    """Contexto próprio, sem proxy: a Amazon responde melhor no IP direto
    da VM do que pelo proxy residencial usado pelo ML."""
    global _pw, _browser, _ctx
    if _ctx is None:
        _pw = pw_shared.acquire("amazon")
        try:
            _browser = _pw.chromium.launch(
                channel="chrome", headless=False, args=_args)
        except Exception:
            _browser = _pw.chromium.launch(headless=False, args=_args)
        _ctx = _browser.new_context(locale="pt-BR")
    return _ctx


def close_context():
    global _pw, _browser, _ctx
    if _ctx:
        try:
            _ctx.close()
            _browser.close()
        finally:
            _ctx = _browser = _pw = None
            pw_shared.release("amazon")


def _to_float(text: str):
    nums = re.sub(r"[^\d,]", "", text).replace(",", ".")
    try:
        return float(nums)
    except ValueError:
        return None


def _blocked(page) -> bool:
    try:
        content = page.content().lower()
        if "captcha" in content:
            return True
        body = page.inner_text("body")[:2000].lower()
        return "robot" in body or "captcha" in body
    except Exception:
        return False


def search_amazon(keyword: str, min_discount: int):
    """Scraping da Amazon BR via Chrome real, conexão direta (sem proxy)."""
    url = f"https://www.amazon.com.br/s?k={quote(keyword)}"
    deals = []
    seen = set()
    ctx = _get_context()
    loaded = False
    for attempt in range(2):
        page = ctx.new_page()
        try:
            page.goto(url, timeout=45000, wait_until="domcontentloaded")
            page.wait_for_selector(
                "div[data-asin][data-component-type='s-search-result']",
                timeout=25000,
            )
            page.wait_for_timeout(2000)
            loaded = True
        except Exception:
            blocked = _blocked(page)
            try:
                body = page.inner_text("body")[:6000].lower()
            except Exception:
                body = ""
            page.close()
            if blocked:
                print(f"[Amazon] captcha em '{keyword}'")
                return []
            if "nenhum resultado" in body or "no results for" in body or "não encontramos" in body:
                # busca muito específica sem resultados: não é timeout, não precisa repetir
                print(f"[Amazon] sem resultados para '{keyword}'")
                return []
            if attempt == 0:
                print(f"[Amazon] timeout em '{keyword}', tentando de novo")
                time.sleep(3)
                continue
            print(f"[Amazon] timeout em '{keyword}'")
            return []
        break
    if not loaded:
        return []

    try:
        cards = page.query_selector_all(
            "div[data-asin][data-component-type='s-search-result']"
        )
        for card in cards[:48]:
            asin = card.get_attribute("data-asin")
            if not asin or asin in seen:
                continue
            title_el = card.query_selector("h2 span")
            price_el = card.query_selector(".a-price .a-offscreen")
            orig_el = card.query_selector(
                ".a-price.a-text-price .a-offscreen")
            img_el = card.query_selector("img.s-image")
            if not (title_el and price_el):
                continue
            price = _to_float(price_el.inner_text())
            original = (_to_float(orig_el.inner_text())
                        if orig_el else None)
            if not price:
                continue
            discount = (
                round((1 - price / original) * 100)
                if original and original > price else 0
            )
            card_text = card.inner_text().lower()
            international = any(term in card_text for term in ("internacional", "import fees", "taxas de importação"))
            seen.add(asin)
            deals.append({
                "id": f"amz-{asin}",
                "store": "Amazon",
                "origin": "international" if international else "unknown",
                "title": title_el.inner_text().strip(),
                "price": price,
                "original_price": original or price,
                "discount": discount,
                "url": f"https://www.amazon.com.br/dp/{asin}",
                "image": (img_el.get_attribute("src") or "")
                         if img_el else "",
            })
    except Exception as e:
        print(f"[Amazon] erro '{keyword}': {e}")
    finally:
        page.close()
    return deals
