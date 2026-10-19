import random
import sys
import threading
import time
from datetime import datetime
from zoneinfo import ZoneInfo

import config
from core import affiliate, approvals, db, filters, manual_jobs
from core.affiliate import to_affiliate_url
from core.notifier import send_deal, send_for_approval, send_price_alert
from scrapers import close_browser, get_scrapers
from scrapers.coupons import search_coupons
from scrapers.ml_coupons import collect_ml_coupons, ml_available


def _is_quiet():
    """Check if we're inside the quiet period (no notifications)."""
    settings = db.get_setting("schedule", {
        "quiet_start": "23:00", "quiet_end": "08:00",
        "timezone": "America/Sao_Paulo"})
    zone = ZoneInfo(settings.get("timezone", "America/Sao_Paulo"))
    now = datetime.now(zone).time()
    start = datetime.strptime(settings["quiet_start"], "%H:%M").time()
    end = datetime.strptime(settings["quiet_end"], "%H:%M").time()
    if start > end:
        return now >= start or now < end
    return start <= now < end


def _ml_search_plan(search_plan, monitored):
    monitored_terms = {item["search_terms"] for item in monitored}
    priority = [(term, discount) for term, discount in search_plan.items()
                if term in monitored_terms]
    regular = [(term, discount) for term, discount in search_plan.items()
               if term not in monitored_terms]
    if not regular:
        return priority
    state = db.get_system_state().get("ml_search_cursor")
    cursor = int(state["value"] if state else 0) % len(regular)
    selected = [regular[(cursor + offset) % len(regular)] for offset in range(min(3, len(regular)))]
    db.set_system_state("ml_search_cursor", (cursor + len(selected)) % len(regular))
    return priority + selected


def _check_deals():
    seen_this_round = set()
    lego_count = 0
    monitored = db.active_monitored_items()
    brand_floor = db.minimum_brand_discount()
    search_floor = min(config.MIN_DISCOUNT, brand_floor) \
        if brand_floor is not None else config.MIN_DISCOUNT
    search_plan = {keyword: search_floor for keyword in config.load_keywords()}
    for item in monitored:
        search_plan[item["search_terms"]] = 0
    for store_name, scraper in get_scrapers():
        store_started = time.time()
        store_offers = 0
        store_errors = []
        if store_name == "Mercado Livre" and not ml_available():
            db.update_store_health(store_name, "blocked", error="Verificação manual necessária")
            continue
        store_plan = _ml_search_plan(search_plan, monitored) \
            if store_name == "Mercado Livre" else search_plan.items()
        for keyword, min_discount in store_plan:
            db.set_system_state("heartbeat", {"phase": "searching",
                                               "store": store_name,
                                               "keyword": keyword})
            manual_jobs.process_jobs()
            manual_jobs.process_scheduled()
            try:
                deals = scraper(keyword, min_discount)
                store_offers += len(deals)
            except Exception as exc:
                deals = []
                store_errors.append(f"{keyword}: {exc}")
            if store_name == "Mercado Livre" and not ml_available():
                store_errors.append("Verificação manual necessária")
                break
            time.sleep(random.uniform(2, 5))  # evita rate limit/captcha
            for deal in deals:
                tracked = [item for item in monitored
                           if item["search_terms"] == keyword
                           and filters.identifies_monitored(deal, item)]
                for item in tracked:
                    db.record_price(item["id"], deal)
                if deal["id"] in seen_this_round:
                    continue
                repost = False
                if db.already_posted(deal["id"]):
                    if db.should_repost(deal["id"], deal.get("price", 0)):
                        repost = True
                        print(f"[↻] republicar: preço caiu >15%: {deal['title'][:50]}")
                    else:
                        continue
                # Price alert: skip if user said "Caro" and price is still above target
                triggered_alert = db.check_price_alerts(
                    deal["title"], deal["price"], deal["store"])
                if triggered_alert:
                    print(f"[!] alerta de preço atingido: {deal['title'][:50]} "
                          f"R${deal['price']:.2f} <= R${triggered_alert['target_price']:.2f}")
                    if not _is_quiet():
                        send_price_alert(triggered_alert, deal)
                if db.is_price_above_alert(deal["title"], deal["price"]):
                    continue
                watched = next((item for item in tracked
                                if deal["price"] <= item["max_price"]), None)
                brand_rule = db.match_brand_rule(deal["title"])
                if not watched and not filters.passes(deal, lego_count, brand_rule):
                    continue
                seen_this_round.add(deal["id"])
                if filters.is_lego(deal["title"]):
                    lego_count += 1
                link = to_affiliate_url(deal)
                monetized = affiliate.is_monetized(link, store_name)
                # Calculate relevance score
                score_data = filters.relevance_score(deal, brand_rule)
                deal["_score"] = score_data["score"]
                deal["_score_reasons"] = "; ".join(score_data["reasons"])
                if watched:
                    needs_approval = False
                elif brand_rule and brand_rule["approval_mode"] == "manual":
                    needs_approval = True
                elif brand_rule and brand_rule["approval_mode"] == "auto":
                    needs_approval = False
                elif score_data["auto_action"] == "approve" and monetized:
                    needs_approval = False
                    print(f"[★] score {score_data['score']}: auto-aprovado: {deal['title'][:50]}")
                elif score_data["auto_action"] == "reject":
                    db.mark_posted(deal["id"], store_name,
                                   deal["title"], deal["price"],
                                   status="rejected", url=deal["url"],
                                   image=deal.get("image", ""),
                                   original_price=deal["original_price"],
                                   discount=deal["discount"],
                                   brand_rule_id=brand_rule["id"] if brand_rule else None,
                                   brand_name=brand_rule["name"] if brand_rule else "",
                                   relevance_score=score_data["score"],
                                   score_reasons=deal["_score_reasons"])
                    print(f"[✗] score {score_data['score']}: auto-rejeitado: {deal['title'][:50]}")
                    continue
                elif brand_rule:
                    needs_approval = deal["discount"] < brand_rule["auto_approve_discount"]
                else:
                    needs_approval = deal["discount"] < config.AUTO_APPROVE_MIN
                _score_args = dict(
                    relevance_score=deal.get("_score"),
                    score_reasons=deal.get("_score_reasons", ""))
                if (config.TELEGRAM_ADMIN_CHAT_ID
                        and (needs_approval or not monetized)):
                    quiet = _is_quiet()
                    sent = not quiet and send_for_approval(deal, link)
                    db.mark_posted(deal["id"], store_name,
                                   deal["title"], deal["price"],
                                   status="pending", url=deal["url"],
                                   image=deal.get("image", ""),
                                   original_price=deal["original_price"],
                                   discount=deal["discount"],
                                   brand_rule_id=brand_rule["id"] if brand_rule else None,
                                   brand_name=brand_rule["name"] if brand_rule else "",
                                   **_score_args)
                    if quiet:
                        print(f"[z] silêncio, enfileirado: {deal['title'][:60]}")
                    else:
                        print(f"[?] aprovação (score {deal.get('_score','-')}): {deal['title'][:60]}")
                    continue
                quiet = _is_quiet()
                if quiet:
                    db.mark_posted(deal["id"], store_name,
                                   deal["title"], deal["price"],
                                   status="pending", url=deal["url"],
                                   image=deal.get("image", ""),
                                   original_price=deal["original_price"],
                                   discount=deal["discount"],
                                   brand_rule_id=brand_rule["id"] if brand_rule else None,
                                   brand_name=brand_rule["name"] if brand_rule else "",
                                   **_score_args)
                    print(f"[z] silêncio, enfileirado auto: {deal['title'][:60]}")
                    continue
                if send_deal(deal, link):
                    db.mark_posted(deal["id"], store_name, deal["title"],
                                   deal["price"], url=deal["url"],
                                   image=deal.get("image", ""),
                                   original_price=deal["original_price"],
                                   discount=deal["discount"],
                                   brand_rule_id=brand_rule["id"] if brand_rule else None,
                                   brand_name=brand_rule["name"] if brand_rule else "",
                                   **_score_args)
                    db.record_publication_details(deal["id"], deal, link)
                    print(f"[+] {deal['store']}: {deal['title'][:60]} "
                          f"({deal['discount']}% off)")
                    time.sleep(2)  # respeita rate limit do Telegram
        db.update_store_health(
            store_name, "degraded" if store_errors else "healthy",
            store_offers, time.time() - store_started, " | ".join(store_errors))
    manual_jobs.process_jobs()
    for coupon in (search_coupons() + collect_ml_coupons())[
            :config.MAX_COUPONS_PER_CYCLE]:
        if db.already_posted(coupon["id"]):
            continue
        link = to_affiliate_url(coupon)
        if send_deal(coupon, link):
            db.mark_posted(coupon["id"], "Cupom", coupon["title"], 0)
            print(f"[+] Cupom: {coupon['coupon']} — {coupon['store']}")
            time.sleep(2)
    print("[*] ciclo concluído")


