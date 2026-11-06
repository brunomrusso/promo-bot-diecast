"""Ranking do site (products.json) gerado no servidor, sem depender do PC do Bruno.

Faz o que a tarefa diária fazia no Chrome dele:
1. Mais Vendidos do Mercado Livre (7 categorias, mesmos filtros) e da Amazon (páginas 1 e 2);
2. reaproveita nome e link de afiliado dos produtos que já estão no site; produto novo ganha
   meli.la (gerador do bot) ou link da Amazon com a tag;
3. atualiza preço e histórico dos achadinhos MANUAIS do Mercado Livre (os do app são do site_export);
4. trava de segurança: captcha/bloqueio ou categoria que some de repente => não publica nada;
5. publica products.json e achadinhos.json por FTP (mesma conta do site_export), com cópia local
   da versão anterior em backups/site/.

Modo "teste" (padrão): os horários automáticos só geram a prévia e comparam com o site.
Modo "publicar": os horários automáticos publicam. O botão do painel pode publicar em qualquer modo.
"""
import json
import random
import re
import time
import unicodedata
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup

import config
from core import db

ZONE = ZoneInfo("America/Sao_Paulo")
ML = "https://www.mercadolivre.com.br"
AZ = "https://www.amazon.com.br"
CATS = ["mini-gt", "hot-wheels", "pixar-cars", "lego", "funko", "blokees", "pokemon-tcg"]
MAX_PER_CAT = 20
RUN_TIMES = ("06:40", "18:40")          # horário de Brasília
STATE_KEY = "site_ranking"
MODE_KEY = "site_ranking_mode"          # "teste" | "publicar"
TITLES_KEY = "site_ranking_az_titles"   # cache ASIN -> título
BASE = Path(__file__).resolve().parent.parent
PREVIEW = BASE / "backups" / "site" / "products.preview.json"
PREVIEW_ACH = BASE / "backups" / "site" / "achadinhos.preview.json"
PREVIEW_MAX_HOURS = 6

# Fonte de cada categoria no ML: página inicial + nomes dos links (filtros) a seguir, em ordem.
ML_SOURCES = {
    "mini-gt": ("/mais-vendidos/MLB2097", ["Mini GT"]),
    "hot-wheels": ("/mais-vendidos/MLB2097", ["Hot Wheels"]),
    "pixar-cars": ("/mais-vendidos/MLB2097", ["Mattel"]),
    "lego": ("/mais-vendidos/MLB455425", ["Blocos e Formas de Montar", "Lego"]),
    "funko": ("/mais-vendidos/MLB264337", ["Figuras de Ação", "Funko"]),
    "blokees": ("/mais-vendidos/MLB264337", ["Figuras de Ação", "Blokees"]),
    "pokemon-tcg": ("/mais-vendidos/MLB6899", ["Pokémon"]),
}
AZ_NODES = {"mini-gt": "23627140011", "hot-wheels": "20802846011", "pixar-cars": "20802846011",
            "lego": "16746738011", "funko": "16746732011", "blokees": "16746732011", "pokemon-tcg": "20802847011"}


class Blocked(Exception):
    """Captcha, login ou bloqueio: nada é publicado."""


class PaginaIndisponivel(Exception):
    """Página do ML respondeu erro (400/404 "Ops! Ocorreu um erro"): não é bloqueio, não pausa o ML."""


class Unsafe(Exception):
    """O resultado não parece confiável (categoria sumiu, poucos itens...): nada é publicado."""


# ---------------- textos e filtros ----------------

def norm(s):
    s = unicodedata.normalize("NFKD", str(s or "").lower())
    return "".join(c for c in s if not unicodedata.combining(c))


def _has(t, pattern):
    return re.search(pattern, norm(t)) is not None


def pokemon_ok(title):
    t = norm(title)
    if "pokemon" not in t:
        return False
    if re.search(r"sleeve|shield|toploader|porta cartas|protetor|deck box|playmat|tapete", t):
        return False
    if re.search(r"\bpasta\b", t) and not re.search(r"\bcartas?\b", t.replace("porta cartas", "")):
        return False
    if re.search(r"\blote\b|aleatori|dourad|metalic|\bgold\b", t):
        return False
    if re.match(r"\s*(kit\s+|combo\s+(com\s+)?)?\d+\s+cartas", t):
        return False
    return True


ML_FILTERS = {
    "mini-gt": lambda t: True,
    "hot-wheels": lambda t: not _has(t, r"monster|1[:/]16"),
    "pixar-cars": lambda t: _has(t, r"carros|cars|mcqueen|pixar") and not _has(t, r"hot wheels"),
    "lego": lambda t: _has(t, r"lego"),
    "funko": lambda t: _has(t, r"funko"),
    "blokees": lambda t: _has(t, r"blokees"),
    "pokemon-tcg": pokemon_ok,
}
AZ_FILTERS = {
    "mini-gt": lambda t: _has(t, r"mini ?gt|kaido"),
    "hot-wheels": lambda t: _has(t, r"hot wheels") and not _has(t, r"pista|monster|monstro|1:16"),
    "pixar-cars": lambda t: _has(t, r"disney|pixar") and not _has(t, r"hot wheels|friccao|toyng"),
    "lego": lambda t: _has(t, r"lego"),
    "funko": lambda t: _has(t, r"funko"),
    "blokees": lambda t: _has(t, r"blokees"),
    "pokemon-tcg": pokemon_ok,
}

# Categorias novas: entram sozinhas no products.json do site na primeira rodada (na posição de CATS).
CAT_DEFS = {
    "blokees": {"id": "blokees", "nome": "Blokees", "icone": "boneco",
                "origem": "Mais vendidos em Figuras de Ação · marca Blokees",
                "url_ml": "https://www.mercadolivre.com.br/mais-vendidos/MLB264337",
                "origem_amazon": "Ordem do ranking de Mais vendidos em Colecionáveis e Miniaturas, só Blokees",
                "url_amazon": "https://www.amazon.com.br/gp/bestsellers/toys/16746732011"},
}


