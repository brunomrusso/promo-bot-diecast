#!/bin/bash
# Migração da VM E2.1.Micro (AMD) para A1.Flex (ARM)
# Uso: executar na VM NOVA (ARM) depois de copiar o projeto
# bash deploy/migrate-to-arm.sh
set -e

echo "=== Migração para ARM64 ==="
echo ""

# 1. Verificar arquitetura
ARCH=$(uname -m)
if [ "$ARCH" != "aarch64" ]; then
    echo "ERRO: Este script é para ARM64. Arquitetura detectada: $ARCH"
    exit 1
fi
echo "[OK] Arquitetura: $ARCH"

# 2. Atualizar sistema
echo ""
echo "=== Instalando dependências do sistema ==="
sudo apt-get update
sudo apt-get install -y python3 python3-venv python3-pip xvfb x11vnc git curl

# 3. Chromium para ARM (não existe Google Chrome para ARM Linux)
# Playwright instala o Chromium ARM64 automaticamente
echo ""
echo "=== Chromium será instalado via Playwright (ARM64 nativo) ==="

# 4. Swap (menor, pois temos mais RAM)
if [ ! -f /swapfile ]; then
    echo ""
    echo "=== Criando swap de 1 GB (precaução) ==="
    sudo fallocate -l 1G /swapfile
    sudo chmod 600 /swapfile
    sudo mkswap /swapfile
    sudo swapon /swapfile
    echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
fi

# 5. Criar venv e instalar dependências Python
echo ""
echo "=== Criando ambiente Python ==="
cd /home/ubuntu/promo-bot-carros
python3 -m venv venv
./venv/bin/pip install --upgrade pip
./venv/bin/pip install -r requirements.txt

# 6. Instalar Playwright Chromium (ARM64)
echo ""
echo "=== Instalando Playwright Chromium (ARM64) ==="
./venv/bin/playwright install chromium
./venv/bin/playwright install-deps chromium

# 7. Instalar Cloudflare Tunnel
if ! command -v cloudflared >/dev/null; then
    echo ""
    echo "=== Instalando cloudflared (ARM64) ==="
    curl -fsSL https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-arm64.deb -o /tmp/cloudflared.deb
    sudo dpkg -i /tmp/cloudflared.deb
fi

# 8. Copiar services do systemd
echo ""
echo "=== Configurando serviços systemd ==="
sudo cp deploy/promobot.service /etc/systemd/system/
sudo cp deploy/dashboard.service /etc/systemd/system/
sudo cp deploy/dashboard-tunnel.service /etc/systemd/system/
sudo cp deploy/promobot-backup.service /etc/systemd/system/
sudo cp deploy/promobot-backup.timer /etc/systemd/system/
sudo systemctl daemon-reload

# 9. Habilitar serviços (sem iniciar ainda)
sudo systemctl enable promobot dashboard dashboard-tunnel promobot-backup.timer

# 10. Teste rápido
echo ""
echo "=== Testando imports ==="
./venv/bin/python3 -c "
from core import db, filters, affiliate, notifier, approvals, health, backup, manual_jobs
import config, dashboard
print('Todos os imports OK')
"

echo ""
echo "========================================="
echo "  Migração ARM64 concluída!"
echo "========================================="
echo ""
echo "Próximos passos:"
echo "  1. Verifique o .env: cat .env"
echo "  2. Teste um ciclo: xvfb-run -a ./venv/bin/python main.py --once"
echo "  3. Login do ML via VNC (veja DEPLOY.md)"
echo "  4. Inicie os serviços:"
echo "     sudo systemctl start promobot dashboard dashboard-tunnel"
echo "  5. Verifique: sudo systemctl status promobot dashboard"
echo ""
