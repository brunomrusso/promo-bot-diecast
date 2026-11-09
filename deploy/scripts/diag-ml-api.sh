#!/usr/bin/env bash
# Só leitura: testa se a API oficial do Mercado Livre entrega o ranking de mais vendidos (sem navegador/proxy).
cd /home/ubuntu/promo-bot-carros
./venv/bin/python - <<'PY'
import json, requests
from scrapers import mercadolivre as M
API = M.API
tok = M._get_token()
st = M._tokens()
print("== token da API:", "OK" if tok else "NÃO", "| inválido:" , st.get("invalid"), "| erro:", st.get("error"))
H = {"Authorization": f"Bearer {tok}"} if tok else {}
def get(path, params=None):
    try:
        r = requests.get(API + path, params=params, headers=H, timeout=20)
        try: j = r.json()
        except ValueError: j = None
        return r.status_code, j
    except Exception as e:
        return "erro " + type(e).__name__, None
def show(nome, path, params=None):
    s, j = get(path, params)
    resumo = ""
    if isinstance(j, dict):
        c = j.get("content") or j.get("results")
        resumo = f"{len(c)} itens" if isinstance(c, list) else "chaves: " + ",".join(list(j)[:8])
        if j.get("message") and s != 200: resumo += f" | msg: {str(j.get('message'))[:90]}"
    print(f"   {nome}: HTTP {s} {resumo}")
    return s, j
print("== 1) mais vendidos por categoria (highlights)")
cats = {"Veículos em Miniatura": "MLB2097", "Blocos de Montar": "MLB455425", "Figuras de Ação": "MLB1839", "Cartas TCG": "MLB6899"}
res = {}
for n, c in cats.items():
    res[c] = show(n, f"/highlights/MLB/category/{c}")
print("== 2) tentativas com filtro de marca (Hot Wheels em MLB2097)")
for params in ({"attribute": "BRAND", "attribute_value": "Hot Wheels"}, {"attribute_id": "BRAND", "attribute_value_id": "6079335"}):
    show(f"params {list(params.items())}", "/highlights/MLB/category/MLB2097", params)
print("== 3) detalhes dos 3 primeiros de MLB2097 (nome, preço, foto)")
s, j = res.get("MLB2097", (None, None))
for e in ((j or {}).get("content") or [])[:3]:
    tipo, i = e.get("type"), e.get("id")
    if tipo == "PRODUCT":
        s1, p = get(f"/products/{i}")
        s2, it = get(f"/products/{i}/items")
        preco = ((it or {}).get("results") or [{}])[0].get("price")
        foto = ((p or {}).get("pictures") or [{}])[0].get("id")
        print(f"   #{e.get('position')} PRODUCT {i}: HTTP {s1}/{s2} · {(p or {}).get('name','?')[:55]} · R$ {preco} · foto {foto}")
    else:
        s1, it = get(f"/items/{i}")
        print(f"   #{e.get('position')} ITEM {i}: HTTP {s1} · {(it or {}).get('title','?')[:55]} · R$ {(it or {}).get('price')} · foto {((it or {}).get('pictures') or [{}])[0].get('id')}")
print("== 4) busca que o bot usa para as minis (products/search)")
show("products/search 'mini gt'", "/products/search", {"status": "active", "site_id": "MLB", "q": "mini gt", "limit": 5})
show("sites/MLB/search 'mini gt'", "/sites/MLB/search", {"q": "mini gt", "limit": 5})
PY
echo "== fim (nada foi mudado)"
