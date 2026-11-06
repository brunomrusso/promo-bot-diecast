#!/usr/bin/env bash
# Só leitura: lê a página de mais vendidos SEM navegador e SEM a conta logada (pedido HTTP simples pelo proxy).
cd /home/ubuntu/promo-bot-carros
./venv/bin/python - <<'PY'
import time, requests, config
from core import site_ranking as sr
P = {"http": config.ML_PROXY_URL, "https": config.ML_PROXY_URL}
H = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
     "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8", "Accept-Language": "pt-BR,pt;q=0.9"}
S = requests.Session()
urls = {"Hot Wheels": "/mais-vendidos/MLB2097?attribute_id=BRAND&attribute_value_id=428690",
        "LEGO": "/mais-vendidos/MLB12443?attribute_id=BRAND&attribute_value_id=1249447",
        "Blokees": "/mais-vendidos/MLB1839?attribute_id=BRAND&attribute_value_id=43345273"}
total = 0
for nome, path in urls.items():
    t = time.time()
    try:
        r = S.get(sr.ML + path, headers=H, proxies=P, timeout=40)
    except Exception as e:
        print(f"== {nome}: erro {type(e).__name__} {str(e)[:120]}"); continue
    total += len(r.content)
    a, b = sr.ml_items(r.text), sr.ml_items_json(r.text)
    itens = a if len(a) >= len(b) else b
    mlbu = [i for i in itens if i["id"].startswith("MLBU")]
    print(f"== {nome}: HTTP {r.status_code} em {time.time()-t:.1f}s · {len(r.content)//1024} KB · foi para {r.url.split('?')[0][-45:]}")
    print(f"   itens lidos: {len(itens)} (HTML {len(a)} / JSON {len(b)}) · MLBU com preço: {len(mlbu)}")
    for i in itens[:3]:
        print(f"   #{i['pos']} {i['id']} · R$ {i['preco']} · {i['t'][:50]}")
    time.sleep(4)
print(f"== total baixado pelo proxy: {total//1024} KB")
PY
echo "== fim (nada foi mudado)"
