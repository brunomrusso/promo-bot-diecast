import requests

import config
from .lomadee import _headers, _shorten, BASE


def search_coupons():
    """Cupons ativos das marcas aderidas no Lomadee."""
    if not config.LOMADEE_APP_TOKEN:
        return []
    try:
        resp = requests.get(
            f"{BASE}/campaigns",
            params={"types": "Coupon", "limit": 50},
            headers=_headers(),
            timeout=15,
        )
        resp.raise_for_status()
    except requests.RequestException as e:
        print(f"[Cupons] erro: {e}")
        return []

    deals = []
    for c in resp.json().get("data", []):
        code = (c.get("couponCode") or c.get("code")
                or (c.get("coupon") or {}).get("code"))
        if not code:
            continue
        org_id = c.get("organizationId", "")
        url = c.get("url") or c.get("link") or ""
        aff = _shorten(org_id, url) if url else ""
        deals.append(
            {
                "id": f"cupom-{c.get('id', code)}",
                "store": c.get("organizationName") or "Lomadee",
                "title": c.get("name") or c.get("description", "Cupom"),
                "coupon": code,
                "url": aff or url,
                "image": "",
                "discount": 0,
                "price": None,
                "original_price": None,
                "affiliate_ready": bool(aff),
            }
        )
    return deals
