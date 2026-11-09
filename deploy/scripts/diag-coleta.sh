#!/usr/bin/env bash
# Diagnostico (so leitura): por que as minis "No site" nao tem preco recente?
cd /home/ubuntu/promo-bot-carros
./venv/bin/python - <<'PY'
import json
from core import db, filters
from scrapers.mercadolivre import ml_api_ready
from scrapers.ml_coupons import ml_session_state
with db._conn() as c:
    print("== lojas (store_health) ==")
    for r in c.execute("SELECT * FROM store_health ORDER BY store"):
        print(f"  {r['store']}: {r['status']} | ofertas {r['offers']} | {r['duration']:.0f}s | {r['last_check']} | {r['error'][:150]}")
    st = db.get_system_state()
    print("\n== estado ==")
    for k in ("heartbeat", "catalog", "site_export", "catalog_cursor_Mercado Livre", "catalog_cursor_Amazon"):
        print(f"  {k}: {json.dumps(st.get(k), ensure_ascii=False, default=str)[:300]}")
    print("  ML API pronta:", ml_api_ready(), "| sessao ML:", json.dumps(ml_session_state(), default=str)[:200])
    items = db.active_monitored_items()
    terms = list(dict.fromkeys(q for i in items for q in filters.search_queries(i["search_terms"])))
    print(f"\n== rodizio: {len(items)} minis ativas, {len(terms)} buscas; 3 buscas por loja por ciclo ==")
    print("\n== leituras de preco nas ultimas 48h por hora ==")
    for r in c.execute("SELECT strftime('%Y-%m-%d %H', observed_at) h, store, COUNT(*) n FROM price_observations WHERE observed_at >= datetime('now','-48 hours') GROUP BY h, store ORDER BY h"):
        print(f"  {r['h']}h {r['store']}: {r['n']}")
    print("\n== minis 'No site' ==")
    for i in db.site_monitored_items():
        print(f"\n#{i['id']} {i['name'][:70]} | alvo R$ {i['max_price']}")
        print(f"   busca: {i['search_terms']!r}")
        print(f"   obrigatorios: {i['required_terms']!r}")
        qs = filters.search_queries(i["search_terms"])
        print("   posicao no rodizio:", [terms.index(q) for q in qs if q in terms])
        for r in c.execute("SELECT store, COUNT(*) n, MAX(observed_at) ult FROM price_observations WHERE monitored_item_id=? GROUP BY store", (i["id"],)):
            print(f"   leituras {r['store']}: {r['n']} (ultima {r['ult']})")
        ex = c.execute("SELECT COUNT(*) FROM monitored_exclusions WHERE monitored_item_id=?", (i["id"],)).fetchone()[0]
        print("   exclusoes ('outra mini'):", ex)
        if ml_api_ready() and qs:
            from scrapers.mercadolivre import search_mercadolivre
            try:
                deals = search_mercadolivre(qs[0], 0) or []
                print(f"   teste ML API '{qs[0]}': {len(deals)} resultados")
                for d in deals[:8]:
                    dg = filters.monitored_match_diagnostic(d, i)
                    print(f"     R$ {d.get('price')} | {d['title'][:60]} | {'OK' if dg['matches'] else '; '.join(dg['reasons'])}")
            except Exception as e:
                print("   teste ML API falhou:", e)
PY
echo
echo "== log do bot (ultimas linhas relevantes) =="
sudo journalctl -u promobot --since "-6 hours" --no-pager 2>/dev/null | grep -iE "ML|Mercado|erro|error|bloque|verific|captcha|ciclo|timeout" | tail -40
