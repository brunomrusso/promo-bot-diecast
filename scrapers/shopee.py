import requests

API_URL = "https://shopee.com.br/api/v4/search/search_items"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Referer": "https://shopee.com.br/search",
    "Accept": "application/json",
}


def search_shopee(keyword: str, min_discount: int):
    """Consulta a API interna de busca da Shopee. Não-oficial, pode quebrar."""
    try:
        resp = requests.get(
            API_URL,
            params={
                "by": "relevancy",
                "keyword": keyword,
                "limit": 60,
                "newest": 0,
                "order": "desc",
                "page_type": "search",
                "scenario": "PAGE_GLOBAL_SEARCH",
                "version": 2,
            },
            headers=HEADERS,
            timeout=15,
        )
        if resp.status_code != 200:
            print(f"[Shopee] status {resp.status_code} em '{keyword}'")
            return []
        data = resp.json()
    except (requests.RequestException, ValueError) as e:
        print(f"[Shopee] erro buscando '{keyword}': {e}")
        return []

    deals = []
    for item in data.get("items") or []:
        info = item.get("item_basic", {})
        price = info.get("price", 0) / 100000
        original = info.get("price_before_discount", 0) / 100000
        if not price or not original or original <= price:
            continue
        discount = round((1 - price / original) * 100)
        if discount < min_discount:
            continue
        shopid, itemid = info["shopid"], info["itemid"]
        deals.append(
            {
                "id": f"shopee-{shopid}-{itemid}",
                "store": "Shopee",
                "title": info["name"],
                "price": price,
                "original_price": original,
                "discount": discount,
                "url": f"https://shopee.com.br/product/{shopid}/{itemid}",
                "image": (
                    f"https://cf.shopee.com.br/file/{info['image']}"
                    if info.get("image") else ""
                ),
            }
        )
    return deals
