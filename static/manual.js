const $=id=>document.getElementById(id);let current=null;
async function waitJob(id){for(let i=0;i<180;i++){await new Promise(r=>setTimeout(r,2000));const r=await fetch(`/api/jobs/${id}`),j=await r.json();if(j.status==='done')return j.result;if(j.status==='error')throw new Error(j.error||'Falha na tarefa')}throw new Error('Tempo limite excedido')}
function money(v){return Number(v||0).toLocaleString('pt-BR',{style:'currency',currency:'BRL'})}
function couponData(){if(!$('coupon-box').open)return{manual_coupon_code:'',manual_coupon_type:'fixed',manual_coupon_value:'',manual_coupon_max_discount:'',manual_coupon_min_purchase:'',manual_coupon_final_price:''};return{manual_coupon_code:$('coupon-code').value.trim().toUpperCase(),manual_coupon_type:$('coupon-type').value,manual_coupon_value:$('coupon-value').value,manual_coupon_max_discount:$('coupon-cap').value,manual_coupon_min_purchase:$('coupon-minimum').value,manual_coupon_final_price:$('coupon-final').value}}
function formDeal(){return{id:$('deal-id').value,store:$('store').value,title:$('title').value,price:$('price').value,original_price:$('original-price').value,discount:$('discount').value,image:$('image').value,url:$('url').value,affiliate_url:$('affiliate-url').value,...couponData()}}
function whatsappText(d){const disc=Number(d.discount)||0;let text=`🔥 *${disc>0?`${disc}% OFF`:'Oferta'}* — ${d.store}\n\n${d.title}\n\n`;if(Number(d.original_price)>Number(d.price))text+=`De: ~${money(d.original_price)}~\nPor: *${money(d.price)}*\n\n`;else text+=`Por: *${money(d.price)}*\n\n`;if(d.manual_coupon_code||Number(d.manual_coupon_final_price)){text+=d.manual_coupon_code?`🎟️ Cupom: *${d.manual_coupon_code}*\n`:'🎟️ Ative o cupom na página do produto\n';if(Number(d.manual_coupon_final_price))text+=`Com cupom: *${money(d.manual_coupon_final_price)}*\n`;if(Number(d.manual_coupon_min_purchase))text+=`Compra mínima: ${money(d.manual_coupon_min_purchase)}\n`;text+='\n'}return text+`👉 ${d.affiliate_url}`}
function updateCoupon(auto=true){const d=formDeal(),price=Number(d.price),value=Number(d.manual_coupon_value),minimum=Number(d.manual_coupon_min_purchase),cap=Number(d.manual_coupon_max_discount);let discount=d.manual_coupon_type==='percent'?price*value/100:value;if(cap)discount=Math.min(discount,cap);const valid=price>0&&value>0&&(!minimum||price>=minimum);if(auto)$('coupon-final').value=valid?Math.max(0,price-discount).toFixed(2):'';const final=Number(couponData().manual_coupon_final_price);const code=d.manual_coupon_code;const preview=$('preview-coupon');const show=$('coupon-box').open&&(code||final);preview.classList.toggle('hidden',!show);preview.textContent=!show?'':final?`Com cupom${code?' '+code:''}: ${money(final)}`:`Cupom ${code}`+(minimum&&price<minimum?' (compra mínima não atingida)':'');$('whatsapp').value=whatsappText(formDeal())}
function updateMonitorLink(){const d=formDeal(),stop=new Set(['com','para','por','dos','das','uma','the','and','de','do','da','em','miniatura','colecionavel','escala','mattel','premium','fast','furious','velozes','furiosos','cor','original']);const words=d.title.toLowerCase().normalize('NFD').replace(/[\u0300-\u036f]/g,'').match(/[a-z0-9]+/g)||[];const useful=[...new Set(words.filter(w=>(w.length>2||/\d/.test(w))&&!stop.has(w)))];const terms=[...useful.filter(w=>/\d/.test(w)),...useful.filter(w=>!(/\d/.test(w)))].slice(0,12);$('monitor-link').href='/monitored?'+new URLSearchParams({name:d.title,search_terms:terms.join(' '),required_terms:terms.join(', '),max_price:'',observed_price:d.price||'',product_id:d.id,store:d.store,url:d.url,image:d.image||''})}
function discLabel(v){const n=Number(v)||0;return n>0?`${n}% OFF`:'OFERTA'}
function couponClear(){['coupon-code','coupon-value','coupon-cap','coupon-minimum','coupon-final'].forEach(id=>$(id).value='');$('coupon-type').value='fixed';$('coupon-last').hidden=true}
function couponFillLast(){const c=(typeof ULTIMO_CUPOM==='object'&&ULTIMO_CUPOM)||{};const vazio=['coupon-code','coupon-value','coupon-cap','coupon-minimum'].every(id=>!$(id).value);if(!vazio||!(c.code||Number(c.value)))return;$('coupon-code').value=c.code||'';$('coupon-type').value=c.type||'fixed';$('coupon-value').value=Number(c.value)||'';$('coupon-cap').value=Number(c.max_discount)||'';$('coupon-minimum').value=Number(c.min_purchase)||'';const l=$('coupon-last');l.textContent='Último cupom usado'+(c.code?' ('+c.code+')':'')+' preenchido. Ajuste ou clique em Limpar cupom.';l.hidden=false}
function render(d){current=d;resetManualShare();couponClear();$('coupon-box').open=false;if(d._error){$('extract-result').innerHTML=`<div class="flash error">${d._error}</div>`;$('editor').classList.add('hidden');return}$('extract-result').innerHTML='';$('deal-id').value=d.id;$('store').value=d.store;$('title').value=d.title;$('price').value=d.price;$('original-price').value=d.original_price;$('discount').value=d.discount;$('image').value=d.image;$('url').value=d.url;$('affiliate-url').value=d.affiliate_url;$('preview-image').src=d.image;$('preview-title').textContent=d.title;$('preview-price').textContent=money(d.price);$('preview-badge').textContent=discLabel(d.discount);$('monetized').textContent=d.monetized?'✓ Link monetizado validado':'⚠ Link ainda não monetizado';$('monetized').style.color=d.monetized?'var(--green)':'var(--red)';$('intl-badge').classList.toggle('hidden',!d.international);$('image-link').href=d.image;updateMonitorLink();updateCoupon(false);$('editor').classList.remove('hidden')}
$('extract').onclick=async()=>{const url=$('source-url').value.trim();if(!url)return;$('extract-result').innerHTML='';$('progress').classList.remove('hidden');$('editor').classList.add('hidden');$('extract').disabled=true;try{const r=await fetch('/api/extract',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({url})}),data=await r.json();if(!r.ok)throw new Error(data.error);render(await waitJob(data.job_id))}catch(e){$('extract-result').innerHTML=`<div class="flash error">${e.message}</div>`}finally{$('progress').classList.add('hidden');$('extract').disabled=false}};
let manualShareReady=null;
const manualShareLabel=()=>document.querySelector('#manual-whatsapp .share-label');
const manualShareSignature=()=>JSON.stringify({deal:formDeal(),text:$('whatsapp').value});
function resetManualShare(){manualShareReady=null;manualShareLabel().textContent='WhatsApp';document.querySelector('#manual-whatsapp .share-link-state').textContent='Validar anúncio';$('manual-share-status').textContent=''}
const manualImage=()=>window.whatsappTools.imageFile('/api/manual/image',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({image:$('image').value})});
document.querySelectorAll('.manual-share [data-share]').forEach(button=>button.addEventListener('click',async()=>{
  const action=button.dataset.share,status=$('manual-share-status'),controls=[...document.querySelectorAll('.manual-share [data-share]')];
  button.closest('.share-options')?.removeAttribute('open');controls.forEach(control=>control.disabled=true);
  try{
    if(action==='image'){window.whatsappTools.download(await manualImage());status.textContent='Download da foto JPEG solicitado.';return}
    if(manualShareReady?.signature!==manualShareSignature())manualShareReady=null;
    if(!manualShareReady){
      const signature=manualShareSignature();status.textContent='Validando anúncio e link monetizado…';
      const response=await fetch('/api/manual/share',{method:'POST',headers:{'Content-Type':'application/json'},body:signature}),result=await response.json();
      if(!response.ok)throw new Error(result.error||'Não foi possível preparar o anúncio');
      const ready={...result};status.textContent='Anúncio validado. Preparando foto…';
      try{ready.file=await manualImage()}catch(error){ready.imageError=error.message}
      if(signature!==manualShareSignature())throw new Error('O anúncio foi alterado durante a preparação. Toque em WhatsApp novamente.');
      $('affiliate-url').value=result.affiliate_url;$('whatsapp').value=result.whatsapp;$('monetized').textContent='Link monetizado validado';$('monetized').style.color='var(--green)';ready.signature=manualShareSignature();manualShareReady=ready;
      manualShareLabel().textContent='Copiar legenda';document.querySelector('#manual-whatsapp .share-link-state').textContent='Link validado';
      status.textContent='Pronto! Toque em Copiar legenda e depois em Enviar foto. '+(ready.imageError?'Imagem indisponível: você pode copiar só o texto.':'No WhatsApp, cole no campo Adicionar legenda.');return;
    }
    if(action==='copy'||!manualShareReady.captionCopied){
      const ready=manualShareReady;await window.whatsappTools.copy(ready.whatsapp);
      if(manualShareReady!==ready||ready.signature!==manualShareSignature())throw new Error('O anúncio mudou. Prepare e copie a legenda novamente.');
      ready.captionCopied=true;manualShareLabel().textContent='Enviar foto';
      status.textContent='Legenda copiada! Toque em Enviar foto, escolha WhatsApp e cole na legenda antes de enviar.';return;
    }
    if(!manualShareReady.file)throw new Error('Imagem indisponível. O anúncio já está copiado; envie uma foto manualmente.');
    if(navigator.share&&navigator.canShare?.({files:[manualShareReady.file]})){
      await navigator.share({files:[manualShareReady.file]});status.textContent='Foto compartilhada. Cole o anúncio na legenda antes de enviar no WhatsApp.';
    }else{status.textContent='Este navegador não compartilha fotos. Use Baixar só a imagem e cole o anúncio na legenda.'}
  }catch(error){status.textContent=error.name==='AbortError'?'Compartilhamento cancelado.':error.message}
  finally{controls.forEach(control=>control.disabled=false)}
}));
document.querySelector('#editor form').addEventListener('input',resetManualShare);
['url','affiliate-url'].forEach(id=>$(id).addEventListener('input',()=>{if(id==='url')$('affiliate-url').value='';updateCoupon(false);updateMonitorLink()}));
document.addEventListener('click',event=>document.querySelectorAll('.manual-share .share-options[open]').forEach(menu=>{if(!menu.contains(event.target))menu.removeAttribute('open')}));
document.addEventListener('keydown',event=>{if(event.key==='Escape')document.querySelectorAll('.manual-share .share-options[open]').forEach(menu=>{menu.removeAttribute('open');menu.querySelector('summary').focus()})});
$('schedule').onclick=async()=>{const scheduleButton=$('schedule'),scheduled_at=$('schedule-at').value;if(!scheduled_at)return alert('Escolha a data e o horário');scheduleButton.disabled=true;try{const r=await fetch('/api/schedule',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({deal:formDeal(),scheduled_at})}),data=await r.json();if(!r.ok)throw new Error(data.error);$('result').innerHTML='<div class="flash">Anúncio adicionado à agenda.</div>'}catch(e){$('result').innerHTML=`<div class="flash error">${e.message}</div>`}finally{scheduleButton.disabled=false}};
$('publish').onclick=async()=>{if(!confirm('Enviar este anúncio agora para o canal?'))return;$('publish').disabled=true;$('result').textContent='Publicando…';try{const r=await fetch('/api/publish',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({deal:formDeal()})}),data=await r.json();if(!r.ok)throw new Error(data.error);const result=await waitJob(data.job_id);$('whatsapp').value=result.whatsapp;$('affiliate-url').value=result.affiliate_url;$('result').innerHTML='<div class="flash">Anúncio publicado no canal.</div>'}catch(e){$('result').innerHTML=`<div class="flash error">${e.message}</div>`}finally{$('publish').disabled=false}};
['title','price','discount','image','original-price','store'].forEach(id=>$(id).addEventListener('input',()=>{const d=formDeal();$('preview-title').textContent=d.title;$('preview-price').textContent=money(d.price);$('preview-badge').textContent=discLabel(d.discount);$('preview-image').src=d.image;updateMonitorLink();updateCoupon(id==='price')}));
['coupon-code','coupon-type','coupon-value','coupon-cap','coupon-minimum'].forEach(id=>$(id).addEventListener('input',()=>updateCoupon(true)));$('coupon-final').addEventListener('input',()=>updateCoupon(false));
$('source-url').addEventListener('keydown',e=>{if(e.key==='Enter'){e.preventDefault();$('extract').click()}});
document.addEventListener('keydown',e=>{if((e.ctrlKey||e.metaKey)&&e.key==='Enter'&&current&&!$('publish').disabled){e.preventDefault();$('publish').click()}});
$('paste-btn').onclick=async()=>{try{const text=await navigator.clipboard.readText();if(text){$('source-url').value=text.trim();$('extract').click()}}catch(e){$('source-url').focus();document.execCommand('paste')}};

$('coupon-box').addEventListener('toggle',()=>{if($('coupon-box').open)couponFillLast();updateCoupon(true)});
$('coupon-clear').addEventListener('click',()=>{couponClear();updateCoupon(true)});

// "Autorizar monitoramento": usa a mesma sugestão do "Preencher pelo link" (marca + até 3 termos específicos).
// Antes, todas as palavras do título viravam termo obrigatório e a busca quase nunca achava a mini.
$('monitor-link').addEventListener('click',async e=>{e.preventDefault();const d=formDeal();
 try{const r=await fetch('/api/monitored/sugestao',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({deal:d})});const g=await r.json();if(!r.ok)throw new Error(g.error);
  location.href='/monitored?'+new URLSearchParams({name:g.name||d.title,search_terms:g.search_terms,required_terms:g.required_terms,max_price:'',observed_price:d.price||'',product_id:d.id,store:d.store,url:d.url,image:d.image||''})}
 catch(_){location.href=$('monitor-link').href}});
