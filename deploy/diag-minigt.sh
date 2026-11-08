#!/usr/bin/env bash
# Só leitura, sem proxy e sem navegador: o que a API oficial do ML diz hoje sobre a Mini GT.
cd /home/ubuntu/promo-bot-carros
./venv/bin/python - <<'PY'
from core import site_ranking as sr
get = sr._ml_api_get
cat, marca = sr.ML_API_SOURCES["mini-gt"]
print("== 1) ranking de mais vendidos da Mini GT")
s, j = get(f"/highlights/MLB/category/{cat}", {"attribute": "BRAND", "attributeValue": marca})
print(f"   HTTP {s}", (f"- {len((j or {}).get('content') or [])} itens" if s == 200 else "(sem ranking)"))
print("== 2) ranking geral de Veículos em Miniatura: quantos são Mini GT")
s, j = get(f"/highlights/MLB/category/{cat}")
ents = (j or {}).get("content") or []
mg = []
for e in ents:
    if e.get("type") == "PRODUCT":
        s2, p = get(f"/products/{e['id']}")
        nome = (p or {}).get("name", "")
        if "mini gt" in nome.lower() or "minigt" in nome.lower():
            mg.append((e.get("position"), nome[:60]))
print(f"   HTTP {s} - {len(ents)} itens no ranking geral; {sum(1 for e in ents if e.get('type')=='PRODUCT')} de catálogo; Mini GT entre eles: {len(mg)}")
for pos, n in mg[:10]: print(f"     #{pos} {n}")
print("== 3) busca da API por 'mini gt'")
for q in ("mini gt", "mini gt 1:64"):
    s, j = get("/products/search", {"status": "active", "site_id": "MLB", "q": q, "limit": 50})
    print(f"   '{q}': HTTP {s} - {len((j or {}).get('results') or [])} produtos (total informado: {((j or {}).get('paging') or {}).get('total')})")
print("== 4) anúncios de Mini GT que estão hoje no site")
site = sr._site_json("products.json")
itens = [p for p in site.get("produtos", []) if p.get("categoria") == "mini-gt" and p.get("loja", "mercadolivre") == "mercadolivre"]
print(f"   {len(itens)} anúncios do ML na Mini GT do site")
for p in itens:
    i = p.get("id_ml", "")
    if i.startswith("MLBU"):
        s1, u = get(f"/user-products/{i}")
        s2, it = get("/items", {"ids": i, "attributes": "id,status,price,title,catalog_product_id,user_product_id,permalink"})
        r0 = (it or [{}])[0] if isinstance(it, list) else (it or {})
        body = r0.get("body") or {}
        info = f"items: código {r0.get('code')} status={body.get('status')} preço={body.get('price')} {str(body.get('message') or body.get('error') or '')[:40]}"
        s3, sr_ = get(f"/user-products/{i}/items")
        info += f" | user-products/items HTTP {s3}"
        if s3 == 200: info += f" {str(sr_)[:120]}"
    else:
        s1, pr = get(f"/products/{i}")
        s2, it = get(f"/products/{i}/items")
        res = (it or {}).get("results") or []
        precos = [r.get("price") for r in res if r.get("price")]
        info = (f"produto HTTP {s1} ({(pr or {}).get('status','?')}); ofertas HTTP {s2}: {len(res)}"
                + (f", menor R$ {min(precos):.2f}" if precos else ""))
    print(f"   {i:<16} site R$ {p.get('preco')!s:<8} {p.get('preco_consultado_em','')[:10]}  {p.get('nome','')[:38]:<38} | {info}")
print("== fim (nada foi mudado)")
PY
