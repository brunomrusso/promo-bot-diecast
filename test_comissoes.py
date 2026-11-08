import gc
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core import comissoes as cm, db

TRACKING = """Relatório de ganhos por ID
Número de rastreamento,cliques,produtos pedidos,receita solicitada,produtos enviados,produtos devolvidos,receita de produtos enviados,receita de produtos devolvidos,ganhos totais,bônus,ganhos de produtos enviados,ganhos de produtos devolvidos
Other,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0,0.0,0.0,0.0
promocoesdiec-20,223.0,31.0,3944.3799999999997,29.0,0.0,2691.0400000000004,0.0,228.6,0.0,228.59999999999997,0.0
"""
LINKED = """Date,Category,Product Title,ASIN,Clicks,Indirect Items Ordered,Direct Items Ordered,Items Ordered,Direct Conversion Rate,Order Quantity,Product Conversion Rate,Order Conversion Rate,Commission Rate,Ordered Revenue,Items Shipped,Items Returned,Items Shipped Revenue,Items Shipped Earnings,Items Returned Revenue,Items Returned Earnings,Total Earnings
10-31-2026,-,-,Other,21.0,16.0,15.0,4.0,71.43,4.0,19.05,19.05,8,566.69,3.0,0.0,378.01,30.240000000000002,0.0,0.0,30.24
10-31-2026,Brinquedos e jogos,Cars de Disney y Pixar Veículo de Brinquedo Temático F1 Pacote com 3,B0GFXXQFJ4,37.0,-,-,-,-,-,-,-,-,-,-,-,-,-,-,-,-
10-31-2026,Brinquedos e jogos,Carros da Disney e Pixar Veículo de Brinquedo Carro De Aniversário Pacote Com 5 3Y+,B0G44FC4JB,165.0,-,-,27.0,-,13.0,16.36,7.88,8.58,3377.6899999999996,26.0,0.0,2313.03,198.35999999999999,0.0,0.0,198.36
"""
TOP = """Classificação,ASIN,Título do produto,Categoria,Tipo de compra
1,B0G44FC4JB,Carros da Disney,Brinquedos e jogos,Direta
"""
ML_VENDAS = """Produtos
Loja
Valor da venda
Ganho por venda
Estado
Hot Wheels Boulevard 2026 Enzo Ferrari Vermelho
30/out
#2000019254232698
Hot Wheels Boulevard 2026 Enzo Ferrari Vermelho
Categoria: Veículos de Brinquedo
STREETCOLECIONAVEIS
R$
119
,
90
1 unidade
R$
11
,
80
Venda direta: 12%
EM REVISÃO

Kaido House 217 Bmw M3 7 Eleven Kaido Works Larry Chen V1 Branco Com Verde
19/out
#2000015595784987
Kaido House 217 Bmw M3 7 Eleven Kaido Works Larry Chen V1 Branco Com Verde
Categoria: Veículos de Brinquedo
SOUKEFI
R$
148
1 unidade
R$
14
,
56
Venda direta: 12%
RECUSADA

Conta vinculada
"""
ML_ETQ = """Etiqueta de rastreamento
Cliques
Unidades vendidas
Taxa de conversão
Ganho estimado
runbrunorun
80
1
1,25%
R$
11
,
80
russowhats
12
0
0%
R$
0
"""


class ComissoesTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.p = patch.object(db, "DB_PATH", Path(self.temp.name) / "deals.db"); self.p.start()
        self.c = patch.multiple("config", AMAZON_TAG="russowhats-20", AMAZON_TAG_SITE="russosite-20",
                                ML_TAG_BOT="russowhats", ML_TAG_SITE="russosite"); self.c.start()

    def tearDown(self):
        self.c.stop(); self.p.stop(); gc.collect(); self.temp.cleanup()

    def test_amazon(self):
        self.assertEqual(cm.importar_amazon(TRACKING, "2026-10"), ("canal", 1))  # "Other" zerado fica de fora
        self.assertEqual(cm.importar_amazon(LINKED, "2026-10", "russowhats-20"), ("produto", 3))
        cm.importar_amazon(LINKED, "2026-10", "russowhats-20")  # reimportar substitui, não duplica
        with self.assertRaises(ValueError):
            cm.importar_amazon(TOP, "2026-10")
        r = cm.resumo("2026-10")["lojas"]["Amazon"]
        self.assertEqual((r["ganho"], r["cliques"], r["unidades"]), (228.6, 223, 29))
        self.assertEqual(r["canais"][0]["canal"], "ID antigo")
        self.assertEqual(r["top"][0]["item_id"], "B0G44FC4JB")
        self.assertEqual(r["top"][0]["ganho"], 198.36)
        self.assertEqual(r["top"][0]["canais"], {"WhatsApp"})
        self.assertEqual([a["item_id"] for a in r["sem_venda"]], ["B0GFXXQFJ4"])  # 37 cliques e nenhuma venda

    def test_ml_vendas(self):
        tipo, n = cm.importar_ml(ML_VENDAS, "2026-10")
        self.assertEqual((tipo, n), ("venda", 2))
        v = cm.resumo("2026-10")["lojas"]["Mercado Livre"]["vendas"]
        self.assertEqual([(x["data"], x["pedido"], x["vendedor"], x["vendas"], x["ganho"], x["estado"], x["motivo"]) for x in v],
                         [("2026-10-30", "2000019254232698", "STREETCOLECIONAVEIS", 119.9, 11.8, "Em revisão", ""),
                          ("2026-10-19", "2000015595784987", "SOUKEFI", 148.0, 14.56, "Recusada", "Conta vinculada")])
        self.assertEqual(cm.resumo("2026-10")["lojas"]["Mercado Livre"]["ganho"], 11.8)  # recusada não conta

    def test_ml_etiquetas_e_ano_virado(self):
        self.assertEqual(cm.importar_ml(ML_ETQ, "2026-11"), ("canal", 2))
        c = {a["canal"]: a for a in cm.resumo("2026-11")["lojas"]["Mercado Livre"]["canais"]}
        self.assertEqual((c["ID antigo"]["cliques"], c["ID antigo"]["ganho"]), (80, 11.8))
        self.assertEqual(c["WhatsApp"]["cliques"], 12)
        self.assertEqual(cm._data_ml("30/dez", "2027-01"), "2026-12-30")
        with self.assertRaises(ValueError):
            cm.importar_ml("qualquer coisa", "2026-11")
        self.assertEqual(cm.mes_anterior(__import__("datetime").date(2027, 1, 5)), "2026-12")


if __name__ == "__main__":
    unittest.main()
