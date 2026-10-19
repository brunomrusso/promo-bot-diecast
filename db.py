import json
import re
import sqlite3
import unicodedata
from pathlib import Path

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
                     ("coupon_savings", "REAL"), ("affiliate_url", "TEXT")]: 
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
    monitored_cols = {r[1] for r in conn.execute("PRAGMA table_info(monitored_items)")}
    for col, typ in [("all_time_min", "REAL"),
                     ("all_time_min_at", "TIMESTAMP"),
                     ("last_seen_price", "REAL"),
                     ("last_seen_at", "TIMESTAMP"),
                     ("image", "TEXT")]:
        if col not in monitored_cols:
            conn.execute(f"ALTER TABLE monitored_items ADD COLUMN {col} {typ}")
    conn.execute(
        "CREATE TABLE IF NOT EXISTS price_observations ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, monitored_item_id INTEGER NOT NULL, "
        "product_id TEXT NOT NULL, store TEXT NOT NULL, title TEXT NOT NULL, "
        "price REAL NOT NULL, original_price REAL, url TEXT, image TEXT, "
        "observed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, "
        "FOREIGN KEY(monitored_item_id) REFERENCES monitored_items(id) ON DELETE CASCADE)"
    )
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
                brand_rule_id=None, brand_name=""):
    with _conn() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO posted "
            "(product_id, store, title, price, status, url, image, "
            "original_price, discount, brand_rule_id, brand_name) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (product_id, store, title, price, status, url, image,
             original_price, discount, brand_rule_id, brand_name),
        )


def set_status(product_id: str, status: str, brand_rule_id=None, brand_name=""):
    with _conn() as conn:
        if brand_rule_id is not None:
            conn.execute(
                "UPDATE posted SET status=?,brand_rule_id=?,brand_name=? "
                "WHERE product_id=?",
                (status, brand_rule_id, brand_name, product_id))
        else:
            conn.execute("UPDATE posted SET status=? WHERE product_id=?",
                         (status, product_id))


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
        conn.execute(
            "UPDATE posted SET status='expired' WHERE status='pending' "
            "AND posted_at < datetime('now', ?)", (f"-{hours} hours",))
    return hours


def get_pending(product_id: str):
    expire_pending()
    with _conn() as conn:
        row = conn.execute(
            "SELECT store,title,price,url,image,original_price,discount "
            "FROM posted WHERE product_id=? AND status='pending'",
            (product_id,),
        ).fetchone()
        return tuple(row) if row else None


def list_pending(store="", search="", sort="discount_desc"):
    expire_pending()
    order = {
        "discount_desc": "discount DESC, posted_at DESC",
        "price_asc": "price ASC, posted_at DESC",
        "newest": "posted_at DESC",
        "oldest": "posted_at ASC",
    }.get(sort, "discount DESC, posted_at DESC")
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
    groups = {}
    for item in items:
        item["quality"] = deal_price_quality(item["title"], item["price"])
        item["group_key"] = product_group_key(
            item["title"], item.get("brand_name", ""),
            item["quality"].get("monitored_item_id"))
        groups.setdefault(item["group_key"], []).append(item)
    for group in groups.values():
        valid_prices = [float(item["price"]) for item in group if item.get("price")]
        minimum = min(valid_prices) if valid_prices else 0
        for item in group:
            item["comparison"] = {
                "count": len(group), "stores": len(set(row["store"] for row in group)),
                "min_price": minimum, "best": bool(minimum and item["price"] == minimum),
            }
    return items, stores


