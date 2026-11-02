(()=>{
const button=document.getElementById('scan-now'),progress=document.getElementById('scan-progress'),status=document.getElementById('scan-status'),container=document.getElementById('scan-results');
const money=v=>Number(v||0).toLocaleString('pt-BR',{style:'currency',currency:'BRL'});
const featured=document.getElementById('scan-featured'),alternatives=document.getElementById('scan-alternatives'),empty=document.getElementById('scan-empty'),cards=new Map();
let offers=[],offerFilter='all';
const target=()=>Number(window.monitoredTarget)||0;
const origin=deal=>deal.origin==='international'||deal.international?'international':deal.origin==='national'?'national':'unknown';
function targetText(price){const goal=target();if(!goal)return 'Sem preço-alvo definido.';return Number(price)>goal?`Seu alvo: ${money(goal)} · faltam ${money(Number(price)-goal)} para atingir o alvo.`:`Seu alvo: ${money(goal)} · alvo atingido${Number(price)<goal?' — '+money(goal-Number(price))+' abaixo':''}.`}
function historyBadges(badges,deal,isFeatured=false,poolSize=0){
  badges.replaceChildren(text('span',deal.store,'pill'));
  const source=origin(deal),summary=window.monitoredHistorySummary||{},days=Number(summary.days)||0;
  badges.append(text('span',source==='national'?'Entrega nacional indicada':source==='international'?'Internacional: confira taxas':'Origem não confirmada','pill'));
  if(deal.previously_posted)badges.append(text('span','Já publicado','pill pending'));
  if(days<5)badges.append(text('span','Histórico inicial','quality-badge quality-initial'));
  else if(summary.min_price&&Number(deal.price)<=Number(summary.min_price))badges.append(text('span','Menor preço observado (90d)','quality-badge quality-record'));
  if(isFeatured)badges.append(text('span',`Menor preço entre ${poolSize} anúncio(s) ${source==='national'?'nacionais':'de origem não confirmada'} consultados`,`quality-badge ${source==='national'?'quality-record':'quality-initial'}`));
}
function historyContext(){const summary=window.monitoredHistorySummary||{};return text('p',summary.observations?`${Number(summary.days)||0} dia(s) com coletas · mínimo 90d: ${money(summary.min_price)} · média das coletas: ${money(summary.avg_price)}`:'Sem coletas suficientes para avaliar o preço.','quality-summary')}
function renderOffers(){
  const matches=offers.filter(deal=>offerFilter==='target'?target()>0&&Number(deal.price)<=target()&&origin(deal)!=='international':offerFilter==='all'||origin(deal)===offerFilter);
  const national=matches.filter(deal=>origin(deal)==='national'),unknown=matches.filter(deal=>origin(deal)==='unknown');
  const pool=national.length?national:unknown,best=pool.reduce((current,deal)=>!current||Number(deal.price)<Number(current.price)?deal:current,null);
  offers.forEach(deal=>{
    const key=String(deal.id);if(!cards.has(key))renderDeal(deal);
    const card=cards.get(key),visible=matches.includes(deal);card.hidden=!visible;
    card.querySelector('.offer-target').textContent=targetText(deal.price);
    historyBadges(card.querySelector('.deal-badges'),deal,deal===best,pool.length);
    (deal===best?featured:container).append(card);
  });
  featured.hidden=!best;
  document.getElementById('featured-note').textContent=best?(origin(best)==='national'?'Candidata em destaque: menor preço nacional indicado entre os anúncios deste filtro. Confira as condições da compra.':'Menor preço de origem não confirmada. Verifique origem e eventuais taxas antes de divulgar.'):(matches.length?'Nenhuma oferta com origem adequada para destaque. Confira as condições dos anúncios abaixo.':'');
  const otherCount=matches.length-(best?1:0);alternatives.hidden=otherCount===0;
  document.getElementById('alternatives-label').textContent=`Ver ${otherCount} outra(s) oferta(s)`;
  empty.hidden=matches.length>0;empty.textContent=offers.length?'Nenhuma oferta corresponde a este filtro.':'Nenhum anúncio correspondente foi encontrado. Consulte o diagnóstico da busca.';
  document.getElementById('offer-filter-status').textContent=`${matches.length} de ${offers.length} anúncios disponíveis nesta tela correspondem ao filtro.`;
  document.querySelectorAll('[data-offer-filter]').forEach(control=>{const active=control.dataset.offerFilter===offerFilter;control.classList.toggle('active',active);control.setAttribute('aria-pressed',String(active));if(control.dataset.offerFilter==='target')control.disabled=target()<=0});
}
document.querySelectorAll('[data-offer-filter]').forEach(control=>control.addEventListener('click',()=>{offerFilter=control.dataset.offerFilter;renderOffers()}));
const targetForm=document.getElementById('history-target-form');
targetForm.addEventListener('submit',async event=>{
  event.preventDefault();const input=document.getElementById('history-target'),output=document.getElementById('target-status'),buttons=[...targetForm.querySelectorAll('button')];buttons.forEach(el=>el.disabled=true);output.textContent='Salvando alvo…';
  try{
    const response=await fetch(`/api/monitored/${window.monitoredItemId}/target`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({max_price:input.value})}),data=await response.json();
    if(!response.ok)throw new Error(data.error||'Não foi possível salvar o alvo');
    window.monitoredTarget=data.max_price;input.value=data.max_price||'';document.getElementById('target-legend').hidden=!data.max_price;
    document.getElementById('target-summary').textContent=data.max_price?`Alvo atual: ${money(data.max_price)}`:'Sem alvo: aprendizado silencioso até haver evidência confiável.';
    if(!data.max_price&&offerFilter==='target')offerFilter='all';
    renderOffers();window.dispatchEvent(new Event('monitored-target-change'));output.textContent='Alvo atualizado no cadastro. As próximas coletas usarão esse valor.';
  }catch(error){output.textContent=error.message}finally{buttons.forEach(el=>el.disabled=false)}
});
document.getElementById('clear-history-target').addEventListener('click',()=>{document.getElementById('history-target').value='';targetForm.requestSubmit()});
async function waitJob(id){for(let i=0;i<300;i++){await new Promise(r=>setTimeout(r,2000));const response=await fetch(`/api/jobs/${id}`),job=await response.json();if(job.progress?.store)status.textContent=`Pesquisando ${job.progress.store} (${job.progress.index}/${job.progress.total})…`;else if(job.status==='pending')status.textContent='Na fila: aguardando o bot terminar a tarefa atual…';if(job.status==='done')return job.result;if(job.status==='error')throw new Error(job.error||'A busca falhou')}throw new Error('A busca excedeu o tempo limite')}
function text(tag,value,className){const el=document.createElement(tag);el.textContent=value;if(className)el.className=className;return el}
function field(labelText,type='number',placeholder=''){const label=text('label',labelText),input=document.createElement('input');input.type=type;if(type==='number'){input.min='0';input.step='0.01'}input.placeholder=placeholder;label.append(input);return{label,input}}
function couponEditor(card,deal){const details=document.createElement('details');details.className='deal-coupon';details.append(text('summary','Adicionar cupom manual'));const fields=document.createElement('div');fields.className='deal-coupon-fields';const code=field('Código','text','PROMO50'),kindLabel=text('label','Tipo'),kind=document.createElement('select');[['fixed','Valor fixo (R$)'],['percent','Percentual (%)']].forEach(([v,t])=>{const option=document.createElement('option');option.value=v;option.textContent=t;kind.append(option)});kindLabel.append(kind);const value=field('Desconto'),cap=field('Teto','number','Opcional'),minimum=field('Compra mínima','number','Opcional'),final=field('Preço final confirmado');const calculated=text('div','','deal-coupon-price');[code.label,kindLabel,value.label,cap.label,minimum.label,final.label,calculated].forEach(el=>fields.append(el));details.append(fields);card._coupon={code:code.input,kind,value:value.input,cap:cap.input,minimum:minimum.input,final:final.input};function calculate(){const price=Number(deal.price),amount=Number(value.input.value),limit=Number(cap.input.value),min=Number(minimum.input.value);let discount=kind.value==='percent'?price*amount/100:amount;if(limit)discount=Math.min(discount,limit);const valid=code.input.value.trim()&&amount>0&&(!min||price>=min),result=valid?Math.max(0,price-discount):0;final.input.value=result?result.toFixed(2):'';calculated.textContent=result?`Preço sugerido: ${money(result)}`:(min>price?'Compra mínima não atingida':'')};[code.input,kind,value.input,cap.input,minimum.input].forEach(el=>el.addEventListener('input',calculate));return details}
function couponFrom(card){const c=card._coupon;if(!c||!c.code.value.trim())return{};return{manual_coupon_code:c.code.value.trim().toUpperCase(),manual_coupon_type:c.kind.value,manual_coupon_value:c.value.value,manual_coupon_max_discount:c.cap.value,manual_coupon_min_purchase:c.minimum.value,manual_coupon_final_price:c.final.value}}
function whatsappActions(card,deal){
  const controls=text('div','','approval-share monitored-whatsapp'),native=text('button','','button');
  native.type='button';native.dataset.share='native';
  const icon=document.createElementNS('http://www.w3.org/2000/svg','svg');
  icon.setAttribute('viewBox','0 0 24 24');icon.setAttribute('width','20');icon.setAttribute('height','20');icon.setAttribute('fill','none');icon.setAttribute('stroke','currentColor');icon.setAttribute('stroke-width','1.8');icon.setAttribute('aria-hidden','true');icon.classList.add('whatsapp-icon');
  const path=document.createElementNS('http://www.w3.org/2000/svg','path');path.setAttribute('d','M21 11.5a9 9 0 01-13.4 7.9L3 21l1.6-4.6A9 9 0 1121 11.5Z M8 7.5c-.7 0-1 1-1 1.5 0 3 4 7 7 7 .5 0 1.5-.3 1.5-1l-2-1.5-1 1c-1.5-.7-2.8-2-3.5-3.5l1-1-1.5-2.5Z');icon.append(path);
  const label=text('span','WhatsApp','share-label'),linkState=text('small','Validar link','share-link-state');native.append(icon,label,linkState);
  const options=text('details','','share-options'),summary=text('summary','⋯','button'),menu=text('div','','share-menu');summary.setAttribute('aria-label','Mais opções do WhatsApp');
  menu.style.top='auto';menu.style.bottom='calc(100% + 6px)';
  const copy=text('button','Copiar só o texto','button'),download=text('button','Baixar só a imagem','button');copy.type=download.type='button';copy.dataset.share='copy';download.dataset.share='image';menu.append(copy,download);options.append(summary,menu);controls.append(native,options);
  const status=text('p','','share-status');status.setAttribute('role','status');status.setAttribute('aria-live','polite');
  let ready=null;
  const signature=()=>JSON.stringify(couponFrom(card));
  const imageFile=()=>window.whatsappTools.imageFile('/api/manual/image',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({image:deal.image})});
  const reset=()=>{ready=null;label.textContent='WhatsApp';linkState.textContent='Validar link';status.textContent=''};
  card.addEventListener('input',reset);
  controls.querySelectorAll('button[data-share]').forEach(shareButton=>shareButton.addEventListener('click',async()=>{
    const action=shareButton.dataset.share,buttons=[...controls.querySelectorAll('button')];options.removeAttribute('open');buttons.forEach(el=>el.disabled=true);
    try{
      if(action==='image'){window.whatsappTools.download(await imageFile());status.textContent='Download da foto JPEG solicitado.';return}
      if(ready?.signature!==signature())ready=null;
      if(!ready){
        const snapshot=signature();status.textContent='Validando anúncio e preparando link monetizado…';
        const response=await fetch(`/api/monitored/${window.monitoredItemId}/share`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({product_id:deal.id,scan_completed_at:window.lastMonitoredScan?.completed_at,coupon:couponFrom(card)})}),data=await response.json();
        if(!response.ok)throw new Error(data.error||'Não foi possível preparar o anúncio');
        const prepared=data.job_id?await waitJob(data.job_id):data;
        if(!prepared.whatsapp||!prepared.affiliate_url)throw new Error('Anúncio monetizado indisponível');
        status.textContent='Anúncio validado. Preparando foto…';
        try{prepared.file=await imageFile()}catch(error){prepared.imageError=error.message}
        if(!card.isConnected||snapshot!==signature())throw new Error('O cupom ou a oferta mudou. Prepare o WhatsApp novamente.');
        prepared.signature=snapshot;ready=prepared;label.textContent='Copiar legenda';linkState.textContent='Link validado';
        status.textContent='Pronto! Toque em Copiar legenda e depois em Enviar foto. '+(ready.imageError?'Imagem indisponível: você pode copiar só o texto.':'No WhatsApp, cole no campo Adicionar legenda.');return;
      }
      if(action==='copy'||!ready.captionCopied){
        const prepared=ready;await window.whatsappTools.copy(prepared.whatsapp);
        if(ready!==prepared||prepared.signature!==signature())throw new Error('O cupom mudou. Prepare e copie a legenda novamente.');
        prepared.captionCopied=true;label.textContent='Enviar foto';status.textContent='Legenda copiada! Toque em Enviar foto e cole na legenda no WhatsApp.';return;
      }
      if(!ready.file)throw new Error('Imagem indisponível. Use Copiar só o texto e anexe uma foto no WhatsApp.');
      if(navigator.share&&navigator.canShare?.({files:[ready.file]})){
        await navigator.share({files:[ready.file]});status.textContent='Foto compartilhada. Cole a legenda antes de enviar no WhatsApp.';
      }else{status.textContent='Este navegador não compartilha fotos. Use Baixar só a imagem, anexe no WhatsApp e cole a legenda.'}
    }catch(error){status.textContent=error.name==='AbortError'?'Compartilhamento cancelado.':error.message}
    finally{buttons.forEach(el=>el.disabled=false)}
  }));
  return[controls,status];
}
document.addEventListener('click',event=>document.querySelectorAll('.monitored-whatsapp .share-options[open]').forEach(menu=>{if(!menu.contains(event.target))menu.removeAttribute('open')}));
document.addEventListener('keydown',event=>{if(event.key==='Escape')document.querySelectorAll('.monitored-whatsapp .share-options[open]').forEach(menu=>{menu.removeAttribute('open');menu.querySelector('summary').focus()})});
async function publish(deal,publishButton,card){if(!confirm('Enviar esta oferta agora para o Telegram?'))return;publishButton.disabled=true;publishButton.textContent='Preparando link…';try{const payload={...deal,...couponFrom(card)},response=await fetch('/api/publish',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({deal:payload})}),data=await response.json();if(!response.ok)throw new Error(data.error);await waitJob(data.job_id);publishButton.textContent='Enviado ao Telegram';publishButton.className='button published'}catch(error){publishButton.disabled=false;publishButton.textContent='Enviar ao Telegram';alert(error.message)}}
function renderDeal(deal){const card=document.createElement('article');card.className='deal-card';cards.set(String(deal.id),card);const image=document.createElement('img');image.loading='lazy';image.decoding='async';image.src=deal.image||'';image.alt=deal.title;card.append(image);const body=document.createElement('div');body.className='deal-body';const badges=document.createElement('div');badges.className='deal-badges';historyBadges(badges,deal);body.append(badges,text('h3',deal.title),text('strong',money(deal.price),'deal-price'));if(deal.original_price>deal.price)body.append(text('span',`Referência informada pela loja: ${money(deal.original_price)}`,'old-price'));body.append(historyContext(),text('p',targetText(deal.price),'offer-target'));body.append(couponEditor(card,deal),...whatsappActions(card,deal));const actions=document.createElement('div');actions.className='deal-actions';const open=document.createElement('a');open.href=deal.url;open.target='_blank';open.rel='noopener noreferrer';open.className='button';open.textContent='Ver produto';const send=document.createElement('button');send.className='primary';send.textContent='Enviar ao Telegram';send.onclick=()=>publish({...deal},send,card);const schedule=document.createElement('button');schedule.className='button';schedule.textContent='Agendar';schedule.onclick=async()=>{const scheduled_at=prompt('Data e hora em Brasília (ex.: 2026-10-15T14:30)');if(!scheduled_at)return;const r=await fetch('/api/schedule',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({deal:{...deal,...couponFrom(card)},scheduled_at})}),data=await r.json();if(!r.ok)return alert(data.error);schedule.textContent='Agendado';schedule.disabled=true};actions.append(send,schedule,open);body.append(actions);card.append(body);container.append(card)}
function renderScan(result){
  const diagnostic=document.getElementById('scan-diagnostics');diagnostic.replaceChildren();container.replaceChildren();featured.replaceChildren();cards.clear();offers=result.results||[];
  const reports=result.diagnostics||[],received=reports.reduce((sum,row)=>sum+row.received,0),matched=result.matches_total??result.results.length;
  const date=result.completed_at?new Date(/[zZ]$|[+-]\d{2}:\d{2}$/.test(result.completed_at)?result.completed_at:result.completed_at+'Z').toLocaleString('pt-BR',{timeZone:'America/Sao_Paulo'})+' (Brasília)':'';
  status.textContent=`${matched} correspondentes · ${offers.length} disponíveis nesta tela · ${received} extraídos · ${result.stores_searched} fontes${date?' · '+date:''}`;
  if(result.item)diagnostic.append(text('p','Busca utilizada: '+result.item.search_terms+' · Exigidos: '+result.item.required_terms,'scan-query'));
  reports.forEach(row=>{
    const panel=text('article','','scan-diagnostic');panel.append(text('strong',row.store));
    panel.append(text('p',`${row.received} extraídos · ${row.matched} aceitos · ${row.discarded} descartados${row.duplicates?' · '+row.duplicates+' repetidos':''}`));
    if(row.status==='error')panel.append(text('p',row.error||'Falha ao consultar a loja','bad'));
    else if(row.status==='empty')panel.append(text('p','A loja não retornou anúncios extraíveis. Pode ser falta de resultados, bloqueio ou mudança na página; não é descarte pelos seus termos.'));
    const missing=Object.entries(row.missing_terms||{});if(missing.length)panel.append(text('p','Trechos ausentes: '+missing.map(([term,count])=>`${term} (${count})`).join(' · ')));
    if(row.samples?.length){const details=document.createElement('details');details.append(text('summary','Ver exemplos descartados'));row.samples.forEach(sample=>{const entry=text('div','','scan-rejected');entry.append(text('b',sample.title),text('p',sample.reasons.join('; ')));details.append(entry)});panel.append(details)}
    diagnostic.append(panel);
  });
  renderOffers();
}
async function scan(){
  button.disabled=true;progress.classList.remove('hidden');offers=[];cards.clear();container.replaceChildren();featured.replaceChildren();featured.hidden=true;alternatives.hidden=true;empty.hidden=true;document.getElementById('featured-note').textContent='';document.getElementById('scan-diagnostics').replaceChildren();status.textContent='Busca em andamento';
  try{
    const response=await fetch(`/api/monitored/${window.monitoredItemId}/scan`,{method:'POST'}),data=await response.json();if(!response.ok)throw new Error(data.error);
    await waitJob(data.job_id);const url=new URL(window.location.href);url.searchParams.delete('scan');window.location.replace(url.pathname+url.search);
  }catch(error){status.textContent='Falha na busca';empty.textContent=error.message;empty.hidden=false;button.disabled=false;progress.classList.add('hidden')}
}
button.addEventListener('click',scan);if(window.lastMonitoredScan)renderScan(window.lastMonitoredScan);if(window.autoScan)scan();
})();
