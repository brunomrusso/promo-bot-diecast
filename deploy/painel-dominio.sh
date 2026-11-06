#!/usr/bin/env bash
# Painel com endereço fixo: https://painel.russodiecast.online (Caddy + Let's Encrypt).
# Roda como ubuntu na VPS. Desliga o túnel trycloudflare só depois que o HTTPS responder.
set -euo pipefail
DOM=painel.russodiecast.online
IP=$(curl -s https://ipinfo.io/ip)
echo "== 1/4 DNS: $DOM -> esperado $IP"
# O DNS da própria VPS pode ter guardado o "não existe" antigo: limpa e, se preciso, pergunta ao DNS público do Google.
sudo resolvectl flush-caches 2>/dev/null || true
R=$(getent hosts "$DOM" | awk '{print $1}' | head -1 || true)
if [[ -z "$R" ]]; then
  R=$(curl -s -m 10 "https://dns.google/resolve?name=$DOM&type=A" | python3 -c "import sys,json;a=[x['data'] for x in json.load(sys.stdin).get('Answer',[]) if x.get('type')==1];print(a[0] if a else '')" 2>/dev/null || true)
fi
echo "   resolve para: ${R:-nada}"
[[ -n "$R" ]] || { echo "!! O DNS ainda não responde para $DOM. Nada foi mudado. Espere alguns minutos e rode de novo."; exit 2; }
RES=(--resolve "$DOM:80:$R" --resolve "$DOM:443:$R")
if [[ "$R" != "$IP" ]]; then
  if curl -sI -m 10 "${RES[@]}" "http://$DOM/" | grep -qi '^server: cloudflare'; then
    echo "   passa pelo proxy da Cloudflare (DNS da HostGator) - ok"
  else
    echo "!! $DOM aponta para $R, que não é esta VPS nem a Cloudflare. Nada foi mudado."; exit 2
  fi
fi
echo "== 2/4 instalando Caddy"
if ! command -v caddy >/dev/null; then
  sudo apt-get install -y -q debian-keyring debian-archive-keyring apt-transport-https curl gnupg >/dev/null
  curl -1sLf https://dl.cloudsmith.io/public/caddy/stable/gpg.key | sudo gpg --dearmor --yes -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
  curl -1sLf https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt | sudo tee /etc/apt/sources.list.d/caddy-stable.list >/dev/null
  sudo apt-get update -q >/dev/null && sudo apt-get install -y -q caddy >/dev/null
fi
caddy version
echo "== 3/4 configurando"
# Atrás da Cloudflare o modo SSL pode ser "Flexível" (Cloudflare->VPS por http) ou "Completo" (por https):
# por isso o painel responde nas duas portas. O certificado da 443 vem do Let's Encrypt automaticamente.
sudo tee /etc/caddy/Caddyfile >/dev/null <<CFG
http://$DOM {
	encode gzip
	reverse_proxy 127.0.0.1:8080
}
https://$DOM {
	encode gzip
	reverse_proxy 127.0.0.1:8080
	header Strict-Transport-Security "max-age=31536000"
}
CFG
if sudo ufw status 2>/dev/null | grep -q "Status: active"; then sudo ufw allow 80/tcp; sudo ufw allow 443/tcp; fi
sudo systemctl enable caddy >/dev/null 2>&1; sudo systemctl restart caddy
echo "== 4/4 testando HTTPS (o certificado pode levar ~30 s)"
ok=0
for i in $(seq 1 18); do
  code=$(curl -s -m 15 -o /dev/null -w '%{http_code}' "${RES[@]}" "https://$DOM/" || true)
  [[ "$code" =~ ^(200|302|303|401)$ ]] && { ok=1; break; }
  sleep 5
done
if [[ $ok == 1 ]]; then
  echo "   HTTPS ok (HTTP $code). Desligando o túnel trycloudflare."
  sudo systemctl disable --now dashboard-tunnel
  echo "== PRONTO: https://$DOM"
else
  echo "!! HTTPS ainda não respondeu (último código: ${code:-nenhum}). O túnel antigo continua ligado."
  sudo journalctl -u caddy -n 20 --no-pager
  exit 3
fi