def product_group_key(title, brand_name="", monitored_item_id=None):
    if monitored_item_id:
        return f"monitored:{monitored_item_id}"
    normalized = unicodedata.normalize("NFKD", title.lower()).encode("ascii", "ignore").decode()
    tokens = re.findall(r"[a-z0-9]+", normalized)
    ignored = {"de", "da", "do", "das", "dos", "com", "para", "por", "em", "e",
               "miniatura", "carrinho", "colecionavel", "novo", "original", "mattel",
               "escala", "diecast", "carro", "veiculo", "unidade", "hot", "wheels"}
    useful = sorted(set(token for token in tokens if token not in ignored and len(token) > 1))[:10]
    prefix = brand_name.lower().replace(" ", "-") if brand_name else "produto"
    return prefix + ":" + "-".join(useful)


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
            if required and all(term in title_lower for term in required):
                matches.append((len(required), candidate))
        if not matches:
            return {"key": "untracked", "label": "Sem histórico",
                    "detail": "Esta oferta não corresponde a uma mini monitorada"}
        item = max(matches, key=lambda match: match[0])[1]
        summary = conn.execute(
            "SELECT MIN(price) min_price,AVG(price) avg_price,COUNT(*) observations "
            "FROM price_observations WHERE monitored_item_id=? "
            "AND observed_at >= datetime('now','-90 days')", (item["id"],)
        ).fetchone()
    quality = classify_price(float(price or 0), summary["min_price"],
                             summary["avg_price"], summary["observations"],
                             item["all_time_min"])
    quality.update({
        "monitored_item_id": item["id"], "monitored_name": item["name"],
        "min_price": summary["min_price"], "avg_price": summary["avg_price"],
        "observations": summary["observations"],
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
    return {"totals": totals, "daily": daily, "stores": stores, "brands": brands,
            "coupons": coupons, "coupon_totals": coupon_totals, "days": days}


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
        return [dict(r) for r in conn.execute(
            "SELECT * FROM monitored_items ORDER BY active DESC, name"
        )]


def save_monitored_item(data, item_id=None):
    values = (data["name"].strip(), data["search_terms"].strip(),
              data.get("required_terms", "").strip(), float(data["max_price"]),
              int(bool(data.get("active", True))))
    img = data.get("image", "").strip()
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
            return item_id
        row_id = conn.execute(
            "INSERT INTO monitored_items "
            "(name,search_terms,required_terms,max_price,active,image) VALUES (?,?,?,?,?,?)",
            values + (img,)).lastrowid
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


def record_price(item_id, deal):
    price = float(deal.get("price") or 0)
    if price <= 0:
        return
    with _conn() as conn:
        latest = conn.execute(
            "SELECT price FROM price_observations WHERE monitored_item_id=? "
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


def monitored_price_history(item_id, days=90):
    with _conn() as conn:
        summary = conn.execute(
            "SELECT MIN(price) min_price,MAX(price) max_price,AVG(price) avg_price,"
            "COUNT(*) observations,COUNT(DISTINCT product_id) products "
            "FROM price_observations WHERE monitored_item_id=? "
            "AND observed_at >= datetime('now', ?)",
            (item_id, f"-{int(days)} days")).fetchone()
        daily = [dict(r) for r in conn.execute(
            "SELECT date(observed_at) day,MIN(price) min_price,"
            "MAX(price) max_price,AVG(price) avg_price "
            "FROM price_observations WHERE monitored_item_id=? "
            "AND observed_at >= datetime('now', ?) GROUP BY date(observed_at) ORDER BY day",
            (item_id, f"-{int(days)} days"))]
        stores = [dict(r) for r in conn.execute(
            "SELECT store,MIN(price) min_price,MAX(price) max_price,AVG(price) avg_price,"
            "COUNT(*) observations FROM price_observations WHERE monitored_item_id=? "
            "AND observed_at >= datetime('now', ?) GROUP BY store ORDER BY min_price",
            (item_id, f"-{int(days)} days"))]
        recent = [dict(r) for r in conn.execute(
            "SELECT * FROM price_observations WHERE monitored_item_id=? "
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


def create_price_alert(product_id, title, store, target_price, current_price,
                       url="", image=""):
    with _conn() as conn:
        conn.execute(
            "INSERT INTO price_alerts(product_id,title,store,target_price,"
            "current_price,url,image) VALUES(?,?,?,?,?,?,?)",
            (product_id, title, store, float(target_price),
             float(current_price), url, image))


def list_price_alerts(active_only=True):
    with _conn() as conn:
        if active_only:
            return [dict(r) for r in conn.execute(
                "SELECT * FROM price_alerts WHERE triggered=0 "
                "ORDER BY created_at DESC")]
        return [dict(r) for r in conn.execute(
            "SELECT * FROM price_alerts ORDER BY triggered, created_at DESC")]


def delete_price_alert(alert_id):
    with _conn() as conn:
        conn.execute("DELETE FROM price_alerts WHERE id=?", (alert_id,))


def check_price_alerts(title, price, store):
    """Check if a deal matches an active price alert and the price is at/below target.
    Returns the alert if triggered, None otherwise."""
    title_lower = title.lower()
    for alert in list_price_alerts(active_only=True):
        alert_title = alert["title"].lower()
        # Match by significant words overlap
        alert_words = set(re.findall(r'[a-z0-9]+', alert_title))
        deal_words = set(re.findall(r'[a-z0-9]+', title_lower))
        common = alert_words & deal_words
        # Need at least 60% of alert words to match
        if len(alert_words) > 0 and len(common) / len(alert_words) >= 0.6:
            if float(price) <= alert["target_price"]:
                with _conn() as conn:
                    conn.execute(
                        "UPDATE price_alerts SET triggered=1,"
                        "triggered_at=CURRENT_TIMESTAMP WHERE id=?",
                        (alert["id"],))
                return alert
    return None


def is_price_above_alert(title, price):
    """Check if a product has an active alert but the price is still above target.
    Returns True if the product should be skipped (price too high)."""
    title_lower = title.lower()
    for alert in list_price_alerts(active_only=True):
        alert_title = alert["title"].lower()
        alert_words = set(re.findall(r'[a-z0-9]+', alert_title))
        deal_words = set(re.findall(r'[a-z0-9]+', title_lower))
        common = alert_words & deal_words
        if len(alert_words) > 0 and len(common) / len(alert_words) >= 0.6:
            if float(price) > alert["target_price"]:
                return True
    return False


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


def cleanup_jobs():
    with _conn() as conn:
        conn.execute("UPDATE manual_jobs SET status='error',error='Tempo limite excedido' "
                     "WHERE status='processing' AND updated_at<datetime('now','-2 hours')")
        deleted = conn.execute("DELETE FROM manual_jobs WHERE status IN ('done','error') "
                               "AND updated_at<datetime('now','-7 days')").rowcount
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


def claim_jobs():
    cleanup_jobs()
    with _conn() as conn:
        restart = conn.execute(
            "SELECT * FROM manual_jobs WHERE status='pending' "
            "AND action='restart_bot' ORDER BY id LIMIT 1").fetchone()
        rows = [restart] if restart else conn.execute(
            "SELECT * FROM manual_jobs WHERE status='pending' ORDER BY id LIMIT 5"
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
