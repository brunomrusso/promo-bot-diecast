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

## 3. Login do Mercado Livre (via VNC, assistente incluído)

O perfil do Chrome do Windows **não** funciona no Linux (cookies são
criptografados por SO) — precisa logar de novo, só uma vez.

**Caminho recomendado (Windows):** execute `deploy\abrir-login-ml.cmd`.
Ele abre o túnel SSH, inicia `deploy/ml-login.sh` no servidor e conecta o
TightVNC automaticamente. O script:

1. Marca `ml_maintenance` no estado do sistema e **para o bot**
   (evita dois Chromes no mesmo perfil).
2. Sobe Xvfb + x11vnc se necessário.
3. Abre o Chrome com o perfil `chrome_profile_ml` para você logar.
4. Ao encerrar (Ctrl+C no terminal do login), valida a sessão no
   linkbuilder, marca `ready` e **religa o bot**.

⚠️ **Importante:** encerre pelo terminal do login (Ctrl+C). Fechar só a
janela do VNC deixa o processo órfão no servidor segurando o perfil —
sintoma: erro "Playwright Sync API inside the asyncio loop" ou
"profile is already in use" nas buscas.

Para fazer manualmente, o equivalente é: parar `promobot`, subir
Xvfb/x11vnc, abrir `scrapers.ml_coupons._get_context()` com `DISPLAY=:99`,
logar, e ao final chamar a validação que existe no fim de `ml-login.sh`.

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

## Mercado Livre bloqueado por IP (out/2026)

- O ML bloqueia o range de IPs da Oracle (datacenter); trocar o IP efemero do VNIC **nao resolve** — qualquer IP `163.176.x.x` recebe a mesma verificacao (`account-verification`/`meli.la` 403).
- Solucao: proxy residencial BR com sessao sticky. Configure `ML_PROXY_URL=http://user:pass@host:port` no `.env`; todo trafego do Chrome persistente do ML sai por ele.
- O circuito `ml_session` continua ativo: bloqueio pausa as buscas do ML e avisa o admin no Telegram; demais lojas nao sao afetadas.
