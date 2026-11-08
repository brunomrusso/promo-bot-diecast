"""Comissões: importa os relatórios mensais da Amazon (CSV) e do Mercado Livre (texto copiado da tela de Métricas).

Nada aqui acessa a internet: o Bruno baixa/copia os relatórios e cola no painel. Reimportar o mesmo
relatório do mesmo mês (mesma loja, tipo e canal) substitui a importação anterior.
"""
import csv
import io
import re
from datetime import date

import config
from core import db

AMAZON, ML = "Amazon", "Mercado Livre"
ANTIGOS = {"promocoesdiec-20", "runbrunorun"}
MESES = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"]

_SCHEMA = (
    "CREATE TABLE IF NOT EXISTS comissoes ("
    "id INTEGER PRIMARY KEY AUTOINCREMENT, loja TEXT NOT NULL, mes TEXT NOT NULL, tipo TEXT NOT NULL, "
    "canal TEXT NOT NULL DEFAULT '', item TEXT NOT NULL DEFAULT '', item_id TEXT NOT NULL DEFAULT '', "
    "pedido TEXT NOT NULL DEFAULT '', data TEXT NOT NULL DEFAULT '', vendedor TEXT NOT NULL DEFAULT '', "
    "cliques INTEGER NOT NULL DEFAULT 0, unidades INTEGER NOT NULL DEFAULT 0, vendas REAL NOT NULL DEFAULT 0, "
    "ganho REAL NOT NULL DEFAULT 0, estado TEXT NOT NULL DEFAULT '', motivo TEXT NOT NULL DEFAULT '', "
    "importado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"
)


def _conn():
    c = db._conn()
    c.execute(_SCHEMA)
    return c


def canal_nome(tag):
    t = (tag or "").strip()
    if t and t in {config.AMAZON_TAG, getattr(config, "ML_TAG_BOT", "")}:
        return "WhatsApp"
    if t and t in {getattr(config, "AMAZON_TAG_SITE", ""), getattr(config, "ML_TAG_SITE", "")}:
        return "Site"
    if t in ANTIGOS:
        return "ID antigo"
    if not t or t.lower() in {"tudo", "other"}:
        return "Todos os canais"
    return t


def _num(v):
    s = str(v or "").strip().replace("R$", "").replace("%", "").strip()
    if s in {"", "-", "—"}:
        return 0.0
    if "," in s:  # formato brasileiro 1.234,56
        s = s.replace(".", "").replace(",", ".")
    try:
        return round(float(s), 2)
    except ValueError:
        return 0.0


def mes_anterior(hoje=None):
    h = hoje or date.today()
    y, m = (h.year, h.month - 1) if h.month > 1 else (h.year - 1, 12)
    return f"{y:04d}-{m:02d}"


def valida_mes(mes):
    if not re.fullmatch(r"20\d\d-(0[1-9]|1[0-2])", mes or ""):
        raise ValueError("Mês inválido (use AAAA-MM).")
    return mes


# ---------------- Amazon (CSV) ----------------
def _csv_rows(texto):
    linhas = texto.lstrip("﻿").splitlines()
    for i, l in enumerate(linhas):  # a Amazon às vezes põe um título antes do cabeçalho
        low = l.lower()
        if ("rastreamento" in low or "tracking" in low or "asin" in low) and "," in l:
            return list(csv.DictReader(io.StringIO("\n".join(linhas[i:]))))
    raise ValueError("Não encontrei o cabeçalho do relatório da Amazon.")


def _pick(row, *nomes):
    low = {(k or "").strip().lower(): v for k, v in row.items()}
    for n in nomes:
        if n in low:
            return low[n]
    return ""


def parse_amazon(texto, canal=""):
    """Detecta o relatório: Tracking-Id (por canal) ou Linked-Product (por produto). Top-Sellers e outros: erro."""
    rows = _csv_rows(texto)
    if not rows:
        raise ValueError("Relatório da Amazon vazio.")
    head = {(k or "").strip().lower() for k in rows[0]}
    out = []
    if {"número de rastreamento", "tracking id"} & head:
        for r in rows:
            tag = _pick(r, "número de rastreamento", "tracking id").strip()
            item = dict(tipo="canal", canal=tag, cliques=int(_num(_pick(r, "cliques", "clicks"))),
                        unidades=int(_num(_pick(r, "produtos enviados", "items shipped"))),
                        vendas=_num(_pick(r, "receita de produtos enviados", "items shipped revenue", "revenue")),
                        ganho=_num(_pick(r, "ganhos totais", "total earnings", "earnings")))
            if tag.lower() == "other" and not (item["cliques"] or item["unidades"] or item["ganho"]):
                continue
            out.append(item)
        return "canal", out
    if "asin" in head and ("clicks" in head or "cliques" in head):
        for r in rows:
            asin = _pick(r, "asin").strip()
            titulo = _pick(r, "product title", "título do produto").strip()
            item = dict(tipo="produto", canal=canal, item_id=asin,
                        item=(titulo if titulo not in {"", "-"} else "Outros produtos (compras indiretas)"),
                        cliques=int(_num(_pick(r, "clicks", "cliques"))),
                        unidades=int(_num(_pick(r, "items shipped", "produtos enviados"))),
                        vendas=_num(_pick(r, "items shipped revenue", "receita de produtos enviados")),
                        ganho=_num(_pick(r, "total earnings", "ganhos totais")))
            if item["cliques"] or item["unidades"] or item["ganho"]:
                out.append(item)
        return "produto", out
    raise ValueError("Este relatório não é usado. Envie o Tracking-Id e o Linked-Product.")


