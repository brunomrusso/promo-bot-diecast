import json
import math
import re
import sqlite3
import unicodedata
from pathlib import Path
from datetime import datetime, timezone

DB_PATH = Path(__file__).parent / "deals.db"


def _conn():
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=30000")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute(
        "CREATE TABLE IF NOT EXISTS posted ("
        "product_id TEXT PRIMARY KEY, store TEXT, title TEXT, price REAL, "
        "posted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"
    )
    cols = {r[1] for r in conn.execute("PRAGMA table_info(posted)")}
    for col, typ in [("status", "TEXT DEFAULT 'posted'"),
                     ("url", "TEXT"), ("image", "TEXT"),
                     ("original_price", "REAL"), ("discount", "INTEGER"),
                     ("brand_rule_id", "INTEGER"), ("brand_name", "TEXT"),
                     ("coupon_code", "TEXT"), ("coupon_type", "TEXT"),
                     ("coupon_value", "REAL"), ("coupon_final_price", "REAL"),
                     ("coupon_savings", "REAL"), ("affiliate_url", "TEXT"),
                     ("relevance_score", "INTEGER"), ("score_reasons", "TEXT"),
                     ("decided_at", "TIMESTAMP"), ("monitored_item_id", "INTEGER"),
                     ("decision_source", "TEXT DEFAULT ''"),
                     ("admin_notified_at", "TIMESTAMP")]:
        if col not in cols:
            conn.execute(f"ALTER TABLE posted ADD COLUMN {col} {typ}")
    brand_rules_new = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='brand_rules'"
    ).fetchone() is None
    conn.execute(
        "CREATE TABLE IF NOT EXISTS brand_rules ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL UNIQUE, "
        "match_terms TEXT NOT NULL, min_discount INTEGER NOT NULL DEFAULT 0, "
        "approval_mode TEXT NOT NULL DEFAULT 'manual', "
        "auto_approve_discount INTEGER NOT NULL DEFAULT 40, "
        "daily_limit INTEGER NOT NULL DEFAULT 10, priority INTEGER NOT NULL DEFAULT 0, "
        "active INTEGER NOT NULL DEFAULT 1, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"
    )
    if brand_rules_new:
        defaults = [
            ("Hot Wheels Premium", "hot wheels premium,car culture,boulevard,elite 64,pop culture", 20, "manual", 40, 10, 100),
            ("Mini GT", "mini gt,minigt", 15, "manual", 35, 8, 90),
            ("Kaido House", "kaido house,kaido", 10, "manual", 30, 5, 90),
            ("Disney/Pixar Cars", "disney cars,carros disney,pixar cars,relâmpago mcqueen", 20, "manual", 40, 8, 80),
            ("LEGO Automotivo", "lego", 35, "manual", 45, 2, 70),
            ("Hot Wheels", "hot wheels", 30, "manual", 40, 10, 50),
            ("Outros Diecast", "matchbox,tomica,majorette,greenlight,m2 machines,johnny lightning,diecast,1:64,1/64", 25, "manual", 40, 10, 10),
        ]
        conn.executemany(
            "INSERT INTO brand_rules(name,match_terms,min_discount,approval_mode,"
            "auto_approve_discount,daily_limit,priority) VALUES(?,?,?,?,?,?,?)", defaults)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS monitored_items ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, "
        "search_terms TEXT NOT NULL, required_terms TEXT NOT NULL DEFAULT '', "
        "max_price REAL NOT NULL, active INTEGER NOT NULL DEFAULT 1, "
        "created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"
    )
    conn.execute("CREATE TABLE IF NOT EXISTS monitored_exclusions (monitored_item_id INTEGER NOT NULL, product_id TEXT NOT NULL, store TEXT NOT NULL, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, PRIMARY KEY(monitored_item_id,product_id,store))")
    monitored_cols = {r[1] for r in conn.execute("PRAGMA table_info(monitored_items)")}
    for col, typ in [("tags", "TEXT NOT NULL DEFAULT '[]'"),
                     ("all_time_min", "REAL"),
                     ("all_time_min_at", "TIMESTAMP"),
                     ("last_seen_price", "REAL"),
                     ("last_seen_at", "TIMESTAMP"),
                     ("image", "TEXT"),
                     ("site_enabled", "INTEGER NOT NULL DEFAULT 0"),
                     ("site_category", "TEXT NOT NULL DEFAULT ''"),
                     ("site_added_at", "TIMESTAMP"),
                     ("forbidden_terms", "TEXT NOT NULL DEFAULT ''")]:
        if col not in monitored_cols:
            conn.execute(f"ALTER TABLE monitored_items ADD COLUMN {col} {typ}")
    conn.execute(
        "CREATE TABLE IF NOT EXISTS catalog_opportunities ("
        "monitored_item_id INTEGER PRIMARY KEY, last_price REAL NOT NULL, "
        "last_notified_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS catalog_archives ("
        "product_id TEXT PRIMARY KEY, previous_status TEXT NOT NULL, "
        "reason TEXT NOT NULL, archived_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS price_observations ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, monitored_item_id INTEGER NOT NULL, "
        "product_id TEXT NOT NULL, store TEXT NOT NULL, title TEXT NOT NULL, "
        "price REAL NOT NULL, original_price REAL, url TEXT, image TEXT, "
        "observed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, "
        "FOREIGN KEY(monitored_item_id) REFERENCES monitored_items(id) ON DELETE CASCADE)"
    )
    conn.execute("CREATE VIEW IF NOT EXISTS valid_price_observations AS SELECT p.* FROM price_observations p WHERE NOT EXISTS (SELECT 1 FROM monitored_exclusions e WHERE e.monitored_item_id=p.monitored_item_id AND e.product_id=p.product_id AND e.store=p.store)")
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_price_item_date "
        "ON price_observations(monitored_item_id, observed_at)"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS blacklist ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT NOT NULL, "
        "value TEXT NOT NULL, label TEXT NOT NULL DEFAULT '', "
        "active INTEGER NOT NULL DEFAULT 1, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, "
        "UNIQUE(kind, value))"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS manual_jobs ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, action TEXT NOT NULL, "
        "status TEXT NOT NULL DEFAULT 'pending', payload TEXT NOT NULL, "
        "result TEXT, error TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, "
        "updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS scheduled_posts ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, product_id TEXT, deal TEXT NOT NULL, "
        "scheduled_at TIMESTAMP NOT NULL, status TEXT NOT NULL DEFAULT 'scheduled', "
        "created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, published_at TIMESTAMP, error TEXT)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_scheduled_due "
        "ON scheduled_posts(status,scheduled_at)"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS coupon_blitzes ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, payload TEXT NOT NULL, "
        "run_at TIMESTAMP NOT NULL, status TEXT NOT NULL DEFAULT 'scheduled', "
        "result TEXT, error TEXT, "
        "created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, executed_at TIMESTAMP)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_blitz_due "
        "ON coupon_blitzes(status,run_at)"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS price_alerts ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "product_id TEXT, title TEXT NOT NULL, store TEXT, "
        "target_price REAL NOT NULL, current_price REAL, "
        "url TEXT, image TEXT, "
        "triggered INTEGER NOT NULL DEFAULT 0, "
        "created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, "
        "triggered_at TIMESTAMP)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_price_alerts_active "
        "ON price_alerts(triggered, title)"
    )
    alert_cols = {r[1] for r in conn.execute("PRAGMA table_info(price_alerts)")}
    if "migrated" not in alert_cols:
        conn.execute(
            "ALTER TABLE price_alerts ADD COLUMN migrated INTEGER NOT NULL DEFAULT 0")
    conn.execute(
        "CREATE TABLE IF NOT EXISTS affiliate_links ("
        "store TEXT NOT NULL, source_url TEXT NOT NULL, affiliate_url TEXT NOT NULL, "
        "updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, PRIMARY KEY(store,source_url))"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS product_prices ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "signature TEXT NOT NULL, product_id TEXT NOT NULL, "
        "store TEXT, title TEXT, "
        "price REAL NOT NULL, original_price REAL, "
        "verdict TEXT NOT NULL DEFAULT 'seen', "
        "day TEXT NOT NULL, seen_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, "
        "UNIQUE(product_id, day))"
    )
    price_cols = {r[1] for r in conn.execute("PRAGMA table_info(product_prices)")}
    for col, typ in [("origin", "TEXT DEFAULT 'unknown'"), ("url", "TEXT")]:
        if col not in price_cols:
            conn.execute(f"ALTER TABLE product_prices ADD COLUMN {col} {typ}")
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_product_prices_sig "
        "ON product_prices(signature, seen_at)"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS app_settings ("
        "key TEXT PRIMARY KEY, value TEXT NOT NULL, "
        "updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS system_state ("
        "key TEXT PRIMARY KEY, value TEXT, updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS store_health ("
        "store TEXT PRIMARY KEY, status TEXT NOT NULL, offers INTEGER DEFAULT 0, "
        "duration REAL DEFAULT 0, error TEXT, "
        "last_check TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS clicks ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "product_id TEXT NOT NULL, clicked_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, "
        "referer TEXT, ua TEXT)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_clicks_product "
        "ON clicks(product_id, clicked_at)"
    )
    conn.commit()
    return conn


def record_click(product_id, referer="", ua=""):
    with _conn() as conn:
        conn.execute(
            "INSERT INTO clicks (product_id, referer, ua) VALUES (?, ?, ?)",
            (product_id, referer[:500], ua[:500]))


