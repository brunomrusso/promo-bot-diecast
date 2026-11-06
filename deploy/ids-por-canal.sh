#!/usr/bin/env bash
# IDs por canal: Amazon (IDs de rastreamento) e Mercado Livre (etiquetas) — bot (WhatsApp/Telegram) e site.
set -euo pipefail
cd /home/ubuntu/promo-bot-carros
BOT="${1:-russowhats-20}"; SITE="${2:-russosite-20}"; MLBOT="${3:-russowhats}"; MLSITE="${4:-russosite}"
cp .env "backups/.env.antes-ids-$(date +%Y%m%d-%H%M%S)"
setvar() { if grep -q "^$1=" .env; then sed -i "s|^$1=.*|$1=$2|" .env; else echo "$1=$2" >> .env; fi; }
setvar AMAZON_TAG "$BOT"
setvar AMAZON_TAG_SITE "$SITE"
setvar ML_TAG_BOT "$MLBOT"
setvar ML_TAG_SITE "$MLSITE"
sudo systemctl restart promobot dashboard
sleep 5; systemctl is-active promobot dashboard
./venv/bin/python -c "import config; print('   bot (WhatsApp/Telegram):', config.AMAZON_TAG); print('   site:', config.AMAZON_TAG_SITE); print('   ML bot:', config.ML_TAG_BOT, '· ML site:', config.ML_TAG_SITE)"
echo "== pronto (os links do site trocam na próxima atualização do site; os do ML levam uns 15-20 min na 1ª vez)"
