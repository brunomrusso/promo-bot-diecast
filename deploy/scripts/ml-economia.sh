#!/usr/bin/env bash
# Liga/desliga o bloqueio de imagens, vídeos, fontes e rastreadores no Chrome do ML (economia de proxy).
set -euo pipefail
cd /home/ubuntu/promo-bot-carros
acao="${1:-desligar}"
cp .env "backups/.env.antes-economia-$(date +%Y%m%d-%H%M%S)"
sed -i '/^ML_ECONOMIA=/d' .env
[[ "$acao" == "desligar" ]] && echo "ML_ECONOMIA=0" >> .env
sudo systemctl restart promobot dashboard; sleep 5; systemctl is-active promobot dashboard
echo "== economia de proxy: $([[ "$acao" == desligar ]] && echo DESLIGADA || echo LIGADA)"
