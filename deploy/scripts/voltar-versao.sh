#!/usr/bin/env bash
# Volta o bot do servidor para uma versão anterior (escolhida na lista). Testa antes de reiniciar.
set -euo pipefail
cd /home/ubuntu/promo-bot-carros
G=(git -c user.name=promobot -c user.email=promobot@painel.russodiecast.online)
[[ -d .git ]] || { echo "!! O servidor ainda não tem histórico (rode o enviar-atualizacao.cmd uma vez)."; exit 2; }
[[ -z "$(git status --porcelain --untracked-files=no)" ]] || { echo "!! Há mudanças feitas direto no servidor; mande esta saída para o Claude."; git status --short --untracked-files=no; exit 2; }
echo "Versões do bot (1 = a que está rodando agora):"
git log -12 --format='%h|%ad|%s' --date=format:'%d/%m %H:%M' | awk -F'|' '{printf "  %2d) %s  %s  (%s)\n", NR, $2, $3, $1}'
read -r -p "Número da versão para voltar (Enter = cancelar): " n
[[ "$n" =~ ^[0-9]+$ && "$n" -ge 2 ]] || { echo "Cancelado. Nada mudou."; exit 0; }
sha=$(git log -12 --format=%h | sed -n "${n}p")
[[ -n "$sha" ]] || { echo "Número inválido. Nada mudou."; exit 0; }
git checkout -q "$sha" -- .
git diff --name-only --diff-filter=A "$sha" HEAD | xargs -r git rm -q --
LOG=$(mktemp)
if ./venv/bin/python -W ignore -m unittest test_site_export test_price_engine test_site_ranking >"$LOG" 2>&1; then
  echo "   testes OK"; rm -f "$LOG"
else
  grep -E '^(ERROR|FAIL):|^Ran |^FAILED' "$LOG" | tail -8; rm -f "$LOG"
  git reset -q --hard HEAD; echo "!! Testes falharam nessa versão: nada mudou."; exit 3
fi
"${G[@]}" commit -q -m "Voltou para a versão $sha ($(git log -1 --format=%s "$sha"))"
sudo systemctl restart promobot dashboard
sleep 5; systemctl is-active promobot dashboard
echo "== pronto: bot na versão $sha"