def click_stats(days=30):
    with _conn() as conn:
        total = conn.execute(
            "SELECT COUNT(*) FROM clicks WHERE clicked_at >= datetime('now', ?)",
            (f'-{days} days',)).fetchone()[0]
        by_store = [dict(r) for r in conn.execute(
            "SELECT p.store, COUNT(c.id) as clicks FROM clicks c "
            "JOIN posted p ON c.product_id=p.product_id "
            "WHERE c.clicked_at >= datetime('now', ?) "
            "GROUP BY p.store ORDER BY clicks DESC",
            (f'-{days} days',))]
        top = [dict(r) for r in conn.execute(
            "SELECT p.title, p.store, COUNT(c.id) as clicks "
            "FROM clicks c JOIN posted p ON c.product_id=p.product_id "
            "WHERE c.clicked_at >= datetime('now', ?) "
            "GROUP BY c.product_id ORDER BY clicks DESC LIMIT 10",
            (f'-{days} days',))]
        daily = [dict(r) for r in conn.execute(
            "SELECT date(clicked_at) as day, COUNT(*) as clicks "
            "FROM clicks WHERE clicked_at >= datetime('now', ?) "
            "GROUP BY day ORDER BY day",
            (f'-{days} days',))]
        return {"total": total, "by_store": by_store, "top": top, "daily": daily}


def cached_affiliate_link(store, source_url):
    with _conn() as conn:
        row = conn.execute(
            "SELECT affiliate_url FROM affiliate_links WHERE store=? AND source_url=? "
            "AND updated_at>=datetime('now','-30 days')", (store, source_url)).fetchone()
        if not row:
            row = conn.execute(
                "SELECT affiliate_url FROM posted WHERE store=? AND url=? "
                "AND affiliate_url!='' AND posted_at>=datetime('now','-30 days') "
                "ORDER BY posted_at DESC LIMIT 1", (store, source_url)).fetchone()
        if not row:
            row = conn.execute(
                "SELECT json_extract(j.result,'$.affiliate_url') FROM manual_jobs j "
                "JOIN posted p ON p.product_id=json_extract(j.payload,'$.product_id') "
                "WHERE j.action='share_pending' AND j.status='done' AND p.store=? AND p.url=? "
                "AND j.updated_at>=datetime('now','-30 days') "
                "AND json_extract(j.result,'$.affiliate_url')!='' ORDER BY j.id DESC LIMIT 1",
                (store, source_url)).fetchone()
        return row[0] if row else ""


def cache_affiliate_link(store, source_url, link):
    with _conn() as conn:
        conn.execute(
            "INSERT INTO affiliate_links(store,source_url,affiliate_url) VALUES(?,?,?) "
            "ON CONFLICT(store,source_url) DO UPDATE SET affiliate_url=excluded.affiliate_url,"
            "updated_at=CURRENT_TIMESTAMP", (store, source_url, link))


def already_posted(product_id: str) -> bool:
    with _conn() as conn:
        return conn.execute(
            "SELECT 1 FROM posted WHERE product_id = ?", (product_id,)
        ).fetchone() is not None


def should_repost(product_id: str, current_price: float,
                  min_drop_pct: float = 15, min_hours: int = 24) -> bool:
    """Return True if product was posted before but price dropped significantly."""
    if current_price <= 0:
        return False
    with _conn() as conn:
        row = conn.execute(
            "SELECT price, posted_at FROM posted WHERE product_id=? "
            "AND status='posted' AND posted_at >= datetime('now',?)",
            (product_id, f'-{min_hours * 24} hours')).fetchone()
        if not row or not row["price"] or row["price"] <= 0:
            return False
        old_price = float(row["price"])
        drop_pct = (old_price - current_price) / old_price * 100
        return drop_pct >= min_drop_pct


def mark_posted(product_id: str, store: str, title: str, price: float,
                status: str = "posted", url: str = "", image: str = "",
                original_price: float = 0, discount: int = 0,
                brand_rule_id=None, brand_name="",
                relevance_score=None, score_reasons=""):
    with _conn() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO posted "
            "(product_id, store, title, price, status, url, image, "
            "original_price, discount, brand_rule_id, brand_name, "
            "relevance_score, score_reasons) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (product_id, store, title, price, status, url, image,
             original_price, discount, brand_rule_id, brand_name,
             relevance_score, score_reasons),
        )


def set_status(product_id: str, status: str, brand_rule_id=None, brand_name=""):
    with _conn() as conn:
        if brand_rule_id is not None:
            conn.execute(
                "UPDATE posted SET status=?,brand_rule_id=?,brand_name=?,"
                "decided_at=CURRENT_TIMESTAMP WHERE product_id=?",
                (status, brand_rule_id, brand_name, product_id))
        else:
            conn.execute(
                "UPDATE posted SET status=?,decided_at=CURRENT_TIMESTAMP "
                "WHERE product_id=?", (status, product_id))


def record_publication_details(product_id, deal, affiliate_url):
    final_price = float(deal.get("manual_coupon_final_price") or 0)
    price = float(deal.get("price") or 0)
    with _conn() as conn:
        conn.execute(
            "UPDATE posted SET coupon_code=?,coupon_type=?,coupon_value=?,"
            "coupon_final_price=?,coupon_savings=?,affiliate_url=? WHERE product_id=?",
            (deal.get("manual_coupon_code", ""), deal.get("manual_coupon_type", ""),
             float(deal.get("manual_coupon_value") or 0), final_price,
             max(0, price - final_price) if final_price else 0,
             affiliate_url, product_id))


def expire_pending():
    hours = int(get_setting("approval_expiry_hours", 24))
    with _conn() as conn:
        expiring = [r[0] for r in conn.execute(
            "SELECT DISTINCT monitored_item_id FROM posted WHERE status='pending' "
            "AND decision_source='catalog' AND monitored_item_id IS NOT NULL "
            "AND posted_at < datetime('now', ?)", (f"-{hours} hours",))]
        conn.execute(
            "UPDATE posted SET status='expired' WHERE status='pending' "
            "AND posted_at < datetime('now', ?)", (f"-{hours} hours",))
        # Expirar não é decisão humana: libera a mini para ser reapresentada no
        # próximo ciclo, mesmo sem nova queda de 3% (antes ela sumia para sempre).
        for item_id in expiring:
            conn.execute("DELETE FROM catalog_opportunities WHERE monitored_item_id=?", (item_id,))
    return hours


def mark_admin_notified(product_id):
    with _conn() as conn:
        conn.execute("UPDATE posted SET admin_notified_at=CURRENT_TIMESTAMP WHERE product_id=?", (product_id,))


def pending_catalog_unnotified(limit=5):
    expire_pending()
    with _conn() as conn:
        return [dict(r) for r in conn.execute(
            "SELECT * FROM posted WHERE status='pending' AND decision_source='catalog' "
            "AND admin_notified_at IS NULL ORDER BY posted_at LIMIT ?", (limit,))]


def get_pending(product_id: str):
    expire_pending()
    with _conn() as conn:
        row = conn.execute(
            "SELECT store,title,price,url,image,original_price,discount "
            "FROM posted WHERE product_id=? AND status='pending'",
            (product_id,),
        ).fetchone()
        return tuple(row) if row else None


def list_pending(store="", search="", sort="newest"):
    expire_pending()
    order = {
        "discount_desc": "discount DESC, posted_at DESC",
        "price_asc": "price ASC, posted_at DESC",
        "newest": "posted_at DESC, product_id DESC",
        "oldest": "posted_at ASC, product_id ASC",
        "score_desc": "COALESCE(relevance_score,50) DESC, posted_at DESC",
        "score_asc": "COALESCE(relevance_score,50) ASC, posted_at DESC",
    }.get(sort, "posted_at DESC, product_id DESC")
    clauses = ["status='pending'"]
    params = []
    if store:
        clauses.append("store=?")
        params.append(store)
    if search:
        clauses.append("title LIKE ?")
        params.append(f"%{search}%")
    with _conn() as conn:
        rows = conn.execute(
            f"SELECT * FROM posted WHERE {' AND '.join(clauses)} ORDER BY {order}",
            params).fetchall()
        stores = [r[0] for r in conn.execute(
            "SELECT DISTINCT store FROM posted WHERE status='pending' ORDER BY store")]
    items = [dict(r) for r in rows]
    from core.filters import relevance_score
    for item in items:
        item["quality"] = market_price_evaluation(item["title"], item["price"], item["product_id"])
        if item.get("decision_source") == "catalog":
            registered = get_monitored_item(item.get("monitored_item_id"))
            if registered and registered["max_price"] > 0 and item["price"] <= registered["max_price"]:
                item["quality"].update(key="target", label="Preço-alvo atingido",
                                       detail=item.get("score_reasons") or "Oportunidade do catálogo aguardando sua revisão.")
        score = relevance_score({**item, "id": item["product_id"], "_price_evaluation": item["quality"]},
                                match_brand_rule(item["title"]))
        item["relevance_score"] = score["score"]
        item["score_reasons"] = "; ".join(score["reasons"])
        item["group_key"] = product_group_key(
            item["title"], item.get("brand_name", ""),
            item["quality"].get("monitored_item_id"))
    # Merge near-duplicate groups: same product in different listings
    signatures = {item["product_id"]: title_signature(item["title"])
                  for item in items}
    groups = []
    monitored_groups = {}
    for item in items:
        if item["group_key"].startswith("monitored:"):
            monitored_groups.setdefault(item["group_key"], []).append(item)
            continue
        sig = signatures[item["product_id"]]
        for group in groups:
            if any(comparable_product(item["title"], o["title"]) for o in group):
                group.append(item)
                break
        else:
            groups.append([item])
    groups.extend(monitored_groups.values())
    for group in groups:
        valid_prices = [float(item["price"]) for item in group if item.get("price")]
        minimum = min(valid_prices) if valid_prices else 0
        for item in group:
            item["comparison"] = {
                "count": len(group), "stores": len(set(row["store"] for row in group)),
                "min_price": minimum, "best": bool(minimum and item["price"] == minimum),
            }
    return items, stores


