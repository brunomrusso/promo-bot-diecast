#!/usr/bin/env bash
# Só leitura e sem proxy: achadinhos do app no ML que ainda não têm link com a etiqueta do site.
cd /home/ubuntu/promo-bot-carros
./venv/bin/python - <<'PY'
import config
from core import db
tag = config.ML_TAG_SITE
print(f"== achadinhos do app no ML sem link da etiqueta '{tag}'")
n = 0
for item in db.site_monitored_items():
    o = db.site_best_offer(item["id"])
    if not o or o["store"] != "Mercado Livre":
        continue
    if db.cached_affiliate_link(f"Mercado Livre#{tag}", o["url"] or ""):
        continue
    n += 1
    print(f"\n{n}) {item['name']}")
    print(f"   anúncio: {o['title'][:80]}  —  R$ {o['price']:.2f}")
    print(f"   link:    {o['url']}")
print(f"\n== {n} anúncio(s). Abra cada link no navegador e cole também no Gerador de Links do ML.")
PY
