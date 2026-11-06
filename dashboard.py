import hmac
import os
import re
from datetime import datetime, timezone
from functools import wraps
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

from flask import Flask, flash, jsonify, redirect, render_template, request, session, url_for

import config
from core import backup, db, health

CHANNEL_PROMOTION_DEFAULT = """**Quem coleciona sabe: encontrar a mini certa por um preço bom faz parte da diversão.**

Estou reunindo achados e ofertas de **Hot Wheels, Mini GT, Kaido House, Disney/Pixar Cars e outras miniaturas** em canais no Telegram e no WhatsApp.

A ideia é facilitar a vida de quem quer aumentar a coleção sem precisar ficar procurando em várias lojas. Compartilho ofertas selecionadas e acompanho preços para ajudar a identificar boas oportunidades.

Se quiser acompanhar, escolha a plataforma que preferir:

**Telegram:** https://t.me/promocoes_diecast
**WhatsApp:** https://chat.whatsapp.com/HHMNjLKePG3AWpLT6CDfm6

Os canais são gratuitos. Preços e estoques podem mudar.

**Qual mini você está procurando para a sua coleção?**"""

app = Flask(__name__)
app.secret_key = os.getenv("PANEL_SECRET_KEY", "change-this-key")
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SECURE=os.getenv("PANEL_HTTPS", "1") == "1",
    SESSION_COOKIE_SAMESITE="Lax",
)


@app.template_filter("sp_datetime")
def sp_datetime(value):
    if not value:
        return "—"
    try:
        parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(ZoneInfo("America/Sao_Paulo")).strftime("%d/%m/%Y %H:%M:%S")
    except (ValueError, TypeError):
        return "—"


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
            row2 = conn.execute("SELECT COUNT(*) FROM monitored_items WHERE active=1 AND max_price>0").fetchone()
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
            "alerts": conn.execute("SELECT COUNT(*) FROM monitored_items WHERE active=1 AND max_price>0").fetchone()[0],
            "scheduled": conn.execute("SELECT COUNT(*) FROM scheduled_posts WHERE status='scheduled'").fetchone()[0],
        }
        history = [dict(r) for r in conn.execute(
            "SELECT * FROM posted ORDER BY posted_at DESC LIMIT 12")]
    return render_template("index.html", stats=stats, history=history)


@app.get("/api/pending-count")
@login_required
def pending_count_api():
    """Lightweight polling endpoint for real-time badge updates."""
    with db._conn() as conn:
        pending = conn.execute(
            "SELECT COUNT(*) FROM posted WHERE status='pending'"
        ).fetchone()[0]
    return jsonify(pending=pending)


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


@app.get("/cupom-relampago")
@login_required
def coupon_blitz():
    items = db.list_monitored_items()
    return render_template("coupon_blitz.html", items=items,
                           blitzes=db.list_blitzes())


@app.post("/api/coupon-blitz")
@login_required
def api_coupon_blitz():
    data = request.json or {}
    code = str(data.get("code", "")).strip().upper()
    try:
        value = float(data.get("value") or 0)
        cap = float(data.get("cap") or 0)
        min_purchase = float(data.get("min_purchase") or 0)
    except (TypeError, ValueError):
        return jsonify({"error": "Desconto, teto e compra mínima precisam ser números"}), 400
    item_ids = [int(i) for i in data.get("item_ids", []) if str(i).isdigit()]
    if not code or value <= 0 or not item_ids:
        return jsonify({"error": "Informe o código, o desconto e pelo menos uma mini"}), 400
    run_at = str(data.get("run_at", "")).strip()
    if run_at:
        try:
            local = datetime.fromisoformat(run_at).replace(
                tzinfo=ZoneInfo("America/Sao_Paulo"))
            utc = local.astimezone(timezone.utc).replace(tzinfo=None)
        except ValueError:
            return jsonify({"error": "Data/hora inválida"}), 400
        if utc <= datetime.utcnow():
            return jsonify({"error": "Escolha um horário futuro ou deixe vazio para rodar agora"}), 400
    else:
        utc = datetime.utcnow()
    blitz_id = db.create_blitz({
        "code": code, "kind": data.get("kind", "percent"), "value": value,
        "cap": cap, "min_purchase": min_purchase,
        "store": data.get("store") or "Mercado Livre", "item_ids": item_ids,
    }, utc.isoformat(sep=" ", timespec="seconds"))
    return jsonify({"blitz_id": blitz_id})


