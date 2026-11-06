#!/usr/bin/env bash
# Só compara (não muda nada): arquivos do pacote enviado x arquivos do servidor.
set -euo pipefail
cd /home/ubuntu/promo-bot-carros
NOVO=$(mktemp -d /tmp/promobot-cmp.XXXX)
tar xzf ~/promobot-update.tgz -C "$NOVO" --no-same-permissions 2>/dev/null
chmod -R u+rwX "$NOVO"
iguais=0
while IFS= read -r f; do
  if [[ ! -f "$f" ]]; then echo "   novo no pacote: $f"; continue; fi
  if cmp -s "$NOVO/$f" "$f"; then iguais=$((iguais+1)); continue; fi
  st=$(diff "$f" "$NOVO/$f" | grep -c '^[<>]' || true)
  echo "   DIFERENTE: $f ($st linhas)"
done < <(cd "$NOVO" && find . -type f ! -path '*/__pycache__/*' | sed 's#^\./##' | sort)
echo "   iguais: $iguais"
echo "== só no servidor (código que o pacote não tem)"
find core scrapers templates static deploy -type f ! -path '*/__pycache__/*' ! -path 'core/backups/*' 2>/dev/null | sort | while read -r f; do [[ -f "$NOVO/$f" ]] || echo "   $f"; done
for f in *.py; do [[ -f "$NOVO/$f" ]] || echo "   $f"; done
echo "== config.py (diferenças)"
diff "config.py" "$NOVO/config.py" | head -30 || true
git --version 2>/dev/null || echo "   git não instalado"
if [[ -d .git ]]; then echo "   já tem .git: $(git log -1 --format='%h %ad %s' --date=short 2>/dev/null) · $(git status --porcelain --untracked-files=no 2>/dev/null | wc -l) arquivos diferentes do último commit"; else echo "   sem .git no servidor"; fi
rm -rf "$NOVO"
echo "== fim (nada foi mudado)"