def ensure_cats(current):
    """Acrescenta ao site as categorias de CATS que ainda não existem lá (sem mexer nas que já existem)."""
    cats = list(current.get("categorias", []))
    if not cats:
        return current
    ids = [c.get("id") for c in cats]
    for c in CATS:
        if c in ids or c not in CAT_DEFS:
            continue
        prev = [x for x in CATS[:CATS.index(c)] if x in ids]
        pos = ids.index(prev[-1]) + 1 if prev else len(ids)
        cats.insert(pos, dict(CAT_DEFS[c]))
        ids.insert(pos, c)
    return dict(current, categorias=cats)


def az_name(title):
    name = title.split(" | ")[0].strip()
    if len(name) > 95 and "," in name:
        name = name[:95].rsplit(",", 1)[0].strip()
    return name


def today():
    return datetime.now(ZONE).strftime("%Y-%m-%d")


def stamp():
    """Data e hora da consulta (o site mostra "06/11 às 07:12")."""
    return datetime.now(ZONE).strftime("%Y-%m-%dT%H:%M")


# ---------------- leitura das páginas (sem rede: testável) ----------------

def ml_links(html):
    """Texto do link -> URL, só para links de Mais Vendidos (filtros de marca/subcategoria)."""
    out = {}
    for a in BeautifulSoup(html, "html.parser").find_all("a", href=True):
        href = a["href"]
        if "mais-vendidos" in href:
            out.setdefault(norm(a.get_text(" ", strip=True)), href if href.startswith("http") else ML + href)
    return out


def _ml_id(href):
    for pat, fmt in ((r"/up/(MLBU\d+)", "{}"), (r"/p/(MLB\d+)", "{}"), (r"MLB-?(\d+)", "MLB{}")):
        m = re.search(pat, href or "")
        if m:
            return fmt.format(m.group(1))
    return None


def ml_items(html):
    items = []
    for li in BeautifulSoup(html, "html.parser").select("li.ui-search-layout__item"):
        a = li.select_one("a.poly-component__title")
        if not a:
            continue
        price = None
        cur = li.select_one(".poly-price__current")
        if cur:
            f = cur.select_one(".andes-money-amount__fraction")
            c = cur.select_one(".andes-money-amount__cents")
            if f:
                price = float(f.get_text(strip=True).replace(".", "") + "." + (c.get_text(strip=True) if c else "00"))
        imgs = " ".join((i.get("data-src") or "") + " " + (i.get("src") or "") for i in li.find_all("img"))
        key = re.search(r"\d+-ML[AB]U?\d+_\d+", imgs)
        pos = re.search(r"(\d+)\s*[º°o]\s*mais vendido", li.get_text(" ", strip=True), re.I)
        items.append({"t": a.get_text(" ", strip=True), "id": _ml_id(a.get("href")), "preco": price,
                      "k": key.group(0) if key else None, "pos": int(pos.group(1)) if pos else None})
    return [x for x in items if x["id"] and x["preco"] and x["k"] and x["pos"]]


def _nordic_state(html):
    """JSON que o ML embute na página (__NORDIC_RENDERING_CTX__): plano B quando o HTML muda de formato."""
    m = re.search(r'<script[^>]*id="__NORDIC_RENDERING_CTX__"[^>]*>(.*?)</script>', html, re.S)
    if not m:
        return None
    txt = m.group(1)
    i = txt.find("{")
    if i < 0:
        return None
    try:
        return json.JSONDecoder().raw_decode(txt, i)[0]
    except ValueError:
        return None


def _find_polycards(x, depth=0):
    if depth > 12:
        return None
    if isinstance(x, dict):
        if isinstance(x.get("polycards"), list) and x["polycards"]:
            return x["polycards"]
        for v in x.values():
            r = _find_polycards(v, depth + 1)
            if r:
                return r
    elif isinstance(x, list):
        for v in x[:30]:
            r = _find_polycards(v, depth + 1)
            if r:
                return r
    return None


def ml_items_json(html):
    """Mesmos campos de ml_items, lidos do JSON embutido (não depende das classes CSS da página)."""
    cards = _find_polycards(_nordic_state(html) or {}) or []
    items = []
    for n, pc in enumerate(cards, 1):
        meta = pc.get("metadata") or {}
        comps = {c.get("type"): c for c in pc.get("components") or [] if isinstance(c, dict)}
        title = (((comps.get("title") or {}).get("title") or {}).get("text") or "").strip()
        price = ((((comps.get("price") or {}).get("price") or {}).get("current_price") or {}).get("value")
                 or (meta.get("signal") or {}).get("prc"))
        pics = (pc.get("pictures") or {}).get("pictures") or []
        key = pics[0].get("id") if pics and isinstance(pics[0], dict) else None
        hl = (((pc.get("float_highlight_generic") or {}).get("highlight") or {}).get("text") or "")
        pos = re.search(r"(\d+)\s*[º°o]\s*mais vendido", hl, re.I)
        items.append({"t": title, "id": _ml_id("/" + (meta.get("url") or "")) or meta.get("id"),
                      "preco": round(float(price), 2) if price else None,
                      "k": key if key and re.fullmatch(r"\d+-ML[AB]U?\d+_\d+", key) else None,
                      "pos": int(pos.group(1)) if pos else n})
    return [x for x in items if x["t"] and x["id"] and x["preco"] and x["k"]]


_avisos = []  # usos do plano B nesta execução (vão no aviso do Telegram e no painel)


