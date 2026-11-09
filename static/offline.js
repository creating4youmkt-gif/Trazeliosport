const TZ={csrf:null,db:null,_s:false,
 abrir(){return new Promise((ok,err)=>{if(this.db)return ok(this.db);const r=indexedDB.open('trazelio',1);r.onupgradeneeded=()=>{r.result.createObjectStore('cola',{autoIncrement:true});r.result.createObjectStore('kv')};r.onsuccess=()=>{this.db=r.result;ok(this.db)};r.onerror=()=>err(r.error)})},
 async tx(store,modo,fn){const d=await this.abrir();return new Promise((ok,err)=>{const t=d.transaction(store,modo);const rq=fn(t.objectStore(store));t.oncomplete=()=>ok(rq&&rq.result);t.onerror=()=>err(t.error)})},
 get(k){return this.tx('kv','readonly',s=>s.get(k))},set(k,v){return this.tx('kv','readwrite',s=>s.put(v,k))},
 encolar(m){return this.tx('cola','readwrite',s=>s.add(m))},todas(){return this.tx('cola','readonly',s=>s.getAll())},limpiar(){return this.tx('cola','readwrite',s=>s.clear())},
 limpiarPaquete(){return this.tx('kv','readwrite',s=>s.clear())},
 ahora(){const d=new Date(),p=n=>String(n).padStart(2,'0');return d.getFullYear()+'-'+p(d.getMonth()+1)+'-'+p(d.getDate())+' '+p(d.getHours())+':'+p(d.getMinutes())+':'+p(d.getSeconds())},
 norm(s){return (s||'').normalize('NFD').replace(/[\u0300-\u036f]/g,'').toLowerCase()},
 async paquete(rostros){try{const r=await fetch('/api/offline/paquete'+(rostros?'?rostros=1':''),{cache:'no-store'});if(r.ok&&(r.headers.get('content-type')||'').includes('json')){const p=await r.json();await this.set('paquete',p);return p}}catch(e){}return this.get('paquete')},
 async buscarLocal(v){const p=await this.get('paquete');if(!p)return [];const t=this.norm(v).split(/\s+/).filter(Boolean);return p.deportistas.filter(d=>t.every(x=>this.norm(d.nombre).includes(x))).slice(0,8).map(d=>({id:d.id,nombre:d.nombre,categoria:d.categoria,presente:false}))},
 async marcar(m){m.ts=m.ts||this.ahora();try{const r=await fetch('/api/offline/sync',{method:'POST',headers:{'Content-Type':'application/json','X-CSRF':this.csrf},body:JSON.stringify({marcas:[m]}),signal:AbortSignal.timeout(6000)});
  if(r.ok&&(r.headers.get('content-type')||'').includes('json')){const j=await r.json();return {enviado:true,nuevos:j.nuevos}}}catch(e){}await this.encolar(m);return {enviado:false}},
 async sincronizar(){if(this._s||!navigator.onLine)return 0;const m=await this.todas();if(!m.length)return 0;this._s=true;try{
  const c=await fetch('/api/csrf',{cache:'no-store'});if(!(c.headers.get('content-type')||'').includes('json'))return 0;const t=(await c.json()).csrf;
  const r=await fetch('/api/offline/sync',{method:'POST',headers:{'Content-Type':'application/json','X-CSRF':t},body:JSON.stringify({marcas:m})});
  if(r.ok){await this.limpiar();return m.length}}catch(e){}finally{this._s=false}return 0},
 distancia(a,b){let s=0;for(let i=0;i<128;i++){const x=a[i]-b[i];s+=x*x}return Math.sqrt(s)},
 identificarLocal(v,p){const mejor={};for(const r of p.rostros){const d=this.distancia(v,r.d);if(!(r.id in mejor)||d<mejor[r.id])mejor[r.id]=d}
  const rk=Object.entries(mejor).sort((a,b)=>a[1]-b[1]);if(!rk.length||rk[0][1]>p.umbral)return {estado:'desconocido'};if(rk.length>1&&rk[1][1]-rk[0][1]<p.margen)return {estado:'ambiguo'};
  const d=p.deportistas.find(x=>x.id==rk[0][0]);if(!d)return {estado:'desconocido'};return {estado:'ok',id:d.id,nombre:d.nombre,categoria:d.categoria,dist:rk[0][1]}},
 async estado(){const e=document.getElementById('red');if(!e)return;let n=0;try{n=(await this.todas()).length}catch(x){}
  e.textContent=(navigator.onLine?'● En línea':'○ Sin conexión')+(n?' · '+n+' por sincronizar':'');e.style.color=navigator.onLine?'':'#F59E0B'}
};
if(typeof window.CSRF!=='undefined')TZ.csrf=window.CSRF;
addEventListener('online',()=>TZ.sincronizar().then(()=>TZ.estado()));addEventListener('offline',()=>TZ.estado());
setInterval(()=>TZ.sincronizar().then(()=>TZ.estado()),30000);addEventListener('load',()=>{TZ.estado();TZ.sincronizar().then(()=>TZ.estado())});
async function salir(e){e.preventDefault();try{await TZ.limpiarPaquete();await caches.delete('trazelio-v3-p')}catch(_){}location.href='/logout'}