_GROUP_STOPWORDS = {
    "de", "da", "do", "das", "dos", "com", "para", "por", "em", "e",
    "miniatura", "miniaturas", "carrinho", "carrinhos", "colecionavel",
    "novo", "nova", "original", "mattel", "escala", "diecast", "carro",
    "carros", "veiculo", "unidade", "hot", "wheels", "lacrado", "lacrada",
    "frete", "gratis", "pronta", "entrega",
}


def title_signature(title):
    """Token set that identifies the product, ignoring filler words."""
    normalized = unicodedata.normalize("NFKD", (title or "").lower()).encode(
        "ascii", "ignore").decode()
    return {t for t in re.findall(r"[a-z0-9]+", normalized)
            if t not in _GROUP_STOPWORDS and len(t) > 1}


def _signatures_similar(a, b):
    if not a or not b:
        return False
    if a <= b or b <= a:
        return True
    return len(a & b) / len(a | b) >= 0.65


def comparable_product(a, b):
    def tokens(title):
        value = unicodedata.normalize("NFKD", title.lower()).encode("ascii", "ignore").decode()
        value = re.sub(r"fast\s+(?:and\s+)?furious|velozes\s+(?:e\s+)?furiosos", "ffseries", value)
        value = re.sub(r"\b(?:19)?(8\d|9\d)\b", lambda m: "19" + m[1], value)
        return (title_signature(value) | set(re.findall(r"\b\d+\b", value))) - {"premium", "cor", "honda"}
    left, right = tokens(a), tokens(b)
    refs = lambda words: {t for t in words if re.fullmatch(r"[a-z]{2,}\d{2,}", t)}
    numbers = lambda words: {t for t in words if t.isdigit()}
    if refs(left) and refs(right) and refs(left) != refs(right):
        return False
    if numbers(left) != numbers(right):
        return False
    colors = {"preto", "branco", "azul", "vermelho", "verde", "amarelo", "prata", "cinza"}
    if (left & colors) and (right & colors) and (left & colors) != (right & colors):
        return False
    return len(left & right) >= 3 and len(left & right) / max(1, len(left | right)) >= 0.70


def market_price_evaluation(title, price, product_id="", monitored_item_id=None):
    with _conn() as conn:
        rows = [dict(r) for r in conn.execute(
            "SELECT * FROM product_prices WHERE origin='national' AND price>0 "
            "AND product_id!='' AND seen_at>=datetime('now','-90 days') ORDER BY seen_at,id")]
    rows = [r for r in rows if comparable_product(title, r["title"])
            and not monitored_offer_excluded(monitored_item_id, {"id": r["product_id"], "store": r["store"]})]
    recent = {r["product_id"]: r for r in rows
              if r["seen_at"] >= datetime.now(timezone.utc).strftime("%Y-%m-%d")}
    alternatives = [r for pid, r in recent.items() if pid != product_id]
    daily_minima = {}
    for row in rows:
        daily_minima[row["day"]] = min(daily_minima.get(row["day"], row["price"]), row["price"])
    prices = list(daily_minima.values())
    days = len(daily_minima)
    best = min(alternatives, key=lambda r: r["price"]) if alternatives else None
    result = {"key": "untracked", "label": "Preço ainda não avaliado",
              "detail": "Sem comparação nacional suficiente. Revisão manual obrigatória; frete não incluído.",
              "confident": False, "observations": len(rows), "days": days,
              "compared": len(alternatives), "best_url": best["url"] if best else "",
              "best_price": best["price"] if best else None}
    if best:
        result.update(key="normal", label="Menor entre ofertas consultadas" if price <= best["price"] else "Há oferta nacional mais barata",
                      detail=f"{len(alternatives)} anúncio(s) nacional(is) consultado(s) hoje; menor R$ {best['price']:.2f}. Frete e condições devem ser conferidos.")
        if price > best["price"] * 1.01:
            result["key"] = "expensive"
    if days >= 5 and len(prices) >= 5:
        quality = classify_price(price, min(prices), sum(prices) / len(prices), len(prices))
        result.update(min_price=min(prices), avg_price=sum(prices) / len(prices))
        if result["key"] != "expensive":
            result.update(key=quality["key"], label=quality["label"],
                          detail=quality["detail"] + "; histórico nacional em pelo menos 5 dias. Frete não incluído.")
        result["confident"] = bool(best and result["key"] in {"record", "excellent", "good"})
    return result


def similar_pending(title, exclude_id=None):
    """Pending offers that look like the same product in other listings."""
    sig = title_signature(title)
    if not sig:
        return []
    with _conn() as conn:
        rows = [dict(r) for r in conn.execute(
            "SELECT product_id,title,price FROM posted WHERE status='pending'")]
    return [r for r in rows if r["product_id"] != exclude_id
            and comparable_product(title, r["title"])]


def supersede_pending(product_ids):
    """Mark pending offers replaced by a better/approved equivalent."""
    ids = [i for i in product_ids if i]
    if not ids:
        return
    with _conn() as conn:
        conn.executemany(
            "UPDATE posted SET status='superseded',decided_at=CURRENT_TIMESTAMP "
            "WHERE product_id=? AND status='pending'", [(i,) for i in ids])


_UNDOABLE_STATUSES = ("rejected", "auto_rejected", "superseded")


def list_decisions(days=7, limit=40):
    """Recent rejections/supersedes, newest first, for review and undo."""
    with _conn() as conn:
        return [dict(r) for r in conn.execute(
            "SELECT product_id,store,title,price,url,image,discount,status,"
            "score_reasons,posted_at,decided_at FROM posted "
            "WHERE status IN ('rejected','auto_rejected','superseded') "
            "AND COALESCE(decided_at,posted_at) >= datetime('now', ?) "
            "ORDER BY COALESCE(decided_at,posted_at) DESC LIMIT ?",
            (f"-{int(days)} days", int(limit)))]


def restore_decision(product_id):
    """Undo a rejection/supersede: the offer returns to the approval queue and
    any learned 'rejected' verdict it left is cleared."""
    from core.filters import identifies_monitored
    active = active_monitored_items()
    with _conn() as conn:
        row = conn.execute(
            "SELECT * FROM posted WHERE product_id=?",
            (product_id,)).fetchone()
        if not row or row["status"] not in _UNDOABLE_STATUSES:
            return False
        item = next((item for item in active if identifies_monitored(dict(row), item)), None)
        restored_status = "pending" if item or product_id.startswith("manual-") else "catalog_archived"
        if restored_status == "catalog_archived":
            conn.execute("INSERT OR IGNORE INTO catalog_archives(product_id,previous_status,reason) VALUES(?,?,?)",
                         (product_id, row["status"], "Veredito desfeito sem autorizar monitoramento"))
        if item:
            count = conn.execute("SELECT COUNT(*) FROM posted WHERE status='pending' AND decision_source='catalog'").fetchone()[0]
            existing = conn.execute("SELECT 1 FROM posted WHERE status='pending' AND monitored_item_id=?", (item["id"],)).fetchone()
            if existing or count >= 20:
                return False
            conn.execute("UPDATE posted SET monitored_item_id=?,decision_source='catalog' WHERE product_id=?", (item["id"], product_id))
        conn.execute(
            "UPDATE posted SET status=?,decided_at=NULL,"
            "posted_at=CURRENT_TIMESTAMP WHERE product_id=?", (restored_status, product_id))
        # Clear the learned 'rejected' stain: by offer id and by this
        # product's signature (covers rows saved with a blank product_id).
        signature = ",".join(sorted(title_signature(row["title"])))
        conn.execute(
            "UPDATE product_prices SET verdict='seen' "
            "WHERE verdict='rejected' AND (product_id=? OR (product_id='' AND signature=?))",
            (product_id, signature))
    return True


def product_group_key(title, brand_name="", monitored_item_id=None):
    if monitored_item_id:
        return f"monitored:{monitored_item_id}"
    useful = sorted(title_signature(title))[:10]
    prefix = brand_name.lower().replace(" ", "-") if brand_name else "produto"
    return prefix + ":" + "-".join(useful)


# ---------------------------------------------------------------------------
# Aprendizado de preços por assinatura do produto
# ---------------------------------------------------------------------------

_MIN_LEARNED_OBS = 5


def record_product_price(deal, verdict="seen"):
    """Record a public price sighting for the learned baseline."""
    price = float(deal.get("price") or 0)
    if price <= 0:
        return
    sig = ",".join(sorted(title_signature(deal.get("title", ""))))
    if not sig:
        return
    with _conn() as conn:
        conn.execute(
            "INSERT INTO product_prices"
            "(signature,product_id,store,title,price,original_price,verdict,day,origin,url) "
            "VALUES(?,?,?,?,?,?,?,date('now'),?,?) "
            "ON CONFLICT(product_id,day) DO UPDATE SET "
            "price=excluded.price,original_price=excluded.original_price,"
            "origin=CASE WHEN excluded.origin='unknown' THEN product_prices.origin ELSE excluded.origin END,"
            "url=COALESCE(NULLIF(excluded.url,''),product_prices.url),"
            "verdict=CASE WHEN product_prices.verdict='seen' "
            "THEN excluded.verdict ELSE product_prices.verdict END,"
            "seen_at=CURRENT_TIMESTAMP",
            (sig, str(deal.get("id") or deal.get("product_id") or ""), deal.get("store", ""),
             str(deal.get("title", ""))[:200], price,
             float(deal.get("original_price") or 0), verdict,
             deal.get("origin", "international" if deal.get("international") else "unknown"),
             deal.get("url", "")))


def record_verdict(product_id, verdict):
    """Record the human verdict (approved/rejected) for a posted offer."""
    with _conn() as conn:
        row = conn.execute(
            "SELECT * FROM posted WHERE product_id=?", (product_id,)).fetchone()
    if row:
        record_product_price({**dict(row), "id": product_id}, verdict)


