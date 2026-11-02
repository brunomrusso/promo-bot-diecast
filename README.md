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
- **Catálogo fechado**: busca em Amazon BR, Mercado Livre, Lomadee e Shopee somente para produtos ativos em Minis monitoradas. Keywords amplas e alertas legados não abrem novas buscas; sem catálogo, não há scraping automático.
- **Aprendizado silencioso**: sem alvo atingido ou histórico nacional confiável, registra preços sem gerar aprovações. Preço-alvo é opcional.
- **Monetização automática** dos links: Amazon (tag), ML (meli.la via linkbuilder com sessão logada), Lomadee (lmdee.link)
- **Avaliação por preço real**: coleta também preços sem desconto; compara equivalentes nacionais consultados hoje e histórico dos menores preços por dia (90 dias). Dados de origem desconhecida ou internacional não entram nessa base confiável.
- **Fila controlada**: uma oportunidade por cadastro; melhoria acima de 1% substitui pendente. Após decisão, exige queda de pelo menos 3% para reapresentar. Até 5 entradas por ciclo e 20 pendentes. Ofertas da busca aberta são arquivadas sem rejeição humana e sem apagar preços.
- **Filtros inteligentes**: relevância temática separada da avaliação de preço; percentual OFF informado pelo vendedor não filtra nem pontua. Bloqueio de títulos/produtos via aba Blacklist.
- **Revisão sempre manual**: atingir o alvo ou identificar preço favorável em histórico confiável gera uma oportunidade, nunca publicação autônoma. Modos automáticos legados não são usados pelo ciclo fechado.
- **Período silencioso**: não envia notificações de madrugada, mas continua monitorando
- **Publicação explícita**: pelo painel, Telegram ou agenda confirmada. Criar anúncio não cadastra monitoramento automaticamente: use “Autorizar monitoramento” e salve os critérios.
- **Cupons**: aplicação manual confirmada permanece disponível; a coleta/publicação aberta de cupons fica desativada no ciclo fechado.
- **Anti-bot**: rotação de headers, delays aleatórios, proteção de sessão do ML com circuito de pausa
- **Fila prioritária**: pedidos manuais (compartilhar WhatsApp, buscar) passam à frente das tarefas automáticas

### Painel administrativo (Dashboard)
- **Visão geral** com 6 KPIs clicáveis (publicados, pendentes, monitoradas, bloqueados, alertas, agendados)
- **Central de aprovações** com filtros recolhíveis, ordenação, classificação de qualidade (histórico monitorado **ou** aprendido), badge "Melhor de N ofertas", ações em lote e atalhos de teclado (J/K/A/R/X/C)
- **Compartilhar no WhatsApp** sem API: fluxo guiado prepara link monetizado, copia a legenda e compartilha a foto JPEG — disponível na aprovação, no criador de anúncios e nos cards da pesquisa no histórico de minis; independente de publicar no Telegram
- **Criar anúncio** manualmente com extração automática de dados, cupom manual e botão "Colar"; aceita links com tag de terceiros e resolve para o produto
- **Minis monitoradas** com thumbnails, busca imediata e publicação explícita. Histórico com melhor candidata nacional indicada em destaque, alternativas recolhidas, filtros por alvo/origem e profundidade da base por dias distintos de coleta.
- **Histórico de preços** com períodos 7/30/90 dias, mínimo/média/máximo diários, linha do alvo e edição do alvo na própria tela. “Enviar ao Telegram” e WhatsApp são ações separadas; filtrar ofertas não descarta cupons preenchidos.
- **Alertas de preço**: alvo único na mini monitorada ("Caro" na aprovação define `max_price`); a aba Alertas é um filtro das Minis e alertas antigos aparecem como legado
- **Blacklist** reversível de produto e termo, com sugestão automática ao rejeitar
- **Agenda de publicações** com horário silencioso e intervalo mínimo configurável
- **Métricas do canal**: publicações, aprovações, rejeições por marca/loja, cupons e tracking de cliques
- **Saúde do sistema**: status por loja, memória, swap, banco, sessão do ML, auto-refresh
- **Configurações centralizadas**: tema claro/escuro, texto de divulgação dos canais, regras e preferências
- **Identidade visual** RUSSO Diecast: paleta dourada/escura, Montserrat, temas claro/escuro, ícone iPhone com fundo preto, responsiva (mobile + desktop)

