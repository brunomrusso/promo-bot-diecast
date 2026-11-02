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
│  1. Carregar somente o catálogo ativo               │
│  2. Arquivar pendentes legados sem veredito humano   │
│  3. Por loja: até 3 buscas autorizadas, em rotação   │
│     ├─ Descartar itens fora dos termos obrigatórios │
│     ├─ Registrar preços autorizados silenciosamente │
│     └─ Selecionar uma oferta por produto            │
│  4. Alvo atingido ou histórico nacional confiável?  │
│     ├─ Não: apenas aprendizado                     │
│     └─ Sim: enfileirar para revisão manual          │
│  5. Limites: 5 entradas/ciclo, 20 pendentes          │
│  6. Processar jobs manuais e agenda explícita        │
│  7. Aguardar intervalo; não publicar autonomamente  │
└─────────────────────────────────────────────────────┘
```

**Threads:**
- `main thread`: loop de scraping, publicação e processamento da fila de jobs (`manual_jobs.process_jobs`, com lotes urgentes entre cada keyword/produto)
- `approvals thread`: polling de callbacks do Telegram (botões inline); aprovações viram jobs na mesma fila

### 2. Dashboard (`dashboard.py`)

Aplicação Flask servida via Gunicorn (1 worker) com as seguintes responsabilidades:

- **Autenticação**: login por usuário/senha via variáveis de ambiente
- **Pages**: 15 templates Jinja2 server-rendered
- **API REST**: endpoints JSON para aprovações, extração, publicação, alertas, blacklist
- **Fila de jobs**: o painel grava pedidos na tabela `manual_jobs` (extração de produto, aprovar, compartilhar, agendar); o **bot** os executa entre as etapas seguras do scraping, com prioridade para ações manuais (`urgent_only`) — sem threads nem Chrome extra no dashboard

### 3. Scrapers (`scrapers/`)

Cada loja tem dois scrapers: HTTP direto (leve) e Playwright (navegador real, para anti-bot):

| Loja | HTTP | Playwright | Notas |
|------|:----:|:----------:|-------|
| Amazon | `amazon.py` | `amazon_pw.py` | HTTP priorizado; resolve links curtos, extrai Buy Box |
| Mercado Livre | `mercadolivre.py` | `mercadolivre_pw.py` | PW necessário; sessão persistente com proteção anti-captcha |
| Shopee | `shopee.py` | `shopee_pw.py` | API interna não-oficial |
| Lomadee | `lomadee.py` | — | API oficial de rede de afiliados |

**Decisão**: O scraper HTTP é preferido quando possível (mais rápido, menos recursos). Playwright é fallback para lojas que exigem JavaScript ou sessão de navegador. Todas as variantes Playwright compartilham **um único contexto persistente** (`chrome_profile_ml`) para evitar processos Chrome concorrentes na VM de 1 GB.

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

┌─────────────────────┐     ┌──────────────────────┐
│   product_prices     │     │    manual_jobs        │
├─────────────────────┤     ├──────────────────────┤
│ signature, prod_id  │     │ action, status       │
│ store, title, price │     │ payload/result (JSON)│
│ verdict (seen/      │     │ error, updated_at    │
│ approved/rejected)  │     └──────────────────────┘
│ day, seen_at        │
│ UNIQUE(prod_id,day) │     ┌──────────────────────┐
└─────────────────────┘     │    system_state       │
                            ├──────────────────────┤
┌─────────────────────┐     │ key (heartbeat,      │
│   affiliate_links    │     │ ml_session, cycle)   │
├─────────────────────┤     │ value (JSON)         │
│ store, source_url   │     └──────────────────────┘
│ affiliate_url       │
│ updated_at          │     ┌──────────────────────┐
└─────────────────────┘     │    store_health       │
                            ├──────────────────────┤
                            │ store, status        │
                            │ offers, duration     │
                            │ error, last_check    │
                            └──────────────────────┘
```

**Status possíveis em `posted`:** `pending` (na fila), `posted`, `rejected`, `auto_rejected` (rejeição aprendida pelo histórico), `superseded` (substituído por anúncio equivalente melhor), `blacklisted`, `expired`, `scheduled`, `price_alert`, `catalog_archived` (arquivamento neutro da busca aberta).

**Decisão**: SQLite foi escolhido por simplicidade (zero configuração), backup trivial (copiar 1 arquivo), e performance suficiente para o volume (~300 deals/semana).

### 5. Notificador (`notifier.py`)

Responsável por toda comunicação com a API do Telegram:

