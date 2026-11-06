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


if __name__ == "__main__":
    unittest.main()
