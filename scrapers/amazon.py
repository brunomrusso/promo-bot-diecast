import re
import requests
from bs4 import BeautifulSoup

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Accept-Language": "pt-BR,pt;q=0.9",
}


def _to_float(text: str):
    nums = re.sub(r"[^\d,]", "", text).replace(",", ".")
    try:
        return float(nums)
    except ValueError:
        return None


def search_amazon(keyword: str, min_discount: int):
    """Scraping da busca da Amazon BR. Frágil: a Amazon bloqueia bots com
    frequência (captcha). Se parar de funcionar, a alternativa é a PA-API
    oficial do programa de afiliados."""
    try:
        resp = requests.get(
            "https://www.amazon.com.br/s",
            params={"k": keyword},
            headers=HEADERS,
            timeout=15,
        )
        if resp.status_code != 200 or "captcha" in resp.text.lower():
            print(f"[Amazon] bloqueado/status {resp.status_code} em '{keyword}'")
            return []
    except requests.RequestException as e:
        print(f"[Amazon] erro buscando '{keyword}': {e}")
        return []

    soup = BeautifulSoup(resp.text, "html.parser")
    deals = []
    for card in soup.select("div[data-asin][data-component-type='s-search-result']"):
        asin = card.get("data-asin")
        title_el = card.select_one("h2 span")
        price_el = card.select_one(".a-price .a-offscreen")
        orig_el = card.select_one(".a-price.a-text-price .a-offscreen")
        img_el = card.select_one("img.s-image")
        if not (asin and title_el and price_el and orig_el):
            continue
        price = _to_float(price_el.get_text())
        original = _to_float(orig_el.get_text())
        if not price or not original or original <= price:
            continue
        discount = round((1 - price / original) * 100)
        if discount < min_discount:
            continue
        deals.append(
            {
                "id": f"amz-{asin}",
                "store": "Amazon",
                "title": title_el.get_text(strip=True),
                "price": price,
                "original_price": original,
                "discount": discount,
                "url": f"https://www.amazon.com.br/dp/{asin}",
                "image": img_el.get("src", "") if img_el else "",
            }
        )
    return deals
