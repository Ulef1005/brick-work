/* Found in (#40): bounded pages, latest request wins, and local wishlist feedback. */
(function(){
'use strict';
function mount(root){
 const form=root.querySelector('[data-found-form]'),results=root.querySelector('[data-found-results]'),
 status=root.querySelector('[data-found-status]'),retry=root.querySelector('[data-found-retry]'),clear=root.querySelector('[data-found-clear]');
 let offset=0,version=0;
 async function load(next=0){
  offset=next;const current=++version,url=new URL(root.dataset.url,location.href);
  new FormData(form).forEach((value,key)=>url.searchParams.set(key,value));
  url.searchParams.set('offset',offset);
  status.textContent='Loading…';retry.hidden=true;results.setAttribute('aria-busy','true');
  clear.hidden=form.elements.type.value==='all';
  clear.textContent=form.elements.type.value==='sets'?'Sets only ×':'Minifigures only ×';
  try{
   const response=await fetch(url,{headers:{'X-Requested-With':'XMLHttpRequest'}});
   if(!response.ok)throw new Error('Could not load Found in.');
   const html=await response.text();
   if(current!==version)return;
   results.innerHTML=html;status.textContent='';
  }catch(error){if(current===version){status.textContent='Could not load Found in. Retry.';retry.hidden=false;}}
  finally{if(current===version)results.setAttribute('aria-busy','false');}
 }
 form.addEventListener('submit',event=>{event.preventDefault();load();});
 form.addEventListener('change',()=>load());
 clear.addEventListener('click',()=>{form.elements.type.value='all';load();});
 retry.addEventListener('click',()=>load(offset));
 root.addEventListener('click',async event=>{
  const page=event.target.closest('[data-found-offset]');
  if(page&&!page.disabled){load(Number(page.dataset.foundOffset));return;}
  const wish=event.target.closest('[data-found-wish]');
  if(!wish||wish.disabled)return;
  const collection=document.getElementById('bw-collection');wish.disabled=true;
  try{
   const response=await fetch(collection.dataset.saveUrl.replace('ACTION','wish'),{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({item_id:Number(wish.dataset.foundWish),csrf_token:collection.dataset.csrf})});
   const body=await response.json();
   if(!response.ok||body.error)throw new Error();
   const text=document.createElement('span');text.textContent='On wishlist';wish.replaceWith(text);
  }catch(error){wish.disabled=false;status.textContent='Could not add to wishlist. Try again.';}
 });
 return {load};
}
document.querySelectorAll('[data-found-in]').forEach(mount);
if(typeof module!=='undefined')module.exports={mount};
})();
