import re
from urllib.parse import quote

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
            page.goto(url, timeout=45000)
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
            original = _to_float(orig_el.inner_text()) if orig_el else None
            if not price:
                continue
            discount = (
                round((1 - price / original) * 100)
                if original and original > price else 0
            )
            if discount < min_discount:
                continue
            m = re.search(r"/p/([A-Z0-9]+)|MLB-?(\d+)", href)
            pid = m.group(0) if m else href.split("?")[0][:80]
            if pid in seen:
                continue
            seen.add(pid)
            deals.append(
                {
                    "id": f"ml-{pid}",
                    "store": "Mercado Livre",
                    "title": title_el.inner_text().strip(),
                    "price": price,
                    "original_price": original or price,
                    "discount": discount,
                    "url": href.split("#")[0].split("?")[0],
                    "image": (img_el.get_attribute("src")
                              or img_el.get_attribute("data-src") or "")
                              if img_el else "",
                }
            )
        page.close()
    except Exception as e:
        print(f"[ML] erro '{keyword}': {e}")
    return deals