- `send_deal()` → Publica no canal (com imagem, tracking link)
- `send_for_approval()` → Envia ao admin com botões inline
- `send_whatsapp_ready()` → Envia texto formatado para WhatsApp
- `format_whatsapp()` → Gera texto para cópia manual

### 6. Sistema de afiliados (`affiliate.py`)

```
URL original
    │
    ▼
┌─────────────────────┐
│  cached_affiliate_url│ → cache persistente (affiliate_links, 7 dias)
│         │ miss       │
│  to_affiliate_url() │
│                     │
│  Amazon?  → limpa URL, adiciona ?tag=AMAZON_TAG
│  ML?      → linkbuilder meli.la via sessão logada (Playwright persistente)
│  Shopee?  → Lomadee deeplink (ou sub-id do programa)
│  Lomadee? → já vem monetizado
└─────────────────────┘
    │
    ▼
is_monetized() → exige https + host meli.la/lmdee.link exato,
                 ou domínio Amazon com a tag configurada
```

**Regra**: Nunca publicar link não-monetizado intencionalmente. Se a geração falhar, a URL original é devolvida mas **rejeitada pelo `is_monetized`** — o job falha com "link não monetizado" em vez de publicar sem comissão. Links colados com tag de terceiros (parâmetros `matt_*`, redirects `meli.la`/`/social/`) são normalizados para a URL do produto antes de gerar o link próprio.

### 7. Aprendizado de preços e deduplicação (`db.py`)

O sistema aprende "o que é um preço bom" em vez de depender só de cadastros manuais:

```
Somente ofertas que correspondem ao catálogo ativo
    │
    ▼
title_signature() → conjunto de tokens relevantes do título
                    (ignora enchimento: "carrinhos", "novo", "frete"...)
    │
    ▼
product_prices: 1 linha por anúncio por dia (preço público, sem cupom)
    ├─ verdict='seen'      → avistamento normal
    ├─ verdict='approved'  → usuário aprovou/publicou
    └─ verdict='rejected'  → usuário rejeitou/bloqueou
    │
    ▼
market_price_evaluation() → equivalência conservadora por tokens (≥0,70)
    com restrições de referência, ano, quantidade e cor
    │
    ▼
Somente origin='national'; registros legados ficam 'unknown'
    ├─ alternativas de hoje por anúncio (sem cupom e sem frete)
    └─ mínimos por dia, com peso igual entre dias, nos últimos 90 dias
    │
    ▼
Decisão no ciclo fechado:
    ├─ alvo explícito atingido → candidato para revisão
    ├─ sem alvo, preço favorável + ≥5 dias + alternativa nacional atual → candidato para revisão
    └─ acima do alvo, sem histórico ou sem confiança → aprendizado silencioso

Percentual OFF não filtra coleta nem participa do score.
Relevância é temática; não significa preço bom.
Até 3 termos autorizados por loja/ciclo em rotação. Até 2 verificações de origem por ciclo no ML, somente de produtos cadastrados, no mesmo Chrome. A leitura usa a coluna de compra/entrega, não recomendações. Origem desconhecida não autoriza uma oportunidade aprendida; alvo explícito pode gerar revisão com aviso para conferir origem e frete.
```

**Fila por cadastro** (`enqueue_catalog_opportunity`, transação `BEGIN IMMEDIATE`):
- Um pendente por `monitored_item_id`; melhoria acima de 1% substitui o anterior (`superseded`).
- `catalog_opportunities` mantém o último preço apresentado. Após uma decisão/expiração, exige queda de pelo menos 3% para reapresentar.
- Até 5 entradas por ciclo e 20 pendentes do catálogo. Acima desses limites, continua coletando sem gerar cards.
- `catalog_archives` preserva a origem dos pendentes da busca aberta. Eles viram `catalog_archived`, não `rejected`; preços e vereditos não são apagados.

**Segurança:** o ciclo automático não publica produtos nem cupons abertos no canal; só solicita revisão. Jobs de publicação manual e agendas confirmadas continuam independentes. Origem nacional e histórico confiável não dispensam revisão. Rejeições genéricas não impõem teto permanente de preço. O criador manual não autoriza monitoramento por si só: o usuário deve clicar em “Autorizar monitoramento” e salvar o cadastro.

**Auditoria e desfazer:** a Central de aprovações tem uma seção "Decisões recentes" (7 dias) listando `rejected`, `auto_rejected` e `superseded` com o motivo (`score_reasons`). O botão **Restaurar** limpa o veredito `rejected` do anúncio (e registros legados sem ID da mesma assinatura). Só devolve ao `pending` se autorizado ou manual, respeitando os limites; fora do catálogo, desfaz a decisão sem iniciar monitoramento.

---

### 8. Histórico orientado à curadoria

