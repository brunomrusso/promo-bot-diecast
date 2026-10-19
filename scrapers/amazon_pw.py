import re
from urllib.parse import quote

from .ml_coupons import _get_context


def _to_float(text: str):
    nums = re.sub(r"[^\d,]", "", text).replace(",", ".")
    try:
        return float(nums)
    except ValueError:
        return None


def search_amazon(keyword: str, min_discount: int):
    """Scraping da Amazon BR via Chrome real (sessão persistente)."""
    url = f"https://www.amazon.com.br/s?k={quote(keyword)}"
    deals = []
    seen = set()
    try:
        ctx = _get_context()
        page = ctx.new_page()
        try:
            page.goto(url, timeout=45000)
            page.wait_for_selector(
                "div[data-asin][data-component-type='s-search-result']",
                timeout=25000,
            )
            page.wait_for_timeout(2000)
        except Exception:
            blocked = ("captcha" in page.content().lower()
                       or "robot" in page.inner_text("body")[:2000].lower())
            page.close()
            print(f"[Amazon] {'captcha' if blocked else 'timeout'} "
                  f"em '{keyword}'")
            return []

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
            if discount < min_discount:
                continue
            seen.add(asin)
            deals.append({
                "id": f"amz-{asin}",
                "store": "Amazon",
                "title": title_el.inner_text().strip(),
                "price": price,
                "original_price": original or price,
                "discount": discount,
                "url": f"https://www.amazon.com.br/dp/{asin}",
                "image": (img_el.get_attribute("src") or "")
                         if img_el else "",
            })
        page.close()
    except Exception as e:
        print(f"[Amazon] erro '{keyword}': {e}")
    return deals
