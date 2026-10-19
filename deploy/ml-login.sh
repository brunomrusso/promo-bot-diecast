#!/usr/bin/env bash

cd /home/ubuntu/promo-bot-carros || exit 1
cleanup() {
    ./venv/bin/python -c "import db; db.set_system_state('ml_maintenance', False)" 2>/dev/null
    sudo systemctl start promobot
}
trap cleanup EXIT HUP TERM
./venv/bin/python -c "import db; db.set_system_state('ml_maintenance', True)"
sudo systemctl stop promobot
for _ in {1..20}; do
    pgrep -f "chrome.*chrome_profile_ml" >/dev/null || break
    sleep 1
done
pgrep -f "Xvfb :99" >/dev/null || Xvfb :99 -screen 0 1366x900x24 >/tmp/xvfb-ml.log 2>&1 &
pgrep -f "x11vnc.*:99" >/dev/null || x11vnc -display :99 -nopw -listen localhost -forever -shared >/tmp/x11vnc-ml.log 2>&1 &
sleep 2
echo "Use o TightVNC em localhost::5901. Quando terminar, pressione Ctrl+C aqui."
DISPLAY=:99 ./venv/bin/python -c "import time; from scrapers.ml_coupons import _get_context; c=_get_context(); p=c.pages[0] if c.pages else c.new_page(); p.goto('https://www.mercadolivre.com.br/', wait_until='domcontentloaded', timeout=60000); time.sleep(3600)"
sleep 3
DISPLAY=:99 ./venv/bin/python -c "from scrapers.ml_coupons import _get_context, close_context, is_ml_verification, mark_ml_ready, mark_ml_verification, LINKBUILDER_URL; c=_get_context(); p=c.pages[0] if c.pages else c.new_page(); p.goto(LINKBUILDER_URL, wait_until='domcontentloaded', timeout=60000); p.wait_for_timeout(3000); blocked=is_ml_verification(p); mark_ml_verification(p.url) if blocked else mark_ml_ready(); close_context(); print('Verificação ainda necessária.' if blocked else 'Sessão validada com sucesso.')"
