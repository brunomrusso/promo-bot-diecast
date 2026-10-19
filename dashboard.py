import hmac
import os
import time
from datetime import datetime, timezone
from functools import wraps
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

from flask import Flask, Response, flash, jsonify, redirect, render_template, request, session, url_for

import config
from core import backup, db, health

app = Flask(__name__)
app.secret_key = os.getenv("PANEL_SECRET_KEY", "change-this-key")
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SECURE=os.getenv("PANEL_HTTPS", "1") == "1",
    SESSION_COOKIE_SAMESITE="Lax",
)


@app.before_request
def protect_posts():
    if request.method == "POST" and session.get("authenticated"):
        origin = request.headers.get("Origin")
        if origin and urlparse(origin).netloc != request.host:
            return "Origem inválida", 403


@app.after_request
def security_headers(response):
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "same-origin"
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response


@app.context_processor
def runtime_context():
    indicator = health.bot_indicator()
    pending_count = 0
    active_alerts = 0
    try:
        with db._conn() as conn:
            row = conn.execute("SELECT COUNT(*) FROM posted WHERE status='pending'").fetchone()
            pending_count = row[0] if row else 0
            row2 = conn.execute("SELECT COUNT(*) FROM price_alerts WHERE triggered=0").fetchone()
            active_alerts = row2[0] if row2 else 0
    except Exception:
        pass
    return {"bot_indicator": indicator, "pending_count": pending_count,
            "active_alerts": active_alerts}


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("authenticated"):
            return redirect(url_for("login", next=request.path))
        return view(*args, **kwargs)
    return wrapped


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        valid_user = hmac.compare_digest(
            request.form.get("username", ""), os.getenv("PANEL_USERNAME", "admin"))
        valid_password = hmac.compare_digest(
            request.form.get("password", ""), os.getenv("PANEL_PASSWORD", ""))
        if valid_user and valid_password:
            session["authenticated"] = True
            return redirect(request.args.get("next") or url_for("index"))
        flash("Usuário ou senha inválidos", "error")
    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/")
@login_required
def index():
    with db._conn() as conn:
        stats = {
            "posted": conn.execute("SELECT COUNT(*) FROM posted WHERE status='posted'").fetchone()[0],
            "pending": conn.execute("SELECT COUNT(*) FROM posted WHERE status='pending'").fetchone()[0],
            "monitored": conn.execute("SELECT COUNT(*) FROM monitored_items WHERE active=1").fetchone()[0],
            "blocked": conn.execute("SELECT COUNT(*) FROM blacklist WHERE active=1").fetchone()[0],
            "alerts": conn.execute("SELECT COUNT(*) FROM price_alerts WHERE triggered=0").fetchone()[0],
            "scheduled": conn.execute("SELECT COUNT(*) FROM scheduled_posts WHERE status='scheduled'").fetchone()[0],
        }
        history = [dict(r) for r in conn.execute(
            "SELECT * FROM posted ORDER BY posted_at DESC LIMIT 12")]
    return render_template("index.html", stats=stats, history=history)


