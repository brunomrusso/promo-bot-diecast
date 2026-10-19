# Promo Bot Diecast

[![Python](https://img.shields.io/badge/Python-3.10+-3776AB?logo=python&logoColor=white)](https://python.org)
[![Flask](https://img.shields.io/badge/Flask-3.x-000000?logo=flask)](https://flask.palletsprojects.com)
[![Telegram](https://img.shields.io/badge/Telegram-Bot-26A5E4?logo=telegram)](https://core.telegram.org/bots)
[![License](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

Bot automatizado e painel administrativo para monitorar, curar e publicar promoções monetizadas de miniaturas diecast em um canal do Telegram.

**Foco:** Hot Wheels Premium, Car Culture, Boulevard, Elite 64, Mini GT, Kaido House, Disney/Pixar Cars, Tomica, Majorette, Greenlight, M2 Machines, Matchbox e LEGO automotivo (escala 1:64).

---

## Funcionalidades

### Bot de monitoramento
- **Scraping automatizado** de Amazon BR, Mercado Livre, Lomadee e Shopee
- **Monetização automática** dos links: Amazon (tag), ML (meli.la), Lomadee (lmdee.link)
- **Filtros inteligentes**: desconto mínimo, relevância por termos, blocklist de produtos não-diecast
- **Regras por marca**: desconto mínimo, modo de aprovação (auto/manual/threshold), limite diário, prioridade
- **Período silencioso**: não envia notificações de madrugada, mas continua monitorando
- **Republicação automática**: republica se o preço caiu >15% desde a última publicação
- **Cupons automáticos**: coleta cupons do ML e publica no canal
- **Anti-bot**: rotação de headers, delays aleatórios, proteção de sessão do ML com circuito de pausa

### Painel administrativo (Dashboard)
- **Visão geral** com 6 KPIs clicáveis (publicados, pendentes, monitoradas, bloqueados, alertas, agendados)
- **Central de aprovações** com filtros, ordenação, classificação de qualidade, ações em lote e atalhos de teclado (J/K/A/R/X/C)
- **Criar anúncio** manualmente com extração automática de dados, cupom manual e botão "Colar"
- **Minis monitoradas** com thumbnails, histórico de preços em gráfico, busca imediata e publicação direta
- **Alertas de preço**: marcar produto como "Caro" com preço-alvo, notificação no Telegram quando atingir
- **Blacklist** reversível de produto e termo, com sugestão automática ao rejeitar
- **Agenda de publicações** com horário silencioso e intervalo mínimo configurável
- **Métricas do canal**: publicações, aprovações, rejeições por marca/loja, cupons e tracking de cliques
- **Saúde do sistema**: status por loja, memória, swap, banco, sessão do ML, auto-refresh
- **Identidade visual** RUSSO Diecast: paleta dourada/escura, Montserrat, responsiva (mobile + desktop)

### Telegram
- Publicação formatada com imagem, preço, desconto e link de compra
- Botões inline para aprovar/rejeitar/bloquear direto no Telegram
- Texto para WhatsApp gerado automaticamente
- Notificação pessoal quando alerta de preço dispara

---

## Stack

| Camada | Tecnologia |
|--------|-----------|
| Linguagem | Python 3.10+ |
| Web framework | Flask 3.x + Gunicorn |
| Banco de dados | SQLite |
| Scraping | Playwright (ML, Shopee) + Requests/BeautifulSoup (Amazon) |
| Frontend | Jinja2 + CSS puro + JS vanilla |
| Mensageria | Telegram Bot API |
| Deploy | Oracle Cloud (Always Free) + systemd + Cloudflare Tunnel |
| Backup | Rotativo automatizado via systemd timer |

---

## Estrutura do projeto

```
promo-bot-carros/
├── main.py              # Loop principal do bot
├── dashboard.py         # Painel web Flask
├── config.py            # Configuração via .env e banco
├── db.py                # Modelo SQLite (todas as tabelas e queries)
├── filters.py           # Filtros de relevância e blocklist
├── affiliate.py         # Geração e validação de links de afiliado
├── notifier.py          # Envio para Telegram (canal + admin)
├── approvals.py         # Callback handler para botões do Telegram
├── manual_jobs.py       # Jobs assíncronos (extração, publicação, agenda)
├── health.py            # Coleta de métricas de saúde do sistema
├── backup.py            # Backup rotativo do banco
├── keywords.txt         # Termos de busca (editável sem reiniciar)
├── scrapers/
│   ├── amazon.py        # Amazon BR via HTTP direto
│   ├── amazon_pw.py     # Amazon via Playwright (fallback)
│   ├── mercadolivre.py  # ML via API pública
│   ├── mercadolivre_pw.py # ML via Playwright (busca + cupons)
│   ├── ml_coupons.py    # Coleta de cupons do ML
│   ├── lomadee.py       # Lomadee (rede de afiliados)
│   ├── shopee.py        # Shopee via API interna
│   ├── shopee_pw.py     # Shopee via Playwright
│   └── coupons.py       # Agregador de cupons
├── static/
│   ├── app.css          # Estilos (identidade RUSSO Diecast)
│   ├── approvals.js     # Lógica da central de aprovações
│   ├── manual.js        # Lógica do criador de anúncios
│   ├── monitored-scan.js # Busca imediata de minis
│   └── price-chart.js   # Gráfico de histórico de preços
├── templates/           # Templates Jinja2 (15 páginas)
├── deploy/
│   ├── setup.sh         # Script de instalação no servidor
│   ├── promobot.service # systemd: bot principal
│   ├── dashboard.service # systemd: painel web
│   ├── dashboard-tunnel.service # Cloudflare Tunnel
│   └── promobot-backup.* # Timer de backup
└── .env.example         # Variáveis de ambiente (template)
```

---

## Setup local

### Pré-requisitos
- Python 3.10+
- Chrome/Chromium (para scrapers Playwright)

### Instalação

```bash
# Clone o repositório
git clone https://github.com/brunomrusso/promo-bot-diecast.git
cd promo-bot-diecast

# Crie o ambiente virtual
python -m venv venv
venv\Scripts\activate          # Windows
# source venv/bin/activate     # Linux/Mac

# Instale as dependências
pip install -r requirements.txt
playwright install chromium

# Configure as variáveis de ambiente
cp .env.example .env
# Edite o .env com suas credenciais
```

### Configuração mínima (.env)

```env
# Obrigatório
TELEGRAM_BOT_TOKEN=seu_token_do_botfather
TELEGRAM_CHAT_ID=@seu_canal
TELEGRAM_ADMIN_CHAT_ID=seu_chat_id_pessoal

# Afiliados (pelo menos um para monetizar)
AMAZON_TAG=seu-tag-20

# Painel web
PANEL_USER=admin
PANEL_PASSWORD=sua_senha_segura
```

### Executar

```bash
# Bot (loop contínuo)
python main.py

# Apenas um ciclo
python main.py --once

# Painel administrativo (desenvolvimento)
flask --app dashboard run --port 8080
```

---

## Deploy (Oracle Cloud)

O bot é projetado para rodar 24h em uma VM gratuita da Oracle Cloud. Consulte o guia completo em [`DEPLOY.md`](DEPLOY.md).

Resumo:
1. Crie uma VM **VM.Standard.E2.1.Micro** (Always Free, AMD x86)
2. Envie o código e execute `deploy/setup.sh`
3. Configure o Cloudflare Tunnel para acesso externo ao painel
4. Ative os serviços: `promobot`, `dashboard`, `dashboard-tunnel`

---

## Arquitetura

Consulte [`ARCHITECTURE.md`](ARCHITECTURE.md) para diagramas e detalhes da arquitetura.

---

## Atalhos do painel

| Tecla | Ação (Central de Aprovações) |
|-------|-----|
| `J` / `K` | Navegar entre ofertas |
| `A` | Aprovar e publicar |
| `R` | Rejeitar |
| `X` | Bloquear produto |
| `C` | Marcar como caro (alerta de preço) |
| `Enter` | Buscar (tela Criar anúncio) |
| `Ctrl+Enter` | Publicar no canal |

---

## Variáveis de ambiente

| Variável | Descrição | Obrigatório |
|----------|-----------|:-----------:|
| `TELEGRAM_BOT_TOKEN` | Token do BotFather | Sim |
| `TELEGRAM_CHAT_ID` | ID do canal/grupo | Sim |
| `TELEGRAM_ADMIN_CHAT_ID` | Seu chat ID pessoal | Sim |
| `AMAZON_TAG` | Tag de afiliado Amazon | Recomendado |
| `ML_CLIENT_ID` | App ID do ML | Para ML |
| `ML_CLIENT_SECRET` | App Secret do ML | Para ML |
| `LOMADEE_APP_TOKEN` | Token Lomadee | Para Lomadee |
| `LOMADEE_SOURCE_ID` | Source ID Lomadee | Para Lomadee |
| `SHOPEE_AFFILIATE_ID` | ID de afiliado Shopee | Para Shopee |
| `ML_AFFILIATE_PREFIX` | Prefixo do link ML | Para ML |
| `PANEL_USER` | Usuário do painel | Sim |
| `PANEL_PASSWORD` | Senha do painel | Sim |
| `MIN_DISCOUNT` | Desconto mínimo (%) | Padrão: 30 |
| `AUTO_APPROVE_MIN` | Auto-aprovar acima de (%) | Padrão: 40 |
| `CHECK_INTERVAL_MINUTES` | Intervalo entre ciclos | Padrão: 15 |
| `ENABLED_STORES` | Lojas ativas (vírgula) | Padrão: amazon |
| `DASHBOARD_URL` | URL pública do painel | Para tracking |

---

## Licença

Este projeto é de código aberto sob a licença MIT. Veja o arquivo [LICENSE](LICENSE) para detalhes.

---

## Créditos

Desenvolvido por [@brunomrusso](https://github.com/brunomrusso) com auxílio do [Devin](https://devin.ai).
