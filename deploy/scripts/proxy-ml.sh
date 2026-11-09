#!/usr/bin/env bash
# Proxy do Mercado Livre: testar | desligar | ligar. A senha nunca aparece.
set -euo pipefail
cd /home/ubuntu/promo-bot-carros
acao="${1:-testar}"
UA="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0 Safari/537.36"
URL=$(grep -E '^(#DESLIGADO )?ML_PROXY_URL=' .env | head -1 | sed -E 's/^(#DESLIGADO )?ML_PROXY_URL=//' || true)
estado=$(grep -q '^ML_PROXY_URL=.\+' .env && echo ligado || echo desligado)
echo "== proxy no .env: $estado ($(echo "$URL" | sed -E 's#//[^@]*@#//***@#'))"
echo "== teste pelo proxy"
if [[ -n "$URL" ]]; then
  IP=$(curl -s --max-time 25 -x "$URL" https://api.ipify.org || true)
  echo "   IP pelo proxy: ${IP:-FALHOU (proxy não respondeu)}"
  echo "   Mercado Livre pelo proxy: HTTP $(curl -s -o /dev/null -w '%{http_code}' --max-time 30 -x "$URL" -A "$UA" https://www.mercadolivre.com.br/mais-vendidos/MLB2097 || echo erro)"
fi
echo "== teste direto (sem proxy, IP da VPS)"
echo "   IP da VPS: $(curl -s --max-time 15 https://api.ipify.org || echo ?)"
for u in https://www.mercadolivre.com.br/mais-vendidos/MLB2097 https://www.mercadolivre.com.br/afiliados/linkbuilder; do
  r=$(curl -sL -o /tmp/ml.html -w '%{http_code} %{url_effective}' --max-time 30 -A "$UA" -H 'Accept-Language: pt-BR' "$u" || echo erro)
  echo "   $u"
  echo "      -> ${r%% *} em $(echo "${r#* }" | cut -c1-90) $(grep -qi 'ui-search-layout__item\|polycard' /tmp/ml.html 2>/dev/null && echo '(COM PRODUTOS)' || echo '(sem produtos)')"
done
if [[ "$acao" == "desligar" || "$acao" == "ligar" ]]; then
  cp .env "backups/.env.antes-proxy-$(date +%Y%m%d-%H%M%S)"
  if [[ "$acao" == "desligar" ]]; then sed -i 's/^ML_PROXY_URL=/#DESLIGADO ML_PROXY_URL=/' .env; else sed -i 's/^#DESLIGADO ML_PROXY_URL=/ML_PROXY_URL=/' .env; fi
  sudo systemctl restart promobot dashboard; sleep 5; systemctl is-active promobot dashboard
  ./venv/bin/python -c "import config; p=config.ml_playwright_proxy(); print('   Chrome do ML agora usa:', p['server'] if p else 'conexão direta da VPS')"
fi
echo "== fim"
