#!/usr/bin/env bash
# Só leitura: o que usou o Chrome do ML (que passa pelo proxy) nas últimas 24 h.
J=$(sudo journalctl -u promobot --since "24 hours ago" --no-pager -o short-iso)
c() { printf '%5s  %s\n' "$(grep -cE "$1" <<<"$J")" "$2"; }
echo "== últimas 24 h (contagem de linhas do log)"
c '\[ML\] usando proxy'                 "vezes que o Chrome do ML abriu (cada abertura carrega páginas pelo proxy)"
c "\[ML\] API falhou"                   "buscas que a API do ML não respondeu e foram para o navegador"
c 'navegador fora da janela'            "buscas no navegador puladas pela janela de tempo"
c '\[ML\] (captcha|bloqueio|timeout)'   "buscas no navegador com captcha/bloqueio/timeout"
c 'oportunidade para revis'             "oportunidades novas (as do ML geram link pelo Gerador de Links)"
c '\[ML-link\]'                         "avisos do Gerador de Links do ML"
c 'ranking|mais vendidos'               "linhas do ranking do site"
c 'site: achadinhos.json enviado'       "envios de achadinhos para o site"
echo
echo "== aberturas do Chrome do ML por hora (horário do servidor, UTC)"
grep -E '\[ML\] usando proxy' <<<"$J" | cut -c1-13 | sort | uniq -c | sed 's/^/   /'
echo
echo "== buscas que caíram no navegador, por termo"
grep -oE "\[ML\] API falhou em '[^']*'" <<<"$J" | sort | uniq -c | sort -rn | head -10 | sed 's/^/   /'
echo
echo "== últimas 15 linhas do ML"
grep -E '\[ML|ranking|oportunidade' <<<"$J" | tail -15 | sed 's/^\([^ ]*\) [^:]*: /   \1 /'
echo "== fim (nada foi mudado)"
