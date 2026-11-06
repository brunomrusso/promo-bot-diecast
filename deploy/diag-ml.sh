#!/usr/bin/env bash
# Só leitura: como o Chrome do ML do bot está configurado e o que ele fez nas últimas horas.
cd /home/ubuntu/promo-bot-carros
echo "== .env (só nomes e valores não secretos)"
grep -nE '^(#DESLIGADO )?(ML_ECONOMIA|ML_PROXY_BYPASS|ML_TAG_BOT|ML_TAG_SITE|AMAZON_TAG|AMAZON_TAG_SITE|ENABLED_STORES|CHECK_INTERVAL_MINUTES|ML_INTERVALO_MIN)=' .env
echo "   linhas grudadas (sem quebra de linha)? $(grep -cE '[a-z0-9]ML_[A-Z_]+=' .env)"
echo "   termina com quebra de linha? $(tail -c1 .env | od -An -c | tr -d ' ')"
./venv/bin/python - <<'PY'
import os, config
print("== o bot enxerga: ML_ECONOMIA =", repr(os.getenv("ML_ECONOMIA")), "->", "economia DESLIGADA" if os.getenv("ML_ECONOMIA", "1") == "0" else "economia LIGADA")
p = config.ml_playwright_proxy() or {}
print("   proxy:", p.get("server"), "| bypass:", p.get("bypass", "nenhum"), "| etiquetas ML:", config.ML_TAG_BOT, config.ML_TAG_SITE)
PY
echo "== log do bot (últimas 6 h): o que o Chrome do ML fez"
sudo journalctl -u promobot --since "6 hours ago" --no-pager | grep -E '\[ML\] (usando proxy|economia)|captcha|verifica|bloque|Blocked|ml_session' | tail -25 | sed 's/^.*\]: /   /'
echo "== fim (nada foi mudado)"
