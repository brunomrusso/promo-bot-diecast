# promo-bot-carros

Monitora promoções de Hot Wheels, miniaturas Disney/Pixar Cars, LEGO de carros
e similares na **Amazon BR, Mercado Livre e Shopee**, e posta as melhores
ofertas num canal/grupo do Telegram com seu link de afiliado.

## Setup

```bash
python -m venv venv
venv\Scripts\activate        # Windows
pip install -r requirements.txt
copy .env.example .env       # e preencha
```

## Telegram

1. Crie um bot com o [@BotFather](https://t.me/BotFather) → `TELEGRAM_BOT_TOKEN`
2. Adicione o bot como admin do seu canal/grupo
3. `TELEGRAM_CHAT_ID`: use `@nomedocanal` para canal público, ou pegue o ID
   numérico com o [@userinfobot](https://t.me/userinfobot) / `getUpdates` da API

## Mercado Livre (necessário para o scraper funcionar)

O ML bloqueia scraping anônimo. Crie um app grátis em
[developers.mercadolivre.com.br](https://developers.mercadolivre.com.br) e
preencha `ML_CLIENT_ID` / `ML_CLIENT_SECRET` no `.env`. O bot usa
`client_credentials` — só leitura de busca pública, sem dados de usuário.

## Afiliados (onde entra o dinheiro)

Cadastre-se e configure no `.env`:

- **Amazon Associates** → `AMAZON_TAG` (ex: `seunome-20`)
- **Shopee Afiliados** → `SHOPEE_AFFILIATE_ID`
- **Mercado Livre** → programa próprio ou via Lomadee/Awin → `ML_AFFILIATE_PREFIX`

Sem credenciais o bot funciona normalmente, só que posta o link direto
(sem comissão).

## Rodar

```bash
python main.py           # loop contínuo (CHECK_INTERVAL_MINUTES)
python main.py --once    # roda um ciclo e sai
```

Como seu PC não fica ligado 24h, o SQLite (`deals.db`) garante que nada é
postado duas vezes entre execuções. Depois é só copiar a pasta pro servidor.

## Ajustes

- `KEYWORDS` em `config.py` — adicione/remova termos de busca
- `MIN_DISCOUNT` no `.env` — desconto mínimo (%) para postar

## Avisos

- O scraper da **Amazon** é frágil: a Amazon bloqueia bots com captcha. Se
  parar de funcionar, use a PA-API oficial (disponível no programa de afiliados).
- O endpoint da **Shopee** é interno/não-oficial e pode mudar ou exigir
  cookies de sessão de navegador.
- Se Shopee/Amazon ficarem inconsistentes, uma alternativa robusta é migrar
  os scrapers para Playwright (navegador real) ou consumir agregadores de
  promoções como Pelando/Promobit.
