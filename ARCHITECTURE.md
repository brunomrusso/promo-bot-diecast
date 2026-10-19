# Arquitetura — Promo Bot Diecast

Este documento descreve a arquitetura do sistema, fluxos de dados, componentes e decisões técnicas.

---

## Visão geral

O sistema é composto por dois processos independentes que compartilham o mesmo banco SQLite:

```
┌─────────────────────────────────────────────────────────┐
│                    Oracle Cloud VM                       │
│                                                         │
│  ┌──────────────┐          ┌──────────────────────┐     │
│  │   main.py    │          │    dashboard.py       │     │
│  │  (promobot)  │          │  (Flask + Gunicorn)   │     │
│  │              │          │                       │     │
│  │  Scraping    │          │  Painel web           │     │
│  │  Filtragem   │◄────────►│  API REST             │     │
│  │  Aprovação   │  SQLite  │  Jobs assíncronos     │     │
│  │  Publicação  │          │                       │     │
│  └──────┬───────┘          └───────────┬───────────┘     │
│         │                              │                 │
│         ▼                              ▼                 │
│  ┌──────────────┐          ┌──────────────────────┐     │
│  │ Telegram API │          │  Cloudflare Tunnel   │     │
│  │  (Bot)       │          │  (HTTPS externo)     │     │
│  └──────────────┘          └──────────────────────┘     │
└─────────────────────────────────────────────────────────┘
```

---

## Componentes

### 1. Bot principal (`main.py`)

Loop contínuo que executa ciclos de busca a cada `CHECK_INTERVAL_MINUTES`:

```
┌─────────────────────────────────────────────────────┐
│                    Ciclo do Bot                      │
│                                                     │
│  1. Carregar keywords e configurações dinâmicas     │
│  2. Para cada loja habilitada:                      │
│     ├─ Buscar produtos por keyword                  │
│     ├─ Para cada produto:                           │
│     │   ├─ Verificar duplicata (já postado?)        │
│     │   ├─ Verificar republicação (preço caiu >15%)│
│     │   ├─ Verificar alerta de preço               │
│     │   ├─ Registrar preço em minis monitoradas     │
│     │   ├─ Aplicar filtros de relevância            │
│     │   ├─ Verificar regra de marca                 │
│     │   ├─ Gerar link de afiliado                   │
│     │   ├─ Verificar período silencioso             │
│     │   └─ Enviar para aprovação ou publicar        │
│  3. Coletar cupons do ML (se habilitado)            │
│  4. Processar publicações agendadas                 │
│  5. Aguardar intervalo                              │
└─────────────────────────────────────────────────────┘
```

**Threads:**
- `main thread`: loop de scraping + publicação
- `approvals thread`: polling de callbacks do Telegram (botões inline)
- `scheduler thread`: APScheduler para processar publicações agendadas

### 2. Dashboard (`dashboard.py`)

Aplicação Flask servida via Gunicorn (1 worker) com as seguintes responsabilidades:

- **Autenticação**: login por usuário/senha via variáveis de ambiente
- **Pages**: 15 templates Jinja2 server-rendered
- **API REST**: endpoints JSON para aprovações, extração, publicação, alertas, blacklist
- **Jobs assíncronos**: extração de produto e publicação rodam em threads separadas via `manual_jobs.py`

### 3. Scrapers (`scrapers/`)

Cada loja tem dois scrapers: HTTP direto (leve) e Playwright (navegador real, para anti-bot):

| Loja | HTTP | Playwright | Notas |
|------|:----:|:----------:|-------|
| Amazon | `amazon.py` | `amazon_pw.py` | HTTP priorizado; resolve links curtos, extrai Buy Box |
| Mercado Livre | `mercadolivre.py` | `mercadolivre_pw.py` | PW necessário; sessão persistente com proteção anti-captcha |
| Shopee | `shopee.py` | `shopee_pw.py` | API interna não-oficial |
| Lomadee | `lomadee.py` | — | API oficial de rede de afiliados |

**Decisão**: O scraper HTTP é preferido quando possível (mais rápido, menos recursos). Playwright é fallback para lojas que exigem JavaScript ou sessão de navegador.

### 4. Banco de dados (`db.py`)

SQLite único (`deals.db`) com as seguintes tabelas:

```
┌─────────────────────┐     ┌──────────────────────┐
│       posted         │     │   monitored_items     │
├─────────────────────┤     ├──────────────────────┤
│ product_id (PK)     │     │ id (PK)              │
│ store, title, price │     │ name, search_terms   │
│ status, url, image  │     │ required_terms       │
│ original_price      │     │ max_price, active    │
│ discount            │     │ historical_min       │
│ brand_rule_id       │     │ last_seen_price      │
│ coupon_code/savings │     │ image                │
│ affiliate_url       │     └──────────────────────┘
│ posted_at           │
└─────────────────────┘     ┌──────────────────────┐
                            │  price_observations   │
┌─────────────────────┐     ├──────────────────────┤
│     blacklist        │     │ item_id → monitored  │
├─────────────────────┤     │ price, store, url    │
│ id, kind, value     │     │ image, observed_at   │
│ label, active       │     └──────────────────────┘
└─────────────────────┘
                            ┌──────────────────────┐
┌─────────────────────┐     │    price_alerts       │
│    brand_rules       │     ├──────────────────────┤
├─────────────────────┤     │ product_id, title    │
│ id, name, active    │     │ target_price         │
│ match_terms         │     │ current_price        │
│ min_discount        │     │ triggered            │
│ approval_mode       │     └──────────────────────┘
│ auto_approve_discount│
│ daily_limit         │     ┌──────────────────────┐
│ priority            │     │   scheduled_posts     │
└─────────────────────┘     ├──────────────────────┤
                            │ deal (JSON)          │
┌─────────────────────┐     │ scheduled_at, status │
│       clicks         │     └──────────────────────┘
├─────────────────────┤
│ product_id          │     ┌──────────────────────┐
│ clicked_at          │     │    app_settings       │
│ referer, ua         │     ├──────────────────────┤
└─────────────────────┘     │ key → value (JSON)   │
                            └──────────────────────┘
```

**Decisão**: SQLite foi escolhido por simplicidade (zero configuração), backup trivial (copiar 1 arquivo), e performance suficiente para o volume (~300 deals/semana).

### 5. Notificador (`notifier.py`)

Responsável por toda comunicação com a API do Telegram:

- `send_deal()` → Publica no canal (com imagem, tracking link)
- `send_for_approval()` → Envia ao admin com botões inline
- `send_price_alert()` → Notifica que alerta foi atingido
- `send_whatsapp_ready()` → Envia texto formatado para WhatsApp
- `format_whatsapp()` → Gera texto para cópia manual

### 6. Sistema de afiliados (`affiliate.py`)

```
URL original
    │
    ▼
┌─────────────────────┐
│  to_affiliate_url() │
│                     │
│  Amazon?  → limpa URL, adiciona ?tag=AMAZON_TAG
│  ML?      → meli.la/PREFIXO/URL (ou Lomadee)
│  Shopee?  → Lomadee deeplink
│  Lomadee? → já vem monetizado
└─────────────────────┘
    │
    ▼
is_monetized() → valida se link contém tag/prefixo
```

**Regra**: Nunca publicar link não-monetizado intencionalmente. Se a monetização falhar, o produto vai para aprovação manual.

---

## Fluxos principais

### Fluxo de publicação automática

```
Scraper encontra deal
    │
    ├─ Já postado? ──────── Sim ──► Verificar republicação (>15% queda)
    │                                    │
    │                               Não reposta ──► Ignorar
    │
    ├─ Alerta ativo? ───── Preço acima ──► Ignorar
    │                       │
    │                       Preço atingiu ──► Notificar + Enviar p/ aprovação
    │
    ├─ Filtros passam? ──── Não ──► Ignorar
    │
    ├─ Período silencioso? ─ Sim ──► Salvar como pending (sem notificar)
    │
    ├─ Aprovação manual? ── Sim ──► Telegram admin (botões inline)
    │                                    │
    │                               Aprovar ──► Publicar no canal
    │                               Rejeitar ──► Marcar rejeitado
    │                               Bloquear ──► Adicionar à blacklist
    │
    └─ Auto-aprovar ──────────────────────► Publicar no canal
```

### Fluxo de criação manual

```
Usuário cola URL no painel
    │
    ▼
Extração assíncrona (thread)
    ├─ Resolver redirects
    ├─ Extrair título, preço, imagem, desconto
    ├─ Gerar link de afiliado
    └─ Retornar preview
    │
    ▼
Usuário edita/confirma/adiciona cupom
    │
    ├─ "Enviar ao canal" ──► Publicar imediatamente
    ├─ "Agendar" ──────────► Salvar com horário
    ├─ "Copiar WhatsApp" ──► Clipboard
    └─ "Monitorar mini" ───► Criar monitoramento
```

### Fluxo de alerta de preço

```
Usuário marca "Caro" na aprovação
    │
    ├─ Define preço-alvo (padrão: 80% do atual)
    └─ Produto sai da fila, vai para Alertas
    │
    ▼
Bot encontra produto novamente
    │
    ├─ Preço > alvo ──► Ignorar silenciosamente
    └─ Preço ≤ alvo ──► Marcar triggered
                        ├─ Notificar no Telegram pessoal
                        └─ Enviar para aprovação
```

