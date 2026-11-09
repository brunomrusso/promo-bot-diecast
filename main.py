import os
import random
import sys
import threading
import time
from datetime import datetime
from zoneinfo import ZoneInfo

import config
from core import approvals, db, filters, manual_jobs, site_export, site_ranking
from core.affiliate import to_affiliate_url
from core.notifier import send_for_approval
from scrapers import close_browser, get_scrapers
from scrapers.ml_coupons import ml_available
from scrapers.mercadolivre import ml_api_ready
from scrapers.mercadolivre_pw import reset_comparison_budget


def _is_quiet():
    """Horário silencioso: sem buscas, sem ranking automático e sem avisos no Telegram."""
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


def _check_deals():
    reset_comparison_budget()
    manual_jobs.process_jobs()
    manual_jobs.process_scheduled()
    archived = db.reconcile_catalog_queue()
    congeladas = db.frozen_monitored_items(config.tempos()["congelar_horas"])
    monitored = [i for i in db.active_monitored_items() if i["id"] not in congeladas]
    terms = list(dict.fromkeys(
        query for item in monitored
        for query in filters.search_queries(item["search_terms"])))
    candidates = {item["id"]: {} for item in monitored}
    new_opportunities = 0
    if not terms:
        db.set_system_state("catalog", {"active": 0, "new_opportunities": 0, "archived": archived})
        return
    for store_name, scraper in get_scrapers():
        store_started = time.time()
        store_offers = 0
        store_errors = []
        if (store_name == "Mercado Livre" and not ml_api_ready()
                and not ml_available()):
            db.update_store_health(store_name, "blocked", error="Verificação manual necessária")
            continue
        state_key = f"catalog_cursor_{store_name}"
        state = db.get_system_state().get(state_key)
        cursor = int(state["value"] if state else 0) % len(terms)
        selected = [terms[(cursor + i) % len(terms)] for i in range(min(config.tempos()["termos_por_ciclo"], len(terms)))]
        db.set_system_state(state_key, cursor + len(selected))
        for keyword in selected:
            db.set_system_state("heartbeat", {"phase": "searching", "store": store_name, "keyword": keyword})
            manual_jobs.process_jobs()
            manual_jobs.process_scheduled()
            current_items = [i for i in db.active_monitored_items() if i["id"] not in congeladas]
            if not any(keyword in filters.search_queries(item["search_terms"])
                       for item in current_items):
                continue
            try:
                deals = scraper(keyword, 0)
                store_offers += len(deals)
            except Exception as exc:
                store_errors.append(f"{keyword}: {exc}")
                continue
            if (store_name == "Mercado Livre" and not ml_api_ready()
                    and not ml_available()):
                store_errors.append("Verificação manual necessária")
                break
            manual_jobs.process_jobs(urgent_only=True)
            time.sleep(random.uniform(2, 5))  # evita rate limit/captcha
            current_items = [i for i in db.active_monitored_items() if i["id"] not in congeladas]
            for deal in deals:
                if deal.get("origin") == "international" or not deal.get("price"):
                    continue
                tracked = [item for item in current_items if filters.identifies_monitored(deal, item)]
                if not tracked:
                    continue
                db.record_product_price(deal)
                for item in tracked:
                    db.record_price(item["id"], deal)
                    candidates.setdefault(item["id"], {})[deal["id"]] = deal
        db.update_store_health(store_name, "degraded" if store_errors else "healthy",
                               store_offers, time.time() - store_started, " | ".join(store_errors))
    congeladas |= db.frozen_monitored_items(config.tempos()["congelar_horas"])
    for item in db.active_monitored_items():
        if item["id"] in congeladas:
            continue
        offers = list(candidates.get(item["id"], {}).values())
        if not offers or new_opportunities >= 5:
            continue
        national = [deal for deal in offers if deal.get("origin") == "national"]
        deal = min(national or offers, key=lambda d: d["price"])
        # Learned rejection: history says this price is bad
        reason = db.catalog_opportunity_reason(item, deal)
        if not reason:
            continue
        # Calculate relevance score
        rule = db.match_brand_rule(deal["title"])
        if rule and not db.brand_limit_available(rule):
            continue
        # Same product in another pending listing: keep the cheapest
        if not db.enqueue_catalog_opportunity(item["id"], deal):
            continue
        new_opportunities += 1
        link = to_affiliate_url(deal)
        if config.TELEGRAM_ADMIN_CHAT_ID and not _is_quiet():
            if send_for_approval(deal, link):
                db.mark_admin_notified(deal["id"])
            time.sleep(2)  # respeita rate limit do Telegram
        print(f"[catálogo] oportunidade para revisão: {item['name'][:60]} — R$ {deal['price']:.2f}")
    _notify_pending_after_quiet()
    manual_jobs.process_jobs()
    db.set_system_state("catalog", {"active": len(monitored), "new_opportunities": new_opportunities,
                                     "archived": archived, "queue_limit": 20, "cycle_limit": 5})
    site = site_export.publish()
    if site.get("status") == "error":
        print(f"[!] site: {site.get('detail')}")
    elif site.get("changed"):
        print(f"[*] site: achadinhos.json enviado ({site['app_items']} do app, {site['total']} no total)")
    print("[*] ciclo do catálogo concluído")


