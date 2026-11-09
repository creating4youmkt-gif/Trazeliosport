(()=>{const $=(s,r=document)=>r.querySelector(s),$$=(s,r=document)=>[...r.querySelectorAll(s)];
const tabs=$$('.tab'),btns=$$('.tabs button'),reducir=matchMedia('(prefers-reduced-motion:reduce)').matches;
function ir(id){tabs.forEach(t=>t.classList.toggle('on',t.id===id));btns.forEach(b=>b.classList.toggle('on',b.dataset.tab===id));scrollTo(0,0);if(id==='stats')contar();if(id==='carta')barra()}
btns.forEach(b=>b.addEventListener('click',()=>ir(b.dataset.tab)));
function contar(){$$('[data-n]').forEach(e=>{const f=+e.dataset.n,dec=e.dataset.d?1:0;if(reducir||e.dataset.hecho){e.textContent=f.toFixed(dec);return}e.dataset.hecho=1;const t0=performance.now();(function p(t){const k=Math.min(1,(t-t0)/900);e.textContent=(f*(1-Math.pow(1-k,3))).toFixed(dec);if(k<1)requestAnimationFrame(p)})(t0)})}
function barra(){const b=$('.barra i');if(b)setTimeout(()=>b.style.width=b.dataset.w+'%',60)}
const c=$('#cromo');if(c&&!reducir){c.addEventListener('pointermove',e=>{const r=c.getBoundingClientRect(),x=(e.clientX-r.left)/r.width-.5,y=(e.clientY-r.top)/r.height-.5;c.style.transform=`rotate(-1.5deg) perspective(700px) rotateY(${x*14}deg) rotateX(${-y*14}deg)`});c.addEventListener('pointerleave',()=>c.style.transform='')}
$$('.logro').forEach(l=>l.addEventListener('click',()=>{const d=l.querySelector('small');if(d)d.hidden=!d.hidden}));
if(window.LOGROS&&window.DID){const k='trz-logros-'+window.DID;let antes=null;try{antes=JSON.parse(localStorage.getItem(k))}catch(e){}
 const nuevos=antes?window.LOGROS.filter(x=>!antes.includes(x)):[];try{localStorage.setItem(k,JSON.stringify(window.LOGROS))}catch(e){}
 if(nuevos.length){const f=$('#fiesta');$('#fnom').textContent=nuevos.join(' · ');f.classList.add('on');$('#fcerrar').onclick=()=>f.classList.remove('on')}}
ir('carta');contar()})();