---

## Decisões técnicas

### Por que SQLite e não PostgreSQL?
- A VM tem 1 GB de RAM; PostgreSQL consumiria ~100MB só parado
- Volume de dados é pequeno (~300 deals/semana, ~2 minis monitoradas)
- Backup é copiar 1 arquivo
- Concorrência é baixa (2 processos, sem escritas simultâneas pesadas)

### Por que Flask e não FastAPI?
- Templates server-rendered (Jinja2) são nativos do Flask
- Não precisa de async no dashboard (requests são rápidos)
- Menor footprint de memória

### Por que Playwright e não Selenium?
- Playwright tem melhor stealth (playwright-stealth)
- API moderna e async-friendly
- Instalação mais simples (`playwright install`)

### Por que Cloudflare Tunnel e não exposição direta?
- A Oracle Cloud bloqueia portas por padrão (security list)
- Tunnel fornece HTTPS gratuito sem certificado manual
- Protege o IP real do servidor

### Por que não WhatsApp Bot?
- APIs oficiais do WhatsApp Business são pagas para mensagens promocionais
- APIs não-oficiais causam banimento da conta
- Solução: gerar texto formatado para WhatsApp que o usuário cola manualmente

---

## Infraestrutura

```
┌──────────────────────────────────────────────────┐
│              Oracle Cloud (Always Free)            │
│              VM.Standard.E2.1.Micro                │
│              Ubuntu 22.04, 1 vCPU, 1 GB RAM       │
│                                                    │
│  systemd services:                                 │
│  ┌────────────────┐  ┌──────────────────────────┐ │
│  │   promobot      │  │     dashboard             │ │
│  │   (main.py)     │  │  (gunicorn :8080)         │ │
│  │                  │  │                           │ │
│  │  + Xvfb :99     │  │  + cloudflared tunnel     │ │
│  │  (display       │  │  (HTTPS → :8080)          │ │
│  │   virtual)      │  │                           │ │
│  └────────────────┘  └──────────────────────────┘ │
│                                                    │
│  ┌────────────────┐  ┌──────────────────────────┐ │
│  │ promobot-backup │  │     deals.db              │ │
│  │ (timer diário)  │  │  (SQLite, ~5 MB)          │ │
│  └────────────────┘  └──────────────────────────┘ │
│                                                    │
│  Swap: 2 GB (compensar RAM limitada)               │
└──────────────────────────────────────────────────┘
         │
         ▼
┌──────────────────┐    ┌───────────────────┐
│ Telegram Bot API │    │ Cloudflare Tunnel │
│ - Canal público  │    │ - HTTPS gratuito  │
│ - Admin privado  │    │ - Sem expor IP    │
└──────────────────┘    └───────────────────┘
```

### Recursos da VM
- **CPU**: 1 vCPU (OCPU 1/8) — suficiente; scraping é I/O-bound
- **RAM**: 1 GB + 2 GB swap — Chrome (Playwright) consome ~300-500MB
- **Disco**: 50 GB boot volume — amplo para o projeto (~100 MB total)
- **Rede**: ~480 Mbps — mais que suficiente para API calls

### Restrição de concorrência
O Playwright abre um navegador Chromium. Para evitar OOM na VM de 1 GB:
- Apenas 1 instância do Chrome por vez
- Scrapers HTTP são priorizados quando possível
- O dashboard não usa Chrome (extração Amazon é HTTP)

---

## Segurança

- **Secrets**: todos em `.env`, nunca no código ou no Git
- **Autenticação**: login obrigatório no painel (comparação com `hmac.compare_digest`)
- **Headers**: `X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy`
- **Cache**: `no-cache, no-store, must-revalidate` para evitar dados stale
- **Cloudflare**: túnel criptografado, sem exposição de portas
- **Blacklist**: proteção contra publicação de produtos irrelevantes
- **Monetização**: validação de link antes de publicar; nunca envia link sem tag

---

## Monitoramento

| Métrica | Onde | Como |
|---------|------|------|
| Status das lojas | Saúde do sistema | Auto-refresh 5min |
| Ofertas/ciclo | Métricas | Contagem diária |
| Cliques | Métricas | Tracking via `/go/` |
| Erros de scraping | Logs | `journalctl -u promobot` |
| Memória/swap | Saúde do sistema | Leitura de `/proc/meminfo` |
| Sessão ML | Saúde do sistema | Verificação de cookies |
| Banco | Saúde do sistema | Tamanho + integridade |