def _matching_signatures(sig_set, days=90):
    """Stored signatures similar to the given token set."""
    with _conn() as conn:
        rows = [r[0] for r in conn.execute(
            "SELECT DISTINCT signature FROM product_prices "
            "WHERE seen_at >= datetime('now', ?)", (f"-{days} days",))]
    return [r for r in rows
            if _signatures_similar(sig_set, set(filter(None, r.split(","))))]


def learned_price_baseline(title, days=90):
    """Min/avg/rejection stats from learned sightings of similar products."""
    sig = title_signature(title)
    if not sig:
        return None
    matches = _matching_signatures(sig, days)
    if not matches:
        return None
    placeholders = ",".join("?" * len(matches))
    with _conn() as conn:
        rows = conn.execute(
            f"SELECT price,verdict FROM product_prices WHERE signature IN ({placeholders}) "
            f"AND seen_at >= datetime('now','-{days} days')", matches).fetchall()
        all_min = conn.execute(
            f"SELECT MIN(price) FROM product_prices WHERE signature IN ({placeholders})",
            matches).fetchone()[0]
    prices = [float(r["price"]) for r in rows if r["price"]]
    if not prices:
        return None
    rejected = [float(r["price"]) for r in rows
                if r["price"] and r["verdict"] == "rejected"]
    return {
        "observations": len(prices),
        "min_price": min(prices),
        "avg_price": sum(prices) / len(prices),
        "all_time_min": all_min,
        "max_rejected": max(rejected) if rejected else None,
    }


def learned_price_quality(title, price):
    """Price quality from learned history (non-monitored products)."""
    baseline = learned_price_baseline(title)
    if not baseline or baseline["observations"] < 2:
        return {"key": "untracked", "label": "Sem histórico",
                "detail": "Ainda não há leituras suficientes deste produto",
                "observations": baseline["observations"] if baseline else 0}
    quality = classify_price(float(price or 0), baseline["min_price"],
                             baseline["avg_price"], baseline["observations"],
                             baseline["all_time_min"])
    quality.update({
        "min_price": baseline["min_price"], "avg_price": baseline["avg_price"],
        "observations": baseline["observations"], "learned": True,
    })
    return quality


def learned_rejection(title, price):
    """Reason to auto-reject based on learned history, or None."""
    evaluation = market_price_evaluation(title, price)
    if evaluation.get("days", 0) >= 5 and evaluation.get("avg_price") \
            and price > evaluation["avg_price"] * 1.05:
        return (f"preço acima da média nacional de R$ {evaluation['avg_price']:.2f} "
                f"em {evaluation['days']} dias distintos")
    return None


def prune_product_prices(days=180):
    with _conn() as conn:
        conn.execute(
            "DELETE FROM product_prices WHERE seen_at < datetime('now', ?)",
            (f"-{days} days",))


def classify_price(price, min_price, avg_price, observations, all_time_min=None):
    if not price or not min_price or not avg_price or observations < 2:
        return {"key": "initial", "label": "Histórico inicial",
                "detail": "Ainda não há leituras suficientes para comparar"}
    if all_time_min and price <= all_time_min:
        return {"key": "record", "label": "Menor preço histórico",
                "detail": "Igualou ou superou o menor preço já registrado"}
    if price <= min_price * 1.05:
        return {"key": "excellent", "label": "Preço excelente",
                "detail": "Até 5% acima do mínimo dos últimos 90 dias"}
    if price <= avg_price * 0.90:
        return {"key": "good", "label": "Bom preço",
                "detail": "Pelo menos 10% abaixo da média de 90 dias"}
    if price <= avg_price * 1.05:
        return {"key": "normal", "label": "Preço normal",
                "detail": "Próximo da média dos últimos 90 dias"}
    return {"key": "expensive", "label": "Preço acima da média",
            "detail": "Mais de 5% acima da média dos últimos 90 dias"}


def deal_price_quality(title, price, monitored_item_id=None):
    with _conn() as conn:
        if monitored_item_id:
            candidates = conn.execute(
                "SELECT * FROM monitored_items WHERE id=?", (monitored_item_id,)
            ).fetchall()
        else:
            candidates = conn.execute("SELECT * FROM monitored_items").fetchall()
        title_lower = title.lower()
        matches = []
        for candidate in candidates:
            required = [term.strip().lower()
                        for term in candidate["required_terms"].split(",")
                        if term.strip()]
            forbidden = [term.strip().lower()
                         for term in (candidate["forbidden_terms"] or "").split(",")
                         if term.strip()]
            if not monitored_item_id and any(term in title_lower for term in forbidden):
                continue
            if monitored_item_id or (required and all(term in title_lower for term in required)):
                matches.append((len(required), candidate))
        if not matches:
            return learned_price_quality(title, price)
        item = max(matches, key=lambda match: match[0])[1]
        summary = conn.execute(
            "SELECT MIN(price) min_price,AVG(price) avg_price,COUNT(*) observations,"
            "COUNT(DISTINCT date(observed_at)) days "
            "FROM valid_price_observations WHERE monitored_item_id=? "
            "AND observed_at >= datetime('now','-90 days')", (item["id"],)
        ).fetchone()
    quality = classify_price(float(price or 0), summary["min_price"],
                             summary["avg_price"], summary["observations"],
                             item["all_time_min"])
    if summary["days"] < 5:
        quality.update(key="initial", label="Histórico inicial",
                       detail=f"{summary['days']} dia(s) com coletas; ainda não há base temporal suficiente para avaliar a oportunidade.")
    quality.update({
        "monitored_item_id": item["id"], "monitored_name": item["name"],
        "min_price": summary["min_price"], "avg_price": summary["avg_price"],
        "observations": summary["observations"], "days": summary["days"],
    })
    return quality


def metrics_summary(days=30):
    period = f"-{int(days)} days"
    with _conn() as conn:
        totals = dict(conn.execute(
            "SELECT COUNT(*) total,SUM(status='posted') posted,SUM(status='pending') pending,"
            "SUM(status='rejected') rejected,SUM(status='blacklisted') blacklisted,"
            "AVG(CASE WHEN status='posted' THEN discount END) avg_discount "
            "FROM posted WHERE posted_at>=datetime('now',?)", (period,)).fetchone())
        daily = [dict(r) for r in conn.execute(
            "SELECT date(posted_at) day,COUNT(*) total,SUM(status='posted') posted "
            "FROM posted WHERE posted_at>=datetime('now',?) GROUP BY date(posted_at) ORDER BY day", (period,))]
        stores = [dict(r) for r in conn.execute(
            "SELECT store,COUNT(*) total,SUM(status='posted') posted,AVG(discount) avg_discount "
            "FROM posted WHERE posted_at>=datetime('now',?) GROUP BY store ORDER BY posted DESC", (period,))]
        brands = [dict(r) for r in conn.execute(
            "SELECT COALESCE(NULLIF(brand_name,''),'Sem categoria') brand,COUNT(*) total,"
            "SUM(status='posted') posted FROM posted WHERE posted_at>=datetime('now',?) "
            "GROUP BY brand ORDER BY posted DESC", (period,))]
        coupons = [dict(r) for r in conn.execute(
            "SELECT coupon_code,COUNT(*) uses,SUM(coupon_savings) savings,"
            "AVG(coupon_final_price) avg_final FROM posted WHERE status='posted' "
            "AND coupon_code!='' AND posted_at>=datetime('now',?) "
            "GROUP BY coupon_code ORDER BY uses DESC", (period,))]
        coupon_totals = dict(conn.execute(
            "SELECT COUNT(*) uses,COALESCE(SUM(coupon_savings),0) savings "
            "FROM posted WHERE status='posted' AND coupon_code!='' "
            "AND posted_at>=datetime('now',?)", (period,)).fetchone())
        score_dist = [dict(r) for r in conn.execute(
            "SELECT CASE WHEN relevance_score>=75 THEN 'alto' "
            "WHEN relevance_score>=50 THEN 'medio' "
            "WHEN relevance_score IS NOT NULL THEN 'baixo' "
            "ELSE 'sem_score' END as faixa, COUNT(*) as total, "
            "SUM(status='posted') as posted, SUM(status='rejected') as rejected "
            "FROM posted WHERE posted_at>=datetime('now',?) GROUP BY faixa", (period,))]
    return {"totals": totals, "daily": daily, "stores": stores, "brands": brands,
            "coupons": coupons, "coupon_totals": coupon_totals, "days": days,
            "score_dist": score_dist}


def list_brand_rules():
    with _conn() as conn:
        return [dict(r) for r in conn.execute(
            "SELECT * FROM brand_rules ORDER BY priority DESC,name")]


def save_brand_rule(data, rule_id=None):
    values = (data["name"].strip(), data["match_terms"].strip(),
              int(data["min_discount"]), data["approval_mode"],
              int(data["auto_approve_discount"]), int(data["daily_limit"]),
              int(data.get("priority", 0)), int(bool(data.get("active", True))))
    with _conn() as conn:
        if rule_id:
            conn.execute(
                "UPDATE brand_rules SET name=?,match_terms=?,min_discount=?,"
                "approval_mode=?,auto_approve_discount=?,daily_limit=?,priority=?,"
                "active=? WHERE id=?", values + (rule_id,))
            return rule_id
        return conn.execute(
            "INSERT INTO brand_rules(name,match_terms,min_discount,approval_mode,"
            "auto_approve_discount,daily_limit,priority,active) VALUES(?,?,?,?,?,?,?,?)",
            values).lastrowid


def delete_brand_rule(rule_id):
    with _conn() as conn:
        conn.execute("DELETE FROM brand_rules WHERE id=?", (rule_id,))


