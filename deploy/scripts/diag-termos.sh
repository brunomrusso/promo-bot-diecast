#!/usr/bin/env bash
# Só leitura: minis com termos obrigatórios demais (a busca quase nunca acha) e uma sugestão mais enxuta.
cd /home/ubuntu/promo-bot-carros
./venv/bin/python - <<'PY'
from core import db, mini_sugestao
itens = db.list_monitored_items()
ruins = []
for i in itens:
    req = [t.strip() for t in (i.get("required_terms") or "").replace(";", ",").split(",") if t.strip()]
    if len(req) > 4:
        s = mini_sugestao.suggest({"title": i["name"]})
        ruins.append((i, req, s))
print(f"== {len(ruins)} de {len(itens)} minis com mais de 4 termos obrigatórios")
for i, req, s in ruins:
    print(f"\n#{i['id']} {i['name'][:70]}  ({'ativa' if i.get('active') else 'pausada'})")
    print(f"   hoje exige ({len(req)}): {', '.join(req)}")
    print(f"   sugestão      : {s['required_terms']}")
    print(f"   busca hoje    : {i.get('search_terms')}")
    print(f"   busca sugerida: {s['search_terms']}")
print("\n== fim (nada foi mudado)")
PY