- `/monitored/<id>?days=7|30|90` filtra gráfico, estatísticas e comparação por loja. `monitored_price_summary` conta leituras e dias distintos; a profundidade exibida considera 90 dias, independentemente do período selecionado. Menos de 5 dias nunca é apresentado como avaliação conclusiva.
- A interface prioriza a menor oferta com indicação nacional entre os anúncios carregados. Sem indicação nacional, destaca a menor de origem desconhecida com aviso; importados não são apresentados como candidata nacional. Alternativas e diagnóstico ficam recolhidos.
- Filtros por alvo e origem movem/ocultam os mesmos cards, preservando inputs de cupom e estado do compartilhamento. Os contadores descrevem somente o conjunto carregado da última pesquisa, não toda a internet.
- `/api/monitored/<id>/target` exige login e valida valor finito não negativo; vazio/zero significa aprender sem alvo. Atualiza somente `monitored_items.max_price`. A tela atualiza diferenças por oferta e a linha tracejada do gráfico sem recarregar nem criar novo cadastro.
- O gráfico usa Canvas já existente: mínimo/média/máximo por dia, espaçamento por datas, alvo incluído na escala e cores adaptadas ao tema. As médias mostradas são das coletas, não estimativa de preço justo; frete/cupom/taxas não estão incluídos.

## Fluxos principais

### Fluxo de oportunidade do catálogo

```
Catálogo ativo → buscar somente termos dos produtos cadastrados
    ├─ Fora dos critérios / internacional → ignorar
    └─ Produto autorizado → registrar preço
         ├─ Sem alvo atingido ou histórico confiável → aprender silenciosamente
         └─ Oportunidade → conferir repetição e limites
              ├─ Mesmo preço / pior / fila cheia → não gerar card
              └─ Novo ou melhor → pending (um por produto)
                   ├─ Horário silencioso → sem notificação
                   └─ Fora do silêncio → avisar admin para revisar

Aprovação explícita → reextrair preço → validar link monetizado → publicar
Rejeição explícita → registrar veredito humano
Não existe saída de auto-publicação no ciclo de monitoramento.
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

### Fluxo de compartilhamento WhatsApp (sem API)

Também disponível nos cards da pesquisa em Minis monitoradas. O endpoint `/api/monitored/<id>/share` recupera a oferta da pesquisa salva (não aceita título, preço ou link fornecidos pelo cliente), aplica o cupom validado e retorna o texto com link monetizado. Se necessário, cria o job prioritário `share_monitored`, sem publicação ou agendamento. A versão da pesquisa e alterações do cupom invalidam preparações desatualizadas.

O WhatsApp não tem API gratuita para anexar imagem com legenda. O painel usa o
compartilhamento nativo do navegador (`whatsapp-share.js`), igual na Central de
aprovações e no criador de anúncios:

```
Usuário toca "WhatsApp" no card
    │
    ├─ Link monetizado em cache? ── Sim ──► resposta direta (sem fila)
    │                        └ Não ──► job 'share_pending' prioritário no bot
    │
    ▼
"Copiar legenda" → clipboard com texto formatado (plain + HTML com quebras)
    │
    ▼
"Enviar foto" → Web Share API só com a imagem JPEG (WebP é convertido
                via canvas, senão o WhatsApp a trata como documento)
    │
    ▼
Usuário escolhe o WhatsApp e cola o texto em "Adicionar legenda" na prévia
```

Compartilhar **não** aprova nem publica a oferta — o card permanece na fila.
Edição posterior do anúncio invalida o compartilhamento preparado.
Fallbacks no menu "⋯": copiar só o texto, baixar só a imagem, abrir foto original.

### Fluxo de alerta de preço (unificado no catálogo)

O alvo é uma propriedade única da mini monitorada (`monitored_items.max_price`).
A antiga tabela `price_alerts` virou legado somente-leitura.

```
Usuário marca "Caro" na aprovação
    │
    ├─ Define preço-alvo (padrão: 80% do atual)
    └─ Alvo gravado em monitored_items.max_price da mini de origem
       (oferta sai da fila como price_alert)
    │
    ▼
Bot coleta preços da mini a cada ciclo
    │
    ├─ Preço > alvo ──► Aprendizado silencioso (sem card)
    └─ Preço ≤ alvo ──► Oportunidade para revisão na Central

Alertas antigos sem mini correspondente ficam listados como "legado"
na tela de Minis até serem removidos ou vinculados (migrated=1).
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
- Solução: compartilhamento nativo do navegador (foto JPEG via Web Share API) +
  legenda copiada para a área de transferência — ver fluxo em "Fluxos principais"

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
