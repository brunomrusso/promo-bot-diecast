#!/usr/bin/env bash
# Aplica no servidor os arquivos listados em deploy/manifesto.txt (genérico, reutilizável).
# Confere md5 antes: se algo foi alterado direto no servidor, para sem mudar nada.
set -euo pipefail
cd /home/ubuntu/promo-bot-carros
PKG=~/promobot-update.tgz
chmod -R u+w /tmp/promobot-novo 2>/dev/null || true; rm -rf /tmp/promobot-novo 2>/dev/null || true
NOVO=$(mktemp -d /tmp/promobot-novo.XXXX)
tar xzf "$PKG" -C "$NOVO" --no-same-permissions
chmod -R u+rwX "$NOVO"
MAN=$NOVO/deploy/manifesto.txt
sed -n '1p' "$MAN"
echo "== 1/4 conferindo arquivos do servidor"
ok=1; files=()
while IFS='|' read -r f antes depois; do
  [[ -z "$f" || "$f" == \#* ]] && continue
  files+=("$f")
  [[ "$antes" == "-" ]] && continue
  atual=$(md5sum "$f" 2>/dev/null | cut -d' ' -f1 || echo nenhum)
  if [[ "$atual" == "$depois" ]]; then echo "   $f já atualizado"
  elif [[ ",$antes," != *",$atual,"* ]]; then echo "!! $f diferente do esperado ($atual)"; ok=0; fi   # "antes" aceita vários md5 separados por vírgula
done < "$MAN"
[[ $ok == 1 ]] || { echo "!! Nada foi mudado. Mande esta saída para o Claude."; exit 2; }
echo "== 2/4 backup"
B=backups/pre-update-$(date +%Y%m%d-%H%M%S); mkdir -p "$B"
tar czf "$B/arquivos.tgz" "${files[@]}" 2>/dev/null || true
echo "   $B/arquivos.tgz"
echo "== 3/4 aplicando e testando"
for f in "${files[@]}"; do mkdir -p "$(dirname "$f")"; cp "$NOVO/$f" "$f"; done
cp "$NOVO"/deploy/* deploy/ 2>/dev/null || true
LOG=$(mktemp)
if ./venv/bin/python -W ignore -m unittest test_site_export test_price_engine test_site_ranking >"$LOG" 2>&1; then
  echo "   testes: $(grep -E '^Ran ' "$LOG") - OK"
else
  grep -E '^(ERROR|FAIL):|Error|^Ran |^FAILED' "$LOG" | tail -12
  echo "!! Testes falharam: voltando os arquivos anteriores (o bot não foi reiniciado)."
  tar xzf "$B/arquivos.tgz"
  exit 3
fi
rm -f "$LOG"
echo "== 4/4 reiniciando bot e painel (pode levar 1-2 min)"
sudo systemctl restart promobot dashboard
sleep 5; systemctl is-active promobot dashboard
sudo journalctl -u promobot -n 8 --no-pager
rm -rf "$NOVO"
echo "== pronto"
