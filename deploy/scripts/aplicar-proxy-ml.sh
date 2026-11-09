#!/usr/bin/env bash
# Configura o proxy residencial do Mercado Livre no .env do servidor, testa e reinicia o bot.
# Chamado por deploy\enviar-proxy-ml.cmd. A senha do proxy nunca é exibida.
set -euo pipefail
cd /home/ubuntu/promo-bot-carros
SRC=~/proxy.env
sed -i 's/\r$//' "$SRC"
LINE=$(grep '^ML_PROXY_URL=' "$SRC" | head -1 || true)
rm -f "$SRC"
URL=${LINE#ML_PROXY_URL=}
[ -n "$URL" ] || { echo "!! ML_PROXY_URL vazio no .env do seu computador"; exit 2; }
case "$URL" in http://*|https://*) ;; *) echo "!! Use o formato http://usuario:senha@host:porta (o Chrome não aceita SOCKS5 com senha)"; exit 2;; esac

echo "== 1/4 testando o proxy"
IP=$(curl -s --max-time 25 -x "$URL" https://api.ipify.org || true)
[ -n "$IP" ] || { echo "!! O proxy não respondeu. Confira host, porta, usuário e senha. Nada foi alterado."; exit 3; }
INFO=$(curl -s --max-time 20 "https://ipinfo.io/$IP/json" || true)
echo "   IP de saída: $IP"
echo "$INFO" | grep -E '"(city|region|country|org)"' | sed 's/^/   /' || true
ML=$(curl -s -o /dev/null -w '%{http_code}' --max-time 30 -x "$URL" -A "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0 Safari/537.36" https://www.mercadolivre.com.br/ || true)
echo "   Mercado Livre pelo proxy: HTTP $ML"

echo "== 2/4 gravando no .env (backup em backups/)"
mkdir -p backups && cp .env "backups/env-pre-proxy-$(date +%Y%m%d-%H%M%S)"
grep -v '^ML_PROXY_URL=' .env > /tmp/promobot.env.new || true
printf 'ML_PROXY_URL=%s\n' "$URL" >> /tmp/promobot.env.new
cp /tmp/promobot.env.new .env && rm -f /tmp/promobot.env.new
./venv/bin/python -c "import config; p=config.ml_playwright_proxy(); print('   Playwright vai usar:', p['server'] if p else 'NENHUM')"

echo "== 3/4 reiniciando o bot (pode levar 1-2 min)"
sudo systemctl restart promobot
sleep 5
systemctl is-active promobot

echo "== 4/4 estado da sessão do ML"
./venv/bin/python - <<'PY'
from core import db
st = db.get_system_state()
for k in ("ml_session", "ml_maintenance"):
    if k in st:
        print(f"   {k}: {st[k]['value']} (em {st[k]['updated_at']})")
PY
echo "== pronto. Se a sessão do ML estiver como 'verification'/bloqueada, rode deploy\\abrir-login-ml.cmd para logar de novo (agora pelo proxy)."
