#!/usr/bin/env bash
# Por que minis com preço dentro do alvo não viraram oportunidade?
cd /home/claude 2>/dev/null; cd /home/ubuntu/promo-bot-carros
./venv/bin/python - <<'PY'
from core import db
with db._conn() as c:
    print("pendentes na aprovação (catálogo):", c.execute("SELECT COUNT(*) FROM posted WHERE status='pending' AND decision_source='catalog'").fetchone()[0])
    for mid in (3, 10, 11, 13):
        m = c.execute("SELECT id,name,max_price FROM monitored_items WHERE id=?", (mid,)).fetchone()
        if not m: continue
        print(f"\n#{m['id']} {m['name'][:60]} | alvo R$ {m['max_price']:.2f}")
        last = c.execute("SELECT price, store, product_id, observed_at FROM valid_price_observations WHERE monitored_item_id=? ORDER BY observed_at DESC LIMIT 3", (mid,)).fetchall()
        for r in last: print(f"   leitura: R$ {r['price']:.2f} {r['store']} {r['product_id']} em {r['observed_at']}")
        op = c.execute("SELECT last_price,last_notified_at FROM catalog_opportunities WHERE monitored_item_id=?", (mid,)).fetchone()
        print("   já apresentada:", f"R$ {op['last_price']:.2f} em {op['last_notified_at']}" if op else "nunca")
        for r in c.execute("SELECT product_id,price,status,posted_at,decided_at FROM posted WHERE monitored_item_id=? ORDER BY posted_at DESC LIMIT 3", (mid,)):
            print(f"   na fila/histórico: {r['product_id']} R$ {r['price']:.2f} status={r['status']} criado {r['posted_at']} decidido {r['decided_at']}")
        t = c.execute("SELECT title FROM valid_price_observations WHERE monitored_item_id=? ORDER BY observed_at DESC LIMIT 1", (mid,)).fetchone()
        if t:
            rule = db.match_brand_rule(t['title'])
            if rule: print(f"   regra de marca: {rule['name'] if 'name' in rule.keys() else rule['id']} limite diário {rule['daily_limit']} -> {'ok' if db.brand_limit_available(rule) else 'LIMITE ATINGIDO'}")
PY