### Telegram
- Publicação formatada com imagem, preço, desconto e link de compra
- Botões inline para aprovar/rejeitar/bloquear direto no Telegram
- Texto para WhatsApp gerado automaticamente ao publicar
- Notificação pessoal quando alerta de preço dispara
- **Todos os vereditos alimentam o aprendizado de preços**

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
├── core/
│   ├── db.py            # Modelo SQLite: tabelas, queries, aprendizado de preços
│   ├── filters.py       # Score de relevância e identificação de produtos monitorados
│   ├── affiliate.py     # Geração e validação de links de afiliado
│   ├── notifier.py      # Envio para Telegram (canal + admin)
│   ├── approvals.py     # Callback handler para botões do Telegram
│   ├── manual_jobs.py   # Fila de jobs (extração, publicação, agenda, prioridade)
│   ├── health.py        # Coleta de métricas de saúde do sistema
│   └── backup.py        # Backup rotativo do banco
├── scrapers/
│   ├── amazon.py        # Amazon BR via HTTP direto
│   ├── amazon_pw.py     # Amazon via Playwright (fallback)
│   ├── mercadolivre.py  # ML via API pública
│   ├── mercadolivre_pw.py # ML via Playwright (busca de ofertas)
│   ├── ml_coupons.py    # ML: sessão persistente, cupons e linkbuilder meli.la
│   ├── lomadee.py       # Lomadee (rede de afiliados)
│   ├── shopee.py        # Shopee via API interna
│   ├── shopee_pw.py     # Shopee via Playwright
│   └── coupons.py       # Agregador de cupons
├── static/
│   ├── app.css          # Estilos (temas claro/escuro, identidade RUSSO Diecast)
│   ├── approvals.js     # Lógica da central de aprovações
│   ├── manual.js        # Lógica do criador de anúncios
│   ├── whatsapp-share.js # Compartilhamento WhatsApp (JPEG + legenda)
│   ├── monitored-scan.js # Busca imediata e diagnóstico de minis
│   ├── price-chart.js   # Gráfico de histórico de preços
│   └── emblema*.png, apple-touch-icon*.png  # Identidade visual e ícones
├── templates/           # Templates Jinja2 (15 páginas)
├── deploy/
│   ├── setup.sh         # Script de instalação no servidor
│   ├── promobot.service # systemd: bot principal (xvfb-run)
│   ├── dashboard.service # systemd: painel web
│   ├── dashboard-tunnel.service # Cloudflare Tunnel
│   ├── promobot-backup.* # Timer de backup
│   ├── ml-login.sh      # Assistente de login do ML via VNC
│   └── abrir-login-ml.cmd # Atalho Windows: túnel SSH + VNC + login ML
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

No criador manual, links do Mercado Livre com catálogo (`/p/MLB...`) e anúncio
selecionado (`pdp_filters=item_id:MLB...`) tentam primeiro a API com o OAuth já
configurado no banco. O preço vem somente do anúncio selecionado; título e foto
vêm do catálogo. Sem preço anterior, nenhum desconto é inferido. Links `meli.la`
são resolvidos por HTTP, usando apenas o botão explícito “Ir para produto” de
páginas sociais, e o link monetizado original é preservado para publicação.

Sem OAuth, com erro da API, variação explícita ou anúncio ausente na primeira
página de ofertas, a extração usa o navegador existente. Links comuns continuam
precisando de monetização, que pode exigir navegador. A fila do bot continua
compartilhada com o monitoramento nesta etapa.

O resultado do job de extração inclui `extraction_method`, `extraction_seconds`,
`monetization_seconds` e `formatting_seconds`. Esses tempos não incluem a espera
na fila nem a preparação da imagem no cliente. Para validar sem rede ou Telegram:

```bash
python -m unittest -v test_manual_extraction test_price_engine
```

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
| `ML_AFFILIATE_PREFIX` | (legado — ML usa linkbuilder com sessão logada) | Opcional |
| `PANEL_USER` | Usuário do painel | Sim |
| `PANEL_PASSWORD` | Senha do painel | Sim |
| `CHECK_INTERVAL_MINUTES` | Intervalo entre ciclos | Padrão: 15 |
| `ENABLED_STORES` | Lojas ativas (vírgula) | Padrão: amazon |
| `DASHBOARD_URL` | URL pública do painel | Para tracking |

---

## Licença

Este projeto é de código aberto sob a licença MIT. Veja o arquivo [LICENSE](LICENSE) para detalhes.

---

## Créditos

Desenvolvido por [@brunomrusso](https://github.com/brunomrusso) com auxílio do [Devin](https://devin.ai).