def ml_items_any(html, onde=""):
    """Lê pelo HTML; se vier quase vazio, tenta o JSON embutido. Usa o que trouxer mais itens."""
    a = ml_items(html)
    if len(a) >= 3:
        return a
    b = ml_items_json(html)
    if len(b) > len(a):
        _avisos.append(f"ML {onde}: lido pelo plano B (JSON da página), {len(b)} itens")
        return b
    return a


def az_ranking(html):
    """[(asin, rank)] do data-client-recs-list e {asin: título} pelos alt das imagens."""
    soup = BeautifulSoup(html, "html.parser")
    el = soup.select_one("[data-client-recs-list]")
    if not el:
        return None, {}
    ranks = [(r["id"], int(r["metadataMap"]["render.zg.rank"])) for r in json.loads(el["data-client-recs-list"])]
    titles = {}
    for g in soup.select("#gridItemRoot"):
        a = g.select_one('a[href*="/dp/"]')
        img = g.find("img")
        m = a and re.search(r"/dp/([A-Z0-9]{10})", a["href"])
        if m and img and img.get("alt"):
            titles[m.group(1)] = img["alt"].strip()
    return ranks, titles


def ml_url(id_ml):
    if id_ml.startswith("MLBU"):
        return f"{ML}/up/{id_ml}"
    return f"{ML}/p/{id_ml}"


# ---------------- montagem (sem rede: testável) ----------------

def pick_ml(raw):
    """Filtra, remove repetidos e corta em 20 por categoria (ordem do ranking real)."""
    out = {}
    for c, items in raw.items():
        seen, keep = set(), []
        for x in sorted(items, key=lambda i: i["pos"]):
            if x["id"] in seen:
                continue
            seen.add(x["id"])
            if ML_FILTERS[c](x["t"]):
                keep.append(x)
        out[c] = keep[:MAX_PER_CAT]
    return out


def pick_az(ranks_by_node, titles, cats=None):
    out = {}
    for c in (cats or CATS):
        seen, keep = set(), []
        for asin, rank in sorted(ranks_by_node.get(AZ_NODES[c], []), key=lambda r: r[1]):
            if asin in seen:
                continue
            seen.add(asin)
            if AZ_FILTERS[c](titles.get(asin, "")):
                keep.append({"asin": asin, "rank": rank, "t": titles.get(asin, "")})
        out[c] = keep[:MAX_PER_CAT]
    return out


def assemble(current, achadinhos, ml, az, hoje, new_ml_link):
    """Monta o products.json novo. new_ml_link(id_ml) -> meli.la ou '' (falhou)."""
    old_ml = {p["id_ml"]: p for p in current.get("produtos", []) if p.get("loja", "mercadolivre") == "mercadolivre" and p.get("id_ml")}
    old_az = {p["asin"]: p for p in current.get("produtos", []) if p.get("loja") == "amazon" and p.get("asin")}
    ach_az = {i["asin"]: i.get("link_afiliado") for i in (achadinhos or {}).get("itens", []) if i.get("loja") == "amazon" and i.get("asin")}
    cat_ids = [c.get("id") for c in current.get("categorias", [])] or CATS
    report = {"novos": [], "removidos": [], "precos": [], "sem_link": []}
    produtos = []
    for c in cat_ids:
        rank = 0
        for x in ml.get(c, []):
            o = old_ml.get(x["id"])
            if o and config.ML_TAG_SITE and o.get("etiqueta") != config.ML_TAG_SITE:
                novo = new_ml_link(x["id"])  # link antigo com outra etiqueta: refaz com a do site
                if (novo or "").startswith("https://meli.la/"):
                    o = dict(o, link_afiliado=novo, etiqueta=config.ML_TAG_SITE)
            if o:
                nome, link = o["nome"], o["link_afiliado"]
                if o.get("preco") != x["preco"]:
                    report["precos"].append(f"{c}: {nome[:40]} {o.get('preco')} -> {x['preco']}")
            else:
                nome, link = x["t"], new_ml_link(x["id"])
                if not (link or "").startswith("https://meli.la/"):
                    report["sem_link"].append(f"{c}: {x['t'][:50]}")
                    continue
                report["novos"].append(f"ML {c}: {nome[:50]}")
            rank += 1
            etq = (o or {}).get("etiqueta") if o else (config.ML_TAG_SITE or None)
            p = {"id": f"{c}-{rank:02d}", "loja": "mercadolivre", "id_ml": x["id"], "nome": nome,
                 "imagem": f"https://http2.mlstatic.com/D_NQ_NP_2X_{x['k']}-F.webp", "preco": x["preco"],
                 "preco_consultado_em": hoje, "categoria": c, "posicao_ranking": rank, "link_afiliado": link}
            if etq:
                p["etiqueta"] = etq
            if c == "pixar-cars":
                p["posicao_ml"] = x["pos"]
            produtos.append(p)
        for i, x in enumerate(az.get(c, []), 1):
            o = old_az.get(x["asin"])
            link = f"{AZ}/dp/{x['asin']}?tag={config.AMAZON_TAG_SITE}"  # site sempre com o ID do site
            if o:
                nome = o["nome"]
            else:
                nome = az_name(x["t"])
                report["novos"].append(f"Amazon {c}: {nome[:50]}")
            produtos.append({"id": f"az-{c}-{i:02d}", "loja": "amazon", "asin": x["asin"], "nome": nome,
                             "categoria": c, "posicao_ranking": i, "posicao_amazon": x["rank"],
                             "consultado_em": hoje, "link_afiliado": link})
    new_keys = {(p["loja"], p.get("id_ml") or p.get("asin")) for p in produtos}
    for p in current.get("produtos", []):
        k = (p.get("loja", "mercadolivre"), p.get("id_ml") or p.get("asin"))
        if k not in new_keys:
            report["removidos"].append(f"{'Amazon' if k[0] == 'amazon' else 'ML'} {p.get('categoria')}: {p.get('nome', '')[:50]}")
    out = {"atualizado_em": hoje, "fonte": current.get("fonte", f"{ML}/mais-vendidos"),
           "categorias": current.get("categorias", []), "produtos": produtos}
    return out, report


