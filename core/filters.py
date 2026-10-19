import config
from core import db


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