def match_brand_rule(title):
    title_lower = title.lower()
    rules = list_brand_rules()
    for rule in rules:
        if not rule["active"]:
            continue
        terms = [term.strip().lower() for term in rule["match_terms"].split(",")
                 if term.strip()]
        if any(term in title_lower for term in terms):
            return rule
    # Fallback: match by partial word overlap (at least 2 words from any rule)
    title_words = set(re.findall(r'[a-z0-9]+', title_lower))
    best, best_score = None, 0
    for rule in rules:
        if not rule["active"]:
            continue
        terms = [t.strip().lower() for t in rule["match_terms"].split(",") if t.strip()]
        rule_words = set()
        for t in terms:
            rule_words.update(re.findall(r'[a-z0-9]+', t))
        overlap = len(title_words & rule_words)
        if overlap >= 2 and overlap > best_score:
            best, best_score = rule, overlap
    return best


def brand_daily_count(rule_id):
    with _conn() as conn:
        return conn.execute(
            "SELECT COUNT(*) FROM posted WHERE brand_rule_id=? AND status='posted' "
            "AND date(posted_at)=date('now')", (rule_id,)).fetchone()[0]


def brand_limit_available(rule):
    return not rule or rule["daily_limit"] <= 0 or brand_daily_count(rule["id"]) < rule["daily_limit"]


def minimum_brand_discount():
    with _conn() as conn:
        row = conn.execute(
            "SELECT MIN(min_discount) FROM brand_rules WHERE active=1").fetchone()
        return row[0] if row and row[0] is not None else None


def list_monitored_items():
    with _conn() as conn:
        items = [dict(r) for r in conn.execute(
            "SELECT * FROM monitored_items ORDER BY active DESC, name"
        )]
        for item in items:
            item["tags"] = json.loads(item["tags"])
            # Price trend: compare last 7d avg vs previous 7d avg
            recent = conn.execute(
                "SELECT AVG(price) avg_price FROM valid_price_observations "
                "WHERE monitored_item_id=? AND observed_at >= datetime('now','-7 days')",
                (item["id"],)).fetchone()
            older = conn.execute(
                "SELECT AVG(price) avg_price FROM valid_price_observations "
                "WHERE monitored_item_id=? AND observed_at >= datetime('now','-14 days') "
                "AND observed_at < datetime('now','-7 days')",
                (item["id"],)).fetchone()
            avg_90d = conn.execute(
                "SELECT AVG(price) avg_price FROM valid_price_observations "
                "WHERE monitored_item_id=? AND observed_at >= datetime('now','-90 days')",
                (item["id"],)).fetchone()
            best_store = conn.execute(
                "SELECT store, MIN(price) min_price FROM valid_price_observations "
                "WHERE monitored_item_id=? AND observed_at >= datetime('now','-7 days') "
                "GROUP BY store ORDER BY min_price LIMIT 1",
                (item["id"],)).fetchone()
            r_avg = float(recent["avg_price"]) if recent and recent["avg_price"] else None
            o_avg = float(older["avg_price"]) if older and older["avg_price"] else None
            a_avg = float(avg_90d["avg_price"]) if avg_90d and avg_90d["avg_price"] else None
            # Trend
            if r_avg and o_avg:
                pct = (r_avg - o_avg) / o_avg * 100
                if pct < -5:
                    item["trend"] = "down"
                    item["trend_pct"] = round(pct, 1)
                elif pct > 5:
                    item["trend"] = "up"
                    item["trend_pct"] = round(pct, 1)
                else:
                    item["trend"] = "stable"
                    item["trend_pct"] = round(pct, 1)
            else:
                item["trend"] = None
                item["trend_pct"] = None
            # Opportunity: last price < 90% of 90d average
            lp = float(item["last_seen_price"]) if item.get("last_seen_price") else None
            item["is_opportunity"] = bool(conn.execute(
                "SELECT 1 FROM posted WHERE status='pending' AND decision_source='catalog' AND monitored_item_id=?",
                (item["id"],)).fetchone())
            item["avg_90d"] = round(a_avg, 2) if a_avg else None
            # Best store right now
            item["best_store"] = dict(best_store) if best_store else None
            # Estado unificado (substitui a antiga aba de alertas)
            if not item["active"]:
                item["state"] = "paused"
            elif item["max_price"] and lp is not None and lp <= float(item["max_price"]):
                item["state"] = "target_hit"
            elif item["max_price"]:
                item["state"] = "watching"
            else:
                item["state"] = "learning"
        return items


def catalog_summary():
    with _conn() as conn:
        return {
            "active": conn.execute("SELECT COUNT(*) FROM monitored_items WHERE active=1").fetchone()[0],
            "pending": conn.execute("SELECT COUNT(*) FROM posted WHERE status='pending' AND decision_source='catalog'").fetchone()[0],
            "archived": conn.execute("SELECT COUNT(*) FROM catalog_archives").fetchone()[0],
        }


def catalog_opportunity_reason(item, deal):
    if not item.get("active") or deal.get("origin") == "international":
        return None
    price = float(deal.get("price") or 0)
    target = float(item.get("max_price") or 0)
    if price <= 0:
        return None
    if target > 0:
        if price > target:
            return None
        return f"Preço-alvo atingido: R$ {price:.2f} até R$ {target:.2f}. Conferir frete e origem antes de publicar."
    evaluation = market_price_evaluation(deal["title"], price, deal["id"], item["id"])
    if deal.get("origin") == "national" and evaluation["confident"]:
        return evaluation["detail"]
    return None


def reconcile_catalog_queue():
    active_ids = {item["id"] for item in active_monitored_items()}
    with _conn() as conn:
        rows = [dict(r) for r in conn.execute("SELECT * FROM posted WHERE status='pending'")]
        archived = 0
        for row in rows:
            if row["product_id"].startswith("manual-") and row.get("decision_source") != "catalog":
                continue
            if row.get("decision_source") == "catalog" and row.get("monitored_item_id") in active_ids:
                continue
            reason = "Transição para catálogo autorizado; sem veredito humano ou penalidade de preço"
            conn.execute("INSERT OR IGNORE INTO catalog_archives(product_id,previous_status,reason) VALUES(?,?,?)",
                         (row["product_id"], row["status"], reason))
            conn.execute("UPDATE posted SET status='catalog_archived',decided_at=CURRENT_TIMESTAMP WHERE product_id=? AND status='pending'",
                         (row["product_id"],))
            archived += 1
    return archived


def frozen_until(hours):
    """{id da mini: até quando (UTC, 'AAAA-MM-DD HH:MM:SS')} das minis congeladas: foram para aprovação
    (ou tiveram decisão: publicada/ignorada) nas últimas N horas. Congeladas: o bot não busca nem reenvia."""
    if not hours or hours <= 0:
        return {}
    janela, soma = f"-{int(hours)} hours", f"+{int(hours)} hours"
    with _conn() as conn:
        rows = conn.execute(
            "SELECT id, datetime(MAX(t), ?) FROM ("
            " SELECT monitored_item_id AS id, last_notified_at AS t FROM catalog_opportunities"
            " UNION ALL SELECT monitored_item_id, posted_at FROM posted WHERE monitored_item_id IS NOT NULL"
            " UNION ALL SELECT monitored_item_id, decided_at FROM posted WHERE monitored_item_id IS NOT NULL AND decided_at IS NOT NULL"
            ") WHERE id IS NOT NULL AND t>=datetime('now',?) GROUP BY id", (soma, janela)).fetchall()
    return {r[0]: r[1] for r in rows}


def frozen_monitored_items(hours):
    return set(frozen_until(hours))


def enqueue_catalog_opportunity(item_id, deal):
    from core.filters import identifies_monitored
    item = get_monitored_item(item_id)
    if not item or not identifies_monitored(deal, item):
        return False
    reason = catalog_opportunity_reason(item, deal)
    if not reason:
        return False
    price = float(deal["price"])
    with _conn() as conn:
        conn.execute("BEGIN IMMEDIATE")
        current = conn.execute(
            "SELECT MIN(price) FROM posted WHERE status='pending' AND monitored_item_id=? AND decision_source='catalog'",
            (item_id,)).fetchone()[0]
        if current is not None and price >= current * 0.99:
            return False
        last = conn.execute("SELECT last_price FROM catalog_opportunities WHERE monitored_item_id=?", (item_id,)).fetchone()
        if current is None and last and price > last[0] * 0.97:
            return False
        count = conn.execute("SELECT COUNT(*) FROM posted WHERE status='pending' AND decision_source='catalog'").fetchone()[0]
        if current is None and count >= 20:
            return False
        conn.execute("UPDATE posted SET status='superseded',decided_at=CURRENT_TIMESTAMP WHERE status='pending' AND monitored_item_id=? AND product_id!=?",
                     (item_id, deal["id"]))
        conn.execute(
            "INSERT INTO posted(product_id,store,title,price,status,url,image,original_price,discount,monitored_item_id,decision_source,score_reasons) "
            "VALUES(?,?,?,?,'pending',?,?,?,?,?,'catalog',?) ON CONFLICT(product_id) DO UPDATE SET "
            "store=excluded.store,title=excluded.title,price=excluded.price,status='pending',url=excluded.url,image=excluded.image,"
            "original_price=excluded.original_price,discount=excluded.discount,monitored_item_id=excluded.monitored_item_id,"
            "decision_source='catalog',score_reasons=excluded.score_reasons,posted_at=CURRENT_TIMESTAMP,decided_at=NULL",
            (deal["id"], deal["store"], deal["title"], price, deal["url"], deal.get("image", ""),
             deal.get("original_price", price), deal.get("discount", 0), item_id, reason))
        conn.execute("UPDATE price_alerts SET triggered=1,current_price=?,triggered_at=CURRENT_TIMESTAMP "
                     "WHERE product_id=? AND store=? AND triggered=0 AND target_price>=?",
                     (price, deal["id"], deal["store"], price))
        conn.execute("INSERT INTO catalog_opportunities(monitored_item_id,last_price) VALUES(?,?) "
                     "ON CONFLICT(monitored_item_id) DO UPDATE SET last_price=excluded.last_price,last_notified_at=CURRENT_TIMESTAMP",
                     (item_id, price))
    return True


