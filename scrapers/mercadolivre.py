from datetime import datetime, timedelta

import requests

import config
from core import db

API = "https://api.mercadolibre.com"


def ml_coupon_status(code: str) -> str:
    """Valida o código na página de cupom do ML (/cupom/{code}): 200 = campanha
    ativa, 404 = inválido. Usa o proxy residencial para evitar o bloqueio de IP."""
    proxies = {"http": config.ML_PROXY_URL, "https": config.ML_PROXY_URL} \
        if getattr(config, "ML_PROXY_URL", "") else None
    try:
        resp = requests.get(
            f"https://www.mercadolivre.com.br/cupom/{code.strip().upper()}",
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                                   "AppleWebKit/537.36 (KHTML, like Gecko) "
                                   "Chrome/131.0.0.0 Safari/537.36"},
            proxies=proxies, timeout=20, allow_redirects=False)
    except requests.RequestException:
        return "unverifiable"
    if resp.status_code == 200:
        return "verified"
    if resp.status_code == 404:
        return "not_found"
    return "unverifiable"


def _tokens():
    state = db.get_system_state().get("ml_oauth")
    return state["value"] if state else {}


def _save_tokens(data):
    db.set_system_state("ml_oauth", {
        "access_token": data["access_token"],
        "refresh_token": data["refresh_token"],
        "expires_at": (datetime.utcnow() + timedelta(
            seconds=int(data.get("expires_in", 21600)) - 300)
        ).isoformat(timespec="seconds"),
        "user_id": data.get("user_id"),
    })


def _get_token(force_refresh=False):
    tok = _tokens()
    if not tok.get("access_token"):
        return None
    exp = tok.get("expires_at")
    if not force_refresh and exp and datetime.utcnow() < datetime.fromisoformat(exp):
        return tok["access_token"]
    resp = requests.post(API + "/oauth/token", data={
        "grant_type": "refresh_token",
        "client_id": config.ML_CLIENT_ID,
        "client_secret": config.ML_CLIENT_SECRET,
        "refresh_token": tok["refresh_token"],
    }, timeout=15)
    if resp.status_code != 200:
        print(f"[ML] refresh token falhou: {resp.status_code}")
        if resp.status_code in (400, 401, 403):
            # refresh token inválido/expirado: sem isso o bot achava que a API estava pronta
            # e devolvia zero ofertas em silêncio, sem cair no Playwright.
            db.set_system_state("ml_oauth", dict(tok, invalid=True, error=f"refresh {resp.status_code}"))
        return None
    _save_tokens(resp.json())
    return _tokens()["access_token"]


def _api(path, params=None, retry=True):
    token = _get_token()
    if not token:
        return None
    resp = requests.get(API + path, params=params, timeout=15,
                        headers={"Authorization": f"Bearer {token}"})
    if resp.status_code == 401 and retry:
        if _get_token(force_refresh=True):
            return _api(path, params, retry=False)
        return None
    if resp.status_code != 200:
        return None
    return resp.json()


def ml_api_ready():
    """Token OAuth de usuário disponível e válido (busca por API, sem browser)."""
    tok = _tokens()
    return bool(tok.get("access_token")) and not tok.get("invalid")


def search_mercadolivre(keyword: str, min_discount: int):
    """Busca via API oficial: catálogo -> itens por produto -> melhor preço.
    Requer ml_oauth em system_state (fluxo authorization_code)."""
    if not ml_api_ready():
        return []
    data = _api("/products/search", {"status": "active", "site_id": "MLB",
                                     "q": keyword, "limit": 10})
    if data is None:
        return None  # falha da API (token/permissão): o chamador decide o fallback
    if not data:
        return []
    deals = []
    for prod in data.get("results", []):
        pid = prod["id"]
        items = _api(f"/products/{pid}/items")
        offers = [i for i in (items or {}).get("results", [])
                  if i.get("price") and i.get("condition") != "used"]
        if not offers:
            continue
        best = min(offers, key=lambda i: i["price"])
        original = best.get("original_price")
        discount = (round((1 - best["price"] / original) * 100)
                    if original and original > best["price"] else 0)
        image = (prod.get("pictures") or [{}])[0].get("url", "")
        item_num = str(best["item_id"]).replace("MLB", "")
        deals.append({
            "id": f"ml-{best['item_id']}",
            "store": "Mercado Livre",
            "title": prod["name"],
            "price": best["price"],
            "original_price": original or best["price"],
            "discount": discount,
            "url": f"https://produto.mercadolivre.com.br/MLB-{item_num}",
            "image": image,
            "origin": ("international"
                       if best.get("international_delivery_mode")
                       not in (None, "none") else "national"),
        })
    return deals
