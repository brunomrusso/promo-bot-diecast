"""Publica as minis marcadas com "Mostrar no site" como achadinhos no russodiecast.com.br.

O site é estático (HostGator) e lê achadinhos.json. Este módulo:
1. monta os achadinhos a partir das minis com site_enabled=1 (melhor oferta recente no ML ou Amazon);
2. baixa o achadinhos.json atual do site e preserva os itens que não vieram do app;
3. envia o arquivo por FTP (conta restrita à pasta do site) só quando algo mudou.

Regras do site respeitadas:
- Mercado Livre: preço, foto (http2.mlstatic.com), histórico diário e ativo = preço <= alvo.
- Amazon: NÃO guarda preço nem foto (o site usa a API via amazon.php e compara com preco_alvo).
- Link sempre monetizado (meli.la ou Amazon com tag); sem link monetizado o item não vai para o site.
"""
import io
import json
import re
import ssl
import time
import urllib.request
from datetime import datetime
from ftplib import FTP_TLS
from zoneinfo import ZoneInfo

import config
from core import db
from core.affiliate import cached_affiliate_url, is_monetized, to_affiliate_url

ZONE = ZoneInfo("America/Sao_Paulo")
ML_IMAGE = re.compile(r"(\d+-ML[A-Z]\d+_\d+)")
ASIN = re.compile(r"(?:/dp/|/gp/product/|amz-)([A-Z0-9]{10})")


def _today():
    return datetime.now(ZONE).strftime("%Y-%m-%d")


def _ml_image(url):
    m = ML_IMAGE.search(url or "")
    return f"https://http2.mlstatic.com/D_NQ_NP_2X_{m.group(1)}-F.webp" if m else ""


def _added(item):
    raw = item.get("site_added_at") or item.get("created_at") or ""
    return str(raw)[:10] or _today()


def build_app_items(generate_links=True):
    """Achadinhos gerados pelo app. Itens sem oferta recente ou sem link monetizado ficam de fora.

    generate_links=False (painel): só usa links já gerados, sem abrir o Chrome do ML fora do bot."""
    out, skipped = [], []
    for item in db.site_monitored_items():
        offer = db.site_best_offer(item["id"])
        if not offer:
            skipped.append((item["name"], "sem oferta recente no ML/Amazon"))
            continue
        deal = {"id": offer["product_id"], "store": offer["store"], "url": offer["url"] or "",
                "title": offer["title"], "price": offer["price"], "image": offer.get("image") or ""}
        if deal["store"] == "Mercado Livre" and config.ML_TAG_SITE:
            from core.affiliate import ml_site_link
            link = ml_site_link(deal["url"], generate=generate_links)  # etiqueta do site
        else:
            link = to_affiliate_url(deal) if generate_links else cached_affiliate_url(deal)
        if not is_monetized(link, deal["store"]):
            skipped.append((item["name"], "link de afiliado ainda não gerado (o bot gera no próximo ciclo)"
                            if not generate_links else "link de afiliado não gerado"))
            continue
        alvo = float(item.get("max_price") or 0)
        if alvo <= 0:
            skipped.append((item["name"], "sem preço-alvo (o site precisa do preço máximo)"))
            continue
        base = {"nome": item["name"], "preco_alvo": round(alvo, 2), "categoria": item["site_category"],
                "link_afiliado": link, "adicionado_em": _added(item), "origem": "app",
                "mini_id": item["id"]}
        if deal["store"] == "Amazon":
            m = ASIN.search(deal["id"]) or ASIN.search(deal["url"])
            if not m:
                skipped.append((item["name"], "ASIN não identificado"))
                continue
            if any(o["id"] == f"ach-az-{m.group(1)}" for o in out):
                skipped.append((item["name"], "mesmo anúncio de outra mini já está no site"))
                continue
            from core.affiliate import amazon_site_link
            out.append({"id": f"ach-az-{m.group(1)}", "loja": "amazon", "asin": m.group(1),
                        **dict(base, link_afiliado=amazon_site_link(m.group(1)))})  # ID de rastreamento do site
            continue
        id_ml = deal["id"].removeprefix("ml-")
        if any(o["id"] == f"ach-ml-{id_ml}" for o in out):
            skipped.append((item["name"], "mesmo anúncio de outra mini já está no site"))
            continue
        imagem = _ml_image(deal["image"]) or _ml_image(item.get("image"))
        historico = [{"data": h["data"], "preco": round(float(h["preco"]), 2)}
                     for h in db.site_daily_history(item["id"], deal["store"], deal["id"])][-180:]
        preco = round(float(deal["price"]), 2)
        out.append({"id": f"ach-ml-{id_ml}", "loja": "mercadolivre", "id_ml": id_ml, **base,
                    "imagem": imagem, "preco": preco, "preco_consultado_em": datetime.now(ZONE).strftime("%Y-%m-%dT%H:%M"),
                    "historico": historico, "ativo": preco <= alvo})
    return out, skipped


