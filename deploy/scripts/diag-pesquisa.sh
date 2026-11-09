#!/usr/bin/env bash
# Só leitura: por que o "Pesquisar" das minis monitoradas não traz resultado.
cd /home/ubuntu/promo-bot-carros
./venv/bin/python - <<'PY'
import json, config
from core import db
print("== lojas ligadas:", config.load_enabled_stores())
with db._conn() as c:
    print("== últimas pesquisas pedidas pelo painel")
    for r in c.execute("SELECT id,status,created_at,updated_at,payload,substr(error,1,200) FROM manual_jobs WHERE action='scan_monitored' ORDER BY id DESC LIMIT 6"):
        print(f"   job {r[0]} {r[1]:<10} criado {r[2]} atualizado {r[3]} {r[4]} {r[5] or ''}")
    rows = c.execute("SELECT key,value FROM app_settings WHERE key LIKE 'monitored_scan_%'").fetchall()
scans = sorted((json.loads(v) for k, v in rows), key=lambda s: s.get("completed_at", ""), reverse=True)[:4]
print(f"== resultado das últimas pesquisas ({len(rows)} salvas)")
for s in scans:
    it = s.get("item", {})
    print(f"\n   {it.get('name','?')[:50]} · {s.get('completed_at')} · {s.get('matches_total')} resultado(s)")
    print(f"   busca: {it.get('search_terms')!r} | exige: {it.get('required_terms')!r} | recusa: {it.get('forbidden_terms')!r}")
    for d in s.get("diagnostics", []):
        print(f"     {d.get('store'):<14} status={d.get('status')} recebidos={d.get('received')} aceitos={d.get('matched')} descartados={d.get('discarded')} {('erro: ' + str(d.get('error'))[:150]) if d.get('error') else ''}")
        if d.get("missing_terms"): print("       termos que faltaram:", dict(sorted(d["missing_terms"].items(), key=lambda x: -x[1])[:6]))
        for smp in d.get("samples", [])[:2]: print("       ex.:", smp.get("title", "")[:70], "→", smp.get("reasons"))
print("\n== log do bot (últimas 24 h) com Amazon/Shopee")
PY
sudo journalctl -u promobot --since "24 hours ago" --no-pager | grep -iE "amazon|shopee" | grep -iE "erro|error|captcha|bloq|falh|timeout" | tail -8 | sed 's/^.*\]: /   /'
echo "== fim (nada foi mudado)"