@app.post("/cupom-relampago/<int:blitz_id>/cancel")
@login_required
def coupon_blitz_cancel(blitz_id):
    db.cancel_blitz(blitz_id)
    flash("Disparo de cupom cancelado", "success")
    return redirect(url_for("coupon_blitz"))


@app.get("/approvals")
@login_required
def approval_center():
    items, stores = db.list_pending(
        request.args.get("store", ""), request.args.get("q", ""),
        request.args.get("sort", "newest"))
    quality = request.args.get("quality", "")
    if quality:
        items = [item for item in items if item["quality"]["key"] == quality]
    total = len(items)
    per_page = 24
    pages = max(1, (total + per_page - 1) // per_page)
    page = min(max(1, request.args.get("page", 1, type=int)), pages)
    items = items[(page - 1) * per_page:page * per_page]
    from core.affiliate import cached_affiliate_url
    for item in items:
        item["share_link_ready"] = bool(item.get("url") and cached_affiliate_url(item))
    return render_template("approvals.html", items=items, stores=stores,
                           decisions=db.list_decisions(), catalog=db.catalog_summary(),
                           expiry_hours=db.get_setting("approval_expiry_hours", 24),
                           total=total, page=page, pages=pages)


@app.post("/api/decisions/<path:product_id>/restore")
@login_required
def api_restore_decision(product_id):
    if not db.restore_decision(product_id):
        return jsonify({"error": "Não foi possível restaurar: autorize o produto no catálogo e verifique se já há oportunidade pendente ou se a fila atingiu 20 itens."}), 409
    pending = bool(db.get_pending(product_id))
    message = ("Oferta restaurada para revisão. Recarregue a página." if pending else
               "Veredito desfeito sem penalidade. O produto continua fora da fila; autorize-o no catálogo para monitorar.")
    return jsonify({"ok": True, "pending": pending, "message": message})


@app.post("/api/approvals/share")
@login_required
def approval_share():
    from core.affiliate import cached_affiliate_url
    from core.notifier import format_whatsapp

    product_id = str((request.json or {}).get("product_id", ""))
    pending = db.get_pending(product_id)
    if not pending:
        return jsonify({"error": "Oferta pendente não encontrada"}), 404
    store, title, price, url, image, original, discount = pending
    deal = {"id": product_id, "store": store, "title": title, "price": price,
            "url": url, "image": image, "original_price": original, "discount": discount}
    link = cached_affiliate_url(deal)
    if link:
        return jsonify({"result": {"whatsapp": format_whatsapp(deal, link),
                                   "affiliate_url": link}, "cached": True})
    if not health.bot_indicator()["online"]:
        return jsonify({"error": "O bot precisa estar ativo para gerar o link monetizado"}), 503
    return jsonify({"job_id": db.create_job("share_pending", {"product_id": product_id})})


@app.get("/api/approvals/<path:product_id>/image")
@login_required
def approval_image(product_id):
    pending = db.get_pending(product_id)
    if not pending or not pending[4]:
        return jsonify({"error": "Imagem não disponível"}), 404
    return _product_image(pending[4])


@app.post("/api/manual/share")
@login_required
def manual_share():
    from math import isfinite
    from core.affiliate import cached_affiliate_url, is_monetized
    from core.manual_jobs import normalize_manual_coupon
    from core.notifier import format_whatsapp

    data = request.json or {}
    deal = data.get("deal")
    if not isinstance(deal, dict) or any(not isinstance(deal.get(key), str) or not deal[key].strip()
                                         for key in ("id", "store", "title", "url")):
        return jsonify({"error": "Busque e preencha os dados do produto antes de compartilhar"}), 400
    try:
        for key in ("price", "original_price", "discount"):
            deal[key] = float(deal.get(key) or 0)
            if not isfinite(deal[key]) or deal[key] < 0:
                raise ValueError("Preço ou desconto inválido")
        if deal["price"] <= 0:
            raise ValueError("Informe um preço válido")
        deal = normalize_manual_coupon(deal)
    except (ValueError, TypeError) as exc:
        return jsonify({"error": str(exc)}), 400
    link = deal.get("affiliate_url", "")
    if not isinstance(link, str) or not is_monetized(link, deal["store"]):
        link = cached_affiliate_url(deal)
    if not link:
        return jsonify({"error": "Busque o produto novamente para gerar um link monetizado"}), 400
    text = data.get("text", "").strip() if isinstance(data.get("text", ""), str) else ""
    text = text or format_whatsapp(deal, link)
    if len(text) > 20000 or link not in text:
        return jsonify({"error": "O texto para WhatsApp precisa conter o link monetizado validado"}), 400
    return jsonify({"whatsapp": text, "affiliate_url": link})


@app.post("/api/monitored/<int:item_id>/share")
@login_required
def monitored_share(item_id):
    from math import isfinite
    from core.affiliate import cached_affiliate_url
    from core.manual_jobs import normalize_manual_coupon
    from core.notifier import format_whatsapp

    data = request.json or {}
    scan = db.get_setting(f"monitored_scan_{item_id}", {})
    product_id = data.get("product_id")
    if data.get("scan_completed_at") is not None and data["scan_completed_at"] != scan.get("completed_at"):
        return jsonify({"error": "A pesquisa foi atualizada. Recarregue o histórico antes de compartilhar."}), 409
    offer = next((offer for offer in scan.get("results", []) if offer.get("id") == product_id), None)
    if not db.get_monitored_item(item_id) or not offer:
        return jsonify({"error": "Oferta não encontrada. Pesquise a mini novamente."}), 404
    coupon = data.get("coupon", {})
    if not isinstance(coupon, dict):
        return jsonify({"error": "Cupom inválido"}), 400
    deal = dict(offer)
    try:
        for key in ("manual_coupon_code", "manual_coupon_type", "manual_coupon_value",
                    "manual_coupon_max_discount", "manual_coupon_min_purchase", "manual_coupon_final_price"):
            if key in coupon:
                deal[key] = coupon[key]
        for key in ("price", "original_price", "discount", "manual_coupon_value", "manual_coupon_max_discount",
                    "manual_coupon_min_purchase", "manual_coupon_final_price"):
            if key not in deal:
                continue
            deal[key] = float(deal[key] or 0)
            if not isfinite(deal[key]) or deal[key] < 0:
                raise ValueError("Preço ou cupom inválido")
        if deal.get("price", 0) <= 0:
            raise ValueError("Oferta sem preço válido")
        deal = normalize_manual_coupon(deal)
    except (ValueError, TypeError) as exc:
        return jsonify({"error": str(exc)}), 400
    link = cached_affiliate_url(deal)
    if link:
        return jsonify({"whatsapp": format_whatsapp(deal, link), "affiliate_url": link})
    if not health.bot_indicator()["online"]:
        return jsonify({"error": "O bot precisa estar ativo para gerar o link monetizado"}), 503
    return jsonify({"job_id": db.create_job("share_monitored", {"item_id": item_id, "deal": deal})})


@app.post("/api/manual/image")
@login_required
def manual_image():
    image = (request.json or {}).get("image", "")
    if not isinstance(image, str) or not image:
        return jsonify({"error": "Informe uma imagem do produto"}), 400
    return _product_image(image)


def _product_image(url):
    from io import BytesIO
    import requests
    from flask import send_file

    try:
        parsed = urlparse(url)
        host = (parsed.hostname or "").lower()
    except ValueError:
        return jsonify({"error": "Endereço de imagem inválido"}), 400
    domains = ("mlstatic.com", "media-amazon.com", "images-amazon.com",
               "susercontent.com", "shopeemobile.com")
    if (parsed.scheme != "https" or parsed.netloc not in (host, host + ":443")
            or parsed.username or parsed.password
            or not any(host == d or host.endswith("." + d) for d in domains)):
        return jsonify({"error": "Esta origem de imagem não permite download pelo painel"}), 400
    try:
        with requests.get(url, stream=True, timeout=(5, 15), allow_redirects=False) as response:
            extensions = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp"}
            mime = response.headers.get("Content-Type", "").split(";")[0].lower()
            if response.status_code != 200 or mime not in extensions:
                return jsonify({"error": "Não foi possível obter a imagem"}), 502
            data = bytearray()
            for chunk in response.iter_content(65536):
                data.extend(chunk)
                if len(data) > 8 * 1024 * 1024:
                    return jsonify({"error": "Imagem excede o limite de 8 MB"}), 413
    except requests.RequestException:
        return jsonify({"error": "Falha ao baixar imagem da loja"}), 502
    return send_file(BytesIO(data), mimetype=mime, as_attachment=True,
                     download_name="oferta." + extensions[mime])


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
            db.record_verdict(product_id, "rejected")
        elif action == "block_product":
            db.add_blacklist("product", product_id, title)
            db.set_status(product_id, "blacklisted")
            db.record_verdict(product_id, "rejected")
        elif action == "block_title":
            db.add_blacklist("term", title, title)
            db.set_status(product_id, "blacklisted")
            db.record_verdict(product_id, "rejected")
    return jsonify({"jobs": jobs, "processed": len(ids)})


@app.post("/api/price-alert")
@login_required
def api_create_price_alert():
    data = request.json or {}
    if not data.get("product_id"):
        return jsonify({"error": "Dados incompletos"}), 400
    try:
        target = float(data["target_price"])
        current = float(data.get("current_price") or 0)
        if target <= 0 or (current > 0 and target >= current):
            return jsonify({"error": "O preço-alvo deve ser menor que o preço atual"}), 400
    except (ValueError, TypeError):
        return jsonify({"error": "Preço inválido"}), 400
    result = db.set_pending_target(data["product_id"], target)
    if result["kind"] == "missing":
        return jsonify({"error": "Oferta pendente não encontrada"}), 404
    if result["kind"] == "legacy":
        return jsonify({"ok": True, "kind": "legacy",
                        "message": "Produto fora do catálogo: alerta criado como legado. Cadastre a mini para monitorar de verdade."})
    return jsonify({"ok": True, "kind": "monitored", "item_id": result["item_id"],
                    "message": "Alvo definido na mini monitorada."})


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
    return redirect(url_for("monitored", f="alvo"))


@app.post("/price-alerts/<int:alert_id>/delete")
@login_required
def price_alert_delete(alert_id):
    db.delete_price_alert(alert_id)
    flash("Alerta removido", "success")
    return redirect(url_for("monitored", f="alvo"))


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
    return jsonify({"job_id": db.create_job("extract", {"url": url, "only_data": bool(request.json.get("only_data"))})})


@app.post("/api/monitored/sugestao")
@login_required
def api_monitored_sugestao():
    from core import mini_sugestao
    deal = (request.get_json(silent=True) or {}).get("deal") or {}
    if not deal.get("title"):
        return jsonify({"error": "Não consegui ler o nome do produto nesse link."}), 400
    return jsonify(mini_sugestao.suggest(deal))


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


@app.get("/site")
@login_required
def site_page():
    from core import site_ranking
    state = db.get_system_state()
    rk = state.get(site_ranking.STATE_KEY, {})
    cats = list(site_ranking.CATS)
    return render_template("site.html", rk=rk.get("value") or {}, rk_at=rk.get("updated_at"),
                           mode=site_ranking.mode(), agenda=site_ranking.get_agenda(), oque=site_ranking.OQUE, cats=cats, nomes=site_ranking.NOMES,
                           labels=getattr(db, "SITE_LABELS", {}),
                           export=(state.get("site_export") or {}).get("value") or {},
                           site_url=config.SITE_URL)


@app.post("/api/site/ranking")
@login_required
def api_site_ranking():
    data = request.get_json(silent=True) or {}
    if data.get("preview"):
        return jsonify({"job_id": db.create_job("site_ranking_publish_preview", {})})
    escopo = data.get("escopo")
    if escopo is not None:
        from core import site_ranking
        try:
            escopo = site_ranking.norm_escopo(escopo)
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
    return jsonify({"job_id": db.create_job("site_ranking", {"publish": bool(data.get("publish")), "escopo": escopo})})


@app.get("/api/site/ranking/status")
@login_required
def api_site_ranking_status():
    from core import site_ranking
    st = db.get_system_state().get(site_ranking.STATE_KEY) or {}
    return jsonify({"state": st.get("value") or {}, "updated_at": st.get("updated_at")})


@app.get("/api/site/achadinhos")
@login_required
def api_site_achadinhos():
    from core import site_achadinhos
    try:
        return jsonify(site_achadinhos.list_manual())
    except Exception as exc:
        return jsonify({"error": f"Não consegui ler o achadinhos.json do site: {exc}"}), 502


@app.post("/api/site/achadinhos")
@login_required
def api_site_achadinhos_add():
    data = request.get_json(silent=True) or {}
    url = (data.get("url") or "").strip()
    if not re.match(r"^https?://", url):
        return jsonify({"error": "Cole o link do produto (Mercado Livre ou Amazon)."}), 400
    if not str(data.get("preco_alvo") or "").strip():
        return jsonify({"error": "Informe o preço máximo."}), 400
    return jsonify({"job_id": db.create_job("site_achadinho_add", {
        "url": url, "preco_alvo": data.get("preco_alvo"), "categoria": data.get("categoria") or None})})


@app.post("/api/site/achadinhos/remove")
@login_required
def api_site_achadinhos_remove():
    from core import site_achadinhos
    try:
        return jsonify(site_achadinhos.remove((request.get_json(silent=True) or {}).get("id", "")))
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:
        return jsonify({"error": f"Não consegui publicar: {exc}"}), 502


@app.post("/api/site/ranking/cancel")
@login_required
def api_site_ranking_cancel():
    from core import site_ranking
    if not site_ranking.request_cancel():
        return jsonify({"error": "Não há execução em andamento para cancelar."}), 409
    return jsonify({"ok": True})


@app.post("/api/site/ranking/agenda")
@login_required
def api_site_ranking_agenda():
    from core import site_ranking
    try:
        agenda = site_ranking.save_agenda((request.get_json(silent=True) or {}).get("itens"))
    except (ValueError, TypeError, AttributeError) as exc:
        return jsonify({"error": str(exc)}), 400
    return jsonify({"itens": agenda})


@app.post("/api/site/ranking/mode")
@login_required
def api_site_ranking_mode():
    from core import site_ranking
    mode = (request.get_json(silent=True) or {}).get("mode")
    if mode not in ("teste", "publicar"):
        return jsonify({"error": "Modo inválido"}), 400
    db.set_setting(site_ranking.MODE_KEY, mode)
    return jsonify({"mode": mode})


@app.get("/api/jobs/<int:job_id>")
@login_required
def api_job(job_id):
    job = db.get_job(job_id)
    if job and job.get("status") in ("pending", "processing"):
        progress = db.get_system_state().get("scan_progress", {}).get("value")
        if progress:
            job["progress"] = progress
    return jsonify(job or {"error": "Tarefa não encontrada"}), 200 if job else 404


@app.route("/monitored", methods=["GET", "POST"])
@login_required
def monitored():
    if request.method == "POST":
        item_id = request.form.get("id", type=int)
        try:
            saved_id = db.save_monitored_item({
                "name": request.form.get("name", ""),
                "search_terms": request.form.get("search_terms", ""),
                "required_terms": request.form.get("required_terms", ""),
                "forbidden_terms": request.form.get("forbidden_terms", ""),
                "tags": request.form.get("tags", ""),
                "max_price": request.form.get("max_price", ""),
                "active": request.form.get("active") == "on",
                "image": request.form.get("image", ""),
            }, item_id)
            if request.form.get("site_form") == "1":
                db.set_monitored_site(saved_id, request.form.get("site_enabled") == "on",
                                      request.form.get("site_category", ""))
        except (ValueError, TypeError) as exc:
            flash(str(exc), "error")
            return redirect(url_for("monitored"))
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
    db.migrate_legacy_price_alerts()
    items = db.list_monitored_items()
    tags = db.monitored_tags()
    selected_tag = " ".join(request.args.get("tag", "").split()).casefold()
    if selected_tag:
        items = [i for i in items if selected_tag in i["tags"]]
    counts = {"all": len(items),
              "alvo": sum(1 for i in items if i["state"] == "watching"),
              "atingido": sum(1 for i in items if i["state"] == "target_hit"),
              "aprendendo": sum(1 for i in items if i["state"] == "learning"),
              "pausadas": sum(1 for i in items if i["state"] == "paused")}
    active_filter = request.args.get("f", "all")
    state_map = {"alvo": "watching", "atingido": "target_hit",
                 "aprendendo": "learning", "pausadas": "paused"}
    if active_filter in state_map:
        items = [i for i in items if i["state"] == state_map[active_filter]]
    else:
        active_filter = "all"
    return render_template("monitored.html", items=items, counts=counts,
                           active_filter=active_filter, tags=tags, selected_tag=selected_tag,
                           legacy_alerts=db.list_legacy_price_alerts(),
                           site_categories=db.SITE_CATEGORIES,
                           site_state=db.get_system_state().get("site_export"))


@app.get("/monitored/<int:item_id>")
@login_required
def monitored_detail(item_id):
    item = db.get_monitored_item(item_id)
    if not item:
        return "Mini não encontrada", 404
    days = request.args.get("days", 90, type=int)
    days = days if days in {7, 30, 90} else 90
    summary, daily, stores, recent = db.monitored_price_history(item_id, days)
    history_summary = summary if days == 90 else db.monitored_price_summary(item_id, 90)
    return render_template("monitored_detail.html", item=item, summary=summary,
                           daily=daily, stores=stores, recent=recent, days=days,
                           history_summary=history_summary,
                           excluded=db.excluded_observations(item_id),
                           last_scan=_curated_scan(item_id))


def _curated_scan(item_id):
    scan = db.get_setting(f"monitored_scan_{item_id}", None)
    if scan:
        scan["results"] = [d for d in scan.get("results", []) if not db.monitored_offer_excluded(item_id, d)]
        scan["matches_total"] = len(scan["results"])
    return scan


@app.post("/monitored/<int:item_id>/observations/<int:observation_id>/curate")
@login_required
def curate_monitored_observation(item_id, observation_id):
    action = request.form.get("action")
    if action not in {"exclude", "restore"}:
        return "Ação inválida", 400
    if not db.curate_observation(item_id, observation_id, action == "exclude"):
        return "Leitura não encontrada", 404
    flash("Anúncio desconsiderado apenas nesta mini." if action == "exclude" else "Leituras restauradas nesta mini.", "success")
    return redirect(url_for("monitored_detail", item_id=item_id))


@app.post("/api/monitored/<int:item_id>/target")
@login_required
def api_monitored_target(item_id):
    data = request.get_json(silent=True)
    if not isinstance(data, dict) or "max_price" not in data:
        return jsonify({"error": "Informe o alvo ou deixe em branco para aprender em silêncio."}), 400
    try:
        updated = db.update_monitored_target(item_id, data["max_price"])
    except (ValueError, TypeError) as exc:
        return jsonify({"error": str(exc)}), 400
    if not updated:
        return jsonify({"error": "Mini não encontrada"}), 404
    return jsonify({"max_price": db.get_monitored_item(item_id)["max_price"]})


@app.post("/api/site/publish")
@login_required
def api_site_publish():
    from core import site_export
    result = site_export.publish(force=True, generate_links=False)
    if request.accept_mimetypes.best == "application/json" or request.is_json:
        return jsonify(result), (200 if result.get("status") == "ok" else 400)
    if result.get("status") == "ok":
        flash(f"Site atualizado: {result['app_items']} achadinho(s) do app, {result['total']} no total.", "success")
    else:
        flash(f"Site não atualizado: {result.get('detail', '')}", "error")
    return redirect(url_for("monitored"))


@app.post("/monitored/<int:item_id>/toggle")
@login_required
def monitored_toggle(item_id):
    item = db.get_monitored_item(item_id)
    if not item:
        return "Mini não encontrada", 404
    if request.form.get("active") not in {"0", "1"}:
        return "Estado inválido", 400
    item["active"] = request.form["active"] == "1"
    db.save_monitored_item(item, item_id)
    flash("Monitoramento retomado" if item["active"] else "Monitoramento pausado", "success")
    return redirect(url_for("monitored"))


@app.post("/monitored/<int:item_id>/delete")
@login_required
def monitored_delete(item_id):
    db.delete_monitored_item(item_id)
    flash("Mini removida", "success")
    return redirect(url_for("monitored"))


@app.route("/search-settings", methods=["GET", "POST"])
@app.route("/settings", methods=["GET", "POST"])
@login_required
def search_settings():
    if request.method == "POST" and request.form.get("section") == "channel_promotion":
        text = request.form.get("channel_promotion", "").replace("\r\n", "\n").strip()
        if not text or len(text) > 20000:
            flash("Informe um texto de divulgação com até 20.000 caracteres", "error")
        else:
            db.set_setting("channel_promotion", text)
            flash("Texto de divulgação salvo", "success")
        return redirect(url_for("search_settings", _anchor="promotion"))
    if request.method == "POST" and request.form.get("section") == "schedule":
        try:
            start = datetime.strptime(request.form["quiet_start"], "%H:%M").strftime("%H:%M")
            end = datetime.strptime(request.form["quiet_end"], "%H:%M").strftime("%H:%M")
            interval = int(request.form["min_interval"])
            if not 1 <= interval <= 1440:
                raise ValueError
        except (KeyError, ValueError):
            flash("Horários ou intervalo inválidos", "error")
            return redirect(url_for("search_settings", _anchor="publishing"))
        db.set_setting("schedule", {"quiet_start": start, "quiet_end": end,
                                   "min_interval": interval, "timezone": "America/Sao_Paulo"})
        flash("Horários atualizados", "success")
        return redirect(url_for("search_settings", _anchor="publishing"))
    if request.method == "POST":
        enabled = request.form.getlist("enabled_stores")
        if not enabled:
            flash("Mantenha pelo menos uma loja habilitada", "error")
            return redirect(url_for("search_settings"))
        db.set_setting("enabled_stores", enabled)
        db.set_setting("approval_expiry_hours", max(1, request.form.get(
            "approval_expiry_hours", 24, type=int)))
        config.clear_dynamic_cache()
        flash("Configurações atualizadas; o próximo ciclo já usará as mudanças", "success")
        return redirect(url_for("search_settings"))
    rules = db.list_brand_rules()
    for rule in rules:
        rule["today_count"] = db.brand_daily_count(rule["id"])
    return render_template(
        "search_settings.html", rules=rules,
        channel_promotion=db.get_setting("channel_promotion", CHANNEL_PROMOTION_DEFAULT),
        settings=db.get_setting("schedule", {"quiet_start": "23:00", "quiet_end": "08:00",
                                             "min_interval": 10, "timezone": "America/Sao_Paulo"}),
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
    return redirect(url_for("search_settings", _anchor="brands"))


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