def normalize_tags(value):
    values = re.split(r"[,;\n]", value) if isinstance(value, str) else value
    if not isinstance(values, list) or any(not isinstance(tag, str) for tag in values):
        raise ValueError("Informe tags separadas por vírgula.")
    tags = list(dict.fromkeys(" ".join(unicodedata.normalize("NFKC", tag).split()).casefold() for tag in values if tag.strip()))
    if len(tags) > 20 or any(len(tag) > 50 for tag in tags):
        raise ValueError("Use até 20 tags por mini, com no máximo 50 caracteres cada.")
    return tags


def monitored_tags():
    with _conn() as conn:
        return sorted({tag for row in conn.execute("SELECT tags FROM monitored_items") for tag in json.loads(row["tags"])})


def normalize_term_list(raw):
    """"vermelho,  HTC66 ,," -> "vermelho, HTC66" (termos separados por vírgula)."""
    return ", ".join(t.strip() for t in str(raw or "").split(",") if t.strip())


def save_monitored_item(data, item_id=None):
    target = float(data.get("max_price") or 0)
    if not math.isfinite(target) or target < 0:
        raise ValueError("Informe um preço-alvo válido ou deixe em branco para aprender.")
    if not all(str(data.get(key, "")).strip() for key in ("name", "search_terms", "required_terms")):
        raise ValueError("Informe nome, busca e termos obrigatórios para identificar o produto autorizado.")
    duplicate = find_monitored_duplicate(data, exclude_id=item_id)
    if duplicate:
        raise ValueError(
            f'Já existe uma mini com nome ou busca equivalente: '
            f'"{duplicate["name"]}" (#{duplicate["id"]}). Edite-a em vez de duplicar.')
    values = (data["name"].strip(), data["search_terms"].strip(),
              data.get("required_terms", "").strip(), target,
              int(bool(data.get("active", True))))
    img = data.get("image", "").strip()
    tags = json.dumps(normalize_tags(data.get("tags", [])), ensure_ascii=False)
    with _conn() as conn:
        if item_id:
            if img:
                conn.execute(
                    "UPDATE monitored_items SET name=?,search_terms=?,required_terms=?,"
                    "max_price=?,active=?,image=? WHERE id=?", values + (img, item_id))
            else:
                conn.execute(
                    "UPDATE monitored_items SET name=?,search_terms=?,required_terms=?,"
                    "max_price=?,active=? WHERE id=?", values + (item_id,))
            if "tags" in data:
                conn.execute("UPDATE monitored_items SET tags=? WHERE id=?", (tags, item_id))
            if "forbidden_terms" in data:
                conn.execute("UPDATE monitored_items SET forbidden_terms=? WHERE id=?",
                             (normalize_term_list(data.get("forbidden_terms")), item_id))
            return item_id
        row_id = conn.execute(
            "INSERT INTO monitored_items "
            "(name,search_terms,required_terms,max_price,active,image) VALUES (?,?,?,?,?,?)",
            values + (img,)).lastrowid
        conn.execute("UPDATE monitored_items SET tags=?,forbidden_terms=? WHERE id=?",
                     (tags, normalize_term_list(data.get("forbidden_terms")), row_id))
        return row_id


def delete_monitored_item(item_id):
    with _conn() as conn:
        conn.execute("DELETE FROM monitored_items WHERE id=?", (item_id,))


def active_monitored_items():
    return [item for item in list_monitored_items() if item["active"]]


def get_monitored_item(item_id):
    with _conn() as conn:
        row = conn.execute(
            "SELECT * FROM monitored_items WHERE id=?", (item_id,)).fetchone()
        return dict(row) if row else None


def monitored_offer_excluded(item_id, deal):
    if not item_id or not deal.get("id"):
        return False
    with _conn() as conn:
        return bool(conn.execute("SELECT 1 FROM monitored_exclusions WHERE monitored_item_id=? AND product_id=? AND store=?", (item_id, deal["id"], deal.get("store", ""))).fetchone())


def excluded_observations(item_id):
    with _conn() as conn:
        return [dict(r) for r in conn.execute("SELECT p.* FROM price_observations p JOIN monitored_exclusions e ON e.monitored_item_id=p.monitored_item_id AND e.product_id=p.product_id AND e.store=p.store WHERE p.monitored_item_id=? AND p.id=(SELECT MAX(q.id) FROM price_observations q WHERE q.monitored_item_id=p.monitored_item_id AND q.product_id=p.product_id AND q.store=p.store) ORDER BY p.observed_at DESC", (item_id,))]


def curate_observation(item_id, observation_id, excluded):
    with _conn() as conn:
        row = conn.execute("SELECT * FROM price_observations WHERE id=? AND monitored_item_id=?", (observation_id, item_id)).fetchone()
        if not row:
            return False
        key = (item_id, row["product_id"], row["store"])
        if excluded:
            conn.execute("INSERT OR IGNORE INTO monitored_exclusions(monitored_item_id,product_id,store) VALUES(?,?,?)", key)
            conn.execute("UPDATE posted SET status='catalog_archived',decided_at=CURRENT_TIMESTAMP WHERE monitored_item_id=? AND product_id=? AND store=? AND status='pending'", key)
        else:
            conn.execute("DELETE FROM monitored_exclusions WHERE monitored_item_id=? AND product_id=? AND store=?", key)
        latest = conn.execute("SELECT * FROM valid_price_observations WHERE monitored_item_id=? ORDER BY observed_at DESC,id DESC LIMIT 1", (item_id,)).fetchone()
        lowest = conn.execute("SELECT * FROM valid_price_observations WHERE monitored_item_id=? ORDER BY price,observed_at LIMIT 1", (item_id,)).fetchone()
        conn.execute("UPDATE monitored_items SET last_seen_price=?,last_seen_at=?,all_time_min=?,all_time_min_at=?,image=? WHERE id=?", (latest["price"] if latest else None, latest["observed_at"] if latest else None, lowest["price"] if lowest else None, lowest["observed_at"] if lowest else None, latest["image"] if latest else "", item_id))
    return True


def record_price(item_id, deal):
    if monitored_offer_excluded(item_id, deal):
        return
    price = float(deal.get("price") or 0)
    if price <= 0:
        return
    with _conn() as conn:
        latest = conn.execute(
            "SELECT price FROM valid_price_observations WHERE monitored_item_id=? "
            "AND product_id=? AND store=? AND observed_at >= datetime('now','-6 hours') "
            "ORDER BY observed_at DESC LIMIT 1",
            (item_id, deal["id"], deal["store"])).fetchone()
        if latest and float(latest["price"]) == price:
            return
        conn.execute(
            "INSERT INTO price_observations "
            "(monitored_item_id,product_id,store,title,price,original_price,url,image) "
            "VALUES(?,?,?,?,?,?,?,?)",
            (item_id, deal["id"], deal["store"], deal["title"], price,
             deal.get("original_price"), deal.get("url", ""),
             deal.get("image", "")))
        img = deal.get("image", "")
        conn.execute(
            "UPDATE monitored_items SET last_seen_price=?,last_seen_at=CURRENT_TIMESTAMP,"
            "all_time_min=CASE WHEN all_time_min IS NULL OR ? < all_time_min THEN ? "
            "ELSE all_time_min END, all_time_min_at=CASE WHEN all_time_min IS NULL "
            "OR ? < all_time_min THEN CURRENT_TIMESTAMP ELSE all_time_min_at END,"
            "image=CASE WHEN ?!='' THEN ? ELSE image END WHERE id=?",
            (price, price, price, price, img, img, item_id))


def monitored_price_summary(item_id, days=90):
    with _conn() as conn:
        return dict(conn.execute(
            "SELECT MIN(price) min_price,MAX(price) max_price,AVG(price) avg_price,"
            "COUNT(*) observations,COUNT(DISTINCT product_id) products,"
            "COUNT(DISTINCT date(observed_at)) days,MIN(observed_at) first_seen,MAX(observed_at) last_seen "
            "FROM valid_price_observations WHERE monitored_item_id=? "
            "AND observed_at >= datetime('now', ?)",
            (item_id, f"-{int(days)} days")).fetchone())


def update_monitored_target(item_id, target):
    target = float(target or 0)
    if not math.isfinite(target) or target < 0:
        raise ValueError("Informe um alvo válido ou deixe em branco para aprender em silêncio.")
    with _conn() as conn:
        return bool(conn.execute("UPDATE monitored_items SET max_price=? WHERE id=?", (target, item_id)).rowcount)


def monitored_price_history(item_id, days=90):
    summary = monitored_price_summary(item_id, days)
    with _conn() as conn:
        daily = [dict(r) for r in conn.execute(
            "SELECT date(observed_at) day,MIN(price) min_price,"
            "MAX(price) max_price,AVG(price) avg_price "
            "FROM valid_price_observations WHERE monitored_item_id=? "
            "AND observed_at >= datetime('now', ?) GROUP BY date(observed_at) ORDER BY day",
            (item_id, f"-{int(days)} days"))]
        stores = [dict(r) for r in conn.execute(
            "SELECT store,MIN(price) min_price,MAX(price) max_price,AVG(price) avg_price,"
            "COUNT(*) observations FROM valid_price_observations WHERE monitored_item_id=? "
            "AND observed_at >= datetime('now', ?) GROUP BY store ORDER BY min_price",
            (item_id, f"-{int(days)} days"))]
        recent = [dict(r) for r in conn.execute(
            "SELECT * FROM valid_price_observations WHERE monitored_item_id=? "
            "ORDER BY observed_at DESC LIMIT 30", (item_id,))]
    return dict(summary), daily, stores, recent


def list_blacklist():
    with _conn() as conn:
        return [dict(r) for r in conn.execute(
            "SELECT * FROM blacklist ORDER BY active DESC, created_at DESC"
        )]


