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
- [x] Gestão visual de keywords, termos relevantes, blocklist, LEGO e lojas habilitadas.
- [x] Agenda de publicações e horários silenciosos.
- [x] Agrupamento de anúncios equivalentes e comparação entre lojas.
- [x] Métricas do canal: publicações, aprovações, rejeições, marcas, lojas, descontos e cupons persistidos.
- [x] Proteção da sessão do Mercado Livre: circuito de pausa por captcha, pesquisas distribuídas, estado no painel e atalho de recuperação.
- [x] Nova identidade visual: logomarca dourada, paleta oficial, Montserrat, títulos geométricos e aplicação responsiva no painel.
- [ ] Integrações adicionais e rastreamento de cliques quando houver APIs confiáveis.

## Funcionalidades já existentes

- Painel web autenticado, responsivo e publicado via Cloudflare Tunnel.
- Criador manual de anúncios com extração, link afiliado, Telegram e texto para WhatsApp.
- Cupom manual com cálculo, compra mínima, teto e preço final confirmado.
- Minis monitoradas com busca imediata, publicação direta e histórico de preços.
- Histórico de 90 dias, mínimo/máximo/média, recorde histórico, gráfico e comparação por loja.
- Blacklist reversível de produto e termo.
- Aprovação atual por botões no Telegram.
- Mercado Livre monetizado por `meli.la`, Amazon por tag e Lomadee por `lmdee.link`.

## Restrições importantes

- Nunca publicar intencionalmente link não monetizado.
- Histórico registra o preço público sem cupom.
- Preço com cupom só é publicado após confirmação manual.
- Não executar o bot local e o bot do servidor simultaneamente.
- A VM possui poucos recursos; manter o painel leve e evitar processos Chrome concorrentes.
- **Toda alteração de frontend deve considerar responsividade mobile e desktop.** Testar layouts em ambas as dimensões, usar media queries quando necessário, e não introduzir grids ou flex que quebrem em tela estreita (< 600px).
