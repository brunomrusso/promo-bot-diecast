import tempfile
import gc
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from core import db, filters
import main


EXPENSIVE = "Hot Wheels Premium Fast And Furious Honda Civic Coupé Ej1 93 Cor Preto"
CHEAP = "Hot Wheels 1993 Honda Civic Coupe Velozes E Furiosos Jbl90 Preto"



# Os testes não podem depender das etiquetas/IDs por canal configurados no .env do servidor.
_canais = patch.multiple("config", ML_TAG_BOT="", ML_TAG_SITE="")


def setUpModule():
    _canais.start()


def tearDownModule():
    _canais.stop()

class PriceEngineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path_patch = patch.object(db, "DB_PATH", Path(self.temp.name) / "deals.db")
        self.path_patch.start()

    def test_ml_consultado_no_maximo_de_hora_em_hora(self):
        import main
        with patch("main.time.time", return_value=1_000_000.0):
            self.assertTrue(main._ml_na_vez())
        with patch("main.time.time", return_value=1_000_000.0 + 15 * 60):
            self.assertFalse(main._ml_na_vez())  # 15 min depois: pula o ML
        with patch("main.time.time", return_value=1_000_000.0 + 60 * 60):
            self.assertTrue(main._ml_na_vez())
        db.set_setting("ml_intervalo_min", 15)
        with patch("main.time.time", return_value=1_000_000.0 + 75 * 60):
            self.assertTrue(main._ml_na_vez())

    def tearDown(self):
        self.path_patch.stop()
        gc.collect()
        self.temp.cleanup()

    def deal(self, pid="cheap", price=140, title=CHEAP, origin="national", discount=0):
        return dict(id=pid, store="Mercado Livre", title=title, price=price,
                    original_price=price, discount=discount, origin=origin,
                    url="https://www.mercadolivre.com.br/p/MLB64840241", image="")

    def test_monitored_multiple_tags_and_filter(self):
        from dashboard import app
        data = dict(name="Super Nova", search_terms="super nova", required_terms="nova", max_price=0, tags=" Boulevard, FAVORITOS, boulevard ; coleção ")
        first = db.save_monitored_item(data)
        second = db.save_monitored_item(dict(data, name="Skyline", search_terms="skyline", tags="japoneses"))
        self.assertEqual(db.monitored_tags(), ["boulevard", "coleção", "favoritos", "japoneses"])
        self.assertEqual(next(i for i in db.list_monitored_items() if i["id"] == first)["tags"], ["boulevard", "favoritos", "coleção"])
        with app.test_client() as client:
            with client.session_transaction() as session:
                session["authenticated"] = True
            response = client.get("/monitored?tag=BOULEVARD&f=aprendendo")
            self.assertEqual(response.status_code, 200)
            self.assertIn(b"Super Nova", response.data)
            self.assertNotIn(b"Skyline</h3>", response.data)
        db.save_monitored_item(dict(data, tags=""), first)
        self.assertEqual(next(i for i in db.list_monitored_items() if i["id"] == first)["tags"], [])
        db.save_monitored_item(dict(data, name="Skyline", search_terms="skyline", tags=["japoneses", "premium"]), second)
        self.assertIn("premium", db.monitored_tags())
        with self.assertRaises(ValueError):
            db.normalize_tags("x" * 51)
        with self.assertRaises(ValueError):
            db.normalize_tags([str(n) for n in range(21)])

    def test_display_dates_use_sao_paulo_without_changing_utc(self):
        from dashboard import sp_datetime
        self.assertEqual(sp_datetime("2026-10-29 01:30:00"), "28/10/2026 22:30:00")
        self.assertEqual(sp_datetime("2026-10-29T12:00:00Z"), "29/10/2026 09:00:00")
        self.assertEqual(sp_datetime("2026-10-29T09:00:00-03:00"), "29/10/2026 09:00:00")
        self.assertEqual(sp_datetime(datetime(2026, 10, 29, 12, tzinfo=timezone.utc)), "29/10/2026 09:00:00")
        self.assertEqual(sp_datetime(None), "—")
        self.assertEqual(sp_datetime("invalid"), "—")

    def test_observation_exclusion_is_reversible_and_scoped(self):
        first = self.register()
        second = db.save_monitored_item(dict(name="Outra mini", search_terms="civic", required_terms="hot wheels", max_price=200))
        cheap, expensive = self.deal(price=50), self.deal(pid="other", price=100)
        for item_id in (first, second):
            db.record_price(item_id, cheap)
            db.record_price(item_id, expensive)
        with db._conn() as conn:
            observation = conn.execute("SELECT id FROM price_observations WHERE monitored_item_id=? AND product_id=?", (first, cheap["id"])).fetchone()[0]
        self.assertTrue(db.curate_observation(first, observation, True))
        self.assertEqual(db.monitored_price_summary(first)["min_price"], 100)
        self.assertEqual(db.get_monitored_item(first)["all_time_min"], 100)
        self.assertEqual(db.monitored_price_summary(second)["min_price"], 50)
        self.assertFalse(filters.identifies_monitored(cheap, db.get_monitored_item(first)))
        db.record_price(first, dict(cheap, price=40))
        self.assertEqual(db.monitored_price_summary(first)["observations"], 1)
        self.assertFalse(db.curate_observation(second, observation, True))
        self.assertTrue(db.curate_observation(first, observation, False))
        self.assertEqual(db.monitored_price_summary(first)["min_price"], 50)
        self.assertEqual(db.get_monitored_item(first)["all_time_min"], 50)

    def test_civic_identity_and_conflicts(self):
        self.assertTrue(db.comparable_product(EXPENSIVE, CHEAP))
        for other in (CHEAP.replace("1993", "1995"), CHEAP.replace("Preto", "Azul"),
                      CHEAP.replace("Jbl90", "Jbl91")):
            self.assertFalse(db.comparable_product(CHEAP, other))
        self.assertFalse(db.comparable_product("Kaido House Civic KHMG179", "Kaido House Civic KHMG260"))
        self.assertFalse(db.comparable_product(CHEAP, CHEAP + " Pack 5"))

    def test_low_discount_is_comparison_evidence(self):
        db.record_product_price(self.deal(discount=6))
        result = db.market_price_evaluation(EXPENSIVE, 158, "expensive")
        self.assertEqual(result["best_price"], 140)
        self.assertEqual(result["key"], "expensive")
        self.assertFalse(result["confident"])

    def test_international_and_unknown_do_not_contaminate(self):
        for origin in ("international", "unknown"):
            db.record_product_price(self.deal(pid=origin, price=50, origin=origin))
        result = db.market_price_evaluation(CHEAP, 140, "candidate")
        self.assertEqual(result["observations"], 0)
        self.assertIsNone(result["best_price"])

    def test_discount_does_not_change_relevance(self):
        rule = {"name": "Hot Wheels Premium", "priority": 100}
        first = filters.relevance_score(self.deal(discount=0), rule)
        second = filters.relevance_score(self.deal(discount=90), rule)
        self.assertEqual(first, second)
        self.assertEqual(first["auto_action"], "review")

    def test_history_requires_distinct_days_and_competitor(self):
        for i in range(8):
            db.record_product_price(self.deal(pid=f"today-{i}", price=160))
        self.assertFalse(db.market_price_evaluation(CHEAP, 140)["confident"])
        for i in range(1, 6):
            pid = f"history-{i}"
            db.record_product_price(self.deal(pid=pid, price=160))
            day = (datetime.now(timezone.utc) - timedelta(days=i)).strftime("%Y-%m-%d")
            with db._conn() as conn:
                conn.execute("UPDATE product_prices SET day=?,seen_at=? WHERE product_id=?",
                             (day, day + " 12:00:00", pid))
        self.assertTrue(db.market_price_evaluation(CHEAP, 140, "candidate")["confident"])

    def test_unknown_origin_is_checked_in_buybox_only(self):
        from scrapers import mercadolivre_pw as ml
        from unittest.mock import Mock
        self.register()
        page = Mock()
        page.locator.return_value.all_inner_texts.return_value = ["Chegará grátis amanhã. Estoque disponível"]
        page.locator.return_value.inner_text.return_value = CHEAP
        price = Mock()
        price.inner_text.return_value = "140"
        page.query_selector.side_effect = lambda s: price if s.endswith("__fraction") else None
        deal = self.deal(origin="unknown")
        with patch.object(ml, "is_ml_verification", return_value=False):
            ml.reset_comparison_budget()
            ml._verify_market_origins(page, [deal])
        self.assertEqual(deal["origin"], "national")
        self.assertEqual(deal["price"], 140)
        self.assertTrue(any("column-right" in call.args[0] for call in page.locator.call_args_list))

    def test_scraper_keeps_no_discount_and_missing_previous_price(self):
        from scrapers.amazon import search_amazon
        from unittest.mock import Mock
        page = '<div data-asin="ABC1234567" data-component-type="s-search-result"><h2><span>Hot Wheels Civic</span></h2><span class="a-price"><span class="a-offscreen">R$ 140,00</span></span></div>'
        with patch("scrapers.amazon.requests.get", return_value=Mock(status_code=200, text=page)):
            deals = search_amazon("civic", 99)
        self.assertEqual(len(deals), 1)
        self.assertEqual(deals[0]["price"], 140)
        self.assertEqual(deals[0]["discount"], 0)

    def register(self, target=145, active=True, name=CHEAP, required="honda, civic, 1993, preto"):
        return db.save_monitored_item(dict(name=name, search_terms=name, required_terms=required,
                                           max_price=target, active=active))

    def run_cycle(self, deals):
        from unittest.mock import Mock
        scraper = Mock(return_value=deals)
        with patch.object(main, "get_scrapers", return_value=[("Mercado Livre", scraper)]), \
                patch.object(main.config, "TELEGRAM_ADMIN_CHAT_ID", "admin"), \
                patch.object(main.manual_jobs, "process_jobs"), \
                patch.object(main.manual_jobs, "process_scheduled"), \
                patch.object(main, "ml_available", return_value=True), \
                patch.object(main, "to_affiliate_url", return_value="https://meli.la/test") as affiliate, \
                patch.object(main, "send_for_approval") as notify, \
                patch.object(main.time, "sleep"), \
                patch.object(main, "_is_quiet", return_value=False), \
                patch("core.notifier.requests.post") as send:
            main._check_deals()
        send.assert_not_called()
        return scraper, affiliate, notify

    def test_empty_catalog_does_not_search_or_notify(self):
        scraper, affiliate, notify = self.run_cycle([self.deal()])
        scraper.assert_not_called()
        affiliate.assert_not_called()
        notify.assert_not_called()

    def test_only_authorized_prices_are_recorded_and_cheapest_is_reviewed(self):
        item_id = self.register()
        deals = [self.deal("expensive", 158, EXPENSIVE, discount=31), self.deal(discount=6)]
        deals += [self.deal(f"noise-{i}", 30, "Hot Wheels Ferrari F40") for i in range(200)]
        scraper, affiliate, notify = self.run_cycle(deals)
        self.assertEqual(scraper.call_args.args, (CHEAP, 0))
        self.assertEqual(notify.call_count, 1)
        with db._conn() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM product_prices").fetchone()[0], 2)
            pending = dict(conn.execute("SELECT product_id,monitored_item_id FROM posted WHERE status='pending'").fetchone())
        self.assertEqual(pending, {"product_id": "cheap", "monitored_item_id": item_id})
        self.run_cycle(deals)[2].assert_not_called()

    def test_learning_and_above_target_are_silent(self):
        self.register(target="")
        self.run_cycle([self.deal()])[1].assert_not_called()
        with db._conn() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM posted WHERE status='pending'").fetchone()[0], 0)
            conn.execute("UPDATE monitored_items SET max_price=100")
        self.run_cycle([self.deal()])[2].assert_not_called()

    def test_paused_catalog_and_numeric_boundaries(self):
        item_id = self.register(active=False)
        self.run_cycle([self.deal()])[0].assert_not_called()
        item = db.get_monitored_item(item_id)
        item["required_terms"] = "kaido house, ef, 179"
        self.assertTrue(filters.identifies_monitored(self.deal(title="Kaido House Civic EF KHMG179"), item))
        self.assertFalse(filters.identifies_monitored(self.deal(title="Kaido House Civic EF KHMG1790"), item))
        self.assertFalse(filters.identifies_monitored(self.deal(title="Kaido House Civic Ref KHMG179"), item))

    def test_forbidden_terms_block_wrong_version(self):
        item_id = db.save_monitored_item(dict(name="84 Mustang SVO Power Trip", search_terms="mustang svo",
                                              required_terms="84, mustang, svo", forbidden_terms=" vermelho,, HTC66 ",
                                              max_price=60))
        item = db.get_monitored_item(item_id)
        self.assertEqual(item["forbidden_terms"], "vermelho, HTC66")
        self.assertTrue(filters.identifies_monitored(self.deal(title="Hot Wheels '84 Mustang Svo - Prata"), item))
        wrong = filters.monitored_match_diagnostic(self.deal(title="Hot Wheels - 84 Mustang SVO - HTC66"), item)
        self.assertFalse(wrong["matches"])
        self.assertEqual(wrong["forbidden_terms"], ["HTC66"])
        self.assertFalse(filters.identifies_monitored(self.deal(title="Miniatura Hot Wheels 84' Mustang SVO Vermelho"), item))
        self.assertTrue(filters.identifies_monitored(self.deal(title="Hot Wheels 84 Mustang SVO Avermelhado"), item))
        item["active"] = False
        db.save_monitored_item(item, item_id)
        self.assertEqual(db.get_monitored_item(item_id)["forbidden_terms"], "vermelho, HTC66")
        db.save_monitored_item(dict(item, forbidden_terms=""), item_id)
        self.assertEqual(db.get_monitored_item(item_id)["forbidden_terms"], "")

    def test_neutral_transition_preserves_prices_and_manual_pending(self):
        for pid in ("old", "manual-user"):
            deal = self.deal(pid)
            db.record_product_price(deal)
            db.mark_posted(pid, deal["store"], deal["title"], deal["price"], status="pending")
        self.assertEqual(db.reconcile_catalog_queue(), 1)
        self.assertEqual(db.reconcile_catalog_queue(), 0)
        with db._conn() as conn:
            self.assertEqual(dict(conn.execute("SELECT product_id,status FROM posted")),
                             {"old": "catalog_archived", "manual-user": "pending"})
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM product_prices WHERE verdict='seen'").fetchone()[0], 2)
        self.assertFalse(db.restore_decision("old"))

    def test_one_opportunity_and_price_improvement_after_decision(self):
        item_id = self.register(target=180)
        self.assertTrue(db.enqueue_catalog_opportunity(item_id, self.deal(price=170)))
        self.assertFalse(db.enqueue_catalog_opportunity(item_id, self.deal("worse", 175)))
        self.assertTrue(db.enqueue_catalog_opportunity(item_id, self.deal("better", 160)))
        self.assertFalse(db.restore_decision("cheap"))
        db.set_status("better", "rejected")
        self.assertFalse(db.enqueue_catalog_opportunity(item_id, self.deal("repeat", 160)))
        self.assertTrue(db.enqueue_catalog_opportunity(item_id, self.deal("drop", 150)))
        with db._conn() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM posted WHERE status='pending'").fetchone()[0], 1)

    def test_undo_outside_catalog_clears_only_selected_verdict(self):
        for pid in ("first", "second"):
            deal = self.deal(pid)
            db.mark_posted(pid, deal["store"], deal["title"], deal["price"], status="rejected")
            db.record_product_price(deal, "rejected")
        self.assertTrue(db.restore_decision("first"))
        with db._conn() as conn:
            self.assertEqual(dict(conn.execute("SELECT product_id,verdict FROM product_prices")),
                             {"first": "seen", "second": "rejected"})
            self.assertEqual(conn.execute("SELECT status FROM posted WHERE product_id='first'").fetchone()[0], "catalog_archived")
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM posted WHERE status='pending'").fetchone()[0], 0)

    def test_learned_opportunity_without_target_still_requires_review(self):
        self.register(target="")
        for i in range(1, 6):
            pid = f"history-{i}"
            db.record_product_price(self.deal(pid=pid, price=160))
            day = (datetime.now(timezone.utc) - timedelta(days=i)).strftime("%Y-%m-%d")
            with db._conn() as conn:
                conn.execute("UPDATE product_prices SET day=?,seen_at=? WHERE product_id=?",
                             (day, day + " 12:00:00", pid))
        self.run_cycle([self.deal(), self.deal("alternative", 160)])[2].assert_called_once()
        self.assertEqual(db.catalog_summary()["pending"], 1)

    def share_client(self):
        from dashboard import app
        item_id = self.register()
        db.set_setting(f"monitored_scan_{item_id}", {"results": [self.deal()]})
        client = app.test_client()
        with client.session_transaction() as session:
            session["authenticated"] = True
        return item_id, client

    def test_history_share_uses_stored_offer_and_coupon_without_publication(self):
        item_id, client = self.share_client()
        deal = self.deal()
        db.cache_affiliate_link(deal["store"], deal["url"], "https://meli.la/test")
        with patch("core.notifier.requests.post") as send:
            response = client.post(f"/api/monitored/{item_id}/share", json={
                "product_id": "cheap", "price": 1, "affiliate_url": "https://evil.test",
                "coupon": {"manual_coupon_code": "CUPOM10", "manual_coupon_value": 10,
                           "manual_coupon_type": "fixed", "manual_coupon_final_price": 130}})
        self.assertEqual(response.status_code, 200)
        self.assertIn("140.00", response.json["whatsapp"])
        self.assertIn("130.00", response.json["whatsapp"])
        self.assertIn("CUPOM10", response.json["whatsapp"])
        self.assertEqual(response.json["affiliate_url"], "https://meli.la/test")
        send.assert_not_called()
        with db._conn() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM manual_jobs").fetchone()[0], 0)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM posted").fetchone()[0], 0)

    def test_history_share_generates_link_in_urgent_job(self):
        from core import manual_jobs
        item_id, client = self.share_client()
        with patch("dashboard.health.bot_indicator", return_value={"online": True}):
            response = client.post(f"/api/monitored/{item_id}/share", json={"product_id": "cheap"})
        self.assertEqual(response.status_code, 200)
        job_id = response.json["job_id"]
        with patch.object(manual_jobs, "to_affiliate_url", return_value="https://meli.la/test"), \
                patch("core.notifier.requests.post") as send:
            manual_jobs.process_jobs(urgent_only=True)
        job = db.get_job(job_id)
        self.assertEqual(job["action"], "share_monitored")
        self.assertEqual(job["status"], "done")
        self.assertEqual(job["result"]["affiliate_url"], "https://meli.la/test")
        send.assert_not_called()
        with db._conn() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM posted").fetchone()[0], 0)

    def test_history_share_blocks_unmonetized_generation(self):
        from core import manual_jobs
        item_id, client = self.share_client()
        with patch("dashboard.health.bot_indicator", return_value={"online": True}):
            response = client.post(f"/api/monitored/{item_id}/share", json={"product_id": "cheap"})
        with patch.object(manual_jobs, "to_affiliate_url", return_value=self.deal()["url"]), \
                patch("core.notifier.requests.post") as send:
            manual_jobs.process_jobs(urgent_only=True)
        job = db.get_job(response.json["job_id"])
        self.assertEqual(job["status"], "error")
        self.assertIn("monetizado", job["error"])
        send.assert_not_called()

    def test_history_share_validates_offer_coupon_and_bot(self):
        item_id, client = self.share_client()
        self.assertEqual(client.post(f"/api/monitored/{item_id}/share", json={"product_id": "not-in-scan"}).status_code, 404)
        self.assertEqual(client.post(f"/api/monitored/{item_id}/share", json={"product_id": "cheap", "scan_completed_at": "stale"}).status_code, 409)
        response = client.post(f"/api/monitored/{item_id}/share", json={"product_id": "cheap", "coupon": {"manual_coupon_value": "NaN"}})
        self.assertEqual(response.status_code, 400)
        with patch("dashboard.health.bot_indicator", return_value={"online": False}):
            response = client.post(f"/api/monitored/{item_id}/share", json={"product_id": "cheap"})
        self.assertEqual(response.status_code, 503)
        self.assertNotIn("whatsapp", response.json)
        with db._conn() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM manual_jobs").fetchone()[0], 0)

    def test_history_confidence_counts_days_not_listing_volume(self):
        item_id = self.register()
        for i in range(10):
            db.record_price(item_id, self.deal(f"listing-{i}", 140 + i))
        summary = db.monitored_price_summary(item_id)
        self.assertEqual(summary["observations"], 10)
        self.assertEqual(summary["days"], 1)
        quality = db.deal_price_quality(CHEAP, 140, item_id)
        self.assertEqual(quality["key"], "initial")
        self.assertEqual(quality["days"], 1)

    def test_history_periods_and_page_labels(self):
        from dashboard import app
        item_id = self.register()
        for age, price in ((0, 140), (10, 120), (45, 100)):
            pid = f"age-{age}"
            db.record_price(item_id, self.deal(pid, price))
            with db._conn() as conn:
                conn.execute("UPDATE price_observations SET observed_at=datetime('now',?) WHERE product_id=?",
                             (f"-{age} days", pid))
        client = app.test_client()
        with client.session_transaction() as session:
            session["authenticated"] = True
        for days, count, minimum in ((7, 1, 140), (30, 2, 120), (90, 3, 100)):
            summary, daily, stores, recent = db.monitored_price_history(item_id, days)
            self.assertEqual(summary["observations"], count)
            self.assertEqual(summary["min_price"], minimum)
            self.assertEqual(len(daily), count)
            response = client.get(f"/monitored/{item_id}?days={days}")
            self.assertEqual(response.status_code, 200)
            self.assertIn(f"ÚLTIMOS {days} DIAS", response.get_data(as_text=True))
        response = client.get(f"/monitored/{item_id}?days=invalid")
        self.assertEqual(response.status_code, 200)
        self.assertIn("ÚLTIMOS 90 DIAS", response.get_data(as_text=True))

    def test_inline_target_update_preserves_catalog_state_and_history(self):
        item_id, client = self.share_client()
        item = db.get_monitored_item(item_id)
        item["active"] = False
        db.save_monitored_item(item, item_id)
        db.record_price(item_id, self.deal())
        response = client.post(f"/api/monitored/{item_id}/target", json={"max_price": "99.50"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["max_price"], 99.5)
        updated = db.get_monitored_item(item_id)
        self.assertFalse(updated["active"])
        self.assertEqual(updated["required_terms"], item["required_terms"])
        response = client.post(f"/api/monitored/{item_id}/target", json={"max_price": ""})
        self.assertEqual(response.json["max_price"], 0)
        for invalid in ("NaN", "Infinity", -1, "invalid"):
            self.assertEqual(client.post(f"/api/monitored/{item_id}/target", json={"max_price": invalid}).status_code, 400)
        self.assertEqual(client.post('/api/monitored/9999/target', json={"max_price": 90}).status_code, 404)
        with db._conn() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM price_observations").fetchone()[0], 1)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM monitored_items").fetchone()[0], 1)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM manual_jobs").fetchone()[0], 0)

    def test_inline_target_requires_authentication(self):
        from dashboard import app
        item_id = self.register()
        response = app.test_client().post(f"/api/monitored/{item_id}/target", json={"max_price": 1})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(db.get_monitored_item(item_id)["max_price"], 145)

    def test_queue_limit_is_twenty(self):
        for i in range(21):
            name = f"Mini GT Modelo ref{i}"
            item_id = self.register(target=180, name=name, required=f"ref{i}")
            result = db.enqueue_catalog_opportunity(item_id, self.deal(f"p{i}", 150, name))
            self.assertEqual(result, i < 20)
        self.assertEqual(db.catalog_summary()["pending"], 20)

    def test_cycle_limit_is_five(self):
        deals = []
        for i in range(7):
            name = f"Mini GT Modelo ref{i}"
            self.register(target=180, name=name, required=f"ref{i}")
            deals.append(self.deal(f"p{i}", 150, name))
        scraper, affiliate, notify = self.run_cycle(deals)
        self.assertLessEqual(scraper.call_count, 3)
        self.assertEqual(notify.call_count, 5)
        self.assertEqual(db.catalog_summary()["pending"], 5)


if __name__ == "__main__":
    unittest.main()
