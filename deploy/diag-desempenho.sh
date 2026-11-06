#!/usr/bin/env bash
# Desempenho do bot na VPS (só leitura). Compara com os números da VM Oracle antiga.
cd /home/ubuntu/promo-bot-carros
echo "== máquina"
echo "   CPUs: $(nproc) | carga (1/5/15 min): $(cut -d' ' -f1-3 /proc/loadavg) | ligada há: $(uptime -p)"
free -m | awk 'NR==2{printf "   memória: %s MB usados de %s MB\n",$3,$2} NR==3{printf "   swap usado: %s MB\n",$3}'
ps -eo rss,comm --sort=-rss | awk 'NR>1 && NR<=6{printf "   %-18s %6.0f MB\n",$2,$1/1024}'
echo
echo "== duração de cada ciclo do catálogo (o bot espera 15 min e então roda o ciclo)"
sudo journalctl -u promobot --since "-24 hours" --no-pager -o short-unix 2>/dev/null | grep "ciclo do catálogo concluído" | python3 -c '
import sys, datetime
t=[float(l.split()[0]) for l in sys.stdin if l.strip()]
d=[b-a for a,b in zip(t,t[1:])]
for a,x in list(zip(t[1:],d))[-10:]:
    c=max(0,x-900); print("   %s  ciclo de %dm%02ds" % (datetime.datetime.utcfromtimestamp(a-10800).strftime("%d/%m %H:%M"), c//60, c%60))
if d: m=max(0,sum(d)/len(d)-900); print("   média: %dm%02ds por ciclo em %d ciclos (VM antiga: ~4m)" % (m//60, m%60, len(d)))
else: print("   ainda sem ciclos suficientes")'
echo
echo "== duração da última busca por loja (store_health)"
./venv/bin/python - <<'PY'
from core import db
antes = {"Amazon": 169, "Mercado Livre": 28, "Lomadee": 83}
with db._conn() as c:
    for r in c.execute("SELECT * FROM store_health ORDER BY store"):
        a = antes.get(r["store"])
        cmp = f" | VM antiga: {a}s" if a else ""
        print(f"   {r['store']}: {r['duration']:.0f}s, {r['offers']} ofertas, {r['status']}{cmp} ({r['last_check']})")
PY
echo
echo "== resposta do painel (5 requisições na própria VPS)"
for i in 1 2 3 4 5; do curl -s -o /dev/null -w "%{time_total}\n" http://127.0.0.1:8080/login; done | awk '{s+=$1; printf "   %.0f ms\n",$1*1000} END{printf "   média: %.0f ms\n", s/NR*1000}'
echo
echo "== erros nas últimas 6 h"
sudo journalctl -u promobot --since "-6 hours" --no-pager | grep -ciE "erro|error|timeout|traceback" | sed 's/^/   linhas com erro\/timeout: /'
echo "   tipos mais comuns:"
sudo journalctl -u promobot --since "-6 hours" --no-pager -o cat | grep -iE "erro|error|timeout|traceback" | sed -E "s/'[^']*'/'…'/g; s/[0-9]{2,}/N/g" | sort | uniq -c | sort -rn | head -8 | cut -c1-170 | sed 's/^/   /'
