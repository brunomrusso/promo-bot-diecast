#!/usr/bin/env bash
# Aplica no servidor a atualização "achadinhos no site" + correção do fallback do ML.
# Roda na VM, chamado por deploy\enviar-atualizacao-site.cmd (Windows).
# Seguro: confere se os arquivos do servidor são os mesmos em que a mudança foi baseada;
# se alguém mexeu neles direto no servidor, para sem alterar nada.
set -euo pipefail
cd /home/ubuntu/promo-bot-carros
PKG=~/promobot-update.tgz
SITE_ENV=~/site.env

echo "== 1/6 conferindo arquivos atuais do servidor"
cat > /tmp/promobot-expected.md5 <<'EOF'
d00375958493ed2e422da176e8f74d2d  core/db.py
fff06ac3e1ba561b310d0084dd2a0f73  config.py
6562eac590049afb1d5bacec60524e7f  main.py
b9f48bf03ed534259ed99e0d2797bc14  dashboard.py
20c2c16c1812d856bcdad6c7ca2a8bb0  templates/monitored.html
c17ef081bdd897312da69759189183a6  scrapers/mercadolivre.py
7e84e32eb50f883153cffb3a255cdb6e  scrapers/__init__.py
EOF
cat > /tmp/promobot-new.md5 <<'EOF'
67d85b86fedd43493e65bc9cd9c59801  core/db.py
923bb7a5859f352fb755f5edcd0a133c  config.py
f22c4482896eaa29eacc982f935fa393  main.py
92b089f674dd320dee39684ab9fa64e3  dashboard.py
37c05ac50c04af3da88e6d5b48cc6699  templates/monitored.html
2c6157420263965042cb3cbd98405ade  scrapers/mercadolivre.py
fa649c90a5427ab04185de059cb1b024  scrapers/__init__.py
EOF
if md5sum -c --quiet /tmp/promobot-new.md5 2>/dev/null; then
  echo "   código novo já aplicado antes; seguindo para configuração e testes"
elif ! md5sum -c --quiet /tmp/promobot-expected.md5; then
  echo "!! Os arquivos acima estão diferentes no servidor (alterados direto lá)."
  echo "!! Nada foi mudado. Mande esta saída para o Claude comparar as versões."
  exit 2
fi

echo "== 2/6 backup dos arquivos que vão mudar"
B=backups/pre-site-$(date +%Y%m%d-%H%M%S)
mkdir -p "$B"
tar czf "$B/arquivos.tgz" core/db.py config.py main.py dashboard.py templates/monitored.html \
  scrapers/mercadolivre.py scrapers/__init__.py .env.example .env
echo "   backup em $B/arquivos.tgz"

echo "== 3/6 extraindo código novo"
tar xzf "$PKG"
sed -i 's/\r$//' core/site_export.py test_site_export.py deploy/aplicar-atualizacao-site.sh 2>/dev/null || true

echo "== 4/6 configurando o FTP do site no .env"
sed -i 's/\r$//' "$SITE_ENV"
grep -v '^SITE_' .env > /tmp/promobot.env.new || true
printf '\n' >> /tmp/promobot.env.new
grep '^SITE_' "$SITE_ENV" >> /tmp/promobot.env.new
cp /tmp/promobot.env.new .env && rm -f /tmp/promobot.env.new "$SITE_ENV"
grep -q '^SITE_FTP_PASSWORD=.' .env || { echo "!! SITE_FTP_PASSWORD vazio no .env"; exit 3; }

echo "== 5/6 testes e teste de conexão FTP"
./venv/bin/python -W ignore -m unittest test_site_export test_price_engine 2>&1 | tail -3
./venv/bin/python - <<'PY'
import config
from ftplib import FTP_TLS
f = FTP_TLS(config.SITE_FTP_HOST, timeout=30)
f.login(config.SITE_FTP_USER, config.SITE_FTP_PASSWORD)
f.prot_p()
if config.SITE_FTP_DIR:
    f.cwd(config.SITE_FTP_DIR)
names = f.nlst()
f.quit()
ok = all(n in names for n in ("index.html", "products.json", "achadinhos.json"))
print("   FTP ok, pasta do site encontrada" if ok else f"!! FTP conectou, mas a pasta não parece a do site: {sorted(names)[:15]}")
from core import site_export
print("   envio de teste:", site_export.publish())
PY

echo "== 6/6 reiniciando bot e painel"
sudo systemctl restart promobot dashboard
sleep 5
systemctl is-active promobot dashboard
sudo journalctl -u promobot -n 15 --no-pager
echo "== pronto"
