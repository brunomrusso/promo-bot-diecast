#!/usr/bin/env bash
# Firewall da VPS: SSH (22) aberto como hoje (só chave); 80/443 só para a Cloudflare (o painel passa por ela).
# Quem tentar abrir o painel direto pelo IP da VPS é recusado. Se o painel parar de responder, desfaz sozinho.
set -euo pipefail
DOM=painel.russodiecast.online
echo "== 1/5 portas abertas hoje"
sudo ss -tlnp | awk 'NR==1||/LISTEN/' | grep -v '127.0.0.1\|::1\|127.0.0.53' || true
echo "== 2/5 lista de IPs da Cloudflare"
V4=$(curl -fsS -m 20 https://www.cloudflare.com/ips-v4) || { echo "!! não consegui baixar a lista. Nada foi mudado."; exit 2; }
V6=$(curl -fsS -m 20 https://www.cloudflare.com/ips-v6) || { echo "!! não consegui baixar a lista. Nada foi mudado."; exit 2; }
n=$(printf '%s\n%s\n' "$V4" "$V6" | grep -c /)
[[ $n -ge 10 ]] || { echo "!! lista estranha ($n faixas). Nada foi mudado."; exit 2; }
echo "   $n faixas"
echo "== 3/5 regras"
command -v ufw >/dev/null || sudo apt-get install -y -q ufw >/dev/null
sudo ufw allow 22/tcp comment 'SSH' >/dev/null
for p in 80 443; do
  while sudo ufw status | grep -qE "^$p/tcp +ALLOW +Anywhere"; do sudo ufw --force delete allow $p/tcp >/dev/null || break; done
done
for r in $V4 $V6; do
  sudo ufw allow proto tcp from "$r" to any port 80,443 comment 'Cloudflare' >/dev/null
done
sudo ufw default deny incoming >/dev/null
sudo ufw default allow outgoing >/dev/null
sudo ufw --force enable >/dev/null
echo "== 4/5 testando o painel pela Cloudflare"
ok=0
for i in 1 2 3 4 5 6; do
  code=$(curl -s -m 15 -o /dev/null -w '%{http_code}' "https://$DOM/" || true)
  [[ "$code" =~ ^(200|302|303|401)$ ]] && { ok=1; break; }
  sleep 5
done
if [[ $ok != 1 ]]; then
  echo "!! o painel não respondeu (código ${code:-nenhum}). Desfazendo: 80/443 abertos de novo."
  sudo ufw allow 80/tcp >/dev/null; sudo ufw allow 443/tcp >/dev/null
  exit 3
fi
echo "   painel ok (HTTP $code)"
echo "== 5/5 situação"
sudo ufw status | grep -E "Status|22/tcp" ; echo "   + $(sudo ufw status | grep -c Cloudflare) regras da Cloudflare (80/443)"
echo "== PRONTO: painel só pela Cloudflare; SSH igual a antes."
