(()=>{
const canvas=document.getElementById('price-chart'),data=window.priceHistory||[];
if(!canvas||!data.length)return;
const series=['min_price','avg_price','max_price'];
const times=data.map(row=>Date.parse(row.day+'T00:00:00Z'));
function draw(){
  const ratio=window.devicePixelRatio||1,w=canvas.clientWidth,h=300;
  if(!w)return;
  canvas.width=Math.round(w*ratio);canvas.height=Math.round(h*ratio);
  const c=canvas.getContext('2d');if(!c)return;c.scale(ratio,ratio);
  const style=getComputedStyle(canvas),color=name=>style.getPropertyValue(name).trim();
  const colors=[color('--green')||'#39d98a',color('--accent')||'#f5b82e',color('--red')||'#ef6c68'];
  const goal=Number(window.monitoredTarget)||0,pad={l:64,r:20,t:25,b:42},cw=Math.max(1,w-pad.l-pad.r),ch=h-pad.t-pad.b;
  const values=data.flatMap(row=>series.map(key=>Number(row[key]))).filter(value=>Number.isFinite(value)&&value>0);
  if(goal>0)values.push(goal);
  if(!values.length)return;
  const lo=Math.floor(Math.min(...values)*0.9),hi=Math.ceil(Math.max(...values)*1.1),range=hi-lo||1;
  c.font='11px '+style.fontFamily;c.strokeStyle=color('--line')||'#292e37';c.fillStyle=color('--muted')||'#929aa7';c.lineWidth=1;
  for(let i=0;i<=4;i++){
    const py=pad.t+ch*i/4,value=hi-range*i/4;c.beginPath();c.moveTo(pad.l,py);c.lineTo(w-pad.r,py);c.stroke();c.fillText(`R$ ${value.toFixed(0)}`,3,py+4);
  }
  const span=times[times.length-1]-times[0],x=i=>pad.l+(span?cw*(times[i]-times[0])/span:cw/2),y=value=>pad.t+ch*(hi-value)/range;
  series.forEach((key,index)=>{
    c.strokeStyle=colors[index];c.lineWidth=index===1?3:2;c.beginPath();
    data.forEach((row,i)=>{const px=x(i),py=y(Number(row[key]));i?c.lineTo(px,py):c.moveTo(px,py)});c.stroke();
    data.forEach((row,i)=>{c.fillStyle=colors[index];c.beginPath();c.arc(x(i),y(Number(row[key])),3,0,Math.PI*2);c.fill()});
  });
  if(goal>0){
    c.save();c.strokeStyle=color('--history-target')||'#86b2ff';c.lineWidth=2;c.setLineDash([7,5]);c.beginPath();c.moveTo(pad.l,y(goal));c.lineTo(w-pad.r,y(goal));c.stroke();c.restore();
  }
  const count=Math.min(6,data.length,Math.max(1,Math.floor(cw/80))),indices=new Set();
  for(let i=0;i<count;i++){
    const stamp=times[0]+span*i/Math.max(1,count-1);
    const index=times.reduce((best,time,j)=>Math.abs(time-stamp)<Math.abs(times[best]-stamp)?j:best,0);indices.add(index);
  }
  c.fillStyle=color('--muted')||'#929aa7';
  indices.forEach(index=>{const date=data[index].day.split('-');c.fillText(`${date[2]}/${date[1]}`,x(index)-15,h-15)});
  canvas.setAttribute('aria-label',`Mínimo, média e máximo dos preços observados por dia.${goal>0?' Linha tracejada: alvo de R$ '+goal.toFixed(2)+'.':' Sem preço-alvo definido.'}`);
}
draw();window.addEventListener('resize',draw);window.addEventListener('monitored-target-change',draw);
new MutationObserver(draw).observe(document.documentElement,{attributes:true,attributeFilter:['data-theme']});
})();
