#!/usr/bin/env bash
# Só leitura, sem proxy e sem navegador: fontes possíveis de "mais vendidos" de Mini GT no ML.
cd /home/ubuntu/promo-bot-carros
./venv/bin/python - <<'PY'
from collections import Counter
from core import site_ranking as sr
get = sr._ml_api_get
eh_mg = lambda n: any(k in (n or "").lower() for k in ("mini gt", "minigt", "kaido house"))
print("== 1) Mini GT no site hoje, por loja")
site = sr._site_json("products.json")
print("  ", dict(Counter(p.get("loja", "mercadolivre") for p in site.get("produtos", []) if p.get("categoria") == "mini-gt")))
print("== 2) o que a busca da API traz em cada produto")
s, j = get("/products/search", {"status": "active", "site_id": "MLB", "q": "mini gt", "limit": 50})
res = (j or {}).get("results") or []
if res:
    print("   campos do resultado da busca:", sorted(res[0].keys()))
s, p = get(f"/products/{res[0]['id']}") if res else (0, None)
if p:
    print("   campos do produto:", sorted(p.keys()))
    print("   category/domain:", p.get("category_id"), p.get("domain_id"), "| vendidos no produto:", p.get("sold_quantity"))
s, it = get(f"/products/{res[0]['id']}/items") if res else (0, None)
r0 = ((it or {}).get("results") or [{}])[0]
print("   campos da oferta:", sorted(r0.keys()))
print("   vendidos na oferta:", r0.get("sold_quantity"), "| status:", r0.get("status"))
print("== 3) categorias dos 50 primeiros produtos Mini GT e o ranking de cada uma")
cats = Counter()
for x in res:
    s, p = get(f"/products/{x['id']}")
    if p and eh_mg(p.get("name")):
        cats[(p.get("category_id") or "?")] += 1
print("  ", cats.most_common(6))
for cat, _ in cats.most_common(4):
    if cat == "?": continue
    for filtro, params in (("sem filtro", None), ("marca Mini GT", {"attribute": "BRAND", "attributeValue": sr.ML_API_SOURCES["mini-gt"][1]})):
        s, h = get(f"/highlights/MLB/category/{cat}", params)
        ents = (h or {}).get("content") or []
        n_mg = 0
        for e in ents[:30]:
            if e.get("type") == "PRODUCT":
                s2, pp = get(f"/products/{e['id']}")
                n_mg += eh_mg((pp or {}).get("name"))
        print(f"   {cat} {filtro:<14} HTTP {s} - {len(ents)} itens; Mini GT (catálogo, entre os 30 primeiros): {n_mg}")
print("== 4) ordenação da busca")
for sort in ("sold_quantity_desc", "relevance"):
    s, j2 = get("/products/search", {"status": "active", "site_id": "MLB", "q": "mini gt", "limit": 5, "sort": sort})
    print(f"   sort={sort}: HTTP {s} -", [x.get("name", "")[:30] for x in ((j2 or {}).get("results") or [])])
print("== fim (nada foi mudado)")
PY