# ---------------- Mercado Livre (texto copiado da tela de Métricas) ----------------
def _junta_dinheiro(texto):
    """'R$\\n119\\n,\\n90' -> 'R$ 119,90' (o ML quebra o valor em várias linhas ao copiar)."""
    t = re.sub(r"R\$\s*([\d.]+)\s*,\s*(\d{1,2})\b", r"R$ \1,\2", texto)
    return re.sub(r"R\$\s*([\d.]+)(?!\s*,\d)", r"R$ \1", t)


def _data_ml(dm, mes):
    m = re.fullmatch(r"(\d{1,2})/([a-zç]{3})", dm.strip().lower())
    if not m or m.group(2) not in MESES:
        return ""
    ano = int(mes[:4]) - (1 if MESES.index(m.group(2)) + 1 > int(mes[5:]) else 0)
    return f"{ano:04d}-{MESES.index(m.group(2)) + 1:02d}-{int(m.group(1)):02d}"


ESTADOS = ("EM REVISÃO", "RECUSADA", "APROVADA", "PAGA", "CANCELADA", "PENDENTE", "LIBERADA", "CONFIRMADA")


def parse_ml_vendas(texto, mes):
    """Aba "Vendas" copiada: cada venda tem data, #pedido, título, categoria, loja, valor, ganho e estado."""
    linhas = [l.strip() for l in _junta_dinheiro(texto).splitlines() if l.strip()]
    eh_data = lambda x: bool(re.fullmatch(r"\d{1,2}/[a-zç]{3}", x.lower()))
    out = []
    for i, l in enumerate(linhas):
        if not re.fullmatch(r"#\d{8,}", l):
            continue
        bloco = []
        for nxt in linhas[i + 1:]:
            if re.fullmatch(r"#\d{8,}", nxt):
                break
            bloco.append(nxt)
        up = [x.upper() for x in bloco]
        pos = next((k for k, x in enumerate(up) if x in ESTADOS), None)
        corpo = bloco[:pos] if pos is not None else bloco
        estado = bloco[pos] if pos is not None else ""
        motivo = ""
        if pos is not None and pos + 1 < len(bloco):
            cand = bloco[pos + 1]
            depois = bloco[pos + 2] if pos + 2 < len(bloco) else ""
            if not eh_data(cand) and not eh_data(depois):  # se vem uma data depois, é o título da próxima venda
                motivo = cand
        titulo = corpo[0] if corpo else ""
        k_cat = next((k for k, x in enumerate(corpo) if x.lower().startswith("categoria:")), None)
        vendedor = corpo[k_cat + 1] if k_cat is not None and k_cat + 1 < len(corpo) and not corpo[k_cat + 1].startswith("R$") else ""
        dinheiro = [x for x in corpo if x.startswith("R$")]
        unid = next((x for x in corpo if re.match(r"\d+\s+unidade", x)), "1 unidade")
        out.append(dict(tipo="venda", pedido=l[1:], data=_data_ml(linhas[i - 1], mes) if i else "", item=titulo,
                        vendedor=vendedor, unidades=int(re.match(r"\d+", unid).group(0)),
                        vendas=_num(dinheiro[0]) if dinheiro else 0.0,
                        ganho=_num(dinheiro[1]) if len(dinheiro) > 1 else 0.0,
                        estado=estado.capitalize(), motivo=motivo))
    return out


def parse_ml_etiquetas(texto):
    plano = " ".join(_junta_dinheiro(texto).split())
    rx = re.compile(r"([A-Za-z0-9_\-]{3,})\s+(\d+)\s+(\d+)\s+[\d.,]+\s*%\s+R\$\s*([\d.]+(?:,\d{1,2})?)")
    out = []
    for tag, cliques, unid, ganho in rx.findall(plano):
        if tag.lower() in {"estimado", "conversão"}:
            continue
        out.append(dict(tipo="canal", canal=tag, cliques=int(cliques), unidades=int(unid), ganho=_num(ganho)))
    return out


def parse_ml(texto, mes):
    if re.search(r"#\d{8,}", texto):
        vendas = parse_ml_vendas(texto, mes)
        if vendas:
            return "venda", vendas
    etq = parse_ml_etiquetas(texto)
    if etq:
        return "canal", etq
    raise ValueError("Não reconheci o texto. Cole a tabela da aba “Vendas” ou da aba “Etiquetas de rastreamento”.")


