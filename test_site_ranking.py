import gc
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core import db, site_ranking as sr

ML_PAGE = """
<a href="/mais-vendidos/MLB2097?brand=1">Mini GT</a><a href="https://www.mercadolivre.com.br/mais-vendidos/MLB2097?b=2">Hot Wheels</a>
<ol>
<li class="ui-search-layout__item"><span>1º MAIS VENDIDO</span><img data-src="https://http2.mlstatic.com/D_Q_NP_756084-MLB118718314622_102026-O.webp">
 <a class="poly-component__title" href="https://www.mercadolivre.com.br/carro/up/MLBU2796847046#x">Chevy Silverado Kaido House Mini Gt</a>
 <div class="poly-price__current"><span class="andes-money-amount__fraction">1.193</span><span class="andes-money-amount__cents">51</span></div></li>
<li class="ui-search-layout__item"><span>2º mais vendido</span><img src="https://http2.mlstatic.com/D_Q_NP_678948-MLA94869475485_102025-O.webp">
 <a class="poly-component__title" href="https://www.mercadolivre.com.br/x/p/MLB59883218">Hot Wheels Monster Truck</a>
 <div class="poly-price__current"><span class="andes-money-amount__fraction">33</span></div></li>
<li class="ui-search-layout__item"><span>3º MAIS VENDIDO</span>
 <a class="poly-component__title" href="https://produto.mercadolivre.com.br/MLB-123">Sem foto</a></li>
</ol>"""

AZ_PAGE = """<div data-client-recs-list='[{"id":"B000GKUEVE","metadataMap":{"render.zg.rank":"1"}},{"id":"B0AAAAAAAA","metadataMap":{"render.zg.rank":"2"}}]'></div>
<div id="gridItemRoot"><a href="/Hot-Wheels/dp/B000GKUEVE/ref=x"><img alt="Hot Wheels Pacote com 5 | Mattel"></a></div>"""

ML_JSON_PAGE = ("<html><body><div class='layout-novo'></div><script id=\"__NORDIC_RENDERING_CTX__\">_n.ctx.r=" + json.dumps({
    "appProps": {"pageProps": {"initialState": {"results": [{"trends_categories": {"polycards": [
        {"metadata": {"id": "MLB7358347786", "url": "www.mercadolivre.com.br/conjunto/p/MLB35762220"},
         "pictures": {"pictures": [{"id": "724815-MLA99876815105_112025"}]},
         "float_highlight_generic": {"highlight": {"text": "1º MAIS VENDIDO"}},
         "components": [{"type": "title", "title": {"text": "Conjunto 5 Carrinhos Hot Wheels"}},
                        {"type": "price", "price": {"current_price": {"value": 72.99}}}]},
        {"metadata": {"id": "MLB1", "url": "www.mercadolivre.com.br/x/up/MLBU4204668530", "signal": {"prc": 21.99}},
         "pictures": {"pictures": [{"id": "678948-MLA94869475485_102025"}]},
         "float_highlight_generic": {"highlight": {"text": "2º MAIS VENDIDO"}},
         "components": [{"type": "title", "title": {"text": "Carrinho Hot Wheels 2026"}}]},
        {"metadata": {"url": "www.mercadolivre.com.br/y/p/MLB9"}, "components": []}]}}]}}}})
    + ";_n.ctx.r.assets={}</script></body></html>")


class SiteRankingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.p = patch.object(db, "DB_PATH", Path(self.temp.name) / "deals.db")
        self.p.start()

    def tearDown(self):
        self.p.stop()
        gc.collect()
        self.temp.cleanup()

    def test_parse_ml(self):
        links = sr.ml_links(ML_PAGE)
        self.assertTrue(links["mini gt"].startswith("https://www.mercadolivre.com.br/mais-vendidos/MLB2097"))
        items = sr.ml_items(ML_PAGE)
        self.assertEqual([i["id"] for i in items], ["MLBU2796847046", "MLB59883218"])  # sem foto fica de fora
        self.assertEqual(items[0]["preco"], 1193.51)
        self.assertEqual(items[0]["k"], "756084-MLB118718314622_102026")
        self.assertEqual(items[1]["pos"], 2)
        self.assertEqual(sr.pick_ml({"hot-wheels": items})["hot-wheels"][0]["id"], "MLBU2796847046")  # monster sai

    def test_parse_az(self):
        ranks, titles = sr.az_ranking(AZ_PAGE)
        self.assertEqual(ranks, [("B000GKUEVE", 1), ("B0AAAAAAAA", 2)])
        self.assertEqual(titles["B000GKUEVE"], "Hot Wheels Pacote com 5 | Mattel")
        self.assertEqual(sr.az_name("Hot Wheels Pacote com 5 | Mattel"), "Hot Wheels Pacote com 5")

    def test_pokemon_filter(self):
        ok = ["Pokémon Coleção com Poster 21 Cartas", "Pokemon Ferramentas de Treinador 94 Cartas"]
        bad = ["Poker cartas", "100 Cartas Pokémon Com 10 Brilhantes", "Kit 55 Cartas Pokémon Gold",
               "Lote 100 Cartas Pokémon", "Cartas Pokémon Douradas Metálicas", "Sleeve Pokémon 65 un", "Pasta Pokémon"]
        self.assertTrue(all(sr.pokemon_ok(t) for t in ok))
        self.assertFalse(any(sr.pokemon_ok(t) for t in bad))

    def test_assemble_reuses_links_and_names(self):
        current = {"fonte": "f", "categorias": [{"id": "hot-wheels"}, {"id": "pixar-cars"}], "produtos": [
            {"id": "hot-wheels-01", "loja": "mercadolivre", "id_ml": "MLB1", "nome": "Nome antigo", "preco": 10,
             "categoria": "hot-wheels", "link_afiliado": "https://meli.la/old"},
            {"id": "hot-wheels-02", "loja": "mercadolivre", "id_ml": "MLB9", "nome": "Saiu", "categoria": "hot-wheels",
             "link_afiliado": "https://meli.la/x"},
            {"id": "az-hot-wheels-01", "loja": "amazon", "asin": "B000000001", "nome": "AZ antigo", "categoria": "hot-wheels",
             "link_afiliado": "https://link.amazon/abc"}]}
        ml = {"hot-wheels": [{"id": "MLB2", "t": "Novo HW", "preco": 20.0, "k": "1-MLB2_1", "pos": 1},
                             {"id": "MLB1", "t": "Título ML", "preco": 12.5, "k": "1-MLB1_1", "pos": 2},
                             {"id": "MLB3", "t": "Sem link", "preco": 5.0, "k": "1-MLB3_1", "pos": 3}],
              "pixar-cars": [{"id": "MLB4", "t": "Carros McQueen", "preco": 30.0, "k": "1-MLB4_1", "pos": 7}]}
        az = {"hot-wheels": [{"asin": "B000000001", "rank": 3, "t": "x"}, {"asin": "B000000002", "rank": 9, "t": "Hot Wheels Novo | Mattel"}]}
        links = {"MLB2": "https://meli.la/new", "MLB4": "https://meli.la/px", "MLB3": "https://www.mercadolivre.com.br/p/MLB3"}
        with patch("config.AMAZON_TAG", "promocoesdiec-20"):
            out, rep = sr.assemble(current, {"itens": []}, ml, az, "2026-11-06", lambda i: links[i])
            sr.check_safe(current, out)
        p = {x["id"]: x for x in out["produtos"]}
        self.assertEqual(p["hot-wheels-01"]["link_afiliado"], "https://meli.la/new")
        self.assertEqual(p["hot-wheels-02"]["nome"], "Nome antigo")
        self.assertEqual(p["hot-wheels-02"]["preco"], 12.5)
        self.assertNotIn("hot-wheels-03", p)  # sem meli.la não entra
        self.assertEqual(rep["sem_link"], ["hot-wheels: Sem link"])
        self.assertEqual(p["pixar-cars-01"]["posicao_ml"], 7)
        self.assertEqual(p["az-hot-wheels-01"]["link_afiliado"], "https://link.amazon/abc")
        self.assertEqual(p["az-hot-wheels-02"]["link_afiliado"], "https://www.amazon.com.br/dp/B000000002?tag=promocoesdiec-20")
        self.assertEqual(p["az-hot-wheels-02"]["nome"], "Hot Wheels Novo")
        self.assertNotIn("preco", p["az-hot-wheels-02"])
        self.assertTrue(any("Saiu" in r for r in rep["removidos"]))
        self.assertEqual([x["id"] for x in out["produtos"]][:2], ["hot-wheels-01", "hot-wheels-02"])

    def test_ml_plano_b_json(self):
        self.assertEqual(sr.ml_items(ML_JSON_PAGE), [])
        sr._avisos.clear()
        items = sr.ml_items_any(ML_JSON_PAGE, "Hot Wheels")
        self.assertEqual([(i["id"], i["pos"], i["preco"]) for i in items], [("MLB35762220", 1, 72.99), ("MLBU4204668530", 2, 21.99)])
        self.assertEqual(items[0]["k"], "724815-MLA99876815105_112025")
        self.assertIn("plano B", sr._avisos[0])
        sr._avisos.clear()
        self.assertEqual(len(sr.ml_items_any(ML_PAGE)), 2)  # HTML normal: não usa o plano B... (só 2 itens válidos, JSON vazio)
        self.assertEqual(sr._avisos, [])

    def test_ml_filter_link_cache(self):
        pages = {sr.ML + "/mais-vendidos/MLB2097": ML_PAGE}
        with patch.object(sr, "_ml_page_html", lambda u: pages.get(u, ML_PAGE)), patch.object(sr, "_pause", lambda: None):
            sr._avisos.clear()
            sr.collect_ml(["mini-gt"])
            self.assertTrue(db.get_setting(sr.ML_LINKS_KEY)["mini-gt|mini gt"].startswith("https://www.mercadolivre.com.br/mais-vendidos/MLB2097"))
            pages[sr.ML + "/mais-vendidos/MLB2097"] = "<html>sem links</html>"
            sr.collect_ml(["mini-gt"])  # link sumiu: usa o último que funcionou, não para
            self.assertTrue(any("último link" in a for a in sr._avisos))
            db.set_setting(sr.ML_LINKS_KEY, {})
            with self.assertRaises(sr.Unsafe):
                sr.collect_ml(["mini-gt"])

    def test_failure_alerts_once_then_on_third(self):
        site = {"categorias": [{"id": "lego"}], "produtos": []}
        sent = []
        def boom(cats):
            raise sr.Blocked("Mercado Livre pede verificação manual (sessão do bot)")
        esc = {"cats": ["lego"], "lojas": ["mercadolivre"], "achadinhos": False}
        with patch("config.AMAZON_TAG", "promocoesdiec-20"), patch.object(sr, "_site_json", lambda n: site), \
                patch.object(sr, "collect_ml", boom), patch("core.notifier.notify_admin", lambda m, *a, **k: sent.append(m)):
            for _ in range(4):
                sr.run(publish=False, escopo=esc)
            self.assertEqual(len(sent), 2)
            self.assertIn("abrir-login-ml.cmd", sent[0])
            self.assertIn("3 vezes seguidas", sent[1])
            with patch.object(sr, "collect_ml", lambda cats: {"lego": []}):
                st = sr.run(publish=False, escopo=esc)
        self.assertEqual(st["status"], "ok")
        self.assertIn("Voltou a funcionar depois de 4", sent[-1])
        self.assertEqual(db.get_setting(sr.FAIL_KEY), 0)

    def test_cancel_stops_before_publishing(self):
        site = {"categorias": [{"id": "lego"}], "produtos": []}
        def fake_collect(cats):
            self.assertTrue(sr.request_cancel())
            sr._progress("Mercado Livre", 10)
            raise AssertionError("não devia continuar")
        with patch("config.AMAZON_TAG", "promocoesdiec-20"), patch.object(sr, "_site_json", lambda n: site), \
                patch.object(sr, "collect_ml", fake_collect), patch.object(sr, "_publish_files") as pub, \
                patch("core.notifier.notify_admin", lambda *a, **k: None):
            st = sr.run(publish=True, escopo={"cats": ["lego"], "lojas": ["mercadolivre"], "achadinhos": False})
        self.assertEqual(st["status"], "cancelado")
        pub.assert_not_called()
        self.assertFalse(sr.request_cancel())  # nada rodando
        self.assertIsNone(db.get_setting(sr.CANCEL_KEY, None))

    def test_blokees_category_added_once(self):
        cur = {"categorias": [{"id": c} for c in ["mini-gt", "hot-wheels", "pixar-cars", "lego", "funko", "pokemon-tcg"]], "produtos": []}
        out = sr.ensure_cats(cur)
        self.assertEqual([c["id"] for c in out["categorias"]],
                         ["mini-gt", "hot-wheels", "pixar-cars", "lego", "funko", "blokees", "pokemon-tcg"])
        self.assertEqual(out["categorias"][5]["nome"], "Blokees")
        self.assertEqual(sr.ensure_cats(out)["categorias"], out["categorias"])
        self.assertEqual(len(cur["categorias"]), 6)  # original intocado
        self.assertTrue(sr.ML_FILTERS["blokees"]("Boneco Blokees Saint Seiya Champion Class"))
        self.assertFalse(sr.ML_FILTERS["blokees"]("Funko Pop Naruto"))

    def test_check_safe_blocks_missing_category(self):
        old = {"produtos": [{"id": f"lego-{i}", "loja": "mercadolivre", "categoria": "lego", "link_afiliado": "https://meli.la/a"} for i in range(5)]}
        with self.assertRaises(sr.Unsafe):
            sr.check_safe(old, {"produtos": []})

    def test_achadinhos(self):
        ach = {"itens": [
            {"id": "ach-ml-MLB1", "loja": "mercadolivre", "id_ml": "MLB1", "nome": "A", "preco": 40, "preco_alvo": 45,
             "historico": [{"data": "2026-11-05", "preco": 40}, {"data": "2026-11-06", "preco": 41}]},
            {"id": "ach-ml-MLB2", "loja": "mercadolivre", "id_ml": "MLB2", "nome": "B", "preco": 40, "preco_alvo": 45, "historico": []},
            {"id": "ach-ml-MLB3", "loja": "mercadolivre", "id_ml": "MLB3", "nome": "App", "origem": "app", "preco": 1, "preco_alvo": 2}]}
        new, resumo = sr.update_achadinhos(ach, {"MLB1": 50.0, "MLB2": None, "MLB3": 9.0}, "2026-11-06")
        a, b, app = new["itens"]
        self.assertEqual(a["historico"], [{"data": "2026-11-05", "preco": 40}, {"data": "2026-11-06", "preco": 50.0}])
        self.assertFalse(a["ativo"])
        self.assertFalse(b["ativo"])
        self.assertEqual(app, ach["itens"][2])  # item do bot intocado
        fresh = {"itens": [ach["itens"][2], {"id": "ach-ml-NOVO", "origem": "app"}, {"id": "ach-ml-MLB1", "loja": "mercadolivre"}]}
        merged = sr.merge_app_items(fresh, new)
        ids = [i["id"] for i in merged["itens"]]
        self.assertEqual(ids, ["ach-ml-MLB3", "ach-ml-NOVO", "ach-ml-MLB1", "ach-ml-MLB2"])
        self.assertEqual(merged["itens"][2]["preco"], 50.0)

    @patch("core.site_ranking.run")
    def test_schedule_runs_once_per_slot(self, run):
        run.return_value = {}
        from datetime import datetime
        D = lambda h, m: datetime(2026, 11, 6, h, m, tzinfo=sr.ZONE)
        with patch("core.site_ranking.datetime") as dt:
            dt.now.return_value = D(7, 0)
            sr.maybe_run(); sr.maybe_run()
            dt.now.return_value = D(12, 0)
            sr.maybe_run()                       # 06:40 já passou da janela de 90 min
            dt.now.return_value = D(18, 45)
            sr.maybe_run()
        self.assertEqual(run.call_count, 2)
        self.assertEqual(run.call_args_list[0].kwargs["publish"], False)  # modo teste por padrão
        self.assertIsNone(run.call_args_list[0].kwargs["escopo"])        # "tudo"

    @patch("core.site_ranking.run")
    def test_custom_agenda(self, run):
        run.return_value = {}
        sr.save_agenda([{"hora": "12:00", "oque": "achadinhos"}, {"hora": "09:30", "oque": "lego", "ativo": False},
                        {"hora": "12:00", "oque": "achadinhos"}])
        self.assertEqual([i["hora"] for i in sr.get_agenda()], ["09:30", "12:00"])  # ordenado e sem repetido
        with self.assertRaises(ValueError):
            sr.save_agenda([{"hora": "25:00", "oque": "tudo"}])
        with self.assertRaises(ValueError):
            sr.save_agenda([{"hora": "10:00", "oque": "xyz"}])
        from datetime import datetime
        with patch("core.site_ranking.datetime") as dt:
            dt.now.return_value = datetime(2026, 11, 6, 9, 40, tzinfo=sr.ZONE)
            sr.maybe_run()                       # 09:30 está desativado
            dt.now.return_value = datetime(2026, 11, 6, 12, 5, tzinfo=sr.ZONE)
            sr.maybe_run(); sr.maybe_run()
        self.assertEqual(run.call_count, 1)
        self.assertEqual(run.call_args.kwargs["escopo"], {"cats": [], "lojas": [], "achadinhos": True})

    def test_stale_chrome_lock_removed(self):
        import os, socket
        from scrapers import ml_coupons
        d = Path(self.temp.name) / "perfil"
        d.mkdir()
        with patch.object(ml_coupons, "PROFILE_DIR", d):
            os.symlink("outra-maquina-1234", d / "SingletonLock")
            os.symlink("x", d / "SingletonSocket")
            ml_coupons._clear_stale_profile_lock()
            self.assertFalse(os.path.lexists(d / "SingletonLock"))
            self.assertFalse(os.path.lexists(d / "SingletonSocket"))
            os.symlink(f"{socket.gethostname()}-{os.getpid()}", d / "SingletonLock")  # dono vivo: fica
            ml_coupons._clear_stale_profile_lock()
            self.assertTrue(os.path.lexists(d / "SingletonLock"))

    def test_escopo(self):
        tudo = sr.norm_escopo(None)
        self.assertEqual(sr.escopo_label(tudo), "tudo")
        so_ach = sr.norm_escopo({"cats": [], "lojas": [], "achadinhos": True})
        self.assertEqual(sr.escopo_label(so_ach), "só achadinhos")
        hw = sr.norm_escopo({"cats": ["hot-wheels"], "lojas": ["mercadolivre"], "achadinhos": False})
        self.assertEqual(sr.escopo_label(hw), "Hot Wheels (só Mercado Livre)")
        with self.assertRaises(ValueError):
            sr.norm_escopo({"cats": [], "lojas": ["amazon"], "achadinhos": False})

    def test_merge_partial_keeps_other_groups(self):
        cur = {"categorias": [{"id": "hot-wheels"}, {"id": "lego"}], "produtos": [
            {"id": "hot-wheels-01", "loja": "mercadolivre", "categoria": "hot-wheels", "v": "velho"},
            {"id": "az-hot-wheels-01", "loja": "amazon", "categoria": "hot-wheels", "v": "velho"},
            {"id": "lego-01", "loja": "mercadolivre", "categoria": "lego", "v": "velho"}]}
        new = {"atualizado_em": "x", "categorias": cur["categorias"], "produtos": [
            {"id": "hot-wheels-01", "loja": "mercadolivre", "categoria": "hot-wheels", "v": "novo"},
            {"id": "hot-wheels-02", "loja": "mercadolivre", "categoria": "hot-wheels", "v": "novo"}]}
        out = sr.merge_partial(cur, new, {("mercadolivre", "hot-wheels")})
        self.assertEqual([(p["id"], p["v"]) for p in out["produtos"]],
                         [("hot-wheels-01", "novo"), ("hot-wheels-02", "novo"), ("az-hot-wheels-01", "velho"), ("lego-01", "velho")])


class SiteAchadinhosTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.p = patch.object(db, "DB_PATH", Path(self.temp.name) / "deals.db")
        self.p.start()

    def tearDown(self):
        self.p.stop()
        gc.collect()
        self.temp.cleanup()

    def test_parse_preco(self):
        from core import site_achadinhos as sa
        self.assertEqual([sa.parse_preco(v) for v in ["39,90", "R$ 1.299,90", "45.5", 30]], [39.9, 1299.9, 45.5, 30.0])
        with self.assertRaises(ValueError):
            sa.parse_preco("abc")

    def test_build_ml_and_amazon(self):
        from core import site_achadinhos as sa
        ml = {"store": "Mercado Livre", "title": "Mini GT Nissan GT-R", "price": 89.9,
              "url": "https://www.mercadolivre.com.br/x/p/MLB123456", "image": "https://http2.mlstatic.com/D_NQ_NP_612345-MLA9988776655_102025-O.webp"}
        it = sa.build_item(ml, "https://meli.la/abc", 95.0, "mini-gt", "2026-11-06T10:00")
        self.assertEqual((it["id"], it["ativo"], it["historico"][0]["data"]), ("ach-ml-MLB123456", True, "2026-11-06"))
        self.assertTrue(it["imagem"].startswith("https://http2.mlstatic.com/D_NQ_NP_2X_"))
        with self.assertRaises(ValueError):
            sa.build_item(ml, "https://www.mercadolivre.com.br/x", 95.0, None, "2026-11-06T10:00")  # sem meli.la
        az = {"store": "Amazon", "title": "LEGO 31134 | Ônibus", "price": 63.99, "url": "https://www.amazon.com.br/dp/B0AAAAAAAA"}
        with patch("config.AMAZON_TAG", "promocoesdiec-20"):
            a = sa.build_item(az, "", 60.0, "lego", "2026-11-06T10:00")
        self.assertEqual(a["link_afiliado"], "https://www.amazon.com.br/dp/B0AAAAAAAA?tag=promocoesdiec-20")
        self.assertNotIn("preco", a)
        self.assertNotIn("imagem", a)

    def test_upsert_and_remove_respect_app_items(self):
        from core import site_achadinhos as sa
        data = {"atualizado_em": "x", "itens": [{"id": "ach-ml-MLB1", "origem": "app"}, {"id": "ach-ml-MLB2", "preco": 50, "preco_alvo": 40}]}
        new, acao = sa.upsert(data, {"id": "ach-ml-MLB2", "preco_alvo": 55, "categoria": "lego"})
        self.assertEqual((acao, new["itens"][1]["ativo"], new["itens"][1]["preco_alvo"]), ("atualizado", True, 55))
        with self.assertRaises(ValueError):
            sa.upsert(data, {"id": "ach-ml-MLB1", "preco_alvo": 1, "categoria": None})
        new, _ = sa.upsert(data, {"id": "ach-az-B0X", "preco_alvo": 9, "categoria": None})
        self.assertEqual(len(new["itens"]), 3)
        new, alvo = sa.remove_from(data, "ach-ml-MLB2")
        self.assertEqual([i["id"] for i in new["itens"]], ["ach-ml-MLB1"])
        with self.assertRaises(ValueError):
            sa.remove_from(data, "ach-ml-MLB1")  # do app

    def test_add_publishes_on_freshest_file(self):
        from core import site_achadinhos as sa
        site = {"atualizado_em": "x", "itens": [{"id": "ach-ml-MLB1", "origem": "app"}]}
        sent = []
        deal = {"store": "Mercado Livre", "title": "Hot Wheels Premium", "price": 30.0, "affiliate_url": "https://meli.la/zz",
                "url": "https://www.mercadolivre.com.br/up/MLBU999", "image": "https://http2.mlstatic.com/D_Q_NP_611111-MLA2222222222_102025-O.webp"}
        def up(content, name):
            sent.append(json.loads(content)); site.update(json.loads(content))
        with patch("core.site_export._fetch_named", lambda n: json.loads(json.dumps(site))), \
                patch("core.site_export._upload", up), patch("core.site_ranking._backup_local", lambda *a: None):
            r = sa.add("https://meli.la/zz", "35,00", "hot-wheels", extract=lambda u: dict(deal))
            self.assertEqual((r["acao"], r["ativo"]), ("adicionado", True))
            self.assertEqual([i["id"] for i in sent[-1]["itens"]], ["ach-ml-MLB1", "ach-ml-MLBU999"])
            sa.remove("ach-ml-MLBU999")
            self.assertEqual([i["id"] for i in sent[-1]["itens"]], ["ach-ml-MLB1"])