def _fetch_named(name):
    """Lê um JSON do site (sem cache) e confere o formato básico."""
    url = f"{config.SITE_URL.rstrip('/')}/{name}?t={int(time.time())}"
    req = urllib.request.Request(url, headers={"Cache-Control": "no-cache", "User-Agent": "promobot-site-export"})
    with urllib.request.urlopen(req, timeout=20, context=ssl.create_default_context()) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    key = "itens" if name == "achadinhos.json" else "produtos"
    if not isinstance(data, dict) or not isinstance(data.get(key), list):
        raise ValueError(f"{name} do site com formato inesperado")
    return data


def _fetch_current():
    return _fetch_named("achadinhos.json")


def merge(current, app_items):
    """Mantém os itens que não vieram do app e substitui os do app (mesmo id do app prevalece)."""
    app_ids = {i["id"] for i in app_items}
    kept = [i for i in current.get("itens", []) if i.get("origem") != "app" and i.get("id") not in app_ids]
    return {"atualizado_em": _today(), "itens": kept + app_items}


REFRESH_HORAS = 6  # mesmo sem mudança, reenvia a cada 6 h para o site mostrar "preço conferido" recente


def _comparable(data):
    """Conteúdo que importa: ignora a hora da consulta (mudava a cada ciclo e forçava envio por FTP à toa)."""
    itens = [{k: v for k, v in i.items() if k != "preco_consultado_em"} for i in data.get("itens", [])]
    return json.dumps(itens, ensure_ascii=False, sort_keys=True)


def _consulta_velha(data, agora=None):
    """True se algum achadinho do app no site tem a hora da consulta com mais de REFRESH_HORAS."""
    agora = agora or datetime.now(ZONE).replace(tzinfo=None)
    for i in data.get("itens", []):
        q = i.get("preco_consultado_em")
        if i.get("origem") != "app" or not q:
            continue
        try:
            if (agora - datetime.fromisoformat(str(q)[:16])).total_seconds() > REFRESH_HORAS * 3600:
                return True
        except ValueError:
            return True
    return False


def _upload(content: bytes, filename: str = "achadinhos.json"):
    ftp = FTP_TLS(config.SITE_FTP_HOST, timeout=30)
    try:
        ftp.login(config.SITE_FTP_USER, config.SITE_FTP_PASSWORD)
        ftp.prot_p()
        if config.SITE_FTP_DIR:
            ftp.cwd(config.SITE_FTP_DIR)
        ftp.storbinary(f"STOR {filename}.tmp", io.BytesIO(content))
        ftp.rename(f"{filename}.tmp", filename)
    finally:
        try:
            ftp.quit()
        except Exception:
            ftp.close()


def publish(force=False, generate_links=True):
    """Gera e envia o achadinhos.json. Retorna um resumo para o estado do sistema/painel."""
    if not config.SITE_FTP_HOST or not config.SITE_FTP_USER:
        return {"status": "disabled", "detail": "FTP do site não configurado no .env"}
    try:
        app_items, skipped = build_app_items(generate_links)
        current = _fetch_current()
        merged = merge(current, app_items)
        changed = force or _comparable(merged) != _comparable(current) or _consulta_velha(current)
        if changed:
            _upload(json.dumps(merged, ensure_ascii=False, indent=2).encode("utf-8"))
        result = {"status": "ok", "changed": changed, "app_items": len(app_items),
                  "total": len(merged["itens"]), "skipped": skipped[:20], "at": datetime.now(ZONE).isoformat()}
    except Exception as exc:
        result = {"status": "error", "detail": str(exc)[:300], "at": datetime.now(ZONE).isoformat()}
    db.set_system_state("site_export", result)
    return result
