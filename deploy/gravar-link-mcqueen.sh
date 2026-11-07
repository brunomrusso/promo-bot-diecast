#!/usr/bin/env bash
# Grava no bot o link do site (etiqueta russosite) que o Bruno gerou à mão para o McQueen Rusteze. Não usa proxy.
cd /home/ubuntu/promo-bot-carros
./venv/bin/python - <<'PY'
import config
from core import db
url = "https://www.mercadolivre.com.br/carros-da-disney-pixar-lightning-mcqueen-rusteze-cor-vermelha/p/MLB41554421?pdp_filters=item_id%3AMLB5375349491"
link = "https://meli.la/1JAhdq9"
assert config.ML_TAG_SITE == "russosite", config.ML_TAG_SITE
db.cache_affiliate_link(f"Mercado Livre#{config.ML_TAG_SITE}", url, link)
falhas = db.get_setting("ml_site_link_falhas", {}) or {}
if falhas.pop(url, None):
    db.set_setting("ml_site_link_falhas", falhas)
print("ok: link gravado ->", db.cached_affiliate_link(f"Mercado Livre#{config.ML_TAG_SITE}", url))
print("O McQueen volta ao site no próximo ciclo do bot (até 15 min).")
PY
