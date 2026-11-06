"""Achadinhos manuais do site (cadastro pelo painel): colar link + preço máximo + categoria.

O bot (site_ranking) atualiza o preço dos achadinhos do Mercado Livre nos horários da agenda;
os da Amazon mostram o preço da API direto no site. Itens "origem": "app" não são tocados aqui.
"""
import json
import re
from datetime import datetime

from core import db

ML_ID = re.compile(r"/up/(MLBU\d+)|/p/(MLB\d+)|MLB-?(\d{6,})")


def _today():
    from core.site_export import ZONE
    return datetime.now(ZONE).strftime("%Y-%m-%d")


def _ml_id(url):
    m = ML_ID.search(url or "")
    if not m:
        return None
    return m.group(1) or m.group(2) or f"MLB{m.group(3)}"


def _asin(url):
    m = re.search(r"/(?:dp|gp/product|product)/([A-Z0-9]{10})", url or "")
    return m.group(1) if m else None


def _nome(t):
    t = re.sub(r"\s+", " ", (t or "")).strip()
    return t if len(t) <= 95 else t[:95].rsplit(" ", 1)[0]


def build_item(deal, link, preco_alvo, categoria, hoje):
    """Monta o item no formato do achadinhos.json. Erro claro se faltar algo."""
    from core.site_export import _ml_image
    import config
    store = deal.get("store")
    if store == "Mercado Livre":
        id_ml = _ml_id(deal.get("url")) or _ml_id(deal.get("source_url"))
        if not id_ml:
            raise ValueError("Não reconheci o anúncio do Mercado Livre nesse link.")
        if not (link or "").startswith("https://meli.la/"):
            raise ValueError("Não consegui gerar o link de afiliado do Mercado Livre (meli.la). Tente de novo.")
        imagem = _ml_image(deal.get("image"))
        preco = round(float(deal.get("price") or 0), 2)
        if not imagem or preco <= 0:
            raise ValueError("O anúncio não mostrou foto ou preço (pode estar sem estoque).")
        return {"id": f"ach-ml-{id_ml}", "loja": "mercadolivre", "id_ml": id_ml, "nome": _nome(deal.get("title")),
                "imagem": imagem, "preco": preco, "preco_consultado_em": hoje, "preco_alvo": preco_alvo,
                "categoria": categoria, "link_afiliado": link, "adicionado_em": hoje[:10],
                "historico": [{"data": hoje[:10], "preco": preco}], "ativo": preco <= preco_alvo}
    if store == "Amazon":
        asin = _asin(deal.get("url"))
        if not asin:
            raise ValueError("Não reconheci o produto da Amazon nesse link.")
        tag = getattr(config, "AMAZON_TAG", "")
        if not (link.startswith("https://link.amazon/") or (f"/dp/{asin}" in link and f"tag={tag}" in link)):
            link = f"https://www.amazon.com.br/dp/{asin}?tag={tag}"
        # Amazon: sem preço/foto no arquivo (regra da Amazon); o site usa a API.
        return {"id": f"ach-az-{asin}", "loja": "amazon", "asin": asin, "nome": _nome(deal.get("title")),
                "preco_alvo": preco_alvo, "categoria": categoria, "link_afiliado": link, "adicionado_em": hoje[:10]}
    raise ValueError("Por enquanto só links do Mercado Livre ou da Amazon.")


def upsert(data, item):
    """Coloca o item no arquivo. Se já existe (manual), só atualiza preço máximo e categoria."""
    itens = list(data.get("itens", []))
    for i, x in enumerate(itens):
        if x.get("id") == item["id"]:
            if x.get("origem") == "app":
                raise ValueError("Esse produto já está no site pelo app (mini monitorada).")
            n = dict(x, preco_alvo=item["preco_alvo"], categoria=item["categoria"])
            if "preco" in n:
                n["ativo"] = n["preco"] <= n["preco_alvo"]
            itens[i] = n
            return dict(data, itens=itens), "atualizado"
    return dict(data, itens=itens + [item]), "adicionado"


def remove_from(data, item_id):
    itens = data.get("itens", [])
    alvo = next((x for x in itens if x.get("id") == item_id), None)
    if not alvo:
        raise ValueError("Achadinho não encontrado (talvez já tenha sido removido).")
    if alvo.get("origem") == "app":
        raise ValueError("Esse item é do app: remova pela mini monitorada.")
    return dict(data, itens=[x for x in itens if x.get("id") != item_id]), alvo


def _publish(op):
    """Aplica op() sobre a versão MAIS RECENTE do arquivo do site (o app publica a cada ~15 min) e envia."""
    from core.site_export import _fetch_named, _upload
    from core.site_ranking import _backup_local
    fresh = _fetch_named("achadinhos.json")
    _backup_local("achadinhos.json", fresh)
    final, extra = op(fresh)
    _upload(json.dumps(final, ensure_ascii=False, indent=2).encode("utf-8"), "achadinhos.json")
    return final, extra


def parse_preco(v):
    s = str(v).replace("R$", "").replace(" ", "").strip()
    if "," in s:
        s = s.replace(".", "").replace(",", ".")
    try:
        return round(float(s), 2)
    except ValueError:
        raise ValueError("Preço máximo inválido (use, por exemplo, 39,90).")


def add(url, preco_alvo, categoria, extract=None):
    from core.affiliate import to_affiliate_url
    from core.site_ranking import stamp
    if extract is None:
        from core.manual_jobs import extract_link as extract
    preco_alvo = parse_preco(preco_alvo)
    if preco_alvo <= 0:
        raise ValueError("Preço máximo inválido.")
    if categoria not in db.SITE_CATEGORIES:
        categoria = None
    deal = extract(url.strip())
    if deal.get("_error"):
        raise ValueError(deal["_error"])
    link = deal.get("affiliate_url") or to_affiliate_url(deal)
    item = build_item(deal, link, preco_alvo, categoria, stamp())
    final, acao = _publish(lambda d: upsert(d, item))
    if not any(x.get("id") == item["id"] for x in final.get("itens", [])):
        raise RuntimeError("Publiquei mas o item não apareceu no arquivo do site. Tente de novo.")
    return {"acao": acao, "id": item["id"], "nome": item["nome"], "loja": item["loja"],
            "preco": item.get("preco"), "preco_alvo": preco_alvo, "ativo": item.get("ativo")}


def remove(item_id):
    _, alvo = _publish(lambda d: remove_from(d, item_id))
    return {"removido": alvo.get("nome", item_id)}


def list_manual():
    from core.site_export import _fetch_named
    data = _fetch_named("achadinhos.json")
    itens = data.get("itens", [])
    manual = [x for x in itens if x.get("origem") != "app"]
    return {"itens": manual, "do_app": len(itens) - len(manual)}