def norm_escopo(escopo):
    """None = tudo. Senão {"cats": [...], "lojas": ["mercadolivre","amazon"], "achadinhos": bool}."""
    e = escopo or {}
    cats = [c for c in (e.get("cats") if escopo else CATS) or [] if c in CATS]
    lojas = [l for l in (e.get("lojas") if escopo else list(LOJAS)) or [] if l in LOJAS]
    ach = bool(e.get("achadinhos")) if escopo else True
    if not (cats and lojas) and not ach:
        raise ValueError("Escolha ao menos uma categoria e uma loja, ou os achadinhos.")
    return {"cats": cats if lojas else [], "lojas": lojas if cats else [], "achadinhos": ach}


def escopo_label(e):
    if len(e["cats"]) == len(CATS) and len(e["lojas"]) == len(LOJAS) and e["achadinhos"]:
        return "tudo"
    partes = []
    if e["cats"]:
        cats = "todas as categorias" if len(e["cats"]) == len(CATS) else ", ".join(NOMES[c] for c in e["cats"])
        lojas = "" if len(e["lojas"]) == len(LOJAS) else " (só " + LOJAS[e["lojas"][0]] + ")"
        partes.append(cats + lojas)
    if e["achadinhos"]:
        partes.append("achadinhos")
    return ("só " if not e["cats"] else "") + " + ".join(partes)


def merge_partial(current, new, groups):
    """Troca no site só os grupos (loja, categoria) escolhidos; o resto fica como está."""
    cat_ids = [c.get("id") for c in current.get("categorias", [])] or CATS
    out = []
    for c in cat_ids:
        for loja in LOJAS:
            src = new if (loja, c) in groups else current
            out += [p for p in src.get("produtos", []) if p.get("loja", "mercadolivre") == loja and p.get("categoria") == c]
    return dict(new, produtos=out)


def counts(prod):
    c = {}
    for p in prod.get("produtos", []):
        k = f"{'az' if p.get('loja') == 'amazon' else 'ml'}:{p.get('categoria')}"
        c[k] = c.get(k, 0) + 1
    return c


def check_safe(old, new):
    """Recusa resultado que pareça quebra de leitura (página do ML/Amazon mudou)."""
    co, cn = counts(old), counts(new)
    problems = [f"{k} caiu de {v} para {cn.get(k, 0)}" for k, v in co.items() if v >= 3 and cn.get(k, 0) == 0]
    ml_old = sum(v for k, v in co.items() if k.startswith("ml:"))
    ml_new = sum(v for k, v in cn.items() if k.startswith("ml:"))
    if ml_old and ml_new < ml_old * 0.5:
        problems.append(f"Mercado Livre caiu de {ml_old} para {ml_new} produtos")
    for p in new["produtos"]:
        link = p.get("link_afiliado", "")
        ok = link.startswith(("https://meli.la/", "https://link.amazon/")) or (
            p.get("loja") == "amazon" and link.startswith(f"{AZ}/dp/") and f"tag={config.AMAZON_TAG_SITE}" in link)
        if not ok:
            problems.append(f"link inválido: {p['id']}")
        if p.get("imagem") and not p["imagem"].startswith("https://http2.mlstatic.com/"):
            problems.append(f"imagem inválida: {p['id']}")
        if p.get("loja") == "amazon" and ("preco" in p or "imagem" in p):
            problems.append(f"Amazon com preço/foto: {p['id']}")
    if problems:
        raise Unsafe("; ".join(problems[:6]))


def update_achadinhos(ach, prices, hoje, relink=None):
    """Achadinhos MANUAIS do ML: preço, histórico (1 por dia, até 180) e ativo. prices[id_ml] = preço ou None."""
    itens, resumo = [], []
    for i in ach.get("itens", []):
        if i.get("origem") != "app" and i.get("loja") == "amazon" and i.get("asin"):
            itens.append(dict(i, link_afiliado=f"{AZ}/dp/{i['asin']}?tag={config.AMAZON_TAG_SITE}"))  # ID do site
            continue
        if i.get("origem") == "app" or i.get("loja") != "mercadolivre" or i.get("id_ml") not in prices:
            itens.append(i)
            continue
        dia = hoje[:10]  # histórico: 1 registro por dia
        n = dict(i, historico=[h for h in i.get("historico", []) if h.get("data") != dia])
        if relink and config.ML_TAG_SITE and n.get("etiqueta") != config.ML_TAG_SITE:
            novo = relink(i["id_ml"])  # link com a etiqueta do site
            if (novo or "").startswith("https://meli.la/"):
                n["link_afiliado"], n["etiqueta"] = novo, config.ML_TAG_SITE
        preco = prices[i["id_ml"]]
        n["preco_consultado_em"] = hoje
        if preco is None:
            n["ativo"] = False
            resumo.append(f"{i['nome'][:40]}: sem preço/estoque")
        else:
            n["preco"] = preco
            n["historico"] = (n["historico"] + [{"data": dia, "preco": preco}])[-180:]
            n["ativo"] = preco <= i["preco_alvo"]
            resumo.append(f"{i['nome'][:40]}: R$ {preco:.2f} (máx. {i['preco_alvo']}) {'ativo' if n['ativo'] else 'fora do preço'}")
        itens.append(n)
    return {"atualizado_em": hoje, "itens": itens}, resumo


