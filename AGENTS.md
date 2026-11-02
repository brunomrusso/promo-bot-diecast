# Informações persistentes do projeto

## Objetivo

Bot e painel administrativo de promoções monetizadas de diecast, com foco em Hot Wheels Premium, Mini GT, Kaido House, Disney/Pixar Cars e escala 1:64. LEGO automotivo é secundário. O serviço principal roda 24h na Oracle Cloud e toda mudança validada localmente deve ser implantada no servidor.

## Roadmap acordado

Implementar por prioridade e, ao final de cada etapa, informar ao usuário o que foi concluído e o que continua pendente.

- [x] Central de aprovações no painel: listar pendentes, filtrar, ordenar, aprovar, rejeitar, adicionar cupom, blacklist e ações em lote.
- [x] Classificação da qualidade da oferta pelo histórico: recorde, excelente, boa, normal ou cara.
- [x] Saúde real do sistema: último ciclo, estado por loja, erros, sessão do ML, memória, swap, banco e reinício controlado.
- [x] Backup automático rotativo do banco, configurações e dados essenciais.
- [x] Regras por marca: desconto mínimo, aprovação e limite diário.
- [x] Gestão visual de lojas habilitadas e blacklist (keywords/termos relevantes/LEGO removidos com a busca aberta).
- [x] Agenda de publicações e horários silenciosos.
- [x] Agrupamento de anúncios equivalentes e comparação entre lojas.
- [x] Métricas do canal: publicações, aprovações, rejeições, marcas, lojas, descontos e cupons persistidos.
- [x] Proteção da sessão do Mercado Livre: circuito de pausa por captcha, pesquisas distribuídas, estado no painel e atalho de recuperação.
- [x] Nova identidade visual: logomarca dourada, paleta oficial, Montserrat, títulos geométricos e aplicação responsiva no painel.
- [x] Aprendizado de preços: histórico universal por assinatura de produto, auto-rejeição acima da média aprendida e vereditos humanos alimentando o baseline.
- [ ] Integrações adicionais e rastreamento de cliques quando houver APIs confiáveis.

## Funcionalidades já existentes

- Painel web autenticado, responsivo e publicado via Cloudflare Tunnel.
- Criador manual de anúncios com extração, link afiliado, Telegram e texto para WhatsApp.
- Cupom manual com cálculo, compra mínima, teto e preço final confirmado.
- Minis monitoradas com busca imediata, publicação direta e histórico de preços.
- Cards do histórico têm WhatsApp independente do Telegram: `/api/monitored/<id>/share` usa a oferta da pesquisa salva e o cupom do card; cache validado ou job prioritário `share_monitored`. Nunca publica durante a preparação. JPEG e clipboard usam `whatsapp-share.js`; editar cupom invalida a preparação.
- Histórico com períodos 7/30/90 dias, linha do alvo no gráfico e edição inline em `/api/monitored/<id>/target` (apenas `monitored_items.max_price`, sem ativar item pausado ou alterar histórico). Profundidade da base conta dias distintos de coleta; menos de 5 dias usa “Histórico inicial”.
- Tela do histórico destaca a menor candidata nacional indicada (ou origem desconhecida com aviso), recolhe alternativas/diagnóstico e filtra todas/alvo/nacionais/origem desconhecida. Filtros preservam DOM, cupons e preparação do WhatsApp. Contagens referem-se aos anúncios carregados, não a todo o marketplace.
- Blacklist reversível de produto e termo.
- Aprovação atual por botões no Telegram.
- Mercado Livre monetizado por `meli.la`, Amazon por tag e Lomadee por `lmdee.link`.
- Links compartilhados do app ML podem abrir `/social/...` com o produto destacado: preservar `ref` até resolver o botão explícito “Ir para produto”, nunca selecionar recomendações. Após resolver, remover rastreamento preservando `pdp_filters` e identificadores de variação. Teste real validado por extração e geração monetizada, sem publicação.

## Restrições importantes

- Nunca publicar intencionalmente link não monetizado.
- Catálogo fechado: somente produtos ativos em `monitored_items` autorizam buscas e novos preços automáticos. Keywords amplas, alertas legados, antigos pendentes e anúncios manuais sem cadastro explícito não autorizam monitoramento. Criar anúncio oferece “Autorizar monitoramento”, com alvo opcional.
- Alvo unificado: `monitored_items.max_price` é a única fonte de alvo. O botão “Caro” na aprovação grava esse alvo na mini de origem (`set_pending_target`). `price_alerts` é legado somente-leitura: `migrate_legacy_price_alerts` vincula alertas antigos à mini equivalente; os restantes aparecem na seção legado da tela Minis. `/price-alerts` redireciona para `/monitored?f=alvo`; a aba Alertas na navegação abre esse filtro.
- Coleta silenciosa; oportunidade apenas ao atingir alvo explícito ou preço favorável com histórico nacional confiável. Sempre revisão manual, nunca auto-publicação de produtos/cupons no ciclo. Jobs manuais e agendas confirmadas continuam funcionando.
- Fila: 1 pendente por cadastro, 5 entradas/ciclo, 20 pendentes no total; substituir somente com melhoria acima de 1%, reapresentar após decisão somente com queda de pelo menos 3%. Até 3 buscas autorizadas por loja/ciclo, em rotação; até 2 verificações de origem no ML por ciclo.
- Migração neutra: antigos pendentes automáticos viram `catalog_archived`, com registro em `catalog_archives`; não apagar preços nem atribuir rejeição humana. `catalog_opportunities` guarda o último preço apresentado.
- Percentual OFF não filtra nem pontua. Dados de origem desconhecida/internacional não entram na base nacional confiável. Desfazer um veredito não autoriza busca; fora do catálogo, limpa a decisão sem reinserir na fila.
- Testes do motor: Windows `./venv/Scripts/python.exe -m unittest test_price_engine -v`; Oracle `venv/bin/python -m unittest test_price_engine -v`. Usam banco temporário e mocks, sem envio real ao Telegram.
- Histórico registra o preço público sem cupom.
- Preço com cupom só é publicado após confirmação manual.
- Não executar o bot local e o bot do servidor simultaneamente.
- A VM possui poucos recursos; manter o painel leve e evitar processos Chrome concorrentes.
- **Toda alteração de frontend deve considerar responsividade mobile e desktop.** Testar layouts em ambas as dimensões, usar media queries quando necessário, e não introduzir grids ou flex que quebrem em tela estreita (< 600px).
