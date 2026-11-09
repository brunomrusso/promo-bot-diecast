#!/usr/bin/env bash
# Liga ou desliga a Lomadee em todo o bot (busca de ofertas, cupons, links de afiliado).
# Uso: bash lomadee.sh desligar | ligar     — o token fica guardado comentado no .env (não se perde).
set -euo pipefail
cd /home/ubuntu/promo-bot-carros
acao="${1:-desligar}"
cp .env "backups/.env.antes-lomadee-$(date +%Y%m%d-%H%M%S)"
if [[ "$acao" == "desligar" ]]; then
  sed -i 's/^LOMADEE_APP_TOKEN=/#DESLIGADO LOMADEE_APP_TOKEN=/; s/^LOMADEE_SOURCE_ID=/#DESLIGADO LOMADEE_SOURCE_ID=/' .env
  sed -i -E '/^ENABLED_STORES=/{s/(,)?lomadee(,)?/\1\2/; s/,,/,/; s/=,/=/; s/,$//}' .env
else
  sed -i 's/^#DESLIGADO LOMADEE_/LOMADEE_/' .env
  grep -q '^ENABLED_STORES=.*lomadee' .env || sed -i -E 's/^(ENABLED_STORES=.+)$/\1,lomadee/' .env
fi
./venv/bin/python - "$acao" <<'PY'
import sys
from core import db
import config
lojas = list(db.get_setting("enabled_stores", None) or config.load_enabled_stores())
lojas = [l for l in lojas if l != "lomadee"] + (["lomadee"] if sys.argv[1] == "ligar" else [])
db.set_setting("enabled_stores", lojas)
print("   lojas pesquisadas:", ", ".join(lojas))
PY
sudo systemctl restart promobot dashboard
sleep 5; systemctl is-active promobot dashboard
echo "   no .env: $(grep -E '^(#DESLIGADO )?LOMADEE_APP_TOKEN|^ENABLED_STORES' .env | sed 's/TOKEN=.*/TOKEN=(guardado)/')"
./venv/bin/python -c "import config; print('   token ativo para o bot:', 'sim' if config.LOMADEE_APP_TOKEN else 'não')"
echo "== pronto: Lomadee $([[ $acao == desligar ]] && echo desligada || echo ligada)"