@app.get("/api/events")
@login_required
def sse_events():
    """Server-Sent Events: push pending count updates to dashboard."""
    def stream():
        last_count = -1
        while True:
            try:
                with db._conn() as conn:
                    pending = conn.execute(
                        "SELECT COUNT(*) FROM posted WHERE status='pending'"
                    ).fetchone()[0]
                if pending != last_count:
                    last_count = pending
                    yield f"data: {jsonify(pending=pending).get_data(as_text=True)}\n\n"
                time.sleep(10)
            except GeneratorExit:
                break
            except Exception:
                time.sleep(30)
    return Response(stream(), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.get("/go/<product_id>")
def click_redirect(product_id):
    with db._conn() as conn:
        row = conn.execute(
            "SELECT affiliate_url, url FROM posted WHERE product_id=?",
            (product_id,)).fetchone()
    if not row:
        return "Link não encontrado", 404
    dest = row["affiliate_url"] or row["url"]
    if not dest:
        return "Link não encontrado", 404
    db.record_click(product_id,
                    request.headers.get("Referer", ""),
                    request.headers.get("User-Agent", ""))
    return redirect(dest)


@app.get("/metrics")
@login_required
def metrics():
    days = request.args.get("days", 30, type=int)
    return render_template("metrics.html", metrics=db.metrics_summary(days if days in {7, 30, 90} else 30),
                           clicks=db.click_stats(days))


@app.get("/health")
@login_required
def system_health():
    return render_template("health.html", health=health.snapshot())


@app.post("/api/health/restart-bot")
@login_required
def api_restart_bot():
    job_id = db.create_job("restart_bot", {})
    return jsonify({"job_id": job_id})


@app.post("/api/health/backup")
@login_required
def api_create_backup():
    try:
        return jsonify(backup.create_backup())
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@app.route("/schedule", methods=["GET", "POST"])
@login_required
def publication_schedule():
    if request.method == "POST":
        db.set_setting("schedule", {
            "quiet_start": request.form.get("quiet_start", "23:00"),
            "quiet_end": request.form.get("quiet_end", "08:00"),
            "min_interval": request.form.get("min_interval", type=int) or 10,
            "timezone": "America/Sao_Paulo",
        })
        flash("Configuração da agenda salva", "success")
        return redirect(url_for("publication_schedule"))
    settings = db.get_setting("schedule", {
        "quiet_start": "23:00", "quiet_end": "08:00",
        "min_interval": 10, "timezone": "America/Sao_Paulo"})
    return render_template("schedule.html", items=db.list_scheduled_posts(), settings=settings)


@app.post("/api/schedule")
@login_required
def api_schedule_post():
    data = request.json or {}
    deal = data.get("deal")
    if data.get("pending_id"):
        pending = db.get_pending(data["pending_id"])
        if not pending:
            return jsonify({"error": "Oferta pendente não encontrada"}), 404
        store, title, price, url, image, original, discount = pending
        deal = {"id": data["pending_id"], "_pending_id": data["pending_id"],
                "store": store, "title": title, "price": price, "url": url,
                "image": image, "original_price": original, "discount": discount}
    if not deal or not data.get("scheduled_at"):
        return jsonify({"error": "Produto e horário são obrigatórios"}), 400
    try:
        local = datetime.fromisoformat(data["scheduled_at"]).replace(
            tzinfo=ZoneInfo("America/Sao_Paulo"))
        utc = local.astimezone(timezone.utc).replace(tzinfo=None)
    except ValueError:
        return jsonify({"error": "Data inválida"}), 400
    if utc <= datetime.utcnow():
        return jsonify({"error": "Escolha um horário futuro"}), 400
    item_id = db.schedule_post(deal, utc.isoformat(sep=" ", timespec="seconds"))
    if data.get("pending_id"):
        db.set_status(data["pending_id"], "scheduled")
    return jsonify({"scheduled_id": item_id})


@app.post("/schedule/<int:item_id>/cancel")
@login_required
def cancel_publication(item_id):
    db.cancel_scheduled_post(item_id)
    flash("Publicação cancelada", "success")
    return redirect(url_for("publication_schedule"))


@app.route("/manual")
@login_required
def manual():
    return render_template("manual.html")


@app.get("/approvals")
@login_required
def approval_center():
    items, stores = db.list_pending(
        request.args.get("store", ""), request.args.get("q", ""),
        request.args.get("sort", "discount_desc"))
    quality = request.args.get("quality", "")
    if quality:
        items = [item for item in items if item["quality"]["key"] == quality]
    total = len(items)
    per_page = 24
    pages = max(1, (total + per_page - 1) // per_page)
    page = min(max(1, request.args.get("page", 1, type=int)), pages)
    items = items[(page - 1) * per_page:page * per_page]
    return render_template("approvals.html", items=items, stores=stores,
                           expiry_hours=db.get_setting("approval_expiry_hours", 24),
                           total=total, page=page, pages=pages)


@app.post("/api/approvals/action")
@login_required
def api_approval_action():
    data = request.json or {}
    ids = [str(item) for item in data.get("ids", []) if item]
    action = data.get("action")
    if not ids or action not in {"approve", "reject", "block_product", "block_title"}:
        return jsonify({"error": "Ação inválida"}), 400
    jobs = []
    for product_id in ids:
        pending = db.get_pending(product_id)
        if not pending:
            continue
        store, title, price, url, image, original, discount = pending
        if action == "approve":
            jobs.append(db.create_job("approve_pending", {
                "product_id": product_id,
                "coupon": data.get("coupon", {}) if len(ids) == 1 else {},
            }))
        elif action == "reject":
            db.set_status(product_id, "rejected")
        elif action == "block_product":
            db.add_blacklist("product", product_id, title)
            db.set_status(product_id, "blacklisted")
        elif action == "block_title":
            db.add_blacklist("term", title, title)
            db.set_status(product_id, "blacklisted")
    return jsonify({"jobs": jobs, "processed": len(ids)})


@app.post("/api/price-alert")
@login_required
def api_create_price_alert():
    data = request.json or {}
    required = ["product_id", "title", "store", "target_price", "current_price"]
    if any(not data.get(f) for f in required):
        return jsonify({"error": "Dados incompletos"}), 400
    try:
        target = float(data["target_price"])
        current = float(data["current_price"])
        if target <= 0 or target >= current:
            return jsonify({"error": "O preço-alvo deve ser menor que o preço atual"}), 400
    except (ValueError, TypeError):
        return jsonify({"error": "Preço inválido"}), 400
    db.create_price_alert(
        data["product_id"], data["title"], data["store"],
        target, current, data.get("url", ""), data.get("image", ""))
    # Reject the pending offer so it leaves the approval queue
    db.set_status(data["product_id"], "price_alert")
    return jsonify({"ok": True})


@app.post("/api/blacklist")
@login_required
def api_add_blacklist():
    data = request.json or {}
    kind = data.get("kind", "term")
    value = data.get("value", "").strip()
    label = data.get("label", "")
    if not value:
        return jsonify({"error": "Valor obrigatório"}), 400
    db.add_blacklist(kind, value, label)
    return jsonify({"ok": True})


@app.get("/price-alerts")
@login_required
def price_alerts_page():
    return render_template("price_alerts.html",
                           alerts=db.list_price_alerts(active_only=False))


@app.post("/price-alerts/<int:alert_id>/delete")
@login_required
def price_alert_delete(alert_id):
    db.delete_price_alert(alert_id)
    flash("Alerta removido", "success")
    return redirect(url_for("price_alerts_page"))


@app.post("/api/extract")
@login_required
def api_extract():
    url = request.json.get("url", "").strip()
    if not url.startswith(("http://", "https://")):
        return jsonify({"error": "Informe um link válido"}), 400
    maintenance = db.get_system_state().get("ml_maintenance", {}).get("value")
    if "mercadolivre" in url and maintenance:
        return jsonify({"error": "Finalize a verificação do Mercado Livre antes de buscar produtos."}), 409
    if not health.bot_indicator()["online"]:
        return jsonify({"error": "O bot está parado e não pode processar a busca agora."}), 503
    return jsonify({"job_id": db.create_job("extract", {"url": url})})


@app.post("/api/publish")
@login_required
def api_publish():
    deal = request.json.get("deal", {})
    required = ["id", "store", "title", "url"]
    if any(not deal.get(field) for field in required):
        return jsonify({"error": "Preencha os dados obrigatórios"}), 400
    for field in ["price", "original_price", "discount",
                  "manual_coupon_value", "manual_coupon_min_purchase",
                  "manual_coupon_max_discount", "manual_coupon_final_price"]:
        if field in deal:
            deal[field] = float(deal.get(field) or 0)
    deal["discount"] = int(deal["discount"])
    return jsonify({"job_id": db.create_job("publish", {"deal": deal})})


@app.post("/api/monitored/<int:item_id>/scan")
@login_required
def api_monitored_scan(item_id):
    if not db.get_monitored_item(item_id):
        return jsonify({"error": "Mini não encontrada"}), 404
    return jsonify({"job_id": db.create_job(
        "scan_monitored", {"item_id": item_id})})


@app.get("/api/jobs/<int:job_id>")
@login_required
def api_job(job_id):
    job = db.get_job(job_id)
    return jsonify(job or {"error": "Tarefa não encontrada"}), 200 if job else 404


@app.route("/monitored", methods=["GET", "POST"])
@login_required
def monitored():
    if request.method == "POST":
        item_id = request.form.get("id", type=int)
        saved_id = db.save_monitored_item({
            "name": request.form["name"],
            "search_terms": request.form["search_terms"],
            "required_terms": request.form.get("required_terms", ""),
            "max_price": request.form["max_price"],
            "active": request.form.get("active") == "on",
            "image": request.form.get("image", ""),
        }, item_id)
        observed_price = request.form.get("observed_price", type=float)
        if not item_id and observed_price and request.form.get("product_id"):
            db.record_price(saved_id, {
                "id": request.form["product_id"],
                "store": request.form.get("store", "Manual"),
                "title": request.form["name"],
                "price": observed_price,
                "original_price": observed_price,
                "url": request.form.get("source_url", ""),
                "image": request.form.get("image", ""),
            })
        flash("Mini salva com sucesso", "success")
        return redirect(url_for("monitored"))
    return render_template("monitored.html", items=db.list_monitored_items())


@app.get("/monitored/<int:item_id>")
@login_required
def monitored_detail(item_id):
    item = db.get_monitored_item(item_id)
    if not item:
        return "Mini não encontrada", 404
    summary, daily, stores, recent = db.monitored_price_history(item_id)
    return render_template("monitored_detail.html", item=item, summary=summary,
                           daily=daily, stores=stores, recent=recent)


@app.post("/monitored/<int:item_id>/delete")
@login_required
def monitored_delete(item_id):
    db.delete_monitored_item(item_id)
    flash("Mini removida", "success")
    return redirect(url_for("monitored"))


@app.route("/search-settings", methods=["GET", "POST"])
@login_required
def search_settings():
    if request.method == "POST":
        def lines(name):
            return list(dict.fromkeys(
                line.strip().lower() for line in request.form.get(name, "").splitlines()
                if line.strip() and not line.strip().startswith("#")))
        enabled = request.form.getlist("enabled_stores")
        if not enabled:
            flash("Mantenha pelo menos uma loja habilitada", "error")
            return redirect(url_for("search_settings"))
        for key in ["keywords", "relevant_terms", "blocklist_terms", "lego_car_terms"]:
            values = lines(key)
            if not values:
                flash(f"A lista {key} não pode ficar vazia", "error")
                return redirect(url_for("search_settings"))
            db.set_setting(key, values)
        db.set_setting("enabled_stores", enabled)
        db.set_setting("approval_expiry_hours", max(1, request.form.get(
            "approval_expiry_hours", 24, type=int)))
        config.clear_dynamic_cache()
        flash("Configurações atualizadas; o próximo ciclo já usará as mudanças", "success")
        return redirect(url_for("search_settings"))
    return render_template(
        "search_settings.html",
        keywords=config.load_keywords(), relevant_terms=config.load_relevant_terms(),
        blocklist_terms=config.load_blocklist_terms(),
        lego_car_terms=config.load_lego_car_terms(),
        enabled_stores=config.load_enabled_stores(),
        approval_expiry_hours=db.get_setting("approval_expiry_hours", 24))


@app.route("/brand-rules", methods=["GET", "POST"])
@login_required
def brand_rules():
    if request.method == "POST":
        mode = request.form.get("approval_mode", "manual")
        if mode not in {"manual", "auto", "threshold"}:
            return "Modo de aprovação inválido", 400
        db.save_brand_rule({
            "name": request.form["name"],
            "match_terms": request.form["match_terms"],
            "min_discount": request.form.get("min_discount", 0),
            "approval_mode": mode,
            "auto_approve_discount": request.form.get("auto_approve_discount", 40),
            "daily_limit": request.form.get("daily_limit", 10),
            "priority": request.form.get("priority", 0),
            "active": request.form.get("active") == "on",
        }, request.form.get("id", type=int))
        flash("Regra salva com sucesso", "success")
        return redirect(url_for("brand_rules"))
    rules = db.list_brand_rules()
    for rule in rules:
        rule["today_count"] = db.brand_daily_count(rule["id"])
    return render_template("brand_rules.html", rules=rules)


@app.post("/brand-rules/<int:rule_id>/delete")
@login_required
def brand_rule_delete(rule_id):
    db.delete_brand_rule(rule_id)
    flash("Regra removida", "success")
    return redirect(url_for("brand_rules"))


@app.route("/blacklist", methods=["GET", "POST"])
@login_required
def blacklist():
    if request.method == "POST":
        db.add_blacklist(request.form["kind"], request.form["value"],
                         request.form.get("label", ""))
        flash("Bloqueio adicionado", "success")
        return redirect(url_for("blacklist"))
    return render_template("blacklist.html", items=db.list_blacklist())


@app.post("/blacklist/<int:item_id>/toggle")
@login_required
def blacklist_toggle(item_id):
    db.set_blacklist_active(item_id, request.form.get("active") == "1")
    return redirect(url_for("blacklist"))


@app.post("/blacklist/<int:item_id>/delete")
@login_required
def blacklist_delete(item_id):
    db.delete_blacklist(item_id)
    flash("Bloqueio removido", "success")
    return redirect(url_for("blacklist"))


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=8080)
