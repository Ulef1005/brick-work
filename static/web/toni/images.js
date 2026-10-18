/* Delegation keeps lightboxes working after table sorting/pagination. Native
 * dialog handles focus containment and Escape; opener restoration is explicit.
 */
(function () {
  'use strict';
  if(document.toniImagesBound)return;document.toniImagesBound=true;
  function missing(img) {
    // Captured errors also cover rows inserted after the shell has loaded.
    const tile=img.closest('.bc-picture,.bw-picture');
    if(tile) {
      const original=[...tile.children],source=img.getAttribute('src');
      const number=document.createElement('span');number.className='mono';number.textContent=tile.dataset.itemNo || '';
      const label=document.createElement('span');label.textContent='No image';
      const retry=document.createElement('button');retry.type='button';retry.textContent='Retry';
      retry.addEventListener('click',()=>{tile.replaceChildren(...original);img.removeAttribute('src');img.setAttribute('src',source);});
      tile.replaceChildren(number,label,retry);return;
    }
    const region=img.closest('.collection-image');if(!region) return;
    const link=img.closest('a');
    const placeholder=region.querySelector('[data-image-missing]');
    if(link && !link.hasAttribute('data-lightbox')) {img.hidden=true;if(placeholder) link.appendChild(placeholder);}
    else if(link) link.hidden=true;
    if(placeholder) placeholder.hidden=false;
  }
  document.addEventListener('error',e=>{if(e.target.tagName==='IMG') missing(e.target);},true);
  document.addEventListener('DOMContentLoaded',()=>{
    document.querySelectorAll('.collection-image img,.bc-picture img,.bw-picture img').forEach(img=>{if(img.complete && !img.naturalWidth) missing(img);});
    const dialog=document.createElement('dialog');dialog.className='dialog-wide';dialog.setAttribute('aria-labelledby','image-title');
    const stack=document.createElement('div');stack.className='stack';
    const title=document.createElement('h2');title.id='image-title';title.textContent='Collection image';
    const close=document.createElement('button');close.textContent='Close image';close.autofocus=true;
    const stage=document.createElement('div');stage.className='lightbox-stage';
    const caption=document.createElement('p');caption.setAttribute('role','status');
    const actions=document.createElement('div');actions.className='actions';
    const prev=document.createElement('button');prev.textContent='Previous';
    const next=document.createElement('button');next.textContent='Next';
    const retry=document.createElement('button');retry.textContent='Retry image';retry.hidden=true;
    actions.append(prev,next,retry);stack.append(title,close,stage,caption,actions);dialog.append(stack);document.body.append(dialog);
    let gallery=[], index=0, opener;
    function show() {
      const link=gallery[index];if(!link) return;
      stage.replaceChildren();retry.hidden=true;
      const img=document.createElement('img');img.alt=link.dataset.caption || (link.tagName==='IMG'?link.alt:link.querySelector('img')?.alt) || 'Part image';
      caption.textContent=img.alt;
      img.onerror=()=>{stage.textContent='Image unavailable';retry.hidden=false;};
      img.src=link.tagName==='IMG'?(link.dataset.full||link.currentSrc||link.src):link.href;img.onclick=()=>dialog.close();stage.append(img);prev.disabled=index===0;next.disabled=index===gallery.length-1;
    }
    prev.onclick=()=>{if(index>0){index--;show();}};next.onclick=()=>{if(index<gallery.length-1){index++;show();}};
    retry.onclick=show;close.onclick=()=>dialog.close();dialog.addEventListener('close',()=>opener?.focus());
    dialog.addEventListener('keydown',e=>{if(e.key==='ArrowLeft'){e.preventDefault();prev.click();}if(e.key==='ArrowRight'){e.preventDefault();next.click();}});
    const selector='#content img:not([src*="/icons/"]):not([data-no-lightbox])';
    function prepare(){document.querySelectorAll(selector).forEach(img=>{if(!img.closest('a,button')){img.tabIndex=0;img.setAttribute('role','button');img.setAttribute('aria-label','Enlarge '+(img.alt||'part picture'));}});}
    prepare();
    if(typeof MutationObserver!=='undefined'){const content=document.querySelector('#content');if(content)new MutationObserver(prepare).observe(content,{childList:true,subtree:true});}
    dialog.addEventListener('click',e=>{if(e.target===dialog)dialog.close();});
    document.addEventListener('keydown',e=>{if((e.key==='Enter'||e.key===' ')&&e.target.matches?.(selector)){e.preventDefault();e.target.click();}});
    document.addEventListener('click',e=>{
      if(e.ctrlKey || e.metaKey || e.shiftKey || e.altKey)return;
      const link=e.target.closest('a[data-lightbox]');
      const picture=e.target.closest('img') || e.target.closest('[data-inventory-image],.image-stage,.collection-image')?.querySelector('img');
      const item=link||(picture?.matches?.(selector)?picture:null);
      if(!item)return;
      e.preventDefault();e.stopPropagation?.();opener=item;
      gallery=link?Array.from(document.querySelectorAll('a[data-lightbox]')).filter(a=>!a.closest('[hidden]')):Array.from(document.querySelectorAll(selector)).filter(img=>!img.closest('[hidden]'));
      index=gallery.indexOf(item);show();dialog.showModal();close.focus();
    },true);
  });
})();
