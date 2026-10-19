#!/bin/bash
# Setup do promo-bot numa VM Ubuntu 22.04/24.04 (Oracle Free Tier, etc.)
# Uso: bash deploy/setup.sh
set -e

sudo apt-get update
sudo apt-get install -y python3 python3-venv python3-pip xvfb x11vnc git curl

# Google Chrome (necessário pro ML/Amazon — Chromium é detectado)
if ! command -v google-chrome >/dev/null; then
    curl -fsSL https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb -o /tmp/chrome.deb
    sudo apt-get install -y /tmp/chrome.deb
fi

python3 -m venv venv
./venv/bin/pip install -r requirements.txt
./venv/bin/playwright install chromium
./venv/bin/playwright install-deps chromium

echo ""
echo "OK. Próximos passos:"
echo "  1. cp .env.example .env  e preencha os valores"
echo "  2. Faça o login do ML uma vez via VNC (veja DEPLOY.md)"
echo "  3. Teste: xvfb-run -a ./venv/bin/python main.py --once"
echo "  4. Ative o serviço: sudo cp deploy/promobot.service /etc/systemd/system/"
echo "     sudo systemctl enable --now promobot"
