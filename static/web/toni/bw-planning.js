(() => {
  'use strict';
  function filter(rows, query, filters, sort, descending=false) {
    const text=query.trim().toLocaleLowerCase();
    const numeric=new Set(['rank','gap','cost','max','undermax','partout']);
    return rows.filter(r=>(!text || [r.number,r.also,r.name,r.colour].join(' ').toLocaleLowerCase().includes(text)) && Object.entries(filters).every(([k,v])=>!v || (k==='pinned'?String(r[k])===(v==='true'?'1':'0'):Array.isArray(r[k])?r[k].includes(v):String(r[k])===v))).sort((a,b)=>{
      if(sort==='rank' && a.pinned!==b.pinned)return Number(b.pinned)-Number(a.pinned);
      const missing=x=>x==null || x==='' || x==='None';
      if(numeric.has(sort) && missing(a[sort])!==missing(b[sort]))return missing(a[sort])?1:-1;
      const diff=numeric.has(sort)?Number(a[sort])-Number(b[sort]):String(a[sort]||'').localeCompare(String(b[sort]||''),undefined,{numeric:true});
      return diff*(descending?-1:1) || String(a.number).localeCompare(String(b.number),undefined,{numeric:true});
    });
  }
  window.BrickPlanning={filter};
  const root=document.querySelector('#bw-planning');if(!root)return;
  const nodes=[...root.querySelectorAll('[data-bp-row]')],records=nodes.map(node=>({...JSON.parse(node.dataset.record),node}));
  const search=root.querySelector('[data-bp-search]'),sort=root.querySelector('[data-bp-sort]'),order=root.querySelector('[data-bp-order]'),controls=[...root.querySelectorAll('[data-bp-filter]')],panel=root.querySelector('#bp-filters'),message=root.querySelector('[data-bp-message]'),undo=root.querySelector('[data-bp-undo]');
  if(root.dataset.screen==='wishlist')window.BrickCollection?.viewSwitch?.(root,root.querySelector('[data-bp-rows]'),'bp',window.BrickCollection.listStateKey?.());
  let receipt=null,visible=records;
  const receiptKey='bw-planning-receipt';
  try{receipt=JSON.parse(sessionStorage.getItem(receiptKey));}catch(_){}
  if(receipt){undo.hidden=false;message.textContent='Saved · Undo';}
  const exp=root.querySelector('[data-bp-export]');
  function syncExport(){
    if(!exp)return;
    const n=root.querySelectorAll('[data-bp-selected]:checked').length;
    exp.disabled=n===0;exp.textContent=n?'Export '+n+' · BrickLink XML':'Export selected · BrickLink XML';
    // #43: the printable list (and its CSV) of the same selection.
    const print=root.querySelector('[data-bp-print]');
    if(print){const ids=[...root.querySelectorAll('[data-bp-selected]:checked')].map(c=>'copy='+encodeURIComponent(c.value));
      print.setAttribute('aria-disabled',String(!n));print.href=print.dataset.url+(ids.length?'?'+ids.join('&'):'');print.textContent=n?'Print missing parts of '+n:'Print missing parts';}
  }
  root.addEventListener('change',e=>{if(e.target.matches?.('[data-bp-selected]'))syncExport();});
  function render(){
    if(!search){syncExport();return;}
    const filters=Object.fromEntries(controls.map(c=>[c.dataset.bpFilter,c.value]));
    root.querySelectorAll('[data-bp-pick]').forEach(b=>b.setAttribute('aria-pressed',String(filters[b.dataset.bpPick]===b.dataset.value)));
    visible=filter(records,search.value,filters,sort.value,order.value==='desc');
    const matching=new Set(visible.map(r=>r.node));
    nodes.forEach(n=>{n.hidden=!matching.has(n);const wish=n.querySelector('[data-wl-selected]');if(wish && n.hidden && wish.checked){wish.checked=false;wish.dispatchEvent?.(new Event('change',{bubbles:true}));}const selected=n.querySelector('[data-bp-selected]');if(selected && n.hidden)selected.checked=false;});
    syncExport();
    const container=root.querySelector('[data-bp-rows]');visible.forEach(r=>{r.node.hidden=false;container.append(r.node);});
    root.querySelector('[data-bp-count]').textContent=window.BrickFormatting.resultCount(visible.length,root.dataset.screen==='wishlist'?(records.length && records.every(r=>r.type==='S')?'sets':'items'):'results');root.querySelector('[data-bp-empty]').hidden=visible.length>0;
    const chips=root.querySelector('[data-bp-chips]');chips.replaceChildren();
    [...controls,search].forEach(c=>{if(!c.value)return;const b=document.createElement('button');b.type='button';b.textContent=(c===search?'Search: '+c.value:c.closest('label').firstChild.textContent.trim()+': '+c.selectedOptions[0].textContent)+' ×';b.setAttribute('aria-label','Remove '+b.textContent);b.addEventListener('click',()=>{c.value='';render();});chips.append(b);});
  }
  [...controls,search,sort,order].filter(Boolean).forEach(c=>c.addEventListener(c===search?'input':'change',render));
  root.querySelectorAll('[data-bp-pick]').forEach(b=>b.addEventListener('click',()=>{
    const c=controls.find(c=>c.dataset.bpFilter===b.dataset.bpPick);if(!c)return;
    c.value=c.value===b.dataset.value?'':b.dataset.value;render();
  }));
  const toggles=[...root.querySelectorAll('[data-bp-filters]')];
  const sortPanel=root.querySelector('[data-bp-sort-panel]'),sortToggles=[...root.querySelectorAll('[data-bp-sort-open]')];
  let opener=null;
  function closePanels(){
    [panel,sortPanel].filter(Boolean).forEach(p=>p.hidden=true);
    [...toggles,...sortToggles].forEach(t=>t.setAttribute('aria-expanded','false'));
  }
  function togglePanel(p,buttons,b){
    const opening=p.hidden;closePanels();p.hidden=!opening;
    buttons.forEach(t=>t.setAttribute('aria-expanded',String(opening)));
    if(opening){opener=b;p.querySelector('button, input, select')?.focus();}else{opener?.focus();}
  }
  toggles.forEach(b=>b.addEventListener('click',()=>togglePanel(panel,toggles,b)));
  sortToggles.forEach(b=>b.addEventListener('click',()=>togglePanel(sortPanel,sortToggles,b)));
  root.querySelector('[data-bp-reset]')?.addEventListener('click',()=>{controls.forEach(c=>c.value='');search.value='';render();});
  document.addEventListener('keydown',e=>{if(e.key==='Escape' && [panel,sortPanel].some(p=>p&&!p.hidden)){closePanels();opener?.focus();}if(e.key==='Tab' && panel && !panel.hidden && window.matchMedia?.('(max-width:1023px)').matches){const focusable=[...panel.querySelectorAll('button, input, select, a[href]')].filter(n=>!n.disabled && n.getClientRects().length);if(focusable.length){const first=focusable[0],last=focusable[focusable.length-1];if(e.shiftKey && document.activeElement===first){e.preventDefault();last.focus();}else if(!e.shiftKey && document.activeElement===last){e.preventDefault();first.focus();}}}if(/INPUT|SELECT|TEXTAREA/.test(e.target.tagName)||e.ctrlKey||e.metaKey||e.altKey)return;const current=e.target.closest?.('[data-bp-row]');if(['ArrowDown','ArrowUp'].includes(e.key)&&visible.length){e.preventDefault();const index=visible.findIndex(r=>r.node===current),next=Math.max(0,Math.min(visible.length-1,index+(e.key==='ArrowDown'?1:-1)));visible[next].node.focus();}if(e.key==='Enter'&&current===e.target){e.preventDefault();current.querySelector('.bp-identity a')?.click();}if(e.key==='/'&&search){e.preventDefault();search.focus();}if(e.key.toLowerCase()==='f'&&toggles[0]){e.preventDefault();toggles[0].click();}});
  async function send(action,data,collection=false){
    const response=await fetch((collection?root.dataset.collectionUrl:root.dataset.saveUrl).replace('ACTION',action),{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({...data,csrf_token:root.dataset.csrf})});
    const result=await response.json();if(!response.ok)throw new Error(result.message||'Not saved · try again');
    if(result.event_id && action!=='undo'){receipt={event_id:result.event_id,collection};sessionStorage.setItem(receiptKey,JSON.stringify(receipt));undo.hidden=false;}
    message.textContent=result.message;return result;
  }
  async function run(button,operation,reload=false){button.disabled=true;message.textContent='Saving';try{await operation();if(reload)location.reload();}catch(e){message.textContent=e.message;}finally{button.disabled=false;}}
  undo?.addEventListener('click',()=>run(undo,async()=>{await send('undo',{event_id:receipt.event_id},receipt.collection);sessionStorage.removeItem(receiptKey);receipt=null;},true));
  root.querySelectorAll('form[data-bp-action]').forEach(form=>form.addEventListener('submit',e=>{e.preventDefault();const values=Object.fromEntries(new FormData(form));run(form.querySelector('button'),()=>form.dataset.bpAction==='wish'?send('save',{entity:'wish',ids:[form.dataset.id],values},true):send('settings',{values}),true);}));
  root.querySelectorAll('[data-bp-pin]').forEach(b=>b.addEventListener('click',()=>run(b,()=>send('pin',{id:b.dataset.bpPin,pinned:b.dataset.pinned!=='true'}),true)));
  root.querySelectorAll('[data-bp-archive]').forEach(b=>b.addEventListener('click',()=>{if(window.confirm('Archive this wish? Undo restores it.'))run(b,()=>send('archive',{entity:'wish',ids:[b.dataset.bpArchive],values:{}},true),true);}));
  exp?.addEventListener('click',()=>run(exp,async()=>{
    const ids=[...root.querySelectorAll('[data-bp-selected]:checked')].map(c=>c.value);
    const response=await fetch(root.dataset.saveUrl.replace('ACTION','export'),{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({ids,summary:true,csrf_token:root.dataset.csrf})});
    const result=await response.json();if(!response.ok)throw new Error(result.message||'Could not export');
    const url=URL.createObjectURL(new Blob([result.content],{type:result.mimetype})),a=document.createElement('a');a.href=url;a.download=result.filename;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
    // A line with no BrickLink number cannot be named in a wanted list: it is left out and said so.
    const left=result.summary.skipped;
    message.textContent='Exported'+(left.length?' · '+left.length+' left out: '+left.map(n=>[n.item_no,n.color,n.reason].filter(Boolean).join(' · ')).join('; '):'');
  }).finally(syncExport));
  render();
})();
