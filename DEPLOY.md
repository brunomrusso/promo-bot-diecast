# Deploy — rodar o bot 24h num servidor gratuito

O bot continua podendo rodar localmente (`python main.py`) sempre que quiser.
Este guia é pra VM gratuita — recomendada: **Oracle Cloud Always Free**
(VM.Standard.E2.1.Micro, AMD x86 — o Chrome não roda na opção ARM).

## 1. Criar a VM (Oracle Cloud)

1. Crie conta em cloud.oracle.com (pede cartão, mas não cobra no Always Free)
2. Compute → Instances → Create instance:
   - Image: **Ubuntu 22.04** (ou 24.04)
   - Shape: **VM.Standard.E2.1.Micro** (sempre grátis, AMD)
3. Baixe a chave SSH privada na criação
4. Anote o IP público

## 2. Subir o código

Do seu PC (PowerShell/Git Bash na pasta do projeto):

```bash
# compacta o projeto sem perfil do Chrome e venv
tar -czf /tmp/promobot.tgz --exclude=venv --exclude=chrome_profile_ml --exclude=.git .

# envia pra VM
scp -i ~/Downloads/sua-chave.key /tmp/promobot.tgz ubuntu@IP_DA_VM:~/
scp -i ~/Downloads/sua-chave.key .env ubuntu@IP_DA_VM:~/
```

Na VM:

```bash
ssh -i ~/Downloads/sua-chave.key ubuntu@IP_DA_VM
mkdir promo-bot-carros && cd promo-bot-carros
tar -xzf ~/promobot.tgz
mv ~/.env .
bash deploy/setup.sh
```

## 3. Login do Mercado Livre (1 vez, via VNC)

O perfil do Chrome do Windows **não** funciona no Linux (cookies são
criptografados por SO) — precisa logar de novo, só uma vez.

Na VM:

```bash
# terminal 1: inicia o display virtual + captura de cupons (abre o login)
Xvfb :99 -screen 0 1280x800x24 &
DISPLAY=:99 x11vnc -display :99 -nopw -listen 0.0.0.0 -once &
```

Do seu PC, crie um túnel SSH e conecte um cliente VNC (TightVNC/RealVNC):

```bash
ssh -i ~/Downloads/sua-chave.key -L 5900:localhost:5900 ubuntu@IP_DA_VM
# cliente VNC → localhost:5900
```

Deixando o túnel aberto, em outro terminal na VM:

```bash
cd promo-bot-carros
DISPLAY=:99 ./venv/bin/python -c "from scrapers.ml_coupons import collect_ml_coupons; collect_ml_coupons()"
```

A janela do Chrome aparece no VNC → faça login no ML → o script detecta
e salva a sessão em `chrome_profile_ml/`.

## 4. Teste e ative o serviço

```bash
xvfb-run -a ./venv/bin/python main.py --once   # ciclo de teste
sudo cp deploy/promobot.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now promobot
journalctl -u promobot -f                       # acompanha os logs
```

## Observações importantes

- **Anti-bot em datacenter**: IP de datacenter é mais suspeito pro ML/Amazon.
  Se o ML passar a pedir captcha mesmo logado, a parte Lomadee/Telegram/
  cupons continua funcionando; o scraping pode precisar de retry/residencial.
- **Rode local quando quiser**: `venv\Scripts\python main.py` continua
  funcionando — só não rode os dois ao mesmo tempo (mensagens de aprovação
  se confundem; o Telegram entrega o update pra um só).
- **deals.db**: copie o arquivo se quiser preservar o histórico de posts
  já publicados; senão o bot começa limpo no servidor.
- **Logs de erro**: `journalctl -u promobot` mostra tudo que acontece.