def merge_app_items(fresh, manual):
    """Na hora de publicar: itens do app vêm da leitura mais recente do site (o bot pode ter publicado)."""
    man = {i["id"]: i for i in manual["itens"] if i.get("origem") != "app"}
    out = []
    for i in fresh.get("itens", []):
        out.append(i if i.get("origem") == "app" else man.pop(i["id"], i))
    out += list(man.values())
    return {"atualizado_em": manual["atualizado_em"], "itens": out}


# ---------------- navegador e rede ----------------

_cur = {}  # estado da rodada em andamento (o painel mostra etapa e %)


CANCEL_KEY = "site_ranking_cancel"
ML_LINKS_KEY = "site_ranking_ml_links"  # último link que funcionou de cada filtro do ML (plano B)


class Cancelled(BaseException):  # BaseException: nenhum "except Exception" interno engole o cancelamento
    """Cancelado pelo painel: nada é publicado."""


FAIL_KEY = "site_ranking_fails"


def dica(exc):
    """O que o Bruno pode fazer com cada tipo de falha (vai no aviso do Telegram)."""
    msg = str(exc)
    if isinstance(exc, Blocked) and "Mercado Livre" in msg:
        return ("O Mercado Livre pediu verificação. No computador, rode deploy\\abrir-login-ml.cmd e faça a verificação "
                "na janela que abrir; o bot tenta de novo no próximo horário.")
    if isinstance(exc, Blocked):
        return "A Amazon pediu captcha. Costuma passar sozinho; o bot tenta de novo no próximo horário."
    if isinstance(exc, Unsafe):
        return ("Os números vieram estranhos (a página da loja pode ter mudado) e, por segurança, nada foi publicado. "
                "Se repetir, mande esta mensagem para o Claude.")
    return "Erro inesperado. O bot tenta de novo no próximo horário; se repetir, mande esta mensagem para o Claude."


def request_cancel():
    """Painel pede para parar a execução em andamento (vale no próximo passo, antes de publicar)."""
    st = (db.get_system_state().get(STATE_KEY) or {}).get("value") or {}
    if st.get("status") != "running":
        return False
    db.set_setting(CANCEL_KEY, st.get("inicio") or "1")
    return True


def _check_cancel():
    if _cur and _cur.get("pct", 0) < 95 and db.get_setting(CANCEL_KEY, None):
        db.set_setting(CANCEL_KEY, None)
        raise Cancelled("Cancelado pelo painel")


def _progress(etapa, pct):
    _check_cancel()
    if _cur:
        _cur.update(etapa=etapa, pct=int(pct))
        db.set_system_state(STATE_KEY, _cur)


def _pause():
    _check_cancel()
    db.set_system_state("heartbeat", {"phase": "searching", "store": "Site", "keyword": "ranking do site"})
    time.sleep(random.uniform(2, 4))


def _ml_page_html(url):
    from scrapers.ml_coupons import _get_context, is_ml_error, is_ml_verification, mark_ml_verification, ml_available
    if not ml_available():
        raise Blocked("Mercado Livre pede verificação manual (sessão do bot)")
    page = _get_context().new_page()
    try:
        resp = page.goto(url, wait_until="domcontentloaded", timeout=45000)
        page.wait_for_timeout(2500)
        status = resp.status if resp is not None else 0
        if status in (400, 404, 410) or is_ml_error(page):  # filtro/página que não existe mais: não é anti-bot
            raise PaginaIndisponivel(f"ML respondeu HTTP {status} em {url[:90]}")
        if status >= 400 or is_ml_verification(page):
            mark_ml_verification(page.url)
            try:
                titulo = page.title()[:60]
            except Exception:
                titulo = "?"
            raise Blocked(f"Mercado Livre bloqueou (HTTP {resp.status if resp else '?'}, foi para "
                          f"{page.url.split('?')[0][-60:]}, título '{titulo}') ao abrir {url[:70]}")
        return page.content()
    finally:
        page.close()


NOMES = {"mini-gt": "Mini GT", "hot-wheels": "Hot Wheels", "pixar-cars": "Pixar Cars", "lego": "LEGO", "funko": "Funko", "blokees": "Blokees", "pokemon-tcg": "Pokémon TCG"}
LOJAS = {"mercadolivre": "Mercado Livre", "amazon": "Amazon"}


_pulados = set()  # categorias do ML que não deu para ler nesta execução (o site mantém as anteriores)


def collect_ml(cats=None):
    raw = {}
    fontes = [(c, v) for c, v in ML_SOURCES.items() if not cats or c in cats]
    for n, (c, (start, path)) in enumerate(fontes):
        _progress(f"Mercado Livre: {NOMES[c]} ({n + 1} de {len(fontes)})", 2 + 42 * n / len(fontes))
        html = _ml_page_html(ML + start)
        cache = db.get_setting(ML_LINKS_KEY, {}) or {}
        try:
            for name in path:
                links = ml_links(html)
                url = links.get(norm(name)) or next((u for t, u in links.items() if t.startswith(norm(name))), None)
                ck = f"{c}|{norm(name)}"
                if url:
                    cache[ck] = url
                elif cache.get(ck):  # plano B: o link do filtro sumiu da página, tenta o último que funcionou
                    url = cache[ck]
                    _avisos.append(f"ML {NOMES[c]}: filtro '{name}' não apareceu na página; tentei o último link conhecido")
                else:
                    raise PaginaIndisponivel(f"filtro '{name}' não aparece hoje na página do ML")
                _pause()
                html = _ml_page_html(url)
        except PaginaIndisponivel as exc:
            # O ML só mostra as marcas mais vendidas do momento; quando uma some (ex.: Mini GT em 06/11),
            # o site mantém os produtos anteriores dessa categoria e as outras seguem normalmente.
            _pulados.add(c)
            _avisos.append(f"ML {NOMES[c]}: não deu para ler ({exc}); mantive os produtos anteriores")
            _pause()
            continue
        db.set_setting(ML_LINKS_KEY, cache)
        raw[c] = ml_items_any(html, NOMES[c])
        _pause()
    return pick_ml(raw)


