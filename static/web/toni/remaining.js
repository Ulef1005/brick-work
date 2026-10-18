/* Disclosure kit: visible sections, actual scopes, counted remainders and sheets.
   No writes occur when showing data or choosing an association scope. */
(() => {
 'use strict';
 const get = key => {try{return sessionStorage.getItem(key);}catch(_){return null;}};
 const put = (key,value) => {try{sessionStorage.setItem(key,value);}catch(_){}};
 const anchor=(dialog,button)=>{
  if(!matchMedia('(min-width:768px)').matches){dialog.style.removeProperty('left');dialog.style.removeProperty('top');dialog.style.removeProperty('margin');return;}
  const box=button.getBoundingClientRect(),width=dialog.getBoundingClientRect().width,height=dialog.getBoundingClientRect().height;
  dialog.style.margin='0';dialog.style.left=`${Math.max(16,Math.min(box.left,innerWidth-width-16))}px`;dialog.style.top=`${Math.max(16,Math.min(box.bottom+8,innerHeight-height-16))}px`;
 };
 document.addEventListener('DOMContentLoaded', () => {
  document.querySelectorAll('dialog[data-collection-disclosure]').forEach(dialog=>{
   const opener=document.querySelector(`[data-open="${dialog.id}"]`);dialog.addEventListener('shell-open',()=>anchor(dialog,opener));window.addEventListener('resize',()=>{if(dialog.open)anchor(dialog,opener);});
  });
  document.querySelectorAll('[data-associations]').forEach(region => {
   const scope=region.querySelector('[data-association-scope]'), tabs=[...region.querySelectorAll('[data-association-kind]')];
   const key=`associations:${location.pathname}`, saved=get(key)?.split(':');let kind=saved?.[0]==='figures' && tabs.length?'figures':'sets';
   if(['all','missing','damaged'].includes(saved?.[1]))scope.value=saved[1];
   const draw=()=>{region.querySelectorAll('[data-association-panel]').forEach(panel=>panel.hidden=panel.dataset.associationPanel!==`${kind}-${scope.value}`);tabs.forEach(tab=>tab.setAttribute('aria-selected',String(tab.dataset.associationKind===kind)));put(key,`${kind}:${scope.value}`);};
   tabs.forEach((tab,index)=>{tab.id=`association-tab-${tab.dataset.associationKind}`;tab.onclick=()=>{kind=tab.dataset.associationKind;draw();};tab.addEventListener('keydown',event=>{if(!['ArrowLeft','ArrowRight','Home','End'].includes(event.key))return;event.preventDefault();const next=event.key==='Home'?0:event.key==='End'?tabs.length-1:(index+1)%tabs.length;tabs[next].click();tabs[next].focus();});});
   const semantics=()=>{tabs.forEach(tab=>{tab.tabIndex=tab.dataset.associationKind===kind?0:-1;const panel=region.querySelector(`[data-association-panel="${tab.dataset.associationKind}-${scope.value}"]`);panel.id=`association-panel-${tab.dataset.associationKind}-${scope.value}`;tab.setAttribute('aria-controls',panel.id);panel.setAttribute('role','tabpanel');panel.setAttribute('aria-labelledby',tab.id);});};
   tabs.forEach(tab=>tab.addEventListener('click',semantics));scope.onchange=()=>{draw();semantics();};draw();semantics();
  });
  document.querySelectorAll('[data-scope-tabs]').forEach(region => {
   const tabs=[...region.querySelectorAll('[data-scope-tab]')];
   tabs.forEach((tab,index)=>{const panel=region.querySelector(`[data-scope-panel="${tab.dataset.scopeTab}"]`);tab.id ||= `scope-tab-${index}-${Math.random().toString(36).slice(2)}`;panel.id ||= tab.id+'-panel';tab.setAttribute('aria-controls',panel.id);panel.setAttribute('role','tabpanel');panel.setAttribute('aria-labelledby',tab.id);
    const activate=()=>{tabs.forEach(t=>{const active=t===tab;t.setAttribute('aria-selected',String(active));t.tabIndex=active?0:-1;});region.querySelectorAll('[data-scope-panel]').forEach(p=>p.hidden=p!==panel);};
    tab.onclick=activate;tab.tabIndex=index===0?0:-1;tab.onkeydown=e=>{if(!['ArrowLeft','ArrowRight','Home','End'].includes(e.key))return;e.preventDefault();const next=e.key==='Home'?0:e.key==='End'?tabs.length-1:(index+(e.key==='ArrowRight'?1:-1)+tabs.length)%tabs.length;tabs[next].click();tabs[next].focus();};
   });
  });
  document.querySelectorAll('[data-counted]').forEach(region => {
   const rows=[...region.querySelectorAll('[data-counted-row]')], sample=Number(region.dataset.sample)||3, hiddenCount=Math.max(0,rows.length-sample);
   if(!hiddenCount)return;
   const button=document.createElement('button');button.type='button';button.className='remainder-trigger';button.setAttribute('aria-expanded','false');
   region.id ||= 'remainder-'+Math.random().toString(36).slice(2);button.setAttribute('aria-controls',region.id);
   const label=`Show ${hiddenCount} more ${region.dataset.counted || 'records'}`;button.textContent=label;
   const draw=open=>{rows.slice(sample).forEach(row=>row.hidden=!open);button.setAttribute('aria-expanded',String(open));button.textContent=open?'Show less':label;};
   button.onclick=()=>{const open=button.getAttribute('aria-expanded')!=='true';if(!open)button.focus();draw(open);};region.after(button);draw(false);
  });
  document.querySelectorAll('[data-reveal]').forEach(button => {
   const panel=document.getElementById(button.dataset.reveal);if(!panel)return;button.setAttribute('aria-controls',panel.id);button.setAttribute('aria-expanded',String(!panel.hidden));
   if(button.closest('.remaining-menu') && panel.hasAttribute('data-reveal-panel')){
    const dialog=document.createElement('dialog');dialog.className='remaining-sheet';dialog.id=panel.id+'-dialog';dialog.setAttribute('aria-label',button.getAttribute('aria-label')||button.textContent.trim());
    const heading=document.createElement('div');heading.className='sheet-heading';const title=document.createElement('h2');title.textContent=button.getAttribute('aria-label')||button.textContent.trim();const closeButton=document.createElement('button');closeButton.type='button';closeButton.textContent='Close';heading.append(title,closeButton);
    const body=document.createElement('div');body.className='sheet-body';panel.before(dialog);body.append(panel);panel.hidden=false;dialog.append(heading,body);button.setAttribute('aria-controls',dialog.id);button.setAttribute('aria-expanded','false');
    button.onclick=()=>{dialog.showModal();button.setAttribute('aria-expanded','true');anchor(dialog,button);};closeButton.onclick=()=>dialog.close();dialog.addEventListener('close',()=>{button.setAttribute('aria-expanded','false');button.focus();});dialog.addEventListener('click',event=>{if(event.target===dialog)dialog.close();});window.addEventListener('resize',()=>{if(dialog.open)anchor(dialog,button);});return;
   }
   const close=()=>{panel.hidden=true;button.setAttribute('aria-expanded','false');button.focus();};
   button.onclick=()=>{panel.hidden=!panel.hidden;button.setAttribute('aria-expanded',String(!panel.hidden));};
   panel.addEventListener('keydown',e=>{if(e.key==='Escape'){e.stopPropagation();close();}});
   document.addEventListener('click',e=>{if(!panel.hidden && !panel.contains(e.target) && !button.contains(e.target)) {panel.hidden=true;button.setAttribute('aria-expanded','false');}});
  });
  document.querySelectorAll('dialog[data-auto-open]').forEach(dialog=>{const opener=document.querySelector(`[data-open="${dialog.id}"]`);window.adminShell.open(dialog,opener);});
  document.querySelectorAll('[data-confirm-cancel]').forEach(cancel=>cancel.focus());
 });
})();
