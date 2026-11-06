#!/usr/bin/env bash
# Roda como ubuntu na VPS nova, depois que o pacote da VM antiga foi extraido em ~/promo-bot-carros.
set -euo pipefail
cd /home/ubuntu/promo-bot-carros
echo "== 1/4 ambiente Python"
python3 -m venv venv
./venv/bin/pip install -q --upgrade pip
./venv/bin/pip install -q -r requirements.txt
./venv/bin/playwright install chromium
sudo ./venv/bin/playwright install-deps chromium >/dev/null
echo "== 2/4 testes"
./venv/bin/python -W ignore -m unittest test_site_export test_price_engine 2>&1 | tail -3
echo "== 3/4 servicos"
sudo cp deploy/promobot.service deploy/dashboard.service deploy/dashboard-tunnel.service \
        deploy/promobot-backup.service deploy/promobot-backup.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now promobot dashboard dashboard-tunnel promobot-backup.timer
sleep 20
echo "== 4/4 estado"
systemctl is-active promobot dashboard dashboard-tunnel
sudo journalctl -u promobot -n 15 --no-pager
sudo journalctl -u dashboard-tunnel --no-pager | grep -o 'https://[a-z0-9-]*\.trycloudflare\.com' | tail -1 | sed 's/^/Painel: /' || true