# ---------------- gravação e resumo ----------------
CAMPOS = ("canal", "item", "item_id", "pedido", "data", "vendedor", "cliques", "unidades", "vendas", "ganho",
          "estado", "motivo")


def salvar(loja, mes, tipo, linhas, canal=""):
    valida_mes(mes)
    with _conn() as c:
        if tipo == "produto":
            c.execute("DELETE FROM comissoes WHERE loja=? AND mes=? AND tipo=? AND canal=?", (loja, mes, tipo, canal))
        else:
            c.execute("DELETE FROM comissoes WHERE loja=? AND mes=? AND tipo=?", (loja, mes, tipo))
        for r in linhas:
            vals = [r.get(k, "" if k in ("canal", "item", "item_id", "pedido", "data", "vendedor", "estado", "motivo") else 0)
                    for k in CAMPOS]
            c.execute(f"INSERT INTO comissoes(loja,mes,tipo,{','.join(CAMPOS)}) VALUES (?,?,?,{','.join('?' * len(CAMPOS))})",
                      [loja, mes, tipo, *vals])
    return len(linhas)


def importar_amazon(texto, mes, canal=""):
    tipo, linhas = parse_amazon(texto, canal)
    if tipo == "produto" and not canal:
        canal = "Tudo"
        for l in linhas:
            l["canal"] = canal
    return tipo, salvar(AMAZON, mes, tipo, linhas, canal)


def importar_ml(texto, mes):
    tipo, linhas = parse_ml(texto, mes)
    return tipo, salvar(ML, mes, tipo, linhas)


def meses():
    with _conn() as c:
        return [r[0] for r in c.execute("SELECT DISTINCT mes FROM comissoes ORDER BY mes DESC")]


def apagar_mes(loja, mes):
    with _conn() as c:
        c.execute("DELETE FROM comissoes WHERE loja=? AND mes=?", (loja, valida_mes(mes)))


def _valida(v):
    return (v.get("estado") or "").upper() not in {"RECUSADA", "CANCELADA"}


def resumo(mes):
    with _conn() as c:
        rows = [dict(r) for r in c.execute("SELECT * FROM comissoes WHERE mes=?", (mes,))]
    lojas = {}
    for loja in (AMAZON, ML):
        canais = [r for r in rows if r["loja"] == loja and r["tipo"] == "canal"]
        vendas = [r for r in rows if r["loja"] == loja and r["tipo"] == "venda"]
        produtos = [r for r in rows if r["loja"] == loja and r["tipo"] == "produto"]
        if loja == ML and vendas:  # no ML a comissão vale pelas vendas (as recusadas não pagam)
            ganho = sum(v["ganho"] for v in vendas if _valida(v))
        else:
            ganho = sum(r["ganho"] for r in canais) or sum(p["ganho"] for p in produtos)
        por_canal = {}
        for r in canais:
            nome = canal_nome(r["canal"])
            a = por_canal.setdefault(nome, dict(canal=nome, tags=[], cliques=0, unidades=0, ganho=0.0))
            a["tags"].append(r["canal"]); a["cliques"] += r["cliques"]; a["unidades"] += r["unidades"]; a["ganho"] += r["ganho"]
        top = {}
        for p in produtos:
            k = p["item_id"] or p["item"]
            a = top.setdefault(k, dict(item=p["item"], item_id=p["item_id"], cliques=0, unidades=0, ganho=0.0, canais=set()))
            a["cliques"] += p["cliques"]; a["unidades"] += p["unidades"]; a["ganho"] += p["ganho"]; a["canais"].add(canal_nome(p["canal"]))
        for v in vendas:
            if not _valida(v):
                continue
            a = top.setdefault(v["item"], dict(item=v["item"], item_id="", cliques=0, unidades=0, ganho=0.0, canais=set()))
            a["unidades"] += v["unidades"]; a["ganho"] += v["ganho"]
        lojas[loja] = dict(
            ganho=round(ganho, 2), cliques=sum(r["cliques"] for r in canais),
            unidades=sum(r["unidades"] for r in canais) or sum(v["unidades"] for v in vendas if _valida(v)),
            canais=sorted(por_canal.values(), key=lambda a: -a["ganho"]),
            top=sorted(top.values(), key=lambda a: (-a["ganho"], -a["cliques"]))[:15],
            sem_venda=sorted([a for a in top.values() if a["cliques"] >= 10 and not a["unidades"]], key=lambda a: -a["cliques"])[:8],
            vendas=sorted(vendas, key=lambda v: v["data"], reverse=True),
            importado={t: any(r["tipo"] == t for r in rows if r["loja"] == loja) for t in ("canal", "produto", "venda")})
    return dict(mes=mes, lojas=lojas, total=round(sum(l["ganho"] for l in lojas.values()), 2))


def historico(n=6):
    out = []
    for m in sorted(meses())[-n:]:
        r = resumo(m)
        out.append(dict(mes=m, amazon=r["lojas"][AMAZON]["ganho"], ml=r["lojas"][ML]["ganho"], total=r["total"]))
    return out
