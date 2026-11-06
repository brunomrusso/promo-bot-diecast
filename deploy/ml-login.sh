#!/usr/bin/env bash
# Login manual do Mercado Livre pelo VNC (chamado por deploy\abrir-login-ml.cmd).
# Pode rodar a qualquer momento: pausa o bot, abre o Chrome do perfil do ML (saindo pelo
# ML_PROXY_URL, se configurado), espera você terminar, valida a sessão e religa o bot.
cd /home/ubuntu/promo-bot-carros || exit 1
PY=./venv/bin/python
BROWSER_PID=""

set_maint() { $PY -c "from core import db; db.set_system_state('ml_maintenance', $1)"; }

stop_browser() {
    if [ -n "$BROWSER_PID" ] && kill -0 "$BROWSER_PID" 2>/dev/null; then
        kill "$BROWSER_PID" 2>/dev/null
        wait "$BROWSER_PID" 2>/dev/null
    fi
    BROWSER_PID=""
    for _ in {1..20}; do
        pgrep -f "chrome.*chrome_profile_ml" >/dev/null || return 0
        sleep 1
    done
    pkill -f "chrome.*chrome_profile_ml" 2>/dev/null
    sleep 2
}

cleanup() {
    trap - EXIT HUP TERM INT
    stop_browser
    set_maint False 2>/dev/null
    sudo systemctl start promobot
    echo "Bot religado."
}
trap cleanup EXIT HUP TERM

set_maint True
echo "Pausando o bot..."
sudo systemctl stop promobot
stop_browser
pgrep -f "Xvfb :99" >/dev/null || { Xvfb :99 -screen 0 1366x900x24 >/tmp/xvfb-ml.log 2>&1 & }
pgrep -f "x11vnc.*:99" >/dev/null || { x11vnc -display :99 -nopw -listen localhost -forever -shared >/tmp/x11vnc-ml.log 2>&1 & }
sleep 2

DISPLAY=:99 $PY -c "
import time
from scrapers.ml_coupons import _get_context
c = _get_context()
p = c.pages[0] if c.pages else c.new_page()
p.goto('https://www.mercadolivre.com.br/', wait_until='domcontentloaded', timeout=90000)
time.sleep(3600)
" &
BROWSER_PID=$!

echo
echo "Chrome aberto no TightVNC (localhost::5901)."
echo "Faça o login no Mercado Livre (e resolva a verificação, se aparecer)."
echo ">>> Quando terminar, volte aqui e pressione ENTER (ou Ctrl+C). <<<"
trap 'echo' INT
read -r _ || true
trap - INT

echo "Fechando o Chrome do login..."
stop_browser
echo "Validando a sessão no Gerador de Links..."
DISPLAY=:99 $PY -c "
from scrapers.ml_coupons import _get_context, close_context, is_ml_verification, mark_ml_ready, mark_ml_verification, LINKBUILDER_URL
c = _get_context()
p = c.pages[0] if c.pages else c.new_page()
p.goto(LINKBUILDER_URL, wait_until='domcontentloaded', timeout=90000)
p.wait_for_timeout(4000)
blocked = is_ml_verification(p) or 'login' in p.url.lower()
mark_ml_verification(p.url) if blocked else mark_ml_ready()
close_context()
print('!! Verificação/login ainda necessários. Rode de novo.' if blocked else 'Sessão validada com sucesso.')
"