def _notify_pending_after_quiet():
    """Oportunidades criadas no horário silencioso ficavam só no painel e expiravam
    sem você ver. Fora do silêncio, avisa no Telegram as que ainda não foram avisadas."""
    if not config.TELEGRAM_ADMIN_CHAT_ID or _is_quiet():
        return
    for row in db.pending_catalog_unnotified():
        deal = {"id": row["product_id"], "store": row["store"], "title": row["title"],
                "price": row["price"], "original_price": row.get("original_price") or row["price"],
                "discount": row.get("discount") or 0, "url": row.get("url") or "",
                "image": row.get("image") or ""}
        try:
            if send_for_approval(deal, to_affiliate_url(deal)):
                db.mark_admin_notified(row["product_id"])
        except Exception as exc:
            print(f"[!] aviso pendente falhou: {exc}")
        time.sleep(2)


def check_deals():
    if _is_quiet():  # horário silencioso: nenhuma busca (economiza proxy); pedidos feitos no painel seguem rodando
        db.set_system_state("heartbeat", {"phase": "quiet"})
        print("[*] horário silencioso: ciclo de buscas pulado")
        return
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
    presos = db.release_interrupted_jobs()  # pedidos do painel que o reinício do bot interrompeu
    if presos:
        print(f"[*] {presos} pedido(s) do painel interrompidos pelo reinício foram marcados como erro")

    if config.TELEGRAM_ADMIN_CHAT_ID:
        threading.Thread(target=approvals.poll_updates, daemon=True).start()
        print("[*] aprovação manual ativa com regras por marca")

    check_deals()

    if "--once" in sys.argv:
        time.sleep(60)  # dá tempo de aprovar pendentes via DM
        return

    print(f"[*] agendado a cada {config.tempos()['ciclo_min']} min (ajustável no painel). Ctrl+C p/ sair")
    try:
        while True:
            deadline = time.time() + config.tempos()["ciclo_min"] * 60
            last_heartbeat = 0
            while time.time() < deadline:
                manual_jobs.process_jobs()
                manual_jobs.process_scheduled()
                if time.time() - last_heartbeat >= 30:
                    db.set_system_state("heartbeat", {"phase": "idle"})
                    last_heartbeat = time.time()
                    try:
                        if not _is_quiet():
                            site_ranking.maybe_run()   # ranking do site: 06:40 e 18:40 (Brasília)
                    except Exception as exc:
                        print(f"[!] ranking do site: {exc}")
                time.sleep(3)
            check_deals()
    except KeyboardInterrupt:
        close_browser()


if __name__ == "__main__":
    main()
