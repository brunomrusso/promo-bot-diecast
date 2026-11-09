#!/usr/bin/env bash
# Diagnóstico da Lomadee (só leitura): a API responde? quais lojas? quantos colecionáveis por loja? links funcionam?
cd /home/ubuntu/promo-bot-carros
./venv/bin/python - <<'PY'
import collections, sqlite3, time
import requests
import config
from scrapers import lomadee as L
H = L._headers()
print("== 1/5 token:", "configurado" if config.LOMADEE_APP_TOKEN else "NÃO configurado")
t = time.time()
try:
    r = requests.get(f"{L.BASE}/brands", params={"limit": 50, "page": 1}, headers=H, timeout=20)
    print(f"== 2/5 API /brands: HTTP {r.status_code} em {time.time()-t:.1f}s")
    marcas = []
    for page in range(1, 10):
        r = requests.get(f"{L.BASE}/brands", params={"limit": 50, "page": page}, headers=H, timeout=20)
        d = (r.json().get("data") or []) if r.status_code == 200 else []
        if not d: break
        marcas += d
    nomes = sorted({(b.get("name") or "?") for b in marcas})
    print(f"   {len(nomes)} lojas aprovadas/disponíveis:", ", ".join(nomes[:80]))
    if r.status_code != 200: print("   resposta:", r.text[:300])
except Exception as e:
    print("!! erro na API:", type(e).__name__, str(e)[:200])
print("== 3/5 busca de produtos por termo (loja: qtde, faixa de preço)")
amostra_url = None
for termo in ["hot wheels", "mini gt", "lego", "funko pop", "pokemon tcg", "blokees", "miniatura 1:64", "matchbox", "carrinho colecionavel"]:
    try:
        t = time.time()
        r = requests.get(f"{L.BASE}/products", params={"search": termo, "limit": 50}, headers=H, timeout=25)
        if r.status_code != 200:
            print(f"   {termo}: HTTP {r.status_code} {r.text[:120]}"); continue
        data = r.json().get("data") or []
        por = collections.defaultdict(list)
        for p in data:
            opt = (p.get("options") or [{}])[0]; pr = (opt.get("pricing") or [{}])[0]
            loja = opt.get("seller") or L._brand_name(p.get("organizationId", ""))
            try: por[loja].append(float(pr.get("price") or 0))
            except (TypeError, ValueError): pass
            if not amostra_url and p.get("url"): amostra_url = (p["organizationId"], p["url"], p.get("name"))
        txt = "; ".join(f"{k}: {len(v)} (R$ {min(v):.0f}-{max(v):.0f})" for k, v in sorted(por.items(), key=lambda x: -len(x[1])) if v)
        print(f"   {termo} [{len(data)} em {time.time()-t:.1f}s]: {txt or 'nada'}")
        exemplos = [p.get('name','')[:60] for p in data[:3]]
        if exemplos: print("      ex.:", " | ".join(exemplos))
    except Exception as e:
        print(f"   {termo}: erro {type(e).__name__} {str(e)[:120]}")
print("== 4/5 link de afiliado (shortener)")
if amostra_url:
    org, url, nome = amostra_url
    link = L._shorten(org, url)
    print("   ", "OK lmdee.link gerado" if "lmdee" in link or link != url else "FALHOU (voltou a URL original)", "·", (nome or "")[:50])
    try:
        rr = requests.get(link, timeout=20, allow_redirects=True)
        print("    abre em:", rr.url.split("?")[0][:90], "HTTP", rr.status_code)
    except Exception as e:
        print("    não abriu:", type(e).__name__)
else:
    print("   sem produto para testar")
print("== 5/5 histórico do bot")
c = sqlite3.connect("deals.db")
try:
    row = c.execute("SELECT status, offers, duration, error, last_check FROM store_health WHERE lower(store) LIKE '%lomadee%'").fetchall()
    print("   saúde:", row or "sem registro")
except Exception as e:
    print("   saúde: ", e)
q = "SELECT store, COUNT(*) FROM posted WHERE store NOT IN ('Amazon','Mercado Livre','Shopee') GROUP BY store ORDER BY 2 DESC LIMIT 15"
try:
    print("   ofertas de outras lojas já vistas/postadas:", c.execute(q).fetchall() or "nenhuma")
    print("   últimos 30 dias:", c.execute("SELECT store, COUNT(*) FROM posted WHERE store NOT IN ('Amazon','Mercado Livre') AND posted_at > datetime('now','-30 days') GROUP BY store ORDER BY 2 DESC LIMIT 10").fetchall() or "nenhuma")
except Exception as e:
    print("   ", e)
PY
echo "== fim (nada foi mudado)"
