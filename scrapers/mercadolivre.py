import requests

import config

TOKEN_URL = "https://api.mercadolibre.com/oauth/token"
API_URL = "https://api.mercadolibre.com/sites/MLB/search"

_token_cache = {"value": None}


def _get_token():
    if _token_cache["value"]:
        return _token_cache["value"]
    resp = requests.post(
        TOKEN_URL,
        data={
            "grant_type": "client_credentials",
            "client_id": config.ML_CLIENT_ID,
            "client_secret": config.ML_CLIENT_SECRET,
        },
        timeout=15,
    )
    resp.raise_for_status()
    _token_cache["value"] = resp.json()["access_token"]
    return _token_cache["value"]


def search_mercadolivre(keyword: str, min_discount: int):
    """Busca na API oficial do ML. Requer ML_CLIENT_ID/SECRET no .env
    (crie um app grátis em developers.mercadolivre.com.br)."""
    if not config.ML_CLIENT_ID or not config.ML_CLIENT_SECRET:
        print("[ML] credenciais não configuradas, pulando")
        return []
    try:
        token = _get_token()
        resp = requests.get(
            API_URL,
            params={"q": keyword, "limit": 50},
            headers={"Authorization": f"Bearer {token}"},
            timeout=15,
        )
        if resp.status_code == 401:  # token expirou
            _token_cache["value"] = None
            token = _get_token()
            resp = requests.get(
                API_URL,
                params={"q": keyword, "limit": 50},
                headers={"Authorization": f"Bearer {token}"},
                timeout=15,
            )
        resp.raise_for_status()
    except requests.RequestException as e:
        print(f"[ML] erro buscando '{keyword}': {e}")
        return []

    deals = []
    for item in resp.json().get("results", []):
        price = item.get("price")
        original = item.get("original_price")
        if not price or not original or original <= price:
            continue
        discount = round((1 - price / original) * 100)
        if discount < min_discount:
            continue
        deals.append(
            {
                "id": f"ml-{item['id']}",
                "store": "Mercado Livre",
                "title": item["title"],
                "price": price,
                "original_price": original,
                "discount": discount,
                "url": item["permalink"],
                "image": item.get("thumbnail", "").replace("-I.jpg", "-O.jpg"),
            }
        )
    return deals