def ml_price(id_ml):
    """Preço atual do anúncio (meta itemprop=price); None se sumiu ou está sem estoque."""
    from scrapers.ml_coupons import _get_context, is_ml_error, is_ml_verification, mark_ml_verification
    page = _get_context().new_page()
    try:
        resp = page.goto(ml_url(id_ml), wait_until="domcontentloaded", timeout=45000)
        page.wait_for_timeout(3000)
        if (resp is not None and resp.status in (400, 404, 410)) or is_ml_error(page):
            return None  # anúncio que não existe mais: achadinho sai do ar, não é bloqueio
        if is_ml_verification(page):
            mark_ml_verification(page.url)
            raise Blocked("Mercado Livre bloqueou a página de um achadinho")
        meta = page.query_selector("meta[itemprop=price]")
        body = norm(page.inner_text("body")[:5000])
        if not meta or re.search(r"sem estoque|indisponivel|anuncio pausado|finalizad", body):
            return None
        return round(float(meta.get_attribute("content")), 2)
    finally:
        page.close()


def collect_az(cats=None):
    from scrapers.amazon_pw import _blocked, _get_context
    ctx = _get_context()
    ranks_by_node, titles = {}, {}
    cats = [c for c in CATS if not cats or c in cats]
    nodes = list(dict.fromkeys(AZ_NODES[c] for c in cats))
    for n, node in enumerate(nodes):
        ranks_by_node[node] = []
        for pg in (1, 2):
            _progress(f"Amazon: página {n * 2 + pg} de {len(nodes) * 2}", 45 + 25 * (n * 2 + pg - 1) / (len(nodes) * 2))
            page = ctx.new_page()
            try:
                page.goto(f"{AZ}/gp/bestsellers/toys/{node}?pg={pg}", wait_until="domcontentloaded", timeout=45000)
                try:
                    page.wait_for_selector("[data-client-recs-list]", timeout=20000)
                except Exception:
                    if _blocked(page):
                        raise Blocked("Amazon pediu captcha")
                    raise Unsafe(f"Amazon: ranking {node} página {pg} não carregou")
                ranks, t = az_ranking(page.content())
            finally:
                page.close()
            ranks_by_node[node] += ranks or []
            titles.update(t)
            _pause()
    cache = db.get_setting(TITLES_KEY, {}) or {}
    need = [a for a in dict.fromkeys(a for rs in ranks_by_node.values() for a, _ in rs) if a not in titles and a not in cache]
    for k, asin in enumerate(need):
        if k % 5 == 0:
            _progress(f"Amazon: buscando títulos ({k + 1} de {len(need)})", 70 + 15 * k / max(1, len(need)))
        try:
            html = ctx.request.get(f"{AZ}/dp/{asin}", timeout=30000).text()
            m = re.search(r'id="productTitle"[^>]*>([\s\S]*?)</span>', html)
            if m:
                cache[asin] = BeautifulSoup(m.group(1), "html.parser").get_text(" ", strip=True)
        except Exception:
            pass
        time.sleep(random.uniform(0.3, 0.8))
    cache.update(titles)
    db.set_setting(TITLES_KEY, dict(list(cache.items())[-3000:]))
    return pick_az(ranks_by_node, {**cache, **titles}, cats)


def _new_ml_link(id_ml):
    from core.affiliate import ml_site_link
    return ml_site_link(ml_url(id_ml))  # etiqueta do site


def _site_json(name):
    from core.site_export import _fetch_named
    return _fetch_named(name)


