import gc
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core import db, site_export



# Os testes não podem depender das etiquetas/IDs por canal configurados no .env do servidor.
_canais = patch.multiple("config", ML_TAG_BOT="", ML_TAG_SITE="")


def setUpModule():
    _canais.start()


def tearDownModule():
    _canais.stop()

class SiteExportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path_patch = patch.object(db, "DB_PATH", Path(self.temp.name) / "deals.db")
        self.path_patch.start()

    def tearDown(self):
        self.path_patch.stop()
        gc.collect()
        self.temp.cleanup()

    def mini(self, name, alvo, cat="hot-wheels", enabled=True):
        item_id = db.save_monitored_item(dict(name=name, search_terms=name.lower(), required_terms=name.split()[-1].lower(), max_price=alvo))
        db.set_monitored_site(item_id, enabled, cat)
        return item_id

    def obs(self, item_id, pid, store, price, url, image=""):
        db.record_price(item_id, dict(id=pid, store=store, title="Anúncio", price=price, original_price=price, url=url, image=image))

    def test_category_required(self):
        item_id = db.save_monitored_item(dict(name="Porsche 993", search_terms="porsche 993", required_terms="993", max_price=60))
        with self.assertRaises(ValueError):
            db.set_monitored_site(item_id, True, "")
        db.set_monitored_site(item_id, False, "")

    @patch("core.site_export.to_affiliate_url")
    def test_build_ml_and_amazon(self, aff):
        aff.side_effect = lambda d: "https://meli.la/abc" if d["store"] == "Mercado Livre" else "https://www.amazon.com.br/dp/B0FK1F7PTQ?tag=promocoesdiec-20"
        with patch("config.AMAZON_TAG", "promocoesdiec-20"), patch("config.AMAZON_TAG_SITE", "russosite-20"):
            ml = self.mini("Hot Wheels Skyline", 45)
            self.obs(ml, "ml-MLB123", "Mercado Livre", 50, "https://www.mercadolivre.com.br/p/MLB123", "https://http2.mlstatic.com/D_Q_NP_2X_756084-MLB118718314622_102026-AB.webp")
            self.obs(ml, "ml-MLB999", "Mercado Livre", 39.9, "https://www.mercadolivre.com.br/p/MLB999", "https://http2.mlstatic.com/D_NQ_NP_640-MLA1_012026-O.webp")
            az = self.mini("Hot Wheels Porsche", 60)
            self.obs(az, "amz-B0FK1F7PTQ", "Amazon", 56.42, "https://www.amazon.com.br/dp/B0FK1F7PTQ")
            self.mini("Hot Wheels Sem Oferta", 30)
            self.mini("Hot Wheels Desligado", 30, enabled=False)
            items, skipped = site_export.build_app_items()
        by = {i["loja"]: i for i in items}
        self.assertEqual(len(items), 2)
        m = by["mercadolivre"]
        self.assertEqual(m["id"], "ach-ml-MLB999")
        self.assertEqual(m["preco"], 39.9)
        self.assertTrue(m["ativo"])
        self.assertEqual(m["imagem"], "https://http2.mlstatic.com/D_NQ_NP_2X_640-MLA1_012026-F.webp")
        self.assertEqual(len(m["historico"]), 1)
        a = by["amazon"]
        self.assertEqual(a["asin"], "B0FK1F7PTQ")
        self.assertEqual(a["link_afiliado"], "https://www.amazon.com.br/dp/B0FK1F7PTQ?tag=russosite-20")  # site usa o ID do site
        self.assertNotIn("preco", a)
        self.assertNotIn("imagem", a)
        self.assertEqual(skipped, [("Hot Wheels Sem Oferta", "sem oferta recente no ML/Amazon")])

    @patch("core.site_export.to_affiliate_url", return_value="https://www.mercadolivre.com.br/p/MLB1")
    def test_unmonetized_link_skipped(self, _):
        ml = self.mini("Hot Wheels Skyline", 45)
        self.obs(ml, "ml-MLB1", "Mercado Livre", 40, "https://www.mercadolivre.com.br/p/MLB1")
        items, skipped = site_export.build_app_items()
        self.assertEqual(items, [])
        self.assertEqual(skipped[0][1], "link de afiliado não gerado")

    def test_merge_keeps_manual_items(self):
        current = {"atualizado_em": "2026-11-04", "itens": [
            {"id": "ach-ml-MLB62900191", "loja": "mercadolivre"},
            {"id": "ach-ml-OLD", "origem": "app"},
            {"id": "ach-az-B0FK1F7PTQ", "loja": "amazon"}]}
        app = [{"id": "ach-az-B0FK1F7PTQ", "origem": "app"}, {"id": "ach-ml-NEW", "origem": "app"}]
        merged = site_export.merge(current, app)
        self.assertEqual([i["id"] for i in merged["itens"]], ["ach-ml-MLB62900191", "ach-az-B0FK1F7PTQ", "ach-ml-NEW"])

    @patch("core.site_export._upload")
    @patch("core.site_export._fetch_current")
    @patch("core.site_export.build_app_items")
    def test_publish_only_when_changed(self, build, fetch, upload):
        build.return_value = ([{"id": "ach-ml-NEW", "origem": "app"}], [])
        fetch.return_value = {"itens": [{"id": "ach-ml-NEW", "origem": "app"}]}
        with patch("config.SITE_FTP_HOST", "ftp.x"), patch("config.SITE_FTP_USER", "u"):
            r = site_export.publish()
            self.assertEqual(r["status"], "ok")
            self.assertFalse(r["changed"])
            upload.assert_not_called()
            fetch.return_value = {"itens": []}
            r = site_export.publish()
            self.assertTrue(r["changed"])
            sent = json.loads(upload.call_args[0][0])
            self.assertEqual(sent["itens"][0]["id"], "ach-ml-NEW")
        self.assertEqual(db.get_system_state()["site_export"]["value"]["status"], "ok")

    @patch("core.site_export._upload")
    @patch("core.site_export._fetch_current")
    @patch("core.site_export.build_app_items")
    def test_so_a_hora_da_consulta_mudou_nao_envia(self, build, fetch, upload):
        from datetime import datetime, timedelta
        agora = datetime.now(site_export.ZONE).replace(tzinfo=None)
        f = lambda dt: dt.strftime("%Y-%m-%dT%H:%M")
        build.return_value = ([{"id": "ach-ml-1", "origem": "app", "preco": 50.0, "preco_consultado_em": f(agora)}], [])
        fetch.return_value = {"itens": [{"id": "ach-ml-1", "origem": "app", "preco": 50.0, "preco_consultado_em": f(agora - timedelta(minutes=15))}]}
        with patch("config.SITE_FTP_HOST", "ftp.x"), patch("config.SITE_FTP_USER", "u"):
            self.assertFalse(site_export.publish()["changed"])  # só a hora mudou: não envia
            upload.assert_not_called()
            fetch.return_value["itens"][0]["preco_consultado_em"] = f(agora - timedelta(hours=7))
            self.assertTrue(site_export.publish()["changed"])   # hora do site ficou velha: reenvia
            fetch.return_value["itens"][0]["preco_consultado_em"] = f(agora - timedelta(minutes=15))
            build.return_value[0][0]["preco"] = 45.0
            self.assertTrue(site_export.publish()["changed"])   # preço mudou: envia

    def test_publish_disabled_without_ftp(self):
        with patch("config.SITE_FTP_HOST", ""):
            self.assertEqual(site_export.publish()["status"], "disabled")

    def test_dashboard_saves_site_fields(self):
        from dashboard import app
        with app.test_client() as client:
            with client.session_transaction() as s:
                s["authenticated"] = True
            r = client.post("/monitored", data=dict(name="Mini GT Supra", search_terms="mini gt supra", required_terms="supra",
                                                    max_price="150", active="on", site_form="1", site_enabled="on", site_category="mini-gt"))
            self.assertEqual(r.status_code, 302)
            item = db.list_monitored_items()[0]
            self.assertEqual((item["site_enabled"], item["site_category"]), (1, "mini-gt"))
            page = client.get("/monitored")
            self.assertIn("Achadinhos no site".encode(), page.data)
            self.assertIn("No site · Mini GT".encode(), page.data)
            client.post(f"/monitored/{item['id']}/toggle", data={"active": "0"})
            self.assertEqual(db.get_monitored_item(item["id"])["site_enabled"], 1)



class MercadoLivreFallbackTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path_patch = patch.object(db, "DB_PATH", Path(self.temp.name) / "deals.db")
        self.path_patch.start()

    def tearDown(self):
        self.path_patch.stop()
        gc.collect()
        self.temp.cleanup()

    def test_invalid_refresh_disables_api_and_falls_back(self):
        import scrapers
        from scrapers import mercadolivre
        db.set_system_state("ml_oauth", {"access_token": "x", "refresh_token": "r", "expires_at": "2000-01-01T00:00:00"})
        self.assertTrue(mercadolivre.ml_api_ready())

        class Resp:
            status_code = 400
        with patch("scrapers.mercadolivre.requests.post", return_value=Resp()):
            self.assertIsNone(mercadolivre.search_mercadolivre("mini gt", 0))
        self.assertFalse(mercadolivre.ml_api_ready())
        with patch.object(scrapers, "_search_ml_pw", return_value=[{"id": "ml-1"}]) as pw:
            self.assertEqual(scrapers.search_mercadolivre("mini gt", 0), [{"id": "ml-1"}])
            pw.assert_called_once()

    def test_api_failure_falls_back_even_with_valid_token(self):
        import scrapers
        with patch.object(scrapers, "ml_api_ready", return_value=True), \
             patch.object(scrapers, "_search_ml_api", return_value=None), \
             patch.object(scrapers, "_search_ml_pw", return_value=[]) as pw:
            self.assertEqual(scrapers.search_mercadolivre("mini gt", 0), [])
            pw.assert_called_once()
        with patch.object(scrapers, "ml_api_ready", return_value=True), \
             patch.object(scrapers, "_search_ml_api", return_value=None), \
             patch.object(scrapers, "_search_ml_pw", None):
            with self.assertRaises(RuntimeError):
                scrapers.search_mercadolivre("mini gt", 0)



class ExpiryAndQuietTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path_patch = patch.object(db, "DB_PATH", Path(self.temp.name) / "deals.db")
        self.path_patch.start()

    def tearDown(self):
        self.path_patch.stop()
        gc.collect()
        self.temp.cleanup()

    def _deal(self, price=38.9):
        return dict(id="ml-MLB1", store="Mercado Livre", title="Hot Wheels Honda Del Sol 1994", price=price,
                    original_price=price, discount=0, origin="national",
                    url="https://www.mercadolivre.com.br/p/MLB1", image="")

    def test_expired_opportunity_can_be_presented_again(self):
        item = db.save_monitored_item(dict(name="Honda Del Sol", search_terms="del sol", required_terms="del sol", max_price=43))
        self.assertTrue(db.enqueue_catalog_opportunity(item, self._deal()))
        with db._conn() as c:
            c.execute("UPDATE posted SET posted_at=datetime('now','-30 hours')")
        db.expire_pending()
        with db._conn() as c:
            self.assertEqual(c.execute("SELECT status FROM posted").fetchone()[0], "expired")
        self.assertTrue(db.enqueue_catalog_opportunity(item, self._deal()))

    def test_decided_opportunity_still_needs_3pct_drop(self):
        item = db.save_monitored_item(dict(name="Honda Del Sol", search_terms="del sol", required_terms="del sol", max_price=43))
        self.assertTrue(db.enqueue_catalog_opportunity(item, self._deal()))
        db.set_status("ml-MLB1", "rejected")
        self.assertFalse(db.enqueue_catalog_opportunity(item, self._deal()))
        self.assertTrue(db.enqueue_catalog_opportunity(item, self._deal(36.0)))

    def test_quiet_hours_opportunity_is_sent_later(self):
        import main
        item = db.save_monitored_item(dict(name="Honda Del Sol", search_terms="del sol", required_terms="del sol", max_price=43))
        db.enqueue_catalog_opportunity(item, self._deal())
        with patch("config.TELEGRAM_ADMIN_CHAT_ID", "1"), patch.object(main, "_is_quiet", return_value=False), \
             patch.object(main, "send_for_approval", return_value=True) as send, \
             patch.object(main, "to_affiliate_url", return_value="https://meli.la/x"), patch.object(main.time, "sleep"):
            main._notify_pending_after_quiet()
            main._notify_pending_after_quiet()
        send.assert_called_once()

    def test_link_do_site_recusado_nao_tenta_a_cada_ciclo(self):
        from core import affiliate
        url = "https://produto.mercadolivre.com.br/MLB-123"
        chamadas = []
        def gerar(u, tag, fallback=True):
            chamadas.append(u)
            return u  # o ML recusou (HTTP 400/409): volta o próprio link, sem meli.la
        with patch("config.ML_TAG_SITE", "russosite"), patch("scrapers.ml_coupons.ml_affiliate_link", gerar), \
             patch("scrapers.ml_coupons.ml_available", lambda: True):
            self.assertEqual(affiliate.ml_site_link(url), url)
            self.assertEqual(affiliate.ml_site_link(url), "")  # próximo ciclo: não reabre o Gerador de Links
            self.assertEqual(len(chamadas), 1)
            affiliate.ml_site_link(url, insistir=True)  # pedido do painel tenta mesmo assim
            self.assertEqual(len(chamadas), 2)
        ok = lambda u, tag, fallback=True: "https://meli.la/abc"
        with patch("config.ML_TAG_SITE", "russosite"), patch("scrapers.ml_coupons.ml_affiliate_link", ok), \
             patch("scrapers.ml_coupons.ml_available", lambda: True):
            self.assertEqual(affiliate.ml_site_link(url, insistir=True), "https://meli.la/abc")
        self.assertNotIn(url, db.get_setting(affiliate.ML_LINK_FALHAS_KEY, {}))

    def test_mini_congelada_nao_volta_para_aprovacao(self):
        item = db.save_monitored_item(dict(name="Honda Del Sol", search_terms="del sol", required_terms="del sol", max_price=43))
        self.assertEqual(db.frozen_monitored_items(24), set())
        self.assertTrue(db.enqueue_catalog_opportunity(item, self._deal()))
        self.assertEqual(db.frozen_monitored_items(24), {item})  # acabou de ir para aprovação
        self.assertEqual(db.frozen_monitored_items(0), set())    # 0 desliga
        with db._conn() as c:
            c.execute("UPDATE posted SET posted_at=datetime('now','-30 hours')")
            c.execute("UPDATE catalog_opportunities SET last_notified_at=datetime('now','-30 hours')")
        self.assertEqual(db.frozen_monitored_items(24), set())   # passou o tempo: volta para o fim da fila
        db.set_status("ml-MLB1", "rejected")                      # decisão (ignorada) recomeça o congelamento
        self.assertEqual(db.frozen_monitored_items(24), {item})

    def test_cupom_sem_campos_obrigatorios(self):
        from core.manual_jobs import normalize_manual_coupon
        base = dict(id="x", store="Mercado Livre", title="T", price=100.0)
        self.assertNotIn("manual_coupon_code", normalize_manual_coupon(dict(base, manual_coupon_code="", manual_coupon_type="fixed")))
        so_codigo = normalize_manual_coupon(dict(base, manual_coupon_code="promo10"))
        self.assertEqual((so_codigo["manual_coupon_code"], so_codigo["manual_coupon_final_price"]), ("PROMO10", 0))
        pct = normalize_manual_coupon(dict(base, manual_coupon_code="", manual_coupon_type="percent", manual_coupon_value=10))
        self.assertEqual((pct["manual_coupon_code"], pct["manual_coupon_final_price"]), ("", 90.0))
        with self.assertRaises(ValueError):
            normalize_manual_coupon(dict(base, manual_coupon_code="X", manual_coupon_value=10, manual_coupon_min_purchase=150))
        from core.notifier import format_whatsapp
        self.assertIn("Cupom: *PROMO10*", format_whatsapp(so_codigo, "https://meli.la/x"))
        self.assertNotIn("Com cupom", format_whatsapp(so_codigo, "https://meli.la/x"))
        self.assertIn("Ative o cupom na página", format_whatsapp(pct, "https://meli.la/x"))


if __name__ == "__main__":
    unittest.main()
