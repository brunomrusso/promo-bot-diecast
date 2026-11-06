"""Sugestão de cadastro de mini monitorada a partir do link de um produto (o Bruno confere antes de salvar)."""
import re
import unicodedata

# (como aparece no título, nome bonito, categoria do site)
MARCAS = [
    ("kaido house", "Kaido House", "mini-gt"), ("mini gt", "Mini GT", "mini-gt"), ("minigt", "Mini GT", "mini-gt"),
    ("hot wheels", "Hot Wheels", "hot-wheels"), ("hotwheels", "Hot Wheels", "hot-wheels"),
    ("matchbox", "Matchbox", None), ("tarmac works", "Tarmac Works", None), ("tarmac", "Tarmac Works", None),
    ("inno64", "INNO64", None), ("inno 64", "INNO64", None), ("pop race", "Pop Race", None),
    ("m2 machines", "M2 Machines", None), ("greenlight", "Greenlight", None), ("majorette", "Majorette", None),
    ("tomica", "Tomica", None), ("bburago", "Bburago", None), ("maisto", "Maisto", None), ("jada", "Jada", None),
    ("blokees", "Blokees", "blokees"), ("funko", "Funko", "funko"), ("lego", "LEGO", "lego"),
    ("pokemon", "Pokémon", "pokemon-tcg"),
]
RUIDO = set("""miniatura miniaturas carrinho carrinhos carro carros veiculo veiculos escala original originais lacrado
lacrada novo nova colecao colecionavel colecionaveis mattel diecast die cast metal presente lancamento edicao para
de da do das dos com e em o a os as um uma kit unidade unidades pronta entrega envio imediato frete gratis brinquedo
brinquedos boneco bonecos figura infantil menino menina oficial licenciado modelo modelos serie linha sortido sortidos escolha cor cores
""".split())
CORES = set("preto preta branco branca vermelho vermelha azul verde amarelo amarela laranja roxo roxa rosa prata cinza dourado dourada bege marrom".split())
# Palavras de linha/coleção: entram no nome e na busca, mas não viram termo obrigatório.
LINHA = set("""premium car culture boulevard mainline basic team transport fast furious speed machines series collector
collectors pro street carbon fiber v1 v2 v3 creator classic pop vinyl edition limited exclusive pack champion class""".split())
PIXAR = re.compile(r"\b(disney|pixar|mcqueen)\b")


def _norm(t):
    t = unicodedata.normalize("NFKD", t or "").encode("ascii", "ignore").decode().lower()
    return re.sub(r"\s+", " ", t).strip()


def _tokens(title):
    """[(palavra original, normalizada)] sem escala, ruído e marca."""
    out = []
    title = re.sub(r"\b1\s*[:/]\s*\d{2,3}\b|\b\d+\s*em\s*\d+\b", " ", title or "", flags=re.I)
    for raw in re.findall(r"[\w'#.-]+", title):
        raw = raw.strip(".-")
        n = _norm(raw).strip("'#")
        if not n or n in RUIDO or re.fullmatch(r"\d{1,2}cm|\d+x|\d", n) or len(n) < 2:
            continue
        out.append((raw, n))
    return out


def suggest(deal):
    title = re.sub(r"\s+", " ", deal.get("title") or "").strip()
    tn = _norm(title)
    marca = next(((k, nome, cat) for k, nome, cat in MARCAS if re.search(r"\b" + re.escape(k) + r"\b", tn)), None)
    cat = marca[2] if marca else None
    if PIXAR.search(tn) and (not marca or marca[0] in ("disney", "mattel")):
        cat = "pixar-cars"
    marca_words = {w for k, _, _ in MARCAS if re.search(r"\b" + re.escape(k) + r"\b", tn) for w in k.split()} | {"x"}
    toks = [(r, n) for r, n in _tokens(title) if n not in marca_words]
    modelo = [(r, n) for r, n in toks if n not in CORES][:6]
    cores = [n for _, n in toks if n in CORES]
    # Termos obrigatórios: marca + até 3 palavras mais específicas (com número primeiro: r34, 993, gt3, '84...)
    esp = sorted((x for x in modelo if x[1] not in LINHA), key=lambda x: (not re.search(r"\d", x[1]), -len(x[1])))
    obrig = ([marca[0]] if marca else []) + [n for _, n in esp[:3]]
    base = " ".join(n for _, n in [x for x in modelo if x[1] not in LINHA][:4])
    busca = "; ".join(dict.fromkeys(filter(None, [
        f"{marca[0]} {base}".strip() if marca else base,
        f"{base} {marca[0]}".strip() if marca and base else "",
    ])))
    nome = " ".join(filter(None, [marca[1] if marca else "", " ".join(r for r, _ in modelo[:5])])).strip() or title[:60]
    return {
        "name": nome[:80], "search_terms": busca or tn[:60], "required_terms": ", ".join(dict.fromkeys(obrig)),
        "forbidden_terms": "", "site_category": cat or "",
        "cores_no_titulo": cores,
        "observed_price": deal.get("price") or "", "product_id": deal.get("id") or "", "store": deal.get("store") or "",
        "source_url": deal.get("url") or "", "image": deal.get("image") or "", "titulo": title,
    }