def _upload(name, data):
    from core.site_export import _upload
    _upload(json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8"), name)


def _backup_local(name, data):
    d = BASE / "backups" / "site"
    d.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(ZONE).strftime("%Y%m%d-%H%M")
    (d / f"{name}.{stamp}").write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    olds = sorted(d.glob(f"{name}.2*"))
    for f in olds[:-40]:
        f.unlink(missing_ok=True)


# ---------------- execução ----------------

def _publish_files(current, produtos=None, ach_new=None):
    if produtos is not None:
        _backup_local("products.json", current)
        _upload("products.json", produtos)
        if json.dumps(_site_json("products.json"), sort_keys=True) != json.dumps(produtos, sort_keys=True):
            raise RuntimeError("products.json publicado não confere na leitura de volta")
    if ach_new is not None:
        fresh = _site_json("achadinhos.json")
        _backup_local("achadinhos.json", fresh)
        _upload("achadinhos.json", merge_app_items(fresh, ach_new))

def run(publish=False, origem="painel", escopo=None):
    t0 = time.time()
    hoje = stamp()
    if not config.AMAZON_TAG:
        raise RuntimeError("AMAZON_TAG não configurada no .env")
    esc = norm_escopo(escopo)
    groups = {(l, c) for l in esc["lojas"] for c in esc["cats"]}
    est_key = "site_ranking_last_duration" + ("" if escopo_label(esc) == "tudo" else ":" + escopo_label(esc))
    state = {"status": "running", "origem": origem, "publicar": publish, "inicio": datetime.now(ZONE).isoformat(timespec="seconds"),
             "etapa": "Começando", "pct": 1, "estimativa": db.get_setting(est_key, None),
             "escopo": esc, "escopo_txt": escopo_label(esc)}
    _cur.clear()
    _cur.update(state)
    _avisos.clear()
    _pulados.clear()
    db.set_setting(CANCEL_KEY, None)
    db.set_system_state(STATE_KEY, state)
    try:
        current = ensure_cats(_site_json("products.json"))
        ach = _site_json("achadinhos.json")
        report = {"novos": [], "removidos": [], "precos": [], "sem_link": []}
        produtos = current
        if groups:
            ml = collect_ml(esc["cats"]) if "mercadolivre" in esc["lojas"] else {}
            az = collect_az(esc["cats"]) if "amazon" in esc["lojas"] else {}
            groups -= {("mercadolivre", c) for c in _pulados}  # categorias puladas ficam como estavam
            n_links = [0]

            def link_com_progresso(id_ml):  # links novos do ML demoram ~10 s cada: mostra no painel
                n_links[0] += 1
                _progress(f"Gerando link de afiliado do Mercado Livre ({n_links[0]})", 85)
                return _new_ml_link(id_ml)

            novo, report = assemble(current, ach, ml, az, hoje, link_com_progresso)
            produtos = merge_partial(current, novo, groups)
            keep = {(p.get("loja", "mercadolivre"), p.get("id_ml") or p.get("asin")) for p in produtos["produtos"]}
            report["removidos"] = [f"{'Amazon' if p.get('loja') == 'amazon' else 'ML'} {p.get('categoria')}: {p.get('nome', '')[:50]}"
                                   for p in current.get("produtos", []) if (p.get("loja", "mercadolivre"), p.get("id_ml") or p.get("asin")) not in keep]
            check_safe(current, produtos)
        manual_ml = [i["id_ml"] for i in ach.get("itens", []) if i.get("origem") != "app" and i.get("loja") == "mercadolivre" and i.get("id_ml")] if esc["achadinhos"] else []
        prices = {}
        for k, id_ml in enumerate(manual_ml):
            _progress(f"Achadinhos: preço {k + 1} de {len(manual_ml)}", 86 + 8 * k / max(1, len(manual_ml)))
            try:
                prices[id_ml] = ml_price(id_ml)
            except Blocked as exc:
                # O ranking já foi lido: publica o ranking e deixa os achadinhos como estavam.
                _avisos.append(f"Achadinhos do ML não atualizados nesta rodada ({exc}); ranking publicado normalmente")
                prices = {}
                break
            except Exception as exc:
                _avisos.append(f"Achadinho {id_ml}: não deu para ler o preço ({type(exc).__name__}); ficou como estava")
            _pause()
        ach_new, ach_resumo = update_achadinhos(ach, prices, hoje, _new_ml_link) if esc["achadinhos"] else (ach, [])
        PREVIEW.parent.mkdir(parents=True, exist_ok=True)
        PREVIEW.write_text(json.dumps(produtos, ensure_ascii=False, indent=2), encoding="utf-8")
        PREVIEW_ACH.write_text(json.dumps(ach_new, ensure_ascii=False, indent=2), encoding="utf-8")
        if publish:
            _progress("Publicando no site", 95)
            _publish_files(current, produtos if groups else None, ach_new if esc["achadinhos"] else None)
        state.update(status="ok", publicado=publish, duracao=round(time.time() - t0),
                     contagem=counts(produtos), antes=counts(current), achadinhos=ach_resumo,
                     novos=report["novos"][:40], removidos=report["removidos"][:40],
                     precos=report["precos"][:40], n_precos=len(report["precos"]), sem_link=report["sem_link"][:20],
                     itens_app=sum(1 for i in ach.get("itens", []) if i.get("origem") == "app"),
                     plano_b=list(_avisos), pulados=sorted(_pulados),
                     fim=datetime.now(ZONE).isoformat(timespec="seconds"))
    except Cancelled:
        state.update(status="cancelado", publicado=False, erro="Cancelado pelo painel. Nada foi publicado.",
                     duracao=round(time.time() - t0), fim=datetime.now(ZONE).isoformat(timespec="seconds"))
    except Exception as exc:
        state.update(status="erro", publicado=False, erro=f"{type(exc).__name__}: {str(exc)[:400]}",
                     duracao=round(time.time() - t0), fim=datetime.now(ZONE).isoformat(timespec="seconds"))
        # Avisa na 1ª falha e na 3ª seguida; depois fica quieto até voltar a funcionar (sem encher o Telegram).
        fails = int(db.get_setting(FAIL_KEY, 0) or 0) + 1
        db.set_setting(FAIL_KEY, fails)
        if fails in (1, 3):
            try:
                from core import notifier
                titulo = "⚠️ Site NÃO foi atualizado" if fails == 1 else "🚨 Site falhou 3 vezes seguidas"
                notifier.notify_admin(f"{titulo} ({state['escopo_txt']} · {origem}). O site segue com a versão anterior.\n"
                                      f"O que fazer: {dica(exc)}\nDetalhe: {state['erro']}"
                                      + ("\nNão vou avisar de novo até voltar a funcionar." if fails == 3 else ""))
            except Exception:
                pass
    state.update(pct=100, etapa={"ok": "Concluído", "cancelado": "Cancelado"}.get(state["status"], "Falhou"))
    _cur.clear()
    if state["status"] == "ok":
        db.set_setting(est_key, state["duracao"])
        falhas_antes = int(db.get_setting(FAIL_KEY, 0) or 0)
        db.set_setting(FAIL_KEY, 0)
        try:
            from core import notifier
            c = state["contagem"]
            ml = sum(v for k, v in c.items() if k.startswith("ml:"))
            az = sum(v for k, v in c.items() if k.startswith("az:"))
            notifier.notify_admin(
                ("✅ Site atualizado" if publish else "📋 Prévia do ranking pronta (nada publicado)")
                + f" · {state['escopo_txt']} · {origem} · {state['duracao'] // 60} min\n"
                f"ML {ml} · Amazon {az} produtos · {len(state['novos'])} novos · {len(state['removidos'])} saíram · "
                f"{state['n_precos']} preços mudaram" + (f" · {len(state['sem_link'])} sem link" if state["sem_link"] else "")
                + (f"\n✔️ Voltou a funcionar depois de {falhas_antes} falha(s)." if falhas_antes else "")
                + ("\n⚙️ Plano B usado (a página do ML mudou; mande isto para o Claude): " + "; ".join(state["plano_b"])
                   if state.get("plano_b") else "")
                + f"\nDetalhes: {getattr(config, 'PANEL_URL', '') or 'https://painel.russodiecast.online'}/site")
        except Exception:
            pass
    db.set_system_state(STATE_KEY, state)
    return state


def mode():
    return db.get_setting(MODE_KEY, "teste") or "teste"


# ---------------- agenda (horários automáticos, editável no painel) ----------------
AGENDA_KEY = "site_ranking_agenda"
DONE_KEY = "site_ranking_done"
WINDOW_MIN = 90          # se o bot estava ocupado/parado, ainda roda até 90 min depois do horário
AGENDA_MAX = 12
OQUE = {"tudo": "Tudo", "achadinhos": "Só achadinhos", "mercadolivre": "Só Mercado Livre (+ achadinhos)",
        "amazon": "Só Amazon", **{c: f"Só {n}" for c, n in NOMES.items()}}


def oque_escopo(oque):
    if oque == "achadinhos":
        return {"cats": [], "lojas": [], "achadinhos": True}
    if oque == "mercadolivre":
        return {"cats": CATS, "lojas": ["mercadolivre"], "achadinhos": True}
    if oque == "amazon":
        return {"cats": CATS, "lojas": ["amazon"], "achadinhos": False}
    if oque in CATS:
        return {"cats": [oque], "lojas": list(LOJAS), "achadinhos": False}
    return None  # tudo


def default_agenda():
    return [{"hora": h, "oque": "tudo", "ativo": True} for h in RUN_TIMES]


def get_agenda():
    ag = db.get_setting(AGENDA_KEY, None)
    return ag if isinstance(ag, list) else default_agenda()


def validate_agenda(itens):
    out, seen = [], set()
    for i in itens or []:
        hora, oque = str(i.get("hora", "")).strip(), str(i.get("oque", "tudo"))
        if not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", hora):
            raise ValueError(f"Horário inválido: '{hora}' (use HH:MM)")
        if oque not in OQUE:
            raise ValueError(f"Opção inválida: {oque}")
        if (hora, oque) in seen:
            continue
        seen.add((hora, oque))
        out.append({"hora": hora, "oque": oque, "ativo": bool(i.get("ativo", True))})
    if len(out) > AGENDA_MAX:
        raise ValueError(f"No máximo {AGENDA_MAX} horários.")
    return sorted(out, key=lambda x: x["hora"])


def save_agenda(itens):
    ag = validate_agenda(itens)
    db.set_setting(AGENDA_KEY, ag)
    return ag


def due_slot(now=None):
    """Primeiro horário ativo que já passou (até 90 min) e ainda não rodou hoje."""
    now = now or datetime.now(ZONE)
    done = set(db.get_setting(DONE_KEY, []) or [])
    for item in get_agenda():
        if not item.get("ativo", True):
            continue
        h, m = map(int, item["hora"].split(":"))
        start = now.replace(hour=h, minute=m, second=0, microsecond=0)
        key = f"{now:%Y-%m-%d} {item['hora']} {item['oque']}"
        if 0 <= (now - start).total_seconds() < WINDOW_MIN * 60 and key not in done:
            return key, item
    return None, None


def maybe_run():
    """Chamado no laço do bot: roda cada horário da agenda uma vez por dia."""
    key, item = due_slot()
    if not key:
        return None
    done = (db.get_setting(DONE_KEY, []) or [])[-40:]
    db.set_setting(DONE_KEY, done + [key])
    return run(publish=(mode() == "publicar"), origem=f"automático {item['hora']}", escopo=oque_escopo(item["oque"]))


def publish_preview():
    """Publica a última prévia sem navegar de novo (rápido). Só vale se for de hoje e tiver menos de 6 h."""
    st = (db.get_system_state().get(STATE_KEY) or {}).get("value") or {}
    if st.get("status") != "ok" or st.get("publicado") or not PREVIEW.exists() or not PREVIEW_ACH.exists():
        raise RuntimeError("Não há prévia pendente para publicar. Gere uma prévia primeiro.")
    idade = (datetime.now(ZONE) - datetime.fromisoformat(st["fim"])).total_seconds() / 3600
    if idade > PREVIEW_MAX_HOURS:
        raise RuntimeError(f"A prévia tem {idade:.0f} h; gere uma nova para publicar preços atualizados.")
    produtos = json.loads(PREVIEW.read_text(encoding="utf-8"))
    ach_new = json.loads(PREVIEW_ACH.read_text(encoding="utf-8"))
    current = ensure_cats(_site_json("products.json"))
    esc = st.get("escopo") or {"cats": CATS, "lojas": list(LOJAS), "achadinhos": True}
    groups = {(l, c) for l in esc["lojas"] for c in esc["cats"]} - {("mercadolivre", c) for c in st.get("pulados") or []}
    if groups:
        # o site pode ter mudado depois da prévia: reaplica só os grupos da prévia sobre o site atual
        produtos = merge_partial(current, produtos, groups)
        check_safe(current, produtos)
    _publish_files(current, produtos if groups else None, ach_new if esc.get("achadinhos") else None)
    st.update(publicado=True, origem=st.get("origem", "") + " → publicada pelo painel",
              publicado_em=datetime.now(ZONE).isoformat(timespec="seconds"))
    db.set_system_state(STATE_KEY, st)
    try:
        from core import notifier
        notifier.notify_admin(f"✅ Site atualizado com a prévia aprovada no painel ({st.get('escopo_txt', 'tudo')}).")
    except Exception:
        pass
    return st
