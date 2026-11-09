#!/usr/bin/env bash
# Só leitura, conexão direta (sem proxy): de onde dá para tirar "mais vendidos" de Mini GT na Amazon.
cd /home/ubuntu/promo-bot-carros
RUN="./venv/bin/python"; command -v xvfb-run >/dev/null && RUN="xvfb-run -a ./venv/bin/python"
$RUN - <<'PY'
import re
from playwright.sync_api import sync_playwright
eh_mg = lambda t: bool(re.search(r"mini\s?gt|kaido", t or "", re.I))
with sync_playwright() as p:
    try: b = p.chromium.launch(channel="chrome", headless=False)
    except Exception: b = p.chromium.launch(headless=False)
    pg = b.new_context(locale="pt-BR").new_page()
    def abre(url):
        pg.goto(url, wait_until="domcontentloaded", timeout=45000); pg.wait_for_timeout(2500)
        txt = pg.content().lower()
        return not ("captcha" in txt and "validatecaptcha" in txt)
    print("== 1) mais vendidos do nó usado hoje (23627140011), páginas 1 e 2")
    for pgn in (1, 2):
        if not abre(f"https://www.amazon.com.br/gp/bestsellers/toys/23627140011?pg={pgn}"):
            print("   captcha"); break
        tit = pg.eval_on_selector_all("div[id^='p13n-asin-index'], .zg-grid-general-faceout", "els=>els.map(e=>e.innerText.split('\\n').find(l=>l.length>15)||'')")
        print(f"   pág {pgn}: {len(tit)} itens; Mini GT/Kaido: {sum(eh_mg(t) for t in tit)}; título da página: {pg.title()[:60]}")
    print("== 2) busca 'mini gt 1:64' na Amazon")
    for sort in ("exact-aware-popularity-rank", ""):
        if not abre("https://www.amazon.com.br/s?k=mini+gt+1%3A64" + (f"&s={sort}" if sort else "")):
            print("   captcha"); break
        opts = pg.eval_on_selector_all("#s-result-sort-select option", "els=>els.map(e=>e.value+'='+e.textContent.trim())")
        res = pg.eval_on_selector_all("div[data-component-type='s-search-result']", "els=>els.map(e=>[e.getAttribute('data-asin'), (e.querySelector('h2')||{}).innerText||'', (e.querySelector('.a-price .a-offscreen')||{}).innerText||''])")
        mg = [r for r in res if eh_mg(r[1])]
        print(f"   ordem={sort or 'padrão'}: {len(res)} resultados, {len(mg)} Mini GT/Kaido com {sum(1 for r in mg if r[2])} com preço")
        if sort: print("   opções de ordenação:", opts)
        for a, t, pr in mg[:12]: print(f"     {a} {pr:>12}  {t[:60]}")
    b.close()
print("== fim (nada foi mudado)")
PY
