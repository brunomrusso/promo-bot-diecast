import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import requests

from core import db, manual_jobs as jobs


URL = "https://www.mercadolivre.com.br/p/MLB2097324092?pdp_filters=item_id:MLB7539980778"
PRODUCT = {"name": "Ferrari", "pictures": [{"url": "https://example.com/photo.jpg"}]}
OFFER = {"item_id": "MLB7539980778", "price": 54.5, "currency_id": "BRL"}


class ManualExtractionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        p = patch.object(db, "DB_PATH", Path(self.tmp.name) / "deals.db")
        p.start()
        self.addCleanup(p.stop)
        p = patch("scrapers.mercadolivre.ml_api_ready", return_value=True)
        p.start()
        self.addCleanup(p.stop)

    def test_exact_offer_without_browser_or_invented_discount(self):
        offers = {"results": [dict(OFFER, item_id="MLB1", price=1), OFFER]}
        with patch("scrapers.mercadolivre._api", side_effect=[PRODUCT, offers]), \
                patch.object(jobs, "_get_context") as browser:
            result = jobs.extract_link(URL)
        browser.assert_not_called()
        self.assertEqual(result["price"], 54.5)
        self.assertEqual(result["original_price"], 54.5)
        self.assertEqual(result["discount"], 0)
        self.assertEqual(result["extraction_method"], "ml_catalog_api")
        self.assertEqual(result["origin"], "unknown")

    def test_missing_exact_offer_uses_browser(self):
        with patch("scrapers.mercadolivre._api", side_effect=[PRODUCT, {"results": []}]), \
                patch.object(jobs, "_extract_link_browser", return_value={"store": "Mercado Livre"}) as browser:
            jobs.extract_link(URL)
        browser.assert_called_once_with(jobs._clean_url(URL))

    def test_catalog_without_selected_seller_does_not_choose_offer(self):
        with patch("scrapers.mercadolivre._api") as api:
            self.assertIsNone(jobs._extract_ml_api("https://www.mercadolivre.com.br/p/MLB2097324092"))
        api.assert_not_called()

    def test_missing_oauth_skips_http_and_api(self):
        with patch("scrapers.mercadolivre.ml_api_ready", return_value=False), \
                patch.object(jobs.http_requests, "get") as get:
            self.assertIsNone(jobs._extract_ml_api("https://meli.la/example"))
        get.assert_not_called()

    def test_explicit_variation_keeps_browser_path(self):
        with patch("scrapers.mercadolivre._api") as api:
            self.assertIsNone(jobs._extract_ml_api(URL + "&variation_id=123"))
        api.assert_not_called()

    def test_denial_or_timeout_falls_back(self):
        for outcome in (None, requests.Timeout()):
            with self.subTest(outcome=outcome), \
                    patch("scrapers.mercadolivre._api", side_effect=outcome if isinstance(outcome, Exception) else None,
                          return_value=None), \
                    patch.object(jobs, "_extract_link_browser", return_value={"store": "Mercado Livre"}) as browser:
                jobs.extract_link(URL)
                browser.assert_called_once()

    def test_social_link_resolves_only_explicit_product(self):
        redirect = Mock(is_redirect=True, headers={"Location": "https://www.mercadolivre.com.br/social/example?ref=keep"})
        social = Mock(is_redirect=False, text=(
            '<a href="https://www.mercadolivre.com.br/p/MLB1">Recomendado</a>'
            f'<a href="{URL}"><span>Ir para produto</span></a>'))
        with patch.object(jobs.http_requests, "get", side_effect=[redirect, social]), \
                patch("scrapers.mercadolivre._api", side_effect=[PRODUCT, {"results": [OFFER]}]), \
                patch.object(jobs, "_get_context") as browser:
            result = jobs.extract_link("https://meli.la/example")
        browser.assert_not_called()
        self.assertEqual(result["affiliate_url"], "https://meli.la/example")
        self.assertEqual(result["url"], jobs._clean_url(URL))

    def test_ambiguous_social_links_and_external_redirect_rejected(self):
        social = Mock(is_redirect=False, text=(
            f'<a href="{URL}">Ir para produto</a>'
            '<a href="https://www.mercadolivre.com.br/p/MLB2">Ir para produto</a>'))
        redirect = Mock(is_redirect=True, headers={"Location": "https://example.com/product"})
        for response in (social, redirect):
            with patch.object(jobs.http_requests, "get", return_value=response) as get:
                self.assertIsNone(jobs._ml_product_url("https://meli.la/example"))
                get.assert_called_once()

    def test_invalid_price_or_missing_image_rejected(self):
        for product, offer in [(PRODUCT, dict(OFFER, price=0)),
                               (PRODUCT, dict(OFFER, price=float("nan"))),
                               ({"name": "Ferrari"}, OFFER)]:
            with patch("scrapers.mercadolivre._api", side_effect=[product, {"results": [offer]}]):
                self.assertIsNone(jobs._extract_ml_api(URL))

    def test_extract_job_does_not_regenerate_submitted_affiliate_link(self):
        import json
        row = {"id": 1, "action": "extract", "payload": json.dumps({"url": URL})}
        deal = {"store": "Mercado Livre", "affiliate_url": "https://meli.la/example"}
        with patch.object(db, "claim_jobs", return_value=[row]), \
                patch.object(jobs, "extract_link", return_value=deal), \
                patch.object(jobs, "to_affiliate_url") as generate, \
                patch.object(jobs, "format_whatsapp", return_value="text"), \
                patch.object(db, "finish_job") as finish:
            jobs.process_jobs()
        generate.assert_not_called()
        self.assertEqual(finish.call_args.args[1]["affiliate_url"], "https://meli.la/example")

    def test_common_link_still_generates_affiliate_link(self):
        import json
        row = {"id": 1, "action": "extract", "payload": json.dumps({"url": URL})}
        with patch.object(db, "claim_jobs", return_value=[row]), \
                patch.object(jobs, "extract_link", return_value={"store": "Mercado Livre", "url": URL}), \
                patch.object(jobs, "to_affiliate_url", return_value="https://meli.la/generated") as generate, \
                patch.object(jobs, "format_whatsapp", return_value="text"), \
                patch.object(db, "finish_job") as finish:
            jobs.process_jobs()
        generate.assert_called_once()
        self.assertTrue(finish.call_args.args[1]["monetized"])

    def test_browser_fallback_also_preserves_affiliate_link(self):
        with patch.object(jobs, "_extract_ml_api", return_value=None), \
                patch.object(jobs, "_extract_link_browser", return_value={"store": "Mercado Livre", "url": URL}):
            result = jobs.extract_link("https://meli.la/example")
        self.assertEqual(result["affiliate_url"], "https://meli.la/example")


if __name__ == "__main__":
    unittest.main()
