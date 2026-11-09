#!/usr/bin/env bash
# Só leitura (3ª rodada): como obter nome/preço/foto dos anúncios MLBU pela API.
cd /home/ubuntu/promo-bot-carros
./venv/bin/python - <<'PY'
import requests
from scrapers import mercadolivre as M
H = {"Authorization": f"Bearer {M._get_token()}"}
def get(path, params=None):
    r = requests.get(M.API + path, params=params, headers=H, timeout=20)
    try: j = r.json()
    except ValueError: j = None
    return r.status_code, j
s, base = get("/highlights/MLB/category/MLB2097", {"attribute": "BRAND", "attributeValue": "428690"})
print("== exemplo de entrada do ranking (campos):", (base.get("content") or [{}])[0])
mlbu = [e["id"] for e in base.get("content", []) if str(e["id"]).startswith("MLBU")][:2]
print("== MLBUs no top 20 de Hot Wheels:", sum(1 for e in base.get("content", []) if str(e["id"]).startswith("MLBU")), "de", len(base.get("content", [])))
for u in mlbu:
    for path, params in ((f"/items", {"ids": u}), (f"/products/{u}", None), (f"/items/{u}", None),
                         ("/products/search", {"site_id": "MLB", "status": "active", "user_product_id": u}),
                         (f"/user-products/{u}/children", None), ("/items", {"ids": u, "attributes": "title,price"})):
        s, j = get(path, params)
        txt = str(j)[:160].replace("\n", " ")
        print(f"   {path} {params or ''}: HTTP {s} · {txt}")
PY
echo "== fim (nada foi mudado)"
