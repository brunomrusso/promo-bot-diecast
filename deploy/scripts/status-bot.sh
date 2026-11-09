#!/usr/bin/env bash
# Resumo do bot: log recente, ciclo, sessão do ML, envio ao site e saúde das lojas.
cd /home/ubuntu/promo-bot-carros
echo "== log (últimas 40 linhas)"
sudo journalctl -u promobot -n 40 --no-pager
echo "== estado"
./venv/bin/python - <<'PY'
import json
from core import db
s = db.get_system_state()
for k in ("cycle", "ml_session", "site_export", "catalog"):
    if k in s:
        print(f"{k}: {json.dumps(s[k]['value'], ensure_ascii=False)[:400]} (em {s[k]['updated_at']})")
with db._conn() as c:
    for r in c.execute("SELECT store,status,offers,round(duration) dur,substr(error,1,160) error,last_check FROM store_health"):
        print("loja:", dict(r))
    print("minis ativas:", c.execute("SELECT COUNT(*) FROM monitored_items WHERE active=1").fetchone()[0],
          "| no site:", c.execute("SELECT COUNT(*) FROM monitored_items WHERE active=1 AND site_enabled=1").fetchone()[0])
    print("preços coletados nas últimas 24h:", dict(c.execute("SELECT store, COUNT(*) FROM price_observations WHERE observed_at >= datetime('now','-1 day') GROUP BY store").fetchall()))
PY
echo "== minis: alvo x menor preço nacional dos últimos 7 dias"
./venv/bin/python - <<'PY'
from core import db
with db._conn() as c:
    rows = c.execute("""
      SELECT m.id, m.name, m.max_price alvo, m.site_enabled site,
             (SELECT MIN(price) FROM valid_price_observations o WHERE o.monitored_item_id=m.id AND o.observed_at>=datetime('now','-7 days')) menor7d,
             (SELECT store FROM valid_price_observations o WHERE o.monitored_item_id=m.id AND o.observed_at>=datetime('now','-7 days') ORDER BY price LIMIT 1) loja,
             (SELECT COUNT(DISTINCT date(observed_at)) FROM valid_price_observations o WHERE o.monitored_item_id=m.id) dias,
             (SELECT MAX(observed_at) FROM valid_price_observations o WHERE o.monitored_item_id=m.id) ultima
      FROM monitored_items m WHERE m.active=1 ORDER BY m.name""").fetchall()
    for r in rows:
        alvo = f"R$ {r['alvo']:.2f}" if r['alvo'] else "sem alvo"
        menor = f"R$ {r['menor7d']:.2f} ({r['loja']})" if r['menor7d'] else "sem preço em 7d"
        flag = " <= ALVO" if r['alvo'] and r['menor7d'] and r['menor7d'] <= r['alvo'] else ""
        print(f"#{r['id']:<3} {r['name'][:48]:<48} alvo {alvo:<11} menor {menor}{flag} | {r['dias']} dia(s) de histórico | última {r['ultima']}{' | SITE' if r['site'] else ''}")
PY
