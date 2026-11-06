#!/usr/bin/env bash
# Quem está gastando o proxy? Conta, nas últimas 24 h do log do bot, o que passou pelo Chrome do ML.
cd /home/ubuntu/promo-bot-carros
L=$(sudo journalctl -u promobot --since "24 hours ago" --no-pager 2>/dev/null)
c() { echo "$L" | grep -c -- "$1" || true; }
echo "== ciclos do bot (24 h): $(c 'ciclo do catálogo concluído')  · intervalo: $(grep -E '^CHECK_INTERVAL_MINUTES' .env | cut -d= -f2) min"
echo "== busca do ML pela API (sem proxy) falhou e foi pro navegador: $(c 'API falhou em')"
echo "== buscas do ML pelo navegador com bloqueio/timeout: $(c "captcha/verificação em") / $(c "timeout/erro em")"
echo "== links meli.la gerados/erros: $(c '\[ML-link\]')"
echo "== exemplos recentes de busca pelo navegador:"; echo "$L" | grep -- 'API falhou em' | tail -5 | sed 's/^.*\[ML\]/   [ML]/'
./venv/bin/python - <<'PY'
from scrapers.mercadolivre import ml_api_ready
from core import db
print("== API oficial do ML pronta (token):", "sim" if ml_api_ready() else "NÃO -> toda busca vai pelo navegador/proxy")
with db._conn() as c:
    n = c.execute("SELECT COUNT(*) FROM monitored_items WHERE active=1").fetchone()[0]
print("== minis monitoradas ativas:", n)
PY
