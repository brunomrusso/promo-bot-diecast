#!/usr/bin/env bash
# Roda como root na VPS nova (Hostinger). Prepara o sistema para o bot:
# usuario ubuntu (os servicos esperam /home/ubuntu), pacotes, Google Chrome, cloudflared,
# e desliga login por senha no SSH (so chave).
set -euo pipefail
echo "== 1/5 usuario ubuntu"
id ubuntu >/dev/null 2>&1 || adduser --disabled-password --gecos "" ubuntu
usermod -aG sudo ubuntu
echo "ubuntu ALL=(ALL) NOPASSWD:ALL" > /etc/sudoers.d/90-ubuntu && chmod 440 /etc/sudoers.d/90-ubuntu
install -d -m 700 -o ubuntu -g ubuntu /home/ubuntu/.ssh
cp /root/.ssh/authorized_keys /home/ubuntu/.ssh/authorized_keys
chown ubuntu:ubuntu /home/ubuntu/.ssh/authorized_keys && chmod 600 /home/ubuntu/.ssh/authorized_keys
echo "== 2/5 pacotes"
export DEBIAN_FRONTEND=noninteractive
apt-get update -q
apt-get install -y -q python3 python3-venv python3-pip xvfb x11vnc git curl ca-certificates
echo "== 3/5 Google Chrome"
if ! command -v google-chrome >/dev/null; then
  curl -fsSL https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb -o /tmp/chrome.deb
  apt-get install -y -q /tmp/chrome.deb
fi
google-chrome --version
echo "== 4/5 cloudflared"
if ! command -v cloudflared >/dev/null; then
  curl -fsSL https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64 -o /usr/local/bin/cloudflared
  chmod +x /usr/local/bin/cloudflared
fi
cloudflared --version
echo "== 5/5 SSH so com chave (desliga senha)"
echo -e "PasswordAuthentication no\nKbdInteractiveAuthentication no\nPermitRootLogin prohibit-password" > /etc/ssh/sshd_config.d/90-so-chave.conf
sshd -t && systemctl reload ssh
timedatectl | grep -i "time zone" || true
echo "== VPS preparada"
