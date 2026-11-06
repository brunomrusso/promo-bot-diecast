#!/usr/bin/env bash
# Só leitura (2ª rodada): filtro de marca na API de mais vendidos e itens do tipo MLBU.
cd /home/ubuntu/promo-bot-carros
./venv/bin/python - <<'PY'
import re, requests
from urllib.parse import urlparse, parse_qs
from scrapers import mercadolivre as M
from core import db
H = {"Authorization": f"Bearer {M._get_token()}"}
def get(path, params=None):
    r = requests.get(M.API + path, params=params, headers=H, timeout=20)
    try: return r.status_code, r.json()
    except ValueError: return r.status_code, None
def nomes(content, n=3):
    out = []
    for e in (content or [])[:n]:
        if e.get("type") == "PRODUCT":
            s, p = get(f"/products/{e['id']}"); out.append((p or {}).get("name", "?")[:40])
        else:
            out.append(f"{e.get('type')} {e.get('id')}")
    return out
s, base = get("/highlights/MLB/category/MLB2097")
print("== sem filtro (MLB2097):", nomes(base.get("content")))
print("== marcas guardadas pelo bot (último link que funcionou) e o teste na API:")
links = db.get_setting("site_ranking_ml_links", {}) or {}
for k, url in links.items():
    u = urlparse(url); q = parse_qs(u.query)
    cat = re.search(r"MLB\d+", u.path).group(0)
    vid = (q.get("attribute_value_id") or [""])[0]
    if not vid:
        print(f"   {k}: {cat} (sem marca no link)"); continue
    s, j = get(f"/highlights/MLB/category/{cat}", {"attribute": "BRAND", "attributeValue": vid})
    c = (j or {}).get("content") or []
    print(f"   {k}: {cat} marca {vid} -> HTTP {s}, {len(c)} itens · {nomes(c)}" + (f" · msg {(j or {}).get('message','')[:80]}" if s != 200 else ""))
print("== itens MLBU (anúncio sem catálogo):")
mlbu = next((e["id"] for e in base.get("content", []) if str(e.get("id", "")).startswith("MLBU")), None)
if mlbu:
    for path in (f"/user-products/{mlbu}", f"/user-products/{mlbu}/items"):
        s, j = get(path)
        print(f"   {path}: HTTP {s} · chaves {list((j or {}).keys())[:8]}")
    s, j = get(f"/user-products/{mlbu}")
    s2, j2 = get(f"/user-products/{mlbu}/items")
    ids = (j2 or {}).get("results") or []
    print("   nome:", (j or {}).get("name", "?")[:60], "| itens:", ids[:3])
    if ids:
        iid = ids[0] if isinstance(ids[0], str) else ids[0].get("id")
        s3, it = get(f"/items/{iid}")
        print(f"   /items/{iid}: HTTP {s3} · {(it or {}).get('title','?')[:50]} · R$ {(it or {}).get('price')}")
PY
echo "== fim (nada foi mudado)"
