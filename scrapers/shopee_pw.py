import re
from urllib.parse import quote

from .ml_coupons import _get_context


def _to_float(text: str):
    nums = re.sub(r"[^\d]", "", text.replace(".", "").replace(",", "."))
    try:
        return float(nums)
    except (ValueError, TypeError):
        return None


def _is_blocked(page) -> bool:
    try:
        url = page.url
        body = page.inner_text("body")[:3000].lower()
        return ("captcha" in body or "login" in url
                or "verifique" in body and "robô" in body)
    except Exception:
        return False


def search_shopee(keyword: str, min_discount: int):
    """Scraping da busca da Shopee via Chrome logado.
    Filtra itens 'Internacional' (preço sem imposto/frete)."""
    url = f"https://shopee.com.br/search?keyword={quote(keyword)}"
    deals = []
    seen = set()
    try:
        ctx = _get_context()
        page = ctx.new_page()
        try:
            page.goto(url, timeout=45000)
            page.wait_for_selector(
                "li.shopee-search-item-result__item", timeout=25000
            )
            page.wait_for_timeout(2000)
        except Exception:
            if _is_blocked(page):
                print("[Shopee] captcha/login — resolva na janela do Chrome "
                      "(só na 1ª vez)")
                try:
                    page.wait_for_selector(
                        "li.shopee-search-item-result__item", timeout=300000
                    )
                    page.wait_for_timeout(2000)
                except Exception:
                    page.close()
                    print("[Shopee] login não resolvido a tempo")
                    return []
            else:
                page.close()
                print(f"[Shopee] timeout em '{keyword}'")
                return []

        items = page.query_selector_all(
            "li.shopee-search-item-result__item"
        )
        for card in items[:60]:
            card_text = card.inner_text().lower()
            if "internacional" in card_text:
                continue  # preço sem imposto de importação
            link_el = card.query_selector("a")
            if not link_el:
                continue
            href = link_el.get_attribute("href") or ""
            if not href:
                continue
            if href.startswith("/"):
                href = "https://shopee.com.br" + href
            # título: primeira linha do card geralmente é o nome
            lines = [l.strip() for l in card_text.split("\n") if l.strip()]
            title = next((l for l in lines if len(l) > 15), lines[0]
                         if lines else "")
            prices = re.findall(r"R\$\s*([\d.,]+)", card_text)
            if len(prices) < 1:
                continue
            price = _to_float(prices[0])
            original = _to_float(prices[1]) if len(prices) > 1 else None
            discount = (
                round((1 - price / original) * 100)
                if price and original and original > price else 0
            )
            if not price or discount < min_discount:
                continue
            img_el = card.query_selector("img")
            pid = href.split("?")[0]
            if pid in seen:
                continue
            seen.add(pid)
            deals.append({
                "id": f"shopee-{pid[-60:]}",
                "store": "Shopee",
                "title": title[:150],
                "price": price,
                "original_price": original or price,
                "discount": discount,
                "url": pid,
                "image": (img_el.get_attribute("src") or "")
                         if img_el else "",
            })
        page.close()
    except Exception as e:
        print(f"[Shopee] erro '{keyword}': {e}")
    return deals
