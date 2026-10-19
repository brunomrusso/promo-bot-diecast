(()=>{const cards=()=>[...document.querySelectorAll('.approval-card')];async function waitJob(id){for(let i=0;i<300;i++){await new Promise(r=>setTimeout(r,2000));const r=await fetch(`/api/jobs/${id}`),j=await r.json();if(j.status==='done')return j.result;if(j.status==='error')throw new Error(j.error||'Falha ao publicar')}throw new Error('Tempo limite excedido')}function coupon(card){const code=card.querySelector('.c-code').value.trim();if(!code)return{};return{manual_coupon_code:code,manual_coupon_type:card.querySelector('.c-type').value,manual_coupon_value:card.querySelector('.c-value').value,manual_coupon_max_discount:card.querySelector('.c-cap').value,manual_coupon_min_purchase:card.querySelector('.c-min').value,manual_coupon_final_price:card.querySelector('.c-final').value}}function setupCoupon(card){const price=Number(card.querySelector('.approval-prices strong').textContent.replace(/[^\d,]/g,'').replace(',','.')),els=['.c-code','.c-type','.c-value','.c-cap','.c-min'].map(s=>card.querySelector(s)),final=card.querySelector('.c-final'),output=card.querySelector('.deal-coupon-price');function calc(){const code=els[0].value.trim(),kind=els[1].value,value=Number(els[2].value),cap=Number(els[3].value),minimum=Number(els[4].value);let discount=kind==='percent'?price*value/100:value;if(cap)discount=Math.min(discount,cap);const valid=code&&value>0&&(!minimum||price>=minimum),result=valid?Math.max(0,price-discount):0;final.value=result?result.toFixed(2):'';output.textContent=result?`Preço sugerido: R$ ${result.toFixed(2).replace('.',',')}`:(minimum>price?'Compra mínima não atingida':'')}els.forEach(e=>e.addEventListener('input',calc))}async function act(ids,action,card=null){const payload={ids,action};if(action==='approve'&&card)payload.coupon=coupon(card);const resultEl=card?.querySelector('.approval-result');if(resultEl)resultEl.textContent=action==='approve'?'Gerando link e publicando…':'Processando…';const r=await fetch('/api/approvals/action',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)}),data=await r.json();if(!r.ok)throw new Error(data.error);if(data.jobs?.length)for(const job of data.jobs)await waitJob(job);ids.forEach(id=>document.querySelector(`.approval-card[data-id="${CSS.escape(id)}"]`)?.remove())}cards().forEach(card=>{setupCoupon(card);card.querySelectorAll('[data-action]').forEach(button=>button.onclick=async()=>{if(!confirm('Confirmar esta ação?'))return;button.disabled=true;try{await act([card.dataset.id],button.dataset.action,card)}catch(e){button.disabled=false;card.querySelector('.approval-result').textContent=e.message}})});document.getElementById('select-all')?.addEventListener('change',e=>cards().forEach(c=>c.querySelector('.item-check').checked=e.target.checked));document.querySelectorAll('[data-bulk]').forEach(button=>button.onclick=async()=>{const selected=cards().filter(c=>c.querySelector('.item-check').checked),ids=selected.map(c=>c.dataset.id);if(!ids.length)return alert('Selecione pelo menos uma oferta');if(!confirm(`Aplicar a ação em ${ids.length} ofertas?`))return;button.disabled=true;try{await act(ids,button.dataset.bulk)}catch(e){alert(e.message)}finally{button.disabled=false}});document.querySelectorAll('[data-action="schedule"]').forEach(button=>button.onclick=async()=>{const card=button.closest('.approval-card'),scheduled_at=prompt('Data e hora em Brasília (ex.: 2026-10-15T14:30)');if(!scheduled_at)return;button.disabled=true;try{const r=await fetch('/api/schedule',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({pending_id:card.dataset.id,scheduled_at})}),data=await r.json();if(!r.ok)throw new Error(data.error);card.remove()}catch(e){button.disabled=false;card.querySelector('.approval-result').textContent=e.message}});
// Price alert: "Caro" button
document.querySelectorAll('[data-action="price_alert"]').forEach(button=>button.onclick=e=>{e.preventDefault();e.stopPropagation();const card=button.closest('.approval-card'),form=card.querySelector('.price-alert-form');form.classList.toggle('hidden');const input=form.querySelector('.alert-target');if(!input.value){const price=Number(card.dataset.price||0);input.value=price>0?(price*0.8).toFixed(2):''}});
document.querySelectorAll('.btn-cancel-alert').forEach(button=>button.onclick=()=>{button.closest('.price-alert-form').classList.add('hidden')});
document.querySelectorAll('.btn-set-alert').forEach(button=>button.onclick=async()=>{const card=button.closest('.approval-card'),form=card.querySelector('.price-alert-form'),target=Number(form.querySelector('.alert-target').value),price=Number(card.dataset.price||0),title=card.querySelector('h3').textContent;if(!target||target<=0){return alert('Informe um preço-alvo válido')}if(target>=price){return alert('O preço-alvo deve ser menor que o preço atual')}button.disabled=true;try{const r=await fetch('/api/price-alert',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({product_id:card.dataset.id,title,store:card.dataset.store,target_price:target,current_price:price,url:card.dataset.url,image:card.dataset.image})}),data=await r.json();if(!r.ok)throw new Error(data.error);card.remove();if(window.toast)toast('Alerta de preço criado')}catch(e){button.disabled=false;alert(e.message)}});
// Keyboard shortcuts: J/K navigate, A approve, R reject, X block
let focusIdx=-1;
function focusCard(i){const c=cards();if(!c.length)return;focusIdx=Math.max(0,Math.min(i,c.length-1));c.forEach((card,j)=>card.classList.toggle('card-focus',j===focusIdx));c[focusIdx].scrollIntoView({block:'nearest',behavior:'smooth'})}
document.addEventListener('keydown',e=>{if(e.target.tagName==='INPUT'||e.target.tagName==='TEXTAREA'||e.target.tagName==='SELECT')return;const c=cards();if(!c.length)return;const focused=focusIdx>=0&&focusIdx<c.length?c[focusIdx]:null;switch(e.key.toLowerCase()){case'j':e.preventDefault();focusCard(focusIdx+1);break;case'k':e.preventDefault();focusCard(focusIdx-1);break;case'a':if(focused){e.preventDefault();focused.querySelector('[data-action="approve"]')?.click()}break;case'r':if(focused){e.preventDefault();focused.querySelector('[data-action="reject"]')?.click()}break;case'x':if(focused){e.preventDefault();focused.querySelector('[data-action="block_product"]')?.click()}break;case'c':if(focused){e.preventDefault();focused.querySelector('[data-action="price_alert"]')?.click()}break}});
// Bulk selection counter
function updateBulkCount(){const n=cards().filter(c=>c.querySelector('.item-check')?.checked).length;const el=document.getElementById('bulk-count');if(el){el.textContent=n+' selecionada'+(n!==1?'s':'');el.classList.toggle('hidden',n===0)}}
document.addEventListener('change',e=>{if(e.target.classList.contains('item-check')||e.target.id==='select-all')updateBulkCount()});
// Suggest blacklist on reject
document.addEventListener('click',async e=>{const btn=e.target.closest('[data-action="reject"]');if(!btn)return;const card=btn.closest('.approval-card');if(!card)return;setTimeout(()=>{const title=card.querySelector('h3')?.textContent||'';const words=title.toLowerCase().normalize('NFD').replace(/[\u0300-\u036f]/g,'').match(/[a-z0-9]+/g)||[];const stop=new Set(['de','do','da','dos','das','com','para','por','uma','um','hot','wheels','miniatura','carro','escala','mattel','edicao','premium']);const unique=[...new Set(words.filter(w=>w.length>3&&!stop.has(w)))].slice(0,5);if(unique.length>0&&confirm('Deseja bloquear algum termo deste produto?\\n\\nTermos: '+unique.join(', ')+'\\n\\nClique OK para escolher.')){const term=prompt('Qual termo bloquear?\\nSugestões: '+unique.join(', '));if(term&&term.trim()){fetch('/api/blacklist',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({kind:'term',value:term.trim(),label:'Sugerido ao rejeitar: '+title.slice(0,40)})}).then(r=>{if(r.ok&&window.toast)toast('Termo "'+term.trim()+'" adicionado à blacklist')})}}},300)});
// Mobile swipe to approve/reject
if('ontouchstart' in window)(function(){
  const THRESHOLD=80;
  document.querySelectorAll('.approval-card').forEach(card=>{
    // Wrap content for sliding
    const inner=document.createElement('div');
    inner.className='swipe-inner';
    while(card.firstChild)inner.appendChild(card.firstChild);
    card.innerHTML='<div class="swipe-hint swipe-approve">Aprovar</div><div class="swipe-hint swipe-reject">Rejeitar</div>';
    card.appendChild(inner);
    card.classList.add('swipe-card');
    inner.style.background='inherit';

    let startX=0,currentX=0,dragging=false;
    inner.addEventListener('touchstart',e=>{
      startX=e.touches[0].clientX;currentX=0;dragging=true;
      inner.style.transition='none';
    },{passive:true});
    inner.addEventListener('touchmove',e=>{
      if(!dragging)return;
      currentX=e.touches[0].clientX-startX;
      // Dampen the movement
      const dx=currentX*0.5;
      inner.style.transform='translateX('+dx+'px)';
      card.classList.toggle('swiping-right',dx>30);
      card.classList.toggle('swiping-left',dx<-30);
    },{passive:true});
    inner.addEventListener('touchend',()=>{
      dragging=false;
      inner.style.transition='transform .2s';
      const dx=currentX*0.5;
      if(dx>THRESHOLD){
        // Approve
        inner.style.transform='translateX(100%)';
        setTimeout(()=>{
          const btn=card.querySelector('[data-action="approve"]');
          if(btn)btn.click();
        },200);
      }else if(dx<-THRESHOLD){
        // Reject
        inner.style.transform='translateX(-100%)';
        setTimeout(()=>{
          const btn=card.querySelector('[data-action="reject"]');
          if(btn)btn.click();
        },200);
      }else{
        inner.style.transform='translateX(0)';
        card.classList.remove('swiping-right','swiping-left');
      }
    });
  });
})();
})();
