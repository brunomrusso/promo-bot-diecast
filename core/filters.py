import re
import unicodedata

from core import db

# ---------------------------------------------------------------------------
# Score de relevância (0-100)
# ---------------------------------------------------------------------------

# Termos de alta relevância (marcas premium 1:64)
_PREMIUM_TERMS = [
    "hot wheels premium", "car culture", "boulevard", "elite 64", "rlc",
    "mini gt", "minigt", "kaido house", "tomica premium", "greenlight",
    "m2 machines", "johnny lightning", "matchbox premium", "auto world",
]
_GOOD_TERMS = [
    "hot wheels", "matchbox", "tomica", "majorette", "disney cars",
    "pixar cars", "relâmpago mcqueen", "diecast", "1:64", "1/64",
]


def relevance_score(deal: dict, brand_rule=None) -> dict:
    """Calculate a 0-100 relevance score for a deal.

    Returns dict with 'score', 'reasons' list, and 'auto_action'
    ('approve', 'reject', or 'review').
    """
    score = 50  # base
    reasons = []
    title = deal.get("title", "").lower()
    discount = deal.get("discount", 0) or 0
    price = deal.get("price", 0) or 0

    # --- Discount bonus (up to +25) ---
    reasons.append("Relevância temática; desconto informado pela loja não pontua")

    # --- Brand rule bonus (up to +15) ---
    if brand_rule:
        score += 10
        reasons.append(f"Regra: {brand_rule['name']}")
        if brand_rule.get("priority", 0) >= 80:
            score += 5
            reasons.append("Marca prioritária")

    # --- Premium terms (up to +15) ---
    for term in _PREMIUM_TERMS:
        if term in title:
            score += 15
            reasons.append(f"Termo premium: {term}")
            break

    # --- Good terms (up to +8) ---
    if not any(t in title for t in _PREMIUM_TERMS):
        for term in _GOOD_TERMS:
            if term in title:
                score += 8
                reasons.append(f"Termo relevante: {term}")
                break

    # --- Price quality from history (up to +15 / -10) ---
    quality = deal.get("_price_evaluation") or db.market_price_evaluation(deal.get("title", ""), price, deal.get("id", ""))

    # --- Rejection pattern penalty (up to -20) ---
    penalty = _rejection_penalty(title)
    if penalty > 0:
        score -= penalty
        reasons.append(f"Padrão de rejeição (-{penalty})")

    # --- Price range bonus ---
    if 20 <= price <= 150:
        score += 5
        reasons.append("Faixa de preço popular")
    elif price > 500:
        score -= 5
        reasons.append("Preço alto (> R$500)")

    # Clamp 0-100
    score = max(0, min(100, score))

    # Determine auto action
    if score >= 75 and quality["confident"] and deal.get("origin") == "national":
        auto_action = "approve"
    elif score <= 25:
        auto_action = "reject"
    else:
        auto_action = "review"

    return {"score": score, "reasons": reasons, "auto_action": auto_action}


def _rejection_penalty(title: str) -> int:
    """Check if title matches frequently rejected patterns."""
    with db._conn() as conn:
        # Count rejections with similar words in last 30 days
        rejected = conn.execute(
            "SELECT title FROM posted WHERE status='rejected' "
            "AND posted_at >= datetime('now', '-30 days')").fetchall()
    if not rejected:
        return 0
    title_words = set(re.findall(r'\w{4,}', title.lower()))
    if not title_words:
        return 0
    match_count = 0
    for row in rejected:
        rej_words = set(re.findall(r'\w{4,}', row["title"].lower()))
        overlap = len(title_words & rej_words)
        if overlap >= 3:
            match_count += 1
    if match_count >= 5:
        return 20
    elif match_count >= 3:
        return 12
    elif match_count >= 1:
        return 5
    return 0


def monitored_match_diagnostic(deal: dict, item: dict) -> dict:
    def normalize(value):
        value = unicodedata.normalize("NFKD", value.lower()).encode("ascii", "ignore").decode()
        return re.sub(r"\b(8\d|9\d)\b", r"19\1", value)
    title = normalize(deal["title"])
    required = [normalize(t.strip()) for t in item["required_terms"].split(",") if t.strip()]
    stopwords = {"e", "de", "do", "da", "the", "and", "com", "a", "o"}
    missing = []
    for term in required:
        words = [w for w in re.findall(r"[a-z0-9]+", term) if w not in stopwords]
        missing_words = []
        for w in words:
            pattern = (r"(?<!\d)" + re.escape(w) + r"(?!\d)" if w.isdigit()
                       else r"(?<![a-z0-9])" + re.escape(w) + r"(?![a-z0-9])")
            if not re.search(pattern, title):
                missing_words.append(w)
        if missing_words:
            missing.append(term if missing_words == words else f"{term} ({' '.join(missing_words)})")
    forbidden_hit = []
    for term in (item.get("forbidden_terms") or "").split(","):
        words = [w for w in re.findall(r"[a-z0-9]+", normalize(term.strip())) if w not in stopwords]
        if words and re.search(r"(?<![a-z0-9])" + r"[^a-z0-9]+".join(map(re.escape, words)) + r"(?![a-z0-9])", title):
            forbidden_hit.append(term.strip())
    reasons = []
    if forbidden_hit:
        reasons.append("Contém termo proibido: " + ", ".join(forbidden_hit))
    if db.monitored_offer_excluded(item.get("id"), deal):
        reasons.append("Marcado como outra mini neste cadastro")
    if not required:
        reasons.append("Nenhum termo obrigatório cadastrado")
    if missing:
        reasons.append("Faltam os trechos: " + ", ".join(missing))
    if deal.get("origin") == "international":
        reasons.append("Compra internacional fora da comparação nacional")
    if db.is_blacklisted(deal):
        reasons.append("Produto ou título na blacklist")
    if not deal.get("price"):
        reasons.append("Preço não extraído")
    return {"matches": not reasons, "missing_terms": missing, "forbidden_terms": forbidden_hit, "reasons": reasons}


def search_queries(raw_terms: str) -> list:
    return [q.strip() for q in re.split(r"[;\n]+", raw_terms or "") if q.strip()]


def identifies_monitored(deal: dict, item: dict) -> bool:
    return monitored_match_diagnostic(deal, item)["matches"]


def matches_monitored(deal: dict, item: dict) -> bool:
    return (identifies_monitored(deal, item)
            and deal["price"] <= item["max_price"])