def check_deals():
    started = time.time()
    db.set_system_state("cycle", {"status": "running", "started_at": started})
    db.set_system_state("heartbeat", {"phase": "cycle_start"})
    try:
        _check_deals()
        db.set_system_state("cycle", {
            "status": "completed", "started_at": started,
            "duration": time.time() - started})
    except Exception as exc:
        db.set_system_state("cycle", {
            "status": "error", "started_at": started,
            "duration": time.time() - started, "error": str(exc)[:500]})
        print(f"[!] ciclo falhou: {exc}")
    finally:
        close_browser()
        db.set_system_state("heartbeat", {"phase": "idle"})


def main():
    if not config.TELEGRAM_BOT_TOKEN or not config.TELEGRAM_CHAT_ID:
        sys.exit("Configure TELEGRAM_BOT_TOKEN e TELEGRAM_CHAT_ID no .env")

    if config.TELEGRAM_ADMIN_CHAT_ID:
        threading.Thread(target=approvals.poll_updates, daemon=True).start()
        print("[*] aprovação manual ativa com regras por marca")

    check_deals()

    if "--once" in sys.argv:
        time.sleep(60)  # dá tempo de aprovar pendentes via DM
        return

    print(f"[*] agendado a cada {config.CHECK_INTERVAL_MINUTES} min. Ctrl+C p/ sair")
    try:
        while True:
            deadline = time.time() + config.CHECK_INTERVAL_MINUTES * 60
            last_heartbeat = 0
            while time.time() < deadline:
                manual_jobs.process_jobs()
                manual_jobs.process_scheduled()
                if time.time() - last_heartbeat >= 30:
                    db.set_system_state("heartbeat", {"phase": "idle"})
                    last_heartbeat = time.time()
                time.sleep(3)
            check_deals()
    except KeyboardInterrupt:
        close_browser()


if __name__ == "__main__":
    main()