def add_blacklist(kind, value, label=""):
    value = value.strip().lower() if kind == "term" else value.strip()
    with _conn() as conn:
        conn.execute(
            "INSERT INTO blacklist(kind,value,label,active) VALUES(?,?,?,1) "
            "ON CONFLICT(kind,value) DO UPDATE SET active=1,label=excluded.label",
            (kind, value, label.strip()))


def set_blacklist_active(item_id, active):
    with _conn() as conn:
        conn.execute("UPDATE blacklist SET active=? WHERE id=?",
                     (int(bool(active)), item_id))


def delete_blacklist(item_id):
    with _conn() as conn:
        conn.execute("DELETE FROM blacklist WHERE id=?", (item_id,))


def is_blacklisted(deal):
    with _conn() as conn:
        rows = conn.execute(
            "SELECT kind,value FROM blacklist WHERE active=1"
        ).fetchall()
    title = deal.get("title", "").lower()
    return any((r["kind"] == "product" and r["value"] == deal.get("id")) or
               (r["kind"] == "term" and r["value"] in title) for r in rows)


def set_pending_target(product_id, target):
    """Ação "Caro" da Central: o alvo é gravado na mini monitorada de origem
    (única fonte de verdade) e a oferta sai da fila como 'price_alert'.
    Pendências manuais sem mini viram alerta legado, visível em Minis."""
    target = float(target)
    with _conn() as conn:
        row = conn.execute(
            "SELECT monitored_item_id,store,title,price,url,image FROM posted "
            "WHERE product_id=? AND status='pending'", (product_id,)).fetchone()
    if not row:
        return {"kind": "missing"}
    if row["monitored_item_id"]:
        update_monitored_target(row["monitored_item_id"], target)
        set_status(product_id, "price_alert")
        return {"kind": "monitored", "item_id": row["monitored_item_id"]}
    conn_insert = (
        "INSERT INTO price_alerts(product_id,title,store,target_price,"
        "current_price,url,image) VALUES(?,?,?,?,?,?,?)")
    with _conn() as conn:
        conn.execute(conn_insert, (product_id, row["title"], row["store"],
                                   target, row["price"], row["url"] or "",
                                   row["image"] or ""))
    set_status(product_id, "price_alert")
    return {"kind": "legacy"}


