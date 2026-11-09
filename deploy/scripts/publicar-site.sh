#!/usr/bin/env bash
# Publica arquivos do site (russodiecast.com.br) pelo FTP restrito, a partir da VM do bot.
# Recebe ~/site-upload.tgz com os arquivos nos caminhos do site (ex.: index.html, assets/js/app.js).
set -euo pipefail
cd /home/ubuntu/promo-bot-carros
rm -rf /tmp/site-upload && mkdir -p /tmp/site-upload && tar xzf ~/site-upload.tgz -C /tmp/site-upload
./venv/bin/python - <<'PY'
import io, json, os, ssl, urllib.request
from ftplib import FTP_TLS, error_perm
import config
root = "/tmp/site-upload"
files = sorted(os.path.relpath(os.path.join(d, f), root) for d, _, fs in os.walk(root) for f in fs)
for f in files:
    if f.endswith(".json"):
        json.load(open(os.path.join(root, f), encoding="utf-8"))  # não publica JSON quebrado
ftp = FTP_TLS(config.SITE_FTP_HOST, timeout=30)
ftp.login(config.SITE_FTP_USER, config.SITE_FTP_PASSWORD); ftp.prot_p()
if config.SITE_FTP_DIR: ftp.cwd(config.SITE_FTP_DIR)
base = ftp.pwd()
backup = "backups-site"
try: ftp.mkd(backup)
except error_perm: pass
for f in files:
    ftp.cwd(base)
    parts = f.split("/")
    for p in parts[:-1]:
        ftp.cwd(p)
    name = parts[-1]
    try:  # guarda a versão anterior
        buf = io.BytesIO(); ftp.retrbinary(f"RETR {name}", buf.write)
        cur = ftp.pwd(); ftp.cwd(base); ftp.storbinary(f"STOR {backup}/{f.replace('/', '__')}", io.BytesIO(buf.getvalue())); ftp.cwd(cur)
    except error_perm:
        pass
    with open(os.path.join(root, f), "rb") as fh:
        ftp.storbinary(f"STOR {name}.tmp", fh)
    try: ftp.delete(name)
    except error_perm: pass
    ftp.rename(f"{name}.tmp", name)
    print("   enviado:", f)
ftp.quit()
for f in files:
    req = urllib.request.Request(config.SITE_URL.rstrip("/") + "/" + f + "?nocache=1", headers={"Cache-Control": "no-cache", "User-Agent": "Mozilla/5.0 (promobot-site-publish)"})
    body = urllib.request.urlopen(req, timeout=20, context=ssl.create_default_context()).read()
    local = open(os.path.join(root, f), "rb").read()
    print("   no ar:", f, "OK" if body == local else "DIFERENTE (cache?)")
PY
echo "== pronto (versões anteriores em backups-site/ no servidor do site)"
