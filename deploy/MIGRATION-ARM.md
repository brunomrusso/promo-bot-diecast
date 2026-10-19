# Migração para Oracle A1.Flex (ARM) — Guia passo a passo

## Por que migrar?

| | E2.1.Micro (atual) | A1.Flex (nova) |
|---|---|---|
| CPU | 1/8 OCPU AMD (burstable) | 2 OCPU ARM (dedicados) |
| RAM | 1 GB (usa swap!) | 12 GB |
| Disco | 47 GB | 100 GB |
| Custo | Grátis | Grátis |

## Passo 1: Criar a VM no Oracle Cloud

1. Acesse [cloud.oracle.com](https://cloud.oracle.com) → **Compute** → **Instances** → **Create instance**

2. Configure:
   - **Name**: `promo-bot-arm` (ou qualquer nome)
   - **Image**: **Ubuntu 22.04** (ou 24.04) — marque **Canonical Ubuntu**
   - **Shape**: clique em **Change shape**
     - Selecione **Ampere** (aba à esquerda)
     - Escolha **VM.Standard.A1.Flex**
     - **OCPUs**: `2`
     - **Memory**: `12` GB
   - **Boot volume**: 100 GB (padrão)
   - **SSH key**: selecione "Generate a key pair" e **baixe a chave privada**

3. Clique **Create** e aguarde o status ficar **Running**

4. Anote o **IP público** da nova VM

> **Nota**: Se aparecer "Out of capacity", tente outra Availability Domain ou região. A Oracle tem capacidade limitada para A1 em algumas regiões.

## Passo 2: Liberar portas no firewall da Oracle

Na página da instância:
1. Clique na **Subnet** → **Security Lists** → **Default Security List**
2. **Ingress Rules** → **Add Ingress Rule**:
   - Source CIDR: `0.0.0.0/0`
   - Destination Port Range: `22`
   - (Porta 22 geralmente já está aberta)

> As portas 8080 (dashboard) **não** precisam ser abertas — o Cloudflare Tunnel cuida disso.

## Passo 3: Copiar dados da VM atual para a nova

No seu PC (PowerShell ou Git Bash), execute:

```bash
# Variáveis — substitua pelos seus valores
OLD_IP=163.176.178.217
OLD_KEY=~/Downloads/ssh-key-2026-10-13.key
NEW_IP=<IP_DA_NOVA_VM>
NEW_KEY=~/Downloads/<CHAVE_DA_NOVA_VM>.key

# 1. Fazer backup na VM antiga
ssh -i $OLD_KEY ubuntu@$OLD_IP "cd /home/ubuntu/promo-bot-carros && tar czf /tmp/promobot-backup.tgz --exclude=venv --exclude=chrome_profile_ml --exclude=__pycache__ ."

# 2. Baixar o backup para o seu PC
scp -i $OLD_KEY ubuntu@$OLD_IP:/tmp/promobot-backup.tgz /tmp/promobot-backup.tgz

# 3. Enviar para a nova VM
scp -i $NEW_KEY /tmp/promobot-backup.tgz ubuntu@$NEW_IP:~/

# 4. Extrair na nova VM
ssh -i $NEW_KEY ubuntu@$NEW_IP "mkdir -p promo-bot-carros && cd promo-bot-carros && tar xzf ~/promobot-backup.tgz"
```

## Passo 4: Executar a migração na nova VM

```bash
ssh -i $NEW_KEY ubuntu@$NEW_IP
cd promo-bot-carros
bash deploy/migrate-to-arm.sh
```

O script instala tudo automaticamente: Python, Playwright (Chromium ARM64), Cloudflare Tunnel, serviços systemd.

## Passo 5: Testar

```bash
# Na nova VM
cd /home/ubuntu/promo-bot-carros

# Verificar o .env
cat .env

# Teste rápido (sem ML, que precisa de login)
xvfb-run -a ./venv/bin/python main.py --once
```

## Passo 6: Login do ML (1 vez, via VNC)

```bash
# Na nova VM — terminal 1
Xvfb :99 -screen 0 1280x800x24 &
DISPLAY=:99 x11vnc -display :99 -nopw -listen 0.0.0.0 -once &
```

No seu PC:
```bash
# Túnel SSH para VNC
ssh -i $NEW_KEY -L 5900:localhost:5900 ubuntu@$NEW_IP
```

Conecte um cliente VNC (TightVNC) em `localhost:5900`, depois na nova VM:
```bash
cd promo-bot-carros
DISPLAY=:99 ./venv/bin/python -c "from scrapers.ml_coupons import collect_ml_coupons; collect_ml_coupons()"
```

Faça login no ML na janela que aparecer no VNC.

## Passo 7: Iniciar os serviços

```bash
sudo systemctl start promobot dashboard dashboard-tunnel promobot-backup.timer

# Verificar
sudo systemctl status promobot
sudo systemctl status dashboard
journalctl -u promobot -f
```

## Passo 8: Desligar a VM antiga

Só depois de confirmar que tudo funciona na nova:

1. Oracle Console → **Compute** → **Instances**
2. Selecione a VM `E2.1.Micro` antiga
3. **More Actions** → **Terminate**
4. Marque "Permanently delete the attached boot volume"

## Troubleshooting

### "Out of capacity" ao criar a A1.Flex
A Oracle tem capacidade limitada. Tente:
- Outro **Availability Domain** (AD-2 ou AD-3)
- Outra **região** (se disponível no seu tenancy)
- Tente novamente em outro horário (madrugada costuma ter mais vagas)

### Playwright falha na instalação
```bash
# Instalar dependências do sistema manualmente
sudo apt-get install -y libnss3 libatk1.0-0 libatk-bridge2.0-0 libcups2 \
    libdrm2 libxkbcommon0 libxcomposite1 libxdamage1 libxfixes3 \
    libxrandr2 libgbm1 libpango-1.0-0 libcairo2 libasound2
./venv/bin/playwright install chromium
```

### Bot não encontra o ML
O perfil do Chrome da VM antiga (x86) **não funciona** na ARM. É necessário fazer o login do ML novamente via VNC (Passo 6).
