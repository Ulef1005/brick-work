(() => {
  'use strict';
  const nowrapTail = window.BrickFormatting.nowrapTail;
  const KINDS = {S:'set',P:'part',M:'minifigure',I:'instructions',O:'box',G:'gear',B:'book',C:'catalog'}, TYPES = Object.fromEntries(Object.entries(KINDS).map(([letter,kind]) => [kind,letter]));
  const filterRows = (rows, query, filter, sort) => rows.filter(r => `${r.name || ''} ${r.number || ''} ${r.colour || ''}`.toLowerCase().includes(query.toLowerCase()) && (!filter || r.filterValue === filter)).sort((a,b) => sort === 'rank' ? a.rank-b.rank : sort === 'need' ? Number(b.need)-Number(a.need) : String(a[sort] || '').localeCompare(String(b[sort] || ''),undefined,{numeric:true}));
  const payload = (action, values, controls, context={}) => {
    const data = {...values,...context};
    if(action==='received')data.counts=Object.fromEntries(controls.received.map(r=>[r.id,r.value]));
    if(action==='save' && controls.pairs.length)data.pairs=Object.fromEntries(controls.pairs.map(r=>[r.id,r.value]));
    if(action==='move')data.selections=controls.selections;
    if(action==='allocate')data.chosen=controls.allocations.filter(r=>Number(r.quantity)>0);
    return data;
  };
  const countText=(node,count)=>node.dataset.noun?`${count} ${count===1&&node.dataset.nounOne?node.dataset.nounOne:node.dataset.noun}`:window.BrickFormatting.resultCount(count);
  window.BrickLedger={filterRows,payload,countText};
  const root=document.querySelector('#bw-ledger');if(!root)return;
  const focusControl=control=>(control.hidden?control.nextElementSibling?.querySelector('button'):control)?.focus();
  let busy=false, retryForm=null, retryUndo=null;
  root.querySelector('[data-retry]')?.addEventListener('click',()=>retryUndo?retryUndo.click():retryForm?.requestSubmit());
  const message=root.querySelector('[data-message]');
  const save=async(action,data) => {
    const multipart=data instanceof FormData;
    if(multipart)data.set('csrf_token',root.dataset.csrf);else data.csrf_token=root.dataset.csrf;
    const response=await fetch(root.dataset.url.replace('ACTION',action),{method:'POST',headers:multipart?{}:{'Content-Type':'application/json'},body:multipart?data:JSON.stringify(data)});
    const result=await response.json();if(!response.ok)throw Error(result.message || 'Not saved · try again');return result;
  };
  root.querySelectorAll('[data-list]').forEach(list=>{
    const container=list.querySelector('[data-rows]'), search=list.querySelector('[data-search]'), filter=list.querySelector('[data-filter]'), sort=list.querySelector('[data-sort]');
    const rows=Array.from(container.querySelectorAll('[data-row]')).map((node,rank)=>({...node.dataset,rank,node}));
    [...new Set(rows.map(r=>r.filterValue).filter(Boolean))].sort().forEach(value=>{const option=document.createElement('option');option.value=value;option.textContent=value;filter.append(option);});
    let page=0;
    const size=Number(root.dataset.pageSize || 0);
    let pager,previous,next,position;
    if(size){
      pager=document.createElement('nav');pager.className='order-pager';pager.setAttribute('aria-label','List pages');
      previous=document.createElement('button');previous.type='button';previous.textContent='Previous';
      next=document.createElement('button');next.type='button';next.textContent='Next';position=document.createElement('span');
      pager.append(previous,position,next);list.append(pager);
      previous.addEventListener('click',()=>{page--;render();});next.addEventListener('click',()=>{page++;render();});
    }
    const render=()=>{
      const shown=filterRows(rows,search.value.trim(),filter.value,sort.value);
      const pages=size?Math.max(1,Math.ceil(shown.length/size)):1;
      page=Math.max(0,Math.min(page,pages-1));
      const visible=size?shown.slice(page*size,(page+1)*size):shown;
      rows.forEach(r=>{r.node.hidden=!visible.includes(r);});shown.forEach(r=>container.append(r.node));
      if(size){pager.hidden=shown.length<=size;previous.disabled=page===0;next.disabled=page===pages-1;position.textContent=`${page+1} of ${pages}`;}
      list.querySelector('[data-count]').textContent=countText(list.querySelector('[data-count]'),shown.filter(r=>r.uncounted===undefined).length);
      const chips=list.querySelector('[data-chips]');chips.replaceChildren();
      [search,filter].filter(c=>c.value).forEach(control=>{const chip=document.createElement('button');chip.type='button';chip.textContent=`${control.value} ×`;chip.setAttribute('aria-label',`Remove filter ${control.value}`);chip.addEventListener('click',()=>{control.value='';if(control.tagName==='SELECT')control.dispatchEvent?.(new Event('change'));render();focusControl(control);});chips.append(chip);});
    };
    search.addEventListener('input',render);filter.addEventListener('change',render);sort.addEventListener('change',render);
    list.querySelector('[data-filters]').addEventListener('click',e=>{const panel=list.querySelector('[data-filter-panel]');panel.hidden=!panel.hidden;e.currentTarget.setAttribute('aria-expanded',String(!panel.hidden));if(!panel.hidden)focusControl(filter);});render();
  });
  root.querySelectorAll('[data-catalogue-search]').forEach(button=>button.addEventListener('click',async()=>{
    const form=button.closest('form'), status=form.querySelector('[data-form-message]'), results=form.querySelector('[data-catalogue-results]');
    button.disabled=true;status.textContent='Searching';
    try {
      const query=new URLSearchParams({type:KINDS[form.elements.item_type.value] || 'part',q:form.querySelector('[data-catalogue-query]').value,sort:'name'});
      const response=await fetch(`${root.dataset.searchUrl}?${query}`);const data=await response.json();if(!response.ok)throw Error(data.error || 'Catalogue is not available');
      results.replaceChildren();status.textContent=window.BrickFormatting.resultCount(data.count)+' · choose an identity';
      data.items.forEach(row=>{const pick=document.createElement('button');pick.type='button';pick.textContent=`${row.label || row.number} · ${nowrapTail(row.name)}`;pick.addEventListener('click',()=>{form.elements.item_id.value=row.item_id;form.elements.item_no.value=row.number || '';form.elements.item_type.value=TYPES[row.kind] || form.elements.item_type.value;status.textContent='Identity chosen · choose the colour and match the line';results.replaceChildren();});results.append(pick);});
    }catch(error){status.textContent=error.message || 'Catalogue is not available · try again';}finally{button.disabled=false;}
  }));
  root.querySelectorAll('[data-candidates]').forEach(select=>select.addEventListener('change',()=>{select.closest('form').elements.item_id.value=select.value;}));
  root.querySelectorAll('form[data-action]').forEach(form=>form.addEventListener('submit',async e=>{
    e.preventDefault();if(busy)return;busy=true;
    const buttons=Array.from(form.querySelectorAll('button'));buttons.forEach(b=>{b.disabled=true;});form.setAttribute('aria-busy','true');
    const status=form.querySelector('[data-form-message]');status.textContent='Saving';
    try {
      const action=form.dataset.action;
      const controls={received:Array.from(form.querySelectorAll('[data-received]')).map(n=>({id:n.dataset.received,value:n.value})),pairs:Array.from(form.querySelectorAll('[data-pair]')).map(n=>({id:n.dataset.pair,value:n.value})),selections:Array.from(form.querySelectorAll('[data-selection]:checked')).map(n=>JSON.parse(n.dataset.selection)),allocations:Array.from(form.querySelectorAll('[data-allocation]')).map(n=>{const row=JSON.parse(n.dataset.allocation);return {...row,quantity:n.value,storage_id:form.querySelector(`[data-storage="${row.line_id}"]`)?.value,lot_id:form.querySelector(`[data-lot="${row.line_id}"]`)?.value};})};
      const data=action==='import'?new FormData(form):payload(action,Object.fromEntries(new FormData(form)),controls,JSON.parse(form.dataset.context || '{}'));
      const result=await save(action,data);status.textContent=result.message;message.textContent=result.message;
      location.assign(result.url || location.href);
    }catch(error){status.textContent=error.message || 'Not saved · waiting for network. Try again';message.textContent=status.textContent;
      retryForm=form;retryUndo=null;
      const notice=root.querySelector('[data-notice]'), retry=root.querySelector('[data-retry]');
      if(notice)notice.hidden=false;if(retry)retry.hidden=false;
    }
    finally{busy=false;buttons.forEach(b=>{b.disabled=false;});form.removeAttribute('aria-busy');}
  }));
  root.querySelectorAll('[data-undo-event]').forEach(button=>button.addEventListener('click',async()=>{if(busy)return;busy=true;button.disabled=true;try{await save('undo',{event_id:Number(button.dataset.undoEvent)});location.reload();}catch(error){message.textContent=error.message || 'Undo could not be saved · try again';retryUndo=button;
    const notice=root.querySelector('[data-notice]'), retry=root.querySelector('[data-retry]');
    if(notice)notice.hidden=false;if(retry)retry.hidden=false;
  }finally{busy=false;button.disabled=false;}}));
  document.addEventListener('keydown',e=>{
    if(/input|textarea|select/i.test(document.activeElement?.tagName) || e.metaKey || e.ctrlKey || e.altKey)return;
    if(e.key==='/'){e.preventDefault();root.querySelector('[data-search]')?.focus();}
    if(e.key.toLowerCase()==='f'){e.preventDefault();root.querySelector('[data-filters]')?.click();}
    if(e.key==='Escape')root.querySelectorAll('[data-filter-panel]').forEach(n=>{n.hidden=true;const opener=n.parentNode.querySelector('[data-filters]');opener.setAttribute('aria-expanded','false');opener.focus();});
    if(e.key==='ArrowDown' || e.key==='ArrowUp'){const rows=Array.from(root.querySelectorAll('[data-row]')).filter(n=>!n.hidden);const i=rows.indexOf(document.activeElement);if(rows.length){e.preventDefault();const node=rows[(i+(e.key==='ArrowDown'?1:-1)+rows.length)%rows.length];node.tabIndex=0;node.focus();}}
    if(e.key==='Enter' && document.activeElement?.matches('[data-row]') && document.activeElement.tagName!=='A')document.activeElement.querySelector('a,button')?.click();
  });
})();
