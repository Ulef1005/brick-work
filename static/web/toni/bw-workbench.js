/* Native dialogs provide focus trapping; shell restores the opening control. */
(() => {
  'use strict';
  const nowrapTail = window.BrickFormatting.nowrapTail;
  // #41: a size in the query ("2x1", "1 2", "x2") matches the part's size key; other words as text.
  const textMatch = (row, query) => {
    const text = `${row.name || ''} ${row.number || ''} ${row.colour || ''}`.toLowerCase();
    const size = (typeof window !== 'undefined' && window.BrickSize) ? window.BrickSize.parse(query) : null;
    if (size && (size.full || size.partial)) return window.BrickSize.matches(row.name, size) && size.rest.toLowerCase().split(/\s+/).filter(Boolean).every(w => text.includes(w));
    return text.includes(query.toLowerCase());
  };
  const filterRows = (rows, query, filter, sort) => rows.filter(row =>
    textMatch(row, query) && (!filter || row.filterValue===filter || (row.filterValue || '').split(' ').includes(filter)))
    .sort((a,b) => sort === 'need' ? Number(b.need)-Number(a.need) : sort === 'rank' ? a.rank-b.rank : String(a[sort] || '').localeCompare(String(b[sort] || ''),undefined,{numeric:true}));
  const step = (value, delta, max) => Math.max(0,Math.min(max,Number(value)+delta));
  // #52: the Part Picker's set list pages 15 at a time with the 12h pager (as the Collection lists).
  const PAGE = 15;
  const pageItems = (pages, page) => {
    const wanted = [...new Set([1, page - 1, page, page + 1, pages].filter(n => n >= 1 && n <= pages))].sort((a, b) => a - b), items = [];
    wanted.forEach((n, i) => { if (i) { const gap = n - wanted[i - 1]; if (gap === 2) items.push(n - 1); else if (gap > 2) items.push('…'); } items.push(n); });
    return items;
  };
  const rangeText = (total, page) => total ? ((page - 1) * PAGE + 1) + ' to ' + Math.min(total, page * PAGE) + ' of ' + total : '';
  const clampPage = (total, page) => Math.min(Math.max(1, page), Math.max(1, Math.ceil(total / PAGE)));
  window.BrickWorkbench = {filterRows,step,nowrapTail,pageItems,rangeText,clampPage,PAGE};
  function pager(container, goTo) {
    const nav = document.createElement('nav'), prev = document.createElement('button'), next = document.createElement('button'), numbers = document.createElement('div'), text = document.createElement('p');
    nav.className = 'bc-pager'; nav.hidden = true; nav.setAttribute('aria-label', 'Pages'); nav.dataset.bcPager = '';
    numbers.className = 'bc-page-numbers'; text.className = 'mono';
    let current = 1;
    for (const [b, label, delta] of [[prev, 'Previous', -1], [next, 'Next', 1]]) {
      b.type = 'button'; b.className = 'bc-page-step bc-page-' + (delta < 0 ? 'prev' : 'next'); b.textContent = label; b.setAttribute('aria-label', label + ' page');
      b.addEventListener('click', () => goTo(current + delta));
    }
    nav.append(prev, numbers, next, text); container.after(nav);
    return {update(total, page) {
      const pages = Math.max(1, Math.ceil(total / PAGE)); current = page;
      nav.hidden = pages < 2; text.textContent = rangeText(total, page); prev.disabled = page <= 1; next.disabled = page >= pages;
      numbers.replaceChildren(...pageItems(pages, page).map(n => {
        if (n === '…') { const gap = document.createElement('span'); gap.className = 'bc-page-gap'; gap.textContent = '…'; gap.setAttribute('aria-hidden', 'true'); return gap; }
        const b = document.createElement('button'); b.type = 'button'; b.textContent = String(n); b.setAttribute('aria-label', 'Page ' + n);
        b.className = 'bc-page-number' + (n !== 1 && n !== pages && n !== page ? ' bc-page-neighbour' : '');
        if (n === page) b.setAttribute('aria-current', 'page');
        b.addEventListener('click', () => goTo(n)); return b;
      }));
    }};
  }
  const root = document.querySelector('#bw-workbench');
  if (!root) return;
  const message = root.querySelector('[data-message]');
  const undoButton = root.querySelector('[data-undo]');
  let lastEvent = null, busy = false, active = 0, foundCount = null;
  const lists = [];
  const announce = text => {if(message)message.textContent = text;};
  const save = async (action, data) => {
    const response = await fetch(root.dataset.url.replace('ACTION',action),{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({...data,csrf_token:root.dataset.csrf})});
    const result = await response.json();
    if (!response.ok) throw Error(result.message || 'Not saved · try again');
    return result;
  };
  root.querySelectorAll('[data-list]').forEach(list => {
    const container = list.querySelector('[data-rows]');
    const rows = Array.from(container.querySelectorAll('[data-row]')).map((node,rank) => ({...node.dataset,rank,node}));
    const search = list.querySelector('[data-search]'), filter = list.querySelector('[data-filter]'), sort = list.querySelector('[data-sort]'), direction=list.querySelector('[data-direction]');
    if (filter.options.length === 1) [...new Set(rows.map(r=>r.filterValue).filter(Boolean))].sort().forEach(value => {
      const option = document.createElement('option'); option.value = value; option.textContent = value; filter.append(option);
    });
    // Hidden rows keep their checkboxes in the form, so a choice on another page is still sent.
    let page = 1;
    const pages = root.dataset.mode==='picker' && list.dataset.list==='copies' ? pager(container, n => {page=n;render();container.scrollIntoView?.({block:'start'});}) : null;
    const render = () => {
      const shown = filterRows(rows,search.value.trim(),filter.value,sort.value);
      if(direction?.value==='desc')shown.reverse();
      rows.forEach(r=>{r.node.hidden = !shown.includes(r);});
      shown.forEach(r=>container.append(r.node));
      if(pages){
        page=clampPage(shown.length,page);
        shown.forEach((r,index)=>{r.node.hidden=index<(page-1)*PAGE || index>=page*PAGE;});
        pages.update(shown.length,page);
      }
      list.shown=shown;
      if(root.dataset.mode==='picker' && list.dataset.list==='parts'){
        active=Math.max(0,Math.min(active,shown.length-1));
        shown.forEach((r,index)=>{
          r.node.hidden=index!==active;
          r.node.querySelector('[data-part-position]').textContent=`Part ${index+1} of ${shown.length}`;
          const progress=r.node.querySelector('[data-part-progress]');progress.max=shown.length;progress.value=index+1;
        });
      }
      const count=list.querySelector('[data-count]');
      if(count)count.textContent = pages && shown.length>PAGE ? rangeText(shown.length,page) : window.BrickFormatting.resultCount(shown.length);
      const chips = list.querySelector('[data-chips]');chips.replaceChildren();
      [search,filter].filter(control=>control.value).forEach(control => {
        const chip = document.createElement('button');chip.type='button';chip.textContent=`${control.value} ×`;chip.setAttribute('aria-label',`Remove filter ${control.value}`);
        chip.addEventListener('click',()=>{control.value='';render();control.focus();});chips.append(chip);
      });
    };
    const first = () => {page=1;render();};
    search.addEventListener('input',first);filter.addEventListener('change',first);sort.addEventListener('change',first);direction?.addEventListener('change',first);
    list.querySelectorAll('[data-filters]').forEach(toggle=>toggle.addEventListener('click',()=>{const panel=list.querySelector('[data-filter-panel]');panel.hidden=!panel.hidden;list.querySelectorAll('[data-filters]').forEach(button=>button.setAttribute('aria-expanded',String(!panel.hidden)));if(!panel.hidden)filter.focus();}));
    list.querySelectorAll('[data-sort-toggle]').forEach(toggle=>toggle.addEventListener('click',()=>{
      const panel=list.querySelector('[data-sort-panel]');panel.hidden=!panel.hidden;
      list.querySelectorAll('[data-sort-toggle]').forEach(button=>button.setAttribute('aria-expanded',String(!panel.hidden)));if(!panel.hidden)sort.focus();
    }));
    lists.push({list,rows,sort,render});render();
  });
  const picker = lists.find(l=>l.list.dataset.list==='parts');
  const visible = () => picker ? picker.list.shown || [] : [];
  const focusPart = delta => {
    const rows=visible();if(!rows.length)return;
    active=(active+delta+rows.length)%rows.length;
    rows.forEach((r,index)=>{r.node.hidden=index!==active;});
    rows[active].node.focus();
  };
  const desktop = () => typeof matchMedia==='function' && matchMedia('(min-width: 1024px)').matches;
  const syncSelectorCount = form => {
    const label=form.querySelector('[data-selector-count]');if(label)label.textContent=form.elements.quantity.value;
  };
  const setDestination = form => {
    const isSet=form.elements.destination.value==='set';
    const quantity=form.querySelector('[data-quantity]');if(quantity)quantity.hidden=isSet;
    const assignments=form.querySelector('.bw-assignments');if(assignments)assignments.hidden=!isSet;
    if(isSet)form.elements.quantity.value=Array.from(form.querySelectorAll('[data-assignment]')).reduce((sum,n)=>sum+Number(n.value),0);
    const card=form.closest('[data-row]');
    const count=card?.querySelector('[data-found-count]');
    if(!isSet&&count)form.elements.quantity.value=count.value;
    syncSelectorCount(form);
    form.querySelectorAll('.bw-destination').forEach(node=>node.classList.toggle('is-selected',node.querySelector('input').checked));
  };
  const openPart = () => {
    const node=visible()[active]?.node,form=node?.querySelector('form[data-action="found"]'),button=node?.querySelector('[data-open]');
    if(!button || button.disabled)return;
    if(foundCount!==null){
      const requested=foundCount;
      const count=node.querySelector('[data-found-count]');if(count)count.value=requested;
      form.elements.quantity.value=requested;setDestination(form);foundCount=null;
      if(Number(form.elements.quantity.value)!==requested)announce(`Found count ${form.elements.quantity.value} · set count follows copy assignments; adjust the steppers to change it`);
    }
    if(desktop())form.querySelector('input[name=destination]').focus();else button.click();
  };
  const selectors = Array.from(root.querySelectorAll('[data-selector]'));
  const placeSelectors = () => selectors.forEach(selector=>{
    const card=selector.closest('[data-row]'),dialog=card.querySelector('[data-mobile-selector]');
    if(dialog.open)dialog.close();
    if(desktop())card.querySelector('.bw-picker-details').insertBefore(selector,dialog);
    else dialog.append(selector);
  });
  if(selectors.length){
    placeSelectors();
    if(typeof matchMedia==='function')matchMedia('(min-width: 1024px)').addEventListener('change',placeSelectors);
    selectors.forEach(selector=>{
      const form=selector.querySelector('form');setDestination(form);
      form.querySelectorAll('input[name=destination]').forEach(n=>n.addEventListener('change',()=>setDestination(form)));
      const card=selector.closest('[data-row]'),count=card.querySelector('[data-found-count]');
      count.addEventListener('input',()=>{form.elements.quantity.value=count.value;syncSelectorCount(form);});
      selector.querySelector('[data-selector-close]').addEventListener('click',()=>card.querySelector('[data-mobile-selector]').close());
      form.elements.quantity.addEventListener('input',()=>{count.value=form.elements.quantity.value;syncSelectorCount(form);});
    });
  }
  const selection = root.querySelector('[data-selection]');
  const selectionCount = () => {
    if (!selection) return;
    const count = Array.from(root.querySelectorAll('input[name=copy]')).filter(n=>n.checked).length;
    const next=root.querySelector('[data-continue]');if(next)next.textContent = `Continue · ${count} ${count===1?'set':'sets'}`;
  };
  const selectMode = all => {
    root.querySelectorAll('input[name=copy]').forEach(n=>{n.checked=all;});
    root.querySelector('[data-all]')?.setAttribute('aria-pressed',String(all));
    root.querySelector('[data-none]')?.setAttribute('aria-pressed',String(!all));
    selectionCount();
  };
  root.querySelector('[data-all]')?.addEventListener('click',()=>selectMode(true));
  root.querySelector('[data-none]')?.addEventListener('click',()=>selectMode(false));
  root.querySelectorAll('input[name=copy]').forEach(n=>n.addEventListener('change',()=>{
    root.querySelector('[data-all]')?.setAttribute('aria-pressed','false');
    root.querySelector('[data-none]')?.setAttribute('aria-pressed','true');selectionCount();
  }));
  if(selection){
    const copies=Array.from(root.querySelectorAll('input[name=copy]'));
    if(!copies.some(n=>n.checked))selectMode(true);
    else {
      const all=copies.every(n=>n.checked);
      root.querySelector('[data-all]')?.setAttribute('aria-pressed',String(all));
      root.querySelector('[data-none]')?.setAttribute('aria-pressed',String(!all));selectionCount();
    }
  }
  root.querySelector('[data-selection]')?.addEventListener('submit',event=>{if(!Array.from(root.querySelectorAll('input[name=copy]')).some(n=>n.checked)){event.preventDefault();announce('Choose at least one copy');}});
  const ranking = root.querySelector('[data-rank-keys]');
  const rankSummary = () => {
    if(!ranking)return;
    let position=0;
    const names=[];
    Array.from(ranking.children).forEach(row=>{
      const toggle=row.querySelector('input');
      row.querySelector('[data-rank-position]').textContent=toggle.checked&&!toggle.disabled?String(++position):'';
      if(toggle.checked&&!toggle.disabled)names.push(row.querySelector('label span').textContent.toLowerCase());
    });
    const text=names.join(', then ') || 'Default order';
    root.querySelector('[data-rank-summary]').textContent=text.charAt(0).toUpperCase()+text.slice(1);
  };
  const canMoveRank = row => row && !row.querySelector('input').disabled && !row.querySelector('[aria-disabled="true"]');
  const moveRank = (row, delta) => {
    if(!canMoveRank(row))return;
    const rows=Array.from(ranking.children),index=rows.indexOf(row),target=rows[index+delta];
    if(!target)return;
    ranking.insertBefore(row,delta<0?target:target.nextSibling);rankSummary();
  };
  if(ranking){
    let dragged=null;
    Array.from(ranking.children).forEach(row=>{
      row.querySelector('input').addEventListener('change',rankSummary);
      row.querySelector('[data-drag]').addEventListener('keydown',event=>{
        if(event.key==='ArrowUp'||event.key==='ArrowDown'){event.preventDefault();moveRank(row,event.key==='ArrowUp'?-1:1);}
      });
      row.addEventListener('dragstart',event=>{if(!canMoveRank(row)){event.preventDefault();dragged=null;return;}dragged=row;event.dataTransfer.setData('text/plain',row.dataset.rankKey);});
      row.addEventListener('dragover',event=>{if(canMoveRank(dragged)&&canMoveRank(row))event.preventDefault();});
      row.addEventListener('drop',event=>{event.preventDefault();if(canMoveRank(dragged)&&canMoveRank(row)&&dragged!==row){ranking.insertBefore(dragged,row);rankSummary();}dragged=null;});
    });rankSummary();
  }
  if (root.dataset.mode==='picker') picker?.rows.forEach(row=>row.node.addEventListener('focus',()=>{active=visible().findIndex(r=>r.node===row.node);}));
  root.querySelector('[data-back]')?.addEventListener('click',()=>focusPart(-1));
  root.querySelector('[data-skip]')?.addEventListener('click',()=>{announce('Skipped for later · missing count unchanged');focusPart(1);});
  root.querySelectorAll('[data-step]').forEach(button=>button.addEventListener('click',()=>{
    const input=button.parentNode.querySelector('input');input.value=step(input.value,Number(button.dataset.step),Number(input.max));
    const form=button.closest('form');form.elements.quantity.value=Array.from(form.querySelectorAll('[data-assignment]')).reduce((sum,n)=>sum+Number(n.value),0);syncSelectorCount(form);
  }));
  root.querySelectorAll('[data-assignment]').forEach(input=>input.addEventListener('input',()=>{const form=input.closest('form');form.elements.quantity.value=Array.from(form.querySelectorAll('[data-assignment]')).reduce((sum,n)=>sum+Number(n.value),0);syncSelectorCount(form);}));
  root.querySelectorAll('form[data-action]').forEach(form=>form.addEventListener('submit',async event=>{
    event.preventDefault();if(busy)return;busy=true;
    const buttons=Array.from(form.querySelectorAll('button'));const disabled=buttons.map(b=>b.disabled);buttons.forEach(b=>{b.disabled=true;});
    const status=form.querySelector('[data-form-message]');status.textContent='Saving';
    try {
      const data={...JSON.parse(form.dataset.identity || '{}'),quantity:form.elements.quantity.value};
      if(form.dataset.action==='found'){
        data.destination=form.elements.destination.value;data.assignments={};
        form.querySelectorAll('[data-assignment]').forEach(input=>{if(Number(input.value)>0)data.assignments[input.dataset.assignment]=input.value;});
      }
      if(form.dataset.action==='booklets')data.text=form.elements.text.value;
      const result=await save(form.dataset.action,data);lastEvent=result.event_id;if(undoButton)undoButton.hidden=false;announce('Saved');status.textContent='Saved';
      if(form.dataset.action==='found') {
        const card=form.closest('[data-row]');const badge=card.querySelector('[data-badge]');badge.dataset.count=Number(badge.dataset.count || 0)+Number(data.quantity);badge.textContent=`${badge.dataset.count} found`;badge.hidden=false;
        if(data.destination==='set') {
          form.querySelectorAll('[data-assignment]').forEach(input=>{input.max=Number(input.max)-Number(input.value);input.value=0;});
          const remaining=Array.from(form.querySelectorAll('[data-assignment]')).reduce((sum,n)=>sum+Number(n.max),0);
          card.dataset.need=remaining;card.querySelector('[data-remaining]').textContent=`Pick ${remaining} still missing`;
        }
        form.closest('dialog')?.close();
        if(root.dataset.mode==='picker')focusPart(1);
      } else {
        // A save navigates to a fresh snapshot; its receipt stays in Recent saves.
        location.reload();
      }
    } catch(error) {status.textContent=error.message || 'Not saved · waiting for network. Try again';announce(status.textContent);}
    finally {busy=false;buttons.forEach((b,index)=>{b.disabled=disabled[index];});}
  }));
  const undo = async identifier => {if(busy)return;busy=true;try{await save('undo',{event_id:identifier});announce('Undone');location.reload();}catch(error){announce(error.message || 'Undo could not be saved · try again');}finally{busy=false;}};
  undoButton?.addEventListener('click',()=>{if(lastEvent)undo(lastEvent);});
  root.querySelectorAll('[data-undo-event]').forEach(button=>button.addEventListener('click',()=>undo(button.dataset.undoEvent)));
  document.addEventListener('keydown',event=>{
    if(event.altKey || event.ctrlKey && !event.metaKey && event.key.toLowerCase()!=='z')return;
    const dialog=root.querySelector('dialog[open]');
    const destinationForm=dialog?.querySelector('form') || (desktop() && visible()[active]?.node.querySelector('form[data-action="found"]'));
    if(destinationForm && ['1','2','3'].includes(event.key) && (!['INPUT','TEXTAREA','SELECT'].includes(event.target.tagName) || event.target.type==='radio')) {
      const value=['set','loose','list'][Number(event.key)-1];destinationForm.querySelector(`input[value="${value}"]`).checked=true;setDestination(destinationForm);event.preventDefault();return;
    }
    if(['INPUT','TEXTAREA','SELECT'].includes(event.target.tagName))return;
    const key=event.key.toLowerCase();
    if(key==='z' && lastEvent){event.preventDefault();undo(lastEvent);return;}
    if(key==='enter' && event.target.tagName==='BUTTON')return;
    if(root.dataset.mode!=='picker' || root.querySelector('[data-pick]')?.hidden || dialog)return;
    if(/^[1-9]$/.test(key)){event.preventDefault();foundCount=Number(key);announce(`Found count ${foundCount} · Enter to choose a destination`);}
    else if(key==='enter' || key==='f'){event.preventDefault();openPart();}
    else if(key==='arrowleft'){event.preventDefault();focusPart(-1);}
    else if(key==='arrowright' || key==='s'){event.preventDefault();focusPart(1);}
    else if(key==='m'){announce('Still missing · count unchanged');focusPart(1);}
    else if(key==='/'){event.preventDefault();picker?.list.querySelector('[data-search]')?.focus();}
  });
})();