def _normalize_key(text):
    text = unicodedata.normalize("NFKD", (text or "").lower())
    text = "".join(c for c in text if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", " ", text)).strip()


def find_monitored_duplicate(data, exclude_id=None):
    """Retorna a mini já cadastrada com mesmo nome ou termo de busca
    (normalizados), ou None."""
    name_key = _normalize_key(data.get("name", ""))
    search_key = _normalize_key(data.get("search_terms", ""))
    with _conn() as conn:
        rows = conn.execute(
            "SELECT id,name,search_terms FROM monitored_items").fetchall()
    for row in rows:
        if exclude_id and row["id"] == exclude_id:
            continue
        if _normalize_key(row["name"]) == name_key or \
                _normalize_key(row["search_terms"]) == search_key:
            return dict(row)
    return None


def list_legacy_price_alerts():
    """Alertas antigos não vinculados a uma mini, deduplicados por título+loja."""
    with _conn() as conn:
        rows = [dict(r) for r in conn.execute(
            "SELECT * FROM price_alerts WHERE triggered=0 AND migrated=0 "
            "ORDER BY created_at DESC")]
    stop = {"miniatura","escala","carro","carrinho","carrinhos","diecast",
            "sortido","novo","original","licenciado","brinquedo","para","com",
            "mattel","oficial","team"}

    def words_of(title):
        key = _normalize_key(title)
        # sinônimos comuns em títulos de diecast
        key = re.sub(r"\bformula\s*1\b", "f1", key)
        words = set(key.split()) - {"1", "64", "164"}  # ruído de escala
        return key, words

    groups = []
    for alert in rows:
        key, words = words_of(alert["title"])
        match = None
        img = (alert.get("image") or "").strip()
        for g in groups:
            if img and g["image"] == img:
                match = g
                break
            common = words & g["words"]
            if words and len(common) / min(len(words), len(g["words"])) >= 0.65:
                match = g
                break
        if match:
            match["alert"]["duplicates"] += 1
            match["words"] |= words
        else:
            hint = [w for w in key.split() if len(w) > 3 and w not in stop]
            alert["duplicates"] = 1
            alert["search_hint"] = " ".join(hint[:6])
            groups.append({"words": set(words), "alert": alert, "image": img})
    return [g["alert"] for g in groups]


def delete_price_alert(alert_id):
    with _conn() as conn:
        conn.execute("DELETE FROM price_alerts WHERE id=?", (alert_id,))


def migrate_legacy_price_alerts():
    """Vincula alertas antigos à mini monitorada equivalente: o alvo passa a
    ser max_price quando a mini ainda não tem alvo próprio."""
    from core.filters import identifies_monitored
    items = active_monitored_items()
    migrated = 0
    with _conn() as conn:
        alerts = [dict(r) for r in conn.execute(
            "SELECT * FROM price_alerts WHERE triggered=0 AND migrated=0")]
        for alert in alerts:
            item = next((i for i in items if identifies_monitored(
                {"title": alert["title"], "store": alert["store"] or "",
                 "price": float(alert["current_price"] or 0)}, i)), None)
            if not item:
                continue
            if not float(item.get("max_price") or 0) > 0:
                conn.execute("UPDATE monitored_items SET max_price=? WHERE id=?",
                             (float(alert["target_price"]), item["id"]))
            conn.execute("UPDATE price_alerts SET migrated=1 WHERE id=?",
                         (alert["id"],))
            migrated += 1
    return migrated


def schedule_post(deal, scheduled_at):
    with _conn() as conn:
        return conn.execute(
            "INSERT INTO scheduled_posts(product_id,deal,scheduled_at) VALUES(?,?,?)",
            (deal.get("id"), json.dumps(deal, ensure_ascii=False), scheduled_at)).lastrowid


def list_scheduled_posts():
    with _conn() as conn:
        rows = conn.execute(
            "SELECT * FROM scheduled_posts ORDER BY "
            "CASE status WHEN 'scheduled' THEN 0 WHEN 'error' THEN 1 ELSE 2 END,"
            "scheduled_at DESC LIMIT 200").fetchall()
    result = []
    for row in rows:
        item = dict(row)
        item["deal"] = json.loads(item["deal"])
        result.append(item)
    return result


def due_scheduled_posts():
    with _conn() as conn:
        rows = conn.execute(
            "SELECT * FROM scheduled_posts WHERE status='scheduled' "
            "AND scheduled_at<=CURRENT_TIMESTAMP ORDER BY scheduled_at LIMIT 3").fetchall()
        return [dict(row) | {"deal": json.loads(row["deal"])} for row in rows]


def reschedule_post(item_id, scheduled_at):
    with _conn() as conn:
        conn.execute("UPDATE scheduled_posts SET scheduled_at=? WHERE id=?",
                     (scheduled_at, item_id))


def last_scheduled_publication():
    with _conn() as conn:
        row = conn.execute(
            "SELECT published_at FROM scheduled_posts WHERE status='published' "
            "ORDER BY published_at DESC LIMIT 1").fetchone()
        return row[0] if row else None


def set_scheduled_status(item_id, status, error=""):
    with _conn() as conn:
        conn.execute(
            "UPDATE scheduled_posts SET status=?,error=?,"
            "published_at=CASE WHEN ?='published' THEN CURRENT_TIMESTAMP ELSE published_at END "
            "WHERE id=?", (status, error[:500], status, item_id))


def create_blitz(payload: dict, run_at: str) -> int:
    with _conn() as conn:
        return conn.execute(
            "INSERT INTO coupon_blitzes(payload,run_at) VALUES(?,?)",
            (json.dumps(payload, ensure_ascii=False), run_at)).lastrowid


def due_blitzes():
    with _conn() as conn:
        rows = conn.execute(
            "SELECT * FROM coupon_blitzes WHERE status='scheduled' "
            "AND run_at<=CURRENT_TIMESTAMP ORDER BY run_at LIMIT 2").fetchall()
        return [dict(row) | {"payload": json.loads(row["payload"])} for row in rows]


def list_blitzes():
    with _conn() as conn:
        rows = conn.execute(
            "SELECT * FROM coupon_blitzes ORDER BY "
            "CASE status WHEN 'scheduled' THEN 0 WHEN 'running' THEN 1 "
            "WHEN 'error' THEN 2 ELSE 3 END, run_at DESC LIMIT 50").fetchall()
        return [dict(row) | {"payload": json.loads(row["payload"]),
                            "result": json.loads(row["result"]) if row["result"] else None}
                for row in rows]


def set_blitz_status(blitz_id, status, result=None, error=""):
    with _conn() as conn:
        conn.execute(
            "UPDATE coupon_blitzes SET status=?,result=?,error=?,"
            "executed_at=CASE WHEN ? IN ('done','error') THEN CURRENT_TIMESTAMP "
            "ELSE executed_at END WHERE id=?",
            (status, json.dumps(result, ensure_ascii=False) if result else None,
             error[:500], status, blitz_id))


def cancel_blitz(blitz_id):
    with _conn() as conn:
        conn.execute(
            "UPDATE coupon_blitzes SET status='cancelled' WHERE id=? AND status='scheduled'",
            (blitz_id,))


def pending_coupon_fields(product_id: str) -> dict:
    with _conn() as conn:
        row = conn.execute(
            "SELECT coupon_code,coupon_type,coupon_value,coupon_final_price "
            "FROM posted WHERE product_id=? AND status='pending'",
            (product_id,)).fetchone()
    if not row or not row["coupon_code"]:
        return {}
    return {"manual_coupon_code": row["coupon_code"],
            "manual_coupon_type": row["coupon_type"] or "percent",
            "manual_coupon_value": row["coupon_value"] or 0,
            "manual_coupon_final_price": row["coupon_final_price"] or 0}


def enqueue_coupon_deal(item_id, deal, coupon, note=""):
    item = get_monitored_item(item_id)
    if not item:
        return False
    price = float(deal["price"])
    final = float(coupon.get("manual_coupon_final_price") or 0)
    savings = max(0, price - final) if final else 0
    with _conn() as conn:
        conn.execute(
            "INSERT INTO posted(product_id,store,title,price,status,url,image,"
            "original_price,discount,monitored_item_id,decision_source,score_reasons,"
            "coupon_code,coupon_type,coupon_value,coupon_final_price,coupon_savings) "
            "VALUES(?,?,?,?,'pending',?,?,?,?,?,'coupon',?,?,?,?,?,?) "
            "ON CONFLICT(product_id) DO UPDATE SET "
            "store=excluded.store,title=excluded.title,price=excluded.price,"
            "status='pending',url=excluded.url,image=excluded.image,"
            "original_price=excluded.original_price,discount=excluded.discount,"
            "monitored_item_id=excluded.monitored_item_id,decision_source='coupon',"
            "score_reasons=excluded.score_reasons,coupon_code=excluded.coupon_code,"
            "coupon_type=excluded.coupon_type,coupon_value=excluded.coupon_value,"
            "coupon_final_price=excluded.coupon_final_price,"
            "coupon_savings=excluded.coupon_savings,"
            "posted_at=CURRENT_TIMESTAMP,decided_at=NULL",
            (deal["id"], deal["store"], deal["title"], price, deal["url"],
             deal.get("image", ""), deal.get("original_price", price),
             deal.get("discount", 0), item_id, note,
             coupon.get("manual_coupon_code", ""), coupon.get("manual_coupon_type", ""),
             float(coupon.get("manual_coupon_value") or 0), final, savings))
    return True


def cancel_scheduled_post(item_id):
    with _conn() as conn:
        row = conn.execute(
            "SELECT deal FROM scheduled_posts WHERE id=? AND status='scheduled'",
            (item_id,)).fetchone()
        if row:
            deal = json.loads(row["deal"])
            conn.execute("UPDATE scheduled_posts SET status='cancelled' WHERE id=?", (item_id,))
            if deal.get("_pending_id"):
                conn.execute("UPDATE posted SET status='pending' WHERE product_id=?",
                             (deal["_pending_id"],))


def get_setting(key, default=None):
    with _conn() as conn:
        row = conn.execute(
            "SELECT value FROM app_settings WHERE key=?", (key,)).fetchone()
    return json.loads(row["value"]) if row else default


def set_setting(key, value):
    with _conn() as conn:
        conn.execute(
            "INSERT INTO app_settings(key,value,updated_at) VALUES(?,?,CURRENT_TIMESTAMP) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value,"
            "updated_at=CURRENT_TIMESTAMP",
            (key, json.dumps(value, ensure_ascii=False)))


def set_system_state(key, value):
    serialized = json.dumps(value, ensure_ascii=False)
    with _conn() as conn:
        conn.execute(
            "INSERT INTO system_state(key,value,updated_at) VALUES(?,?,CURRENT_TIMESTAMP) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value,"
            "updated_at=CURRENT_TIMESTAMP", (key, serialized))


def get_system_state():
    with _conn() as conn:
        return {r["key"]: {"value": json.loads(r["value"]),
                            "updated_at": r["updated_at"]}
                for r in conn.execute("SELECT * FROM system_state")}


def update_store_health(store, status, offers=0, duration=0, error=""):
    with _conn() as conn:
        conn.execute(
            "INSERT INTO store_health(store,status,offers,duration,error,last_check) "
            "VALUES(?,?,?,?,?,CURRENT_TIMESTAMP) ON CONFLICT(store) DO UPDATE SET "
            "status=excluded.status,offers=excluded.offers,duration=excluded.duration,"
            "error=excluded.error,last_check=CURRENT_TIMESTAMP",
            (store, status, int(offers), float(duration), str(error)[:500]))


def list_store_health():
    with _conn() as conn:
        return [dict(r) for r in conn.execute(
            "SELECT * FROM store_health ORDER BY store")]


def create_job(action, payload):
    with _conn() as conn:
        if action == "share_pending":
            conn.execute("BEGIN IMMEDIATE")
            existing = conn.execute(
                "SELECT id FROM manual_jobs WHERE action='share_pending' "
                "AND status IN ('pending','processing') "
                "AND json_extract(payload,'$.product_id')=? ORDER BY id LIMIT 1",
                (payload["product_id"],)).fetchone()
            if existing:
                return existing["id"]
        return conn.execute(
            "INSERT INTO manual_jobs(action,payload) VALUES(?,?)",
            (action, json.dumps(payload, ensure_ascii=False))).lastrowid


def get_job(job_id):
    with _conn() as conn:
        row = conn.execute("SELECT * FROM manual_jobs WHERE id=?", (job_id,)).fetchone()
        if not row:
            return None
        data = dict(row)
        data["payload"] = json.loads(data["payload"])
        data["result"] = json.loads(data["result"]) if data["result"] else None
        return data


def release_interrupted_jobs():
    """Na partida do bot nenhum pedido pode estar em andamento: os que ficaram "processing" foram
    interrompidos pelo reinício (ex.: enviar-atualizacao no meio de uma pesquisa)."""
    with _conn() as conn:
        return conn.execute("UPDATE manual_jobs SET status='error',error='Interrompido pelo reinício do bot; peça de novo',"
                            "updated_at=CURRENT_TIMESTAMP WHERE status='processing'").rowcount


def cleanup_jobs():
    with _conn() as conn:
        conn.execute("UPDATE manual_jobs SET status='error',error='Tempo limite excedido' "
                     "WHERE status='processing' AND updated_at<datetime('now','-2 hours')")
        deleted = conn.execute("DELETE FROM manual_jobs WHERE status IN ('done','error') "
                               "AND updated_at<datetime('now','-7 days')").rowcount
    prune_product_prices()
    return deleted


def job_audit():
    with _conn() as conn:
        counts = {r[0]: r[1] for r in conn.execute(
            "SELECT status,COUNT(*) FROM manual_jobs GROUP BY status")}
        integrity = conn.execute("PRAGMA quick_check").fetchone()[0]
        errors = [dict(r) for r in conn.execute(
            "SELECT action,error,updated_at FROM manual_jobs WHERE status='error' "
            "ORDER BY updated_at DESC LIMIT 10")]
    return {"counts": counts, "integrity": integrity, "errors": errors}


def claim_jobs(urgent_only=False):
    cleanup_jobs()
    with _conn() as conn:
        conn.execute("BEGIN IMMEDIATE")
        restriction = " AND action IN ('restart_bot','share_pending','share_monitored','approve_pending','publish')" if urgent_only else ""
        rows = conn.execute(
            "SELECT * FROM manual_jobs WHERE status='pending'" + restriction +
            " ORDER BY CASE action WHEN 'restart_bot' THEN 0 WHEN 'share_pending' THEN 1 WHEN 'share_monitored' THEN 1 "
            "WHEN 'approve_pending' THEN 2 WHEN 'publish' THEN 2 ELSE 3 END,id LIMIT 1"
        ).fetchall()
        for row in rows:
            conn.execute(
                "UPDATE manual_jobs SET status='processing',updated_at=CURRENT_TIMESTAMP "
                "WHERE id=?", (row["id"],))
        return [dict(r) for r in rows]


def finish_job(job_id, result=None, error=None):
    with _conn() as conn:
        conn.execute(
            "UPDATE manual_jobs SET status=?,result=?,error=?,updated_at=CURRENT_TIMESTAMP "
            "WHERE id=?", ("error" if error else "done",
                            json.dumps(result, ensure_ascii=False) if result else None,
                            error, job_id))


_conn().close()


SITE_CATEGORIES = ("hot-wheels", "mini-gt", "pixar-cars", "lego", "funko", "blokees", "pokemon-tcg")


def set_monitored_site(item_id, enabled, category=""):
    """Marca/desmarca a mini para aparecer como achadinho no site."""
    category = (category or "").strip()
    if enabled and category not in SITE_CATEGORIES:
        raise ValueError("Escolha a categoria do site para mostrar a mini como achadinho.")
    with _conn() as conn:
        conn.execute(
            "UPDATE monitored_items SET site_enabled=?, site_category=?, "
            "site_added_at=CASE WHEN ?=1 AND site_added_at IS NULL THEN CURRENT_TIMESTAMP "
            "WHEN ?=0 THEN NULL ELSE site_added_at END WHERE id=?",
            (int(bool(enabled)), category if enabled else "", int(bool(enabled)),
             int(bool(enabled)), item_id))


def site_monitored_items():
    with _conn() as conn:
        return [dict(r) for r in conn.execute(
            "SELECT * FROM monitored_items WHERE site_enabled=1 AND active=1 ORDER BY id")]


def site_best_offer(item_id, hours=36):
    """Melhor oferta nacional recente (ML ou Amazon) de uma mini, para o site."""
    with _conn() as conn:
        row = conn.execute(
            "SELECT * FROM valid_price_observations WHERE monitored_item_id=? "
            "AND store IN ('Mercado Livre','Amazon') AND observed_at >= datetime('now', ?) "
            "ORDER BY price ASC, observed_at DESC LIMIT 1",
            (item_id, f"-{int(hours)} hours")).fetchone()
        return dict(row) if row else None


def site_daily_history(item_id, store, product_id, days=180):
    with _conn() as conn:
        return [dict(r) for r in conn.execute(
            "SELECT date(observed_at, '-3 hours') data, MIN(price) preco FROM valid_price_observations "
            "WHERE monitored_item_id=? AND store=? AND product_id=? AND observed_at >= datetime('now', ?) "
            "GROUP BY date(observed_at, '-3 hours') ORDER BY data",
            (item_id, store, product_id, f"-{int(days)} days"))]
