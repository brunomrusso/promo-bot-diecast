import requests

import config

BASE = "https://api.lomadee.com.br/affiliate"
_brands_cache = {}


def _headers():
    return {"x-api-key": config.LOMADEE_APP_TOKEN}


def _brand_name(org_id: str) -> str:
    if org_id not in _brands_cache:
        try:
            r = requests.get(
                f"{BASE}/brands/{org_id}", headers=_headers(), timeout=15
            )
            _brands_cache[org_id] = (
                r.json().get("data", {}).get("name", "Lomadee")
                if r.status_code == 200 else "Lomadee"
            )
        except requests.RequestException:
            _brands_cache[org_id] = "Lomadee"
    return _brands_cache[org_id]


def get_brand_id(name_fragment: str):
    """Procura o organizationId de uma marca pelo nome (ex: 'shopee')."""
    frag = name_fragment.lower()
    for page in range(1, 8):
        try:
            r = requests.get(
                f"{BASE}/brands", params={"limit": 50, "page": page},
                headers=_headers(), timeout=15,
            )
        except requests.RequestException:
            break
        data = r.json().get("data", [])
        if not data:
            break
        for b in data:
            if frag in b.get("name", "").lower():
                return b["id"]
    return None


def _shorten(org_id: str, url: str) -> str:
    """Gera link de afiliado (lmdee.link) pro produto."""
    try:
        r = requests.post(
            f"{BASE}/shortener/url",
            json={"organizationId": org_id, "type": "Custom", "url": url},
            headers=_headers(),
            timeout=15,
        )
        if r.status_code in (200, 201):
            data = r.json()
            entry = data[0] if isinstance(data, list) else data.get("data", data)
            shorts = entry.get("shortUrls") or []
            if shorts:
                return shorts[0]
    except requests.RequestException:
        pass
    return url


def search_lomadee(keyword: str, min_discount: int):
    """Produtos da Lomadee já com link de afiliado gerado via shortener."""
    if not config.LOMADEE_APP_TOKEN:
        print("[Lomadee] LOMADEE_APP_TOKEN não configurado, pulando")
        return []
    try:
        resp = requests.get(
            f"{BASE}/products",
            params={"search": keyword, "limit": 50},
            headers=_headers(),
            timeout=20,
        )
        resp.raise_for_status()
    except requests.RequestException as e:
        print(f"[Lomadee] erro buscando '{keyword}': {e}")
        return []

    deals = []
    for p in resp.json().get("data", []):
        url = p.get("url")
        if not url or not p.get("available", True):
            continue
        opt = (p.get("options") or [{}])[0]
        pricing = (opt.get("pricing") or [{}])[0]
        try:
            price = float(pricing.get("price") or 0)
            original = float(pricing.get("listPrice") or 0)
        except (TypeError, ValueError):
            continue
        if not price:
            continue
        discount = (
            round((1 - price / original) * 100)
            if original and original > price else 0
        )
        if discount < min_discount:
            continue
        seller = opt.get("seller") or _brand_name(p.get("organizationId", ""))
        images = p.get("images") or opt.get("images") or []
        aff_url = _shorten(p["organizationId"], url)
        deals.append(
            {
                "id": f"lomadee-{p['id']}",
                "store": seller,
                "title": p.get("name", "Oferta"),
                "price": price,
                "original_price": original or price,
                "discount": discount,
                "url": aff_url,
                "image": images[0].get("url", "") if images else "",
                "affiliate_ready": True,
            }
        )
    return deals
