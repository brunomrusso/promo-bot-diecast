(()=>{
async function imageFile(endpoint,options){
  const response=await fetch(endpoint,options);
  if(!response.ok){const error=await response.json();throw new Error(error.error||'Imagem indisponível')}
  const blob=await response.blob();
  if(!['image/jpeg','image/png','image/webp'].includes(blob.type))throw new Error('Formato de imagem não suportado');
  const url=URL.createObjectURL(blob),image=new Image();
  try{
    await new Promise((resolve,reject)=>{image.onload=resolve;image.onerror=()=>reject(new Error('Não foi possível converter a imagem'));image.src=url});
    const scale=Math.min(1,1600/Math.max(image.naturalWidth,image.naturalHeight)),canvas=document.createElement('canvas');
    canvas.width=Math.max(1,Math.round(image.naturalWidth*scale));canvas.height=Math.max(1,Math.round(image.naturalHeight*scale));
    const context=canvas.getContext('2d');if(!context)throw new Error('Conversão de imagem indisponível');
    context.fillStyle='#fff';context.fillRect(0,0,canvas.width,canvas.height);context.drawImage(image,0,0,canvas.width,canvas.height);
    const jpeg=await new Promise(resolve=>canvas.toBlob(resolve,'image/jpeg',0.9));
    if(!jpeg)throw new Error('Não foi possível converter a imagem');
    return new File([jpeg],'oferta.jpg',{type:'image/jpeg'});
  }finally{URL.revokeObjectURL(url)}
}
async function copy(text){
  const normalized=text.replace(/\r\n?/g,'\n'),plain=normalized.replace(/\n/g,'\r\n');
  if(navigator.clipboard?.write&&window.ClipboardItem){
    const escaped=document.createElement('div');escaped.textContent=normalized;
    const html='<html><body><div>'+escaped.innerHTML.replace(/\n/g,'<br>')+'</div></body></html>';
    try{await navigator.clipboard.write([new ClipboardItem({'text/plain':new Blob([plain],{type:'text/plain'}),'text/html':new Blob([html],{type:'text/html'})})]);return}catch(error){if(!navigator.clipboard.writeText)throw error}
  }
  if(navigator.clipboard?.writeText){await navigator.clipboard.writeText(plain);return}
  const input=document.createElement('textarea');input.value=normalized;input.style.position='fixed';input.style.opacity='0';document.body.appendChild(input);input.select();
  const copied=document.execCommand('copy');input.remove();if(!copied)throw new Error('O navegador não permitiu copiar o anúncio');
}
function download(file){const url=URL.createObjectURL(file),link=document.createElement('a');link.href=url;link.download=file.name;document.body.appendChild(link);link.click();link.remove();setTimeout(()=>URL.revokeObjectURL(url),60000)}
window.whatsappTools={imageFile,copy,download};
})();
