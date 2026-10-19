import re

import config
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
    if discount >= 50:
        score += 25
        reasons.append(f"Desconto excelente ({discount}%)")
    elif discount >= 40:
        score += 18
        reasons.append(f"Bom desconto ({discount}%)")
    elif discount >= 30:
        score += 10
        reasons.append(f"Desconto razoável ({discount}%)")
    elif discount < 15:
        score -= 15
        reasons.append(f"Desconto baixo ({discount}%)")

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
    quality = db.deal_price_quality(deal.get("title", ""), price)
    hist_label = quality.get("label", "")
    if hist_label == "recorde":
        score += 15
        reasons.append("Menor preço histórico!")
    elif hist_label == "excelente":
        score += 10
        reasons.append("Preço excelente vs histórico")
    elif hist_label == "boa":
        score += 5
        reasons.append("Bom preço vs histórico")
    elif hist_label == "cara":
        score -= 10
        reasons.append("Preço acima do normal")

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
    if score >= 75:
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


def is_relevant(title: str) -> bool:
    t = title.lower()
    if any(b in t for b in config.load_blocklist_terms()):
        return False
    if is_lego(title):
        return any(term in t for term in config.load_lego_car_terms())
    return any(term in t for term in config.load_relevant_terms())


def is_lego(title: str) -> bool:
    t = title.lower()
    return any(term in t for term in config.LEGO_TERMS)


def passes(deal: dict, lego_count: int, brand_rule=None) -> bool:
    """Aplica regras de relevância e o cap de LEGO por ciclo."""
    if db.is_blacklisted(deal):
        return False
    if not is_relevant(deal["title"]):
        return False
    if brand_rule:
        if deal["discount"] < brand_rule["min_discount"]:
            return False
        if not db.brand_limit_available(brand_rule):
            return False
        return True
    if is_lego(deal["title"]):
        if deal["discount"] < config.LEGO_MIN_DISCOUNT:
            return False
        if lego_count >= config.LEGO_MAX_PER_CYCLE:
            return False
    return True


def identifies_monitored(deal: dict, item: dict) -> bool:
    title = deal["title"].lower()
    required = [t.strip().lower() for t in item["required_terms"].split(",")
                if t.strip()]
    return (not db.is_blacklisted(deal)
            and bool(required)
            and all(term in title for term in required)
            and bool(deal.get("price")))


def matches_monitored(deal: dict, item: dict) -> bool:
    return (identifies_monitored(deal, item)
            and deal["price"] <= item["max_price"])