class MiniSugestaoTests(unittest.TestCase):
    def test_suggest_from_titles(self):
        from core.mini_sugestao import suggest
        s = suggest({"title": "Miniatura Mini GT 1:64 Nissan Skyline GT-R (R34) V-Spec II", "price": 89.9,
                     "id": "ml-1", "store": "Mercado Livre", "url": "u", "image": "i"})
        self.assertEqual((s["site_category"], s["required_terms"].split(", ")[:2]), ("mini-gt", ["mini gt", "r34"]))
        self.assertTrue(s["search_terms"].startswith("mini gt nissan skyline"))
        self.assertEqual((s["observed_price"], s["store"], s["product_id"]), (89.9, "Mercado Livre", "ml-1"))
        hw = suggest({"title": "Hot Wheels Premium Car Culture '84 Mustang SVO Power Trip Mattel"})
        self.assertEqual(hw["required_terms"], "hot wheels, 84, mustang, svo")
        self.assertEqual(hw["search_terms"].split(";")[0], "hot wheels 84 mustang svo")
        self.assertEqual(suggest({"title": "Carros Disney Pixar Relâmpago McQueen Mattel 1:55"})["site_category"], "pixar-cars")
        self.assertEqual(suggest({"title": "Carrinho Hot Wheels Koenigsegg CC850 Prata"})["cores_no_titulo"], ["prata"])


if __name__ == "__main__":
    unittest.main()
