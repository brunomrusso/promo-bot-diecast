#!/usr/bin/env bash
# Simplifica os termos obrigatórios (e a busca) das minis aprovadas pelo Bruno em 09/11.
# Guarda os valores antigos em ~/termos-antes-AAAAMMDD-HHMM.json antes de mudar.
cd /home/ubuntu/promo-bot-carros
./venv/bin/python - <<'PY'
import json, time
from core import db
NOVOS = {  # id: (termos obrigatórios, busca)
    13: ("pixar, f1, pacote", "cars disney pixar f1 pacote 3"),
    10: ("pixar, aniversario, pacote", "carros disney pixar aniversario pacote 5"),
    24: ("funko, mcqueen, salto", "funko pop disney carros salto mcqueen"),
    35: ("hot wheels, land cruiser, forza", "hot wheels forza land cruiser"),
    31: ("hot wheels, audi, 90, quattro", "hot wheels audi 90 quattro"),
    29: ("hot wheels, k5, blazer, stranger", "hot wheels k5 blazer stranger things"),
    19: ("expositor, 50, nichos", "expositor 50 nichos 1:64"),
    33: ("hot wheels, boulevard, enzo", "hot wheels boulevard enzo ferrari"),
    27: ("hot wheels, boulevard, supra", "hot wheels boulevard toyota supra"),
    21: ("hot wheels, brick, silverado", "hot wheels brick shop silverado"),
    12: ("hot wheels, clk, amg", "hot wheels mercedes clk amg black series"),
    26: ("hot wheels, 993, gt2", "hot wheels porsche 993 gt2"),
    3:  ("hot wheels, del sol", "hot wheels honda del sol"),
    9:  ("hot wheels, mustang, svo", "hot wheels 84 mustang svo"),
    28: ("hot wheels, celica, japan historics", "hot wheels japan historics toyota celica"),
    36: ("hot wheels, mclaren, solus", "hot wheels mclaren solus gt"),
    23: ("hot wheels, simpsons, homer", "hot wheels simpsons homer"),
    14: ("hot wheels, kombi, dracula", "hot wheels kool kombi dracula"),
    8:  ("kaido house, bmw, m3, v2", "kaido house bmw m3 v2"),
    16: ("kaido house, datsun, 510, koi", "kaido house datsun 510 koi"),
    11: ("hot wheels, formula 1, 10", "kit 10 carrinhos hot wheels formula 1"),
    25: ("lego, 77255", "lego 77255 relampago mcqueen"),
    22: ("lego, 77260", "lego 77260 toyota supra"),
    37: ("hot wheels, chevy, custom, 1967", "hot wheels chevy custom c10 1967"),
    32: ("mini gt, 1143", "mini gt 1143 porsche 911 gt3"),
    30: ("mini gt, 1138", "mini gt 1138 mustang mach 1"),
    1:  ("kaido house, honda, 179", "kaido house honda civic ef 179"),
}
antes = {}
with db._conn() as c:
    for i, (req, busca) in NOVOS.items():
        r = c.execute("SELECT name, required_terms, search_terms FROM monitored_items WHERE id=?", (i,)).fetchone()
        if not r:
            print(f"   #{i}: não existe, pulei"); continue
        antes[i] = {"name": r[0], "required_terms": r[1], "search_terms": r[2]}
        c.execute("UPDATE monitored_items SET required_terms=?, search_terms=? WHERE id=?", (req, busca, i))
        print(f"   #{i} {r[0][:45]:<45} exige: {req}")
arq = f"/home/ubuntu/termos-antes-{time.strftime('%Y%m%d-%H%M')}.json"
json.dump(antes, open(arq, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print(f"== {len(antes)} minis atualizadas. Valores antigos guardados em {arq}")
PY
