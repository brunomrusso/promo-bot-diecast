#!/usr/bin/env bash
# Aplica no servidor o pacote enviado pelo enviar-atualizacao.cmd, com histórico Git no próprio servidor:
# - para se alguém mudou arquivo direto no servidor (guarda essas mudanças no histórico antes);
# - roda os testes; se falharem, volta tudo como estava e não reinicia nada;
# - cada envio vira uma versão (deploy/voltar-versao.cmd volta para qualquer uma).
set -euo pipefail
cd /home/ubuntu/promo-bot-carros
MSG="${1:-Envio $(date +%d/%m\ %H:%M)}"
G=(git -c user.name=promobot -c user.email=promobot@painel.russodiecast.online)
CODE=(core scrapers templates static deploy main.py dashboard.py config.py requirements.txt .gitignore .gitattributes)
existing() { for p in "${CODE[@]}" test_*.py; do [[ -e "$p" ]] && echo "$p"; done; }
command -v git >/dev/null || { echo "   instalando git"; sudo apt-get install -y -q git >/dev/null; }
NOVO=$(mktemp -d /tmp/promobot-novo.XXXX)
trap 'rm -rf "$NOVO"' EXIT
tar xzf ~/promobot-update.tgz -C "$NOVO" --no-same-permissions 2>&1 | grep -v SCHILY || true
chmod -R u+rwX "$NOVO"

echo "== 1/4 versão atual do servidor"
if [[ ! -d .git ]]; then
  git init -q && git symbolic-ref HEAD refs/heads/servidor
  [[ -f .gitignore ]] || cp "$NOVO/.gitignore" .gitignore
  "${G[@]}" add -- $(existing)
  "${G[@]}" commit -q -m "Estado do servidor antes do Git"
  echo "   histórico criado"
fi
mexidos=$(git status --porcelain --untracked-files=no)
if [[ -n "$mexidos" ]]; then
  echo "!! Estes arquivos foram mudados direto no servidor:"; echo "$mexidos" | sed 's/^/   /'
  "${G[@]}" commit -q -am "Mudanças feitas direto no servidor (guardadas antes do envio)"
  echo "!! Guardei essas mudanças no histórico e NÃO apliquei o envio."
  echo "!! Mande esta saída para o Claude ANTES de rodar de novo (senão o envio passa por cima delas)."
  exit 2
fi
echo "   $(git log -1 --format='%h · %ad · %s' --date=format:'%d/%m %H:%M')"

echo "== 2/4 aplicando"
cp -r "$NOVO/." .
"${G[@]}" add -A -- $(existing)
if git diff --cached --quiet; then echo "   nada mudou: o servidor já está com esta versão"; exit 0; fi
git diff --cached --name-status | sed 's/^M\t/   alterado: /; s/^A\t/   novo:     /; s/^D\t/   removido: /'

echo "== 3/4 testando"
LOG=$(mktemp)
if ./venv/bin/python -W ignore -m unittest test_site_export test_price_engine test_site_ranking test_comissoes >"$LOG" 2>&1; then
  echo "   testes: $(grep -E '^Ran ' "$LOG") - OK"; rm -f "$LOG"
else
  grep -E '^(ERROR|FAIL):|Error|^Ran |^FAILED' "$LOG" | tail -12; rm -f "$LOG"
  git reset -q --hard HEAD
  echo "!! Testes falharam: voltei tudo como estava (o bot não foi reiniciado)."
  exit 3
fi
"${G[@]}" commit -q -m "$MSG"
echo "   nova versão: $(git log -1 --format='%h · %s')"

echo "== 4/4 reiniciando bot e painel (pode levar 1-2 min)"
sudo systemctl restart promobot dashboard
sleep 5; systemctl is-active promobot dashboard
sudo journalctl -u promobot -n 5 --no-pager
echo "== pronto"
