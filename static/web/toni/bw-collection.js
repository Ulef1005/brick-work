/* Collection lists materialize only their visible records. */
(() => {
  'use strict';
  const nowrapTail = window.BrickFormatting.nowrapTail;
  // The Rebrickable number first, the BrickLink number beside it where it differs, a local BrickLink-born item marked (core/items.py).
  function numberLabel(r){return !r.number?'':r.source==='bricklink'?r.number+' (BrickLink)':r.also?r.number+' · BrickLink '+r.also:r.number;}
  function filterRows(rows, query='', filters={}, sort='number', direction='asc', group='') {
    // #41: a size in the query ("2x1", "1 2", "1*2", "x2") matches by size key; other words as text.
    const size=(typeof window!=='undefined'&&window.BrickSize)?window.BrickSize.parse(query):{full:null,partial:null,rest:query};
    const sized=size.full||size.partial,term=(sized?size.rest:query).trim().toLocaleLowerCase();
    const text=r=>[r.name,r.number,r.also,r.colour,r.category,r.theme,r.year].join(' ').toLocaleLowerCase();
    const matches=rows.filter(r => (!sized || window.BrickSize.matches(r.name,size)) && (!term || (sized?term.split(/\s+/).every(w=>text(r).includes(w)):text(r).includes(term))) && Object.entries(filters).every(([key,value]) => {
      if (!value) return true;
      if (key==='inventory') return (value==='parts'?!['M','?','I','O'].includes(r.type):value==='figures'?['M','?'].includes(r.type):['I','O'].includes(r.type));
      if (key==='status' && value==='unknown') return (r.status||[]).includes('');
      if (key==='tag' || key==='has') return (r.flags||[]).includes(value);
      if (key==='lot' && value==='any') return (r.lot||[]).some(x=>String(x)!=='null');
      if (key==='problem') return Number(r[value])>0;
      if (key==='duplicates') return String(!!r.duplicates)===value;
      return (Array.isArray(r[key])?r[key].map(String):[String(r[key]??'')]).includes(value);
    }));
    const compare=(a,b,key)=>['lot','storage','place'].includes(key)?(groupValue(a,key)==='null')-(groupValue(b,key)==='null')||groupValue(a,key).localeCompare(groupValue(b,key),undefined,{numeric:true}):key==='index'?Number(a.index||0)-Number(b.index||0):key==='used_price'?comparePrice(a,b):key==='missing'?(Number(a.missing||0)+Number(a.damaged||0))-(Number(b.missing||0)+Number(b.damaged||0)):['quantity','missing','year','damaged'].includes(key)?Number(a[key]||0)-Number(b[key]||0):String(a[key]||'').localeCompare(String(b[key]||''),undefined,{numeric:true});
    return matches.sort((a,b)=> (group?compare(a,b,group):0) || (sort==='used_price' && (!a.price || !b.price)?Number(!a.price)-Number(!b.price):0) || (compare(a,b,sort)*(direction==='desc' || sort==='missing'?-1:1)) || compare(a,b,'number') || compare(a,b,'id'));
  }
  // Array-valued fields (lot, storage, place) group by their first recorded value; 'null' means none.
  function groupValue(r,key) {
    const v=r[key];
    if(Array.isArray(v))return String(v.find(x=>String(x)!=='null')??(v.length?'null':''));
    return String(v??'');
  }
  function comparePrice(a,b) {
    // Keep unpriced rows last in either direction; currencies stay separate.
    if(!a.price || !b.price)return !a.price-!b.price;
    return String(a.price[0]).localeCompare(String(b.price[0])) || Number(a.price[1])-Number(b.price[1]);
  }
  function missingSummary(rows) {
    const gaps=rows.flatMap(r=>{
      const parts=Number(r.missing_parts||0),figures=Number(r.missing_figures||0);
      const labels=[parts?parts+' '+(parts===1?'part':'parts'):'',figures?figures+' '+(figures===1?'fig':'figs'):''].filter(Boolean);
      return labels.length?[labels.join(', ')+' in '+(numberLabel(r)||r.name)]:[];
    });
    // Kit 1c shows a short line: the first few sets, then a bare count of the rest.
    const shown=gaps.slice(0,3),more=gaps.length-shown.length;
    return gaps.length?'Missing in view: '+shown.join(' · ')+(more?' · and '+more+' more':''):'';
  }
  // The Instructions list counts booklets (its heading says so); resultNoun stays 'instructions' for other callers.
  function listNoun(kind) {
    return kind==='I'?'booklets':resultNoun(kind);
  }
  function singularNoun(kind) {
    return {S:'set',M:'minifigure',P:'part',I:'booklet',O:'box',G:'gear',B:'book',C:'catalog','?':'item',wish:'wish'}[kind]||'result';
  }
  function resultNoun(kind) {
    return {S:'sets',M:'minifigures',P:'parts',I:'instructions',O:'boxes',G:'gear',B:'books',C:'catalogs','?':'unresolved items',wish:'wishes'}[kind]||'results';
  }
  const resultCount = window.BrickFormatting.resultCount;
  function selectedInstances(checks) {
    const selected=checks.filter(c=>c.checked && !c.hidden).map(c=>({entity:c.entity,ids:c.ids}));
    if (new Set(selected.map(c=>c.entity)).size>1) throw new Error('Choose one instance type at a time');
    return {entity:selected[0]?.entity,ids:[...new Set(selected.flatMap(c=>c.ids))]};
  }
  function decodeRecords(data) {
    return data.rows.map(packed=>{
      const r={quantity:0,missing:0,damaged:0,in_sets:0,condition:[''],status:[''],storage:['null'],place:['null'],flags:[],lot:['null'],ids:[],lot_links:[],selected:false};
      Object.entries(packed).forEach(([i,value])=>r[data.fields[i]]=value);
      r.name=r.name||'';r.colour=r.colour||'';r.stock=[...(r.quantity?['loose']:[]),...(r.in_sets?['sets']:[])];return r;
    });
  }
  // One row builder for every Collection kind, including wishes. Record values
  // are always text or DOM properties; no HTML parsing is involved.
  function buildRow(r, config, selecting, changed) {
    const el=(tag,cls,text)=>{const n=document.createElement(tag);if(cls)n.className=cls;if(text!==undefined)n.textContent=String(text);return n;};
    const name=r.type==='P'?window.BrickFormatting.partName(r.name):r.name;
    const label=numberLabel(r),displayName=name||label||'Unidentified item';
    const row=el('article','bc-card');row.dataset.bcRow='';row.tabIndex=0;
    if(config.editable==='true' && r.ids.length){
      const label=el('label','bc-selection'),check=el('input');label.hidden=!selecting;check.type='checkbox';check.dataset.bcSelected='';check.checked=r.selected;
      check.setAttribute('aria-label','Select '+displayName);check.addEventListener('change',()=>{r.selected=check.checked;changed();});label.append(check,el('span','','Select'));row.append(label);
    }
    const picture=el('div','bc-picture');picture.dataset.itemNo=r.number;
    if(r.image){const button=el('button'),img=el('img');button.type='button';button.dataset.bwLightbox=config.imageBase.replace(/0$/,r.image);button.dataset.caption=displayName+(r.colour?' · '+r.colour:'');button.setAttribute('aria-label','View '+displayName);const full=button.dataset.bwLightbox;img.src=full+'?w=320';img.srcset=full+'?w=320 320w, '+full+'?w=640 640w';img.sizes='160px';img.dataset.full=full;img.alt=button.dataset.caption;img.loading='lazy';button.append(img);picture.append(button);button.addEventListener('click',()=>openPicture(button));}
    else picture.append(...(label?[el('span','mono',label)]:[]),el('span','','No image'));
    row.append(picture);
    const link=el('a'),identity=el('div','bc-identity');link.dataset.bcItemLink='';
    link.href=r.entity==='wish'?config.wishBase.replace(/0$/,r.ids[0]):config.itemBase.replace(/0$/,r.item_id)+(r.type==='P'&&r.color_id!=null?'?colour='+encodeURIComponent(r.color_id):'');
    if(r.type==='P'){const top=el('span','bc-identity-top'),colour=el('span','bc-colour',r.colour||'Unknown colour');if(/^[0-9a-f]{6}$/i.test(r.rgb||'')){colour.style.background='#'+r.rgb;colour.style.color=r.ink;}top.append(colour,...(label?[el('span','mono',label)]:[]));identity.append(top);}
    else if(label)identity.append(el('span','mono',label));
    if(r.name)identity.append(el('strong','',nowrapTail(name)));
    // Sets name the theme and sub-theme before the year ("Castle / Lion Knights · 1984").
    const secondary=[[r.theme||r.category,r.type==='S'&&r.entity!=='wish'?r.subtheme:''].filter(Boolean).join(' / '),r.year].filter(Boolean).join(' · ');
    if(secondary)identity.append(el('span','secondary',secondary));
    if(r.unresolved)identity.append(el('span','status',r.number?'To check':'Unidentified'));
    link.append(identity);row.append(link);
    if(r.unresolved){const unresolved=el('a','','Unresolved items');unresolved.href=config.unresolvedUrl;row.append(unresolved);}
    if(r.entity==='wish'){const max=el('div','bc-wish-max');max.append(el('span','bc-wish-max-label','Your max price'),el('strong','mono',r.max_price||'Not recorded'));row.append(max);}
    const foot=el('div','bc-card-foot');
    if(r.entity==='wish'){
      foot.append(el('span','mono',r.defects||r.quantity+' wanted'));
    }else if(config.type==='S'){
      // Kit 1c: status pill left and price right on one line; the gap count and the price date below; tags last.
      const main=el('div','bc-foot-main'),pills=el('div','bc-foot-pills'),sub=el('div','bc-foot-sub');
      [...new Set(r.status)].forEach(value=>{const states={C:['complete','Complete'],I:['incomplete','Incomplete'],S:['sealed','Sealed']},state=states[value]||['unknown','Not checked'];pills.append(el('span','bc-status '+state[0],state[1]));});
      main.append(pills);
      if(r.price){main.append(el('span','bc-card-money mono',r.price[4]));}else main.append(el('span','secondary','no sales'));
      const left=[r.quantity>1?r.quantity+' copies':'',r.defects].filter(Boolean).join(' · ');
      sub.append(el('span','mono bc-foot-gaps',left));
      if(r.price)sub.append(el('span','mono bc-age',r.price[5]+(r.price[3]?' · stale':'')));
      foot.append(main);if(left||r.price)foot.append(sub);
      if((r.tags||[]).length){const tags=el('div','bc-tags');r.tags.forEach(t=>tags.append(el('span','bc-tag',t)));foot.append(tags);}
    }else {
      const stock=el('span','bc-stock-count mono',r.quantity+' loose'+(r.in_sets?' · '+r.in_sets+' in sets':''));foot.append(stock);
      if(config.type==='I')foot.append(el('span','bc-pdf',r.pdf_available?'PDF available':'No PDF'));
    }
    if(r.entity!=='wish' && config.type!=='S' && r.defects)foot.append(el('span','mono',r.defects));
    if(config.type!=='S'){
      if(r.price){const price=el('span','bc-card-money mono');price.append(el('span','',r.price[4]),el('span','bc-age',r.price[5]+(r.price[3]?' · stale':'')));foot.append(price);}else foot.append(el('span','secondary','no sales'));
    }
    r.lot_links.forEach(([id,name])=>{const lot=el('a','','Lot · '+name);lot.href=config.lotBase.replace('LOT',encodeURIComponent(id));foot.append(lot);});
    row.append(foot);
    if(config.type==='P' && r.entity!=='wish')row.append(...partCells(r,config,el));
    return row;
  }
  // Parts table (kit 7a): damaged, lot, used price and quantity as cells of the row grid.
  // The grid view hides them and shows the card foot instead; the table view does the reverse.
  function partCells(r,config,el) {
    // The header row is aria-hidden, so each cell names its own column for assistive technology.
    const hid=(cell,text)=>cell.append(el('span','bc-visually-hidden',text));
    const damaged=el('span','bc-cell bc-cell-damaged'),lot=el('span','bc-cell bc-cell-lot'),price=el('span','bc-cell bc-cell-price'),qty=el('span','bc-cell bc-cell-qty');
    hid(damaged,Number(r.damaged)>0||Number(r.missing)>0?'Damaged or missing ':'No damaged pieces');
    hid(lot,r.lot_links.length?'Lot ':'No lot');hid(price,'Used price ');hid(qty,'Quantity ');
    if(Number(r.damaged)>0)damaged.append(el('span','bc-status incomplete',r.damaged+' damaged'));
    if(Number(r.missing)>0)damaged.append(el('span','mono bc-cell-missing',r.missing+' missing'));
    if(r.lot_links.length)r.lot_links.forEach(([id,name])=>{const link=el('a','bc-lot-link',name);link.href=config.lotBase.replace('LOT',encodeURIComponent(id));lot.append(link);});
    else{const none=el('span','secondary','—');none.setAttribute('aria-hidden','true');lot.append(none);}
    if(r.price){price.append(el('span','bc-cell-money mono',r.price[4]),el('span','mono bc-age',r.price[5]+(r.price[3]?' · stale':'')));}else price.append(el('span','secondary','no sales'));
    qty.append(el('span','mono bc-cell-qty-main','×'+r.quantity));
    if(r.in_sets)qty.append(el('span','mono bc-age',r.in_sets+' in sets'));
    return [damaged,lot,price,qty];
  }
  function priceBasis(rows) {
    const prices=rows.filter(r=>r.price).map(r=>r.price_basis||[]);
    if(!prices.length)return '';
    const bases=new Set(prices.map(p=>p.slice(0,2).join(':'))),sources=[...new Set(prices.map(p=>p[2]).filter(Boolean))];
    const names={bricklink:'BrickLink',brickset:'Brickset',rebrickable:'Rebrickable'};
    const labels={used:'used',new:'new'},guide={sold:'averages',stock:'listings'};
    const basis=bases.size===1&&labels[prices[0][0]]&&guide[prices[0][1]]?'prices are '+labels[prices[0][0]]+' '+guide[prices[0][1]]:'prices have mixed bases';
    return ' · '+basis+(sources.length===1?' from '+(names[sources[0]]||sources[0]):' from mixed sources');
  }
  function inventorySections(result) {
    const missing=result.filter(r=>Number(r.missing||0)+Number(r.damaged||0)+Number(r.parts_missing||0)>0);
    const missingSet=new Set(missing);
    return {missing,present:result.filter(r=>!missingSet.has(r))};
  }
  // Both Collection and Planning use the same per-viewer list state and switch.
  function listStateKey(index=0) {
    const params=new URLSearchParams(location.search);params.delete('inventory');
    const query=params.toString();
    return 'bw-collection-list:'+location.pathname+(query?'?'+query:'')+':'+index;
  }
  function viewSwitch(list,container,prefix,key,type) {
    const buttons=[...list.querySelectorAll('[data-'+prefix+'-view]')];
    // 49b: Instructions and Parts open as compact rows on a phone (kit 7a); the switch still offers the grid.
    if(['I','P'].includes(type)&&typeof matchMedia==='function'&&matchMedia('(max-width: 767px)').matches)container.dataset.view='list';
    try {const saved=JSON.parse(sessionStorage.getItem(key));if(['grid','list'].includes(saved?.view))container.dataset.view=saved.view;}catch(_){}
    const update=()=>buttons.forEach(b=>b.setAttribute('aria-pressed',String(b.dataset[prefix+'View']===container.dataset.view)));
    buttons.forEach(b=>b.addEventListener('click',()=>{
      container.dataset.view=b.dataset[prefix+'View'];update();
      let state={};try{state=JSON.parse(sessionStorage.getItem(key))||{};}catch(_){}
      sessionStorage.setItem(key,JSON.stringify({...state,view:container.dataset.view}));
    }));
    update();
  }
  /* Typing in the search box renders on a pause, not on every key. Without timers (the test harness) it runs at once. */
  function debounce(fn,ms){let timer;return (...args)=>{if(typeof setTimeout!=='function'){fn(...args);return;}clearTimeout(timer);timer=setTimeout(()=>fn(...args),ms);};}
  window.BrickCollection={debounce,groupValue,singularNoun,listStateKey,viewSwitch,nowrapTail,filterRows,selectedInstances,decodeRecords,buildRow,priceBasis,inventorySections,missingSummary,resultNoun,listNoun,resultCount};
  const root=document.querySelector('#bw-collection'); if (!root) return;
  const message=root.querySelector('[data-bc-message]'),undo=root.querySelector('[data-bc-undo]');
  const receiptKey='bw-collection-receipt';let receipt;
  try {receipt=JSON.parse(sessionStorage.getItem(receiptKey));}catch(_){}
  function showReceipt(data) {receipt=data;sessionStorage.setItem(receiptKey,JSON.stringify(data));if(message)message.textContent=data.message+' · Undo';if(undo)undo.hidden=false;}
  if(receipt) {if(message)message.textContent=receipt.message+' · Undo';if(undo)undo.hidden=false;}
  async function send(action,data,multipart=false) {
    if(multipart)data.append('csrf_token',root.dataset.csrf);else data.csrf_token=root.dataset.csrf;
    const response=await fetch(root.dataset.saveUrl.replace('ACTION',action),{method:'POST',headers:multipart?{}:{'Content-Type':'application/json'},body:multipart?data:JSON.stringify(data)});
    const result=await response.json();if(!response.ok)throw new Error(result.message||'Not saved · try again');
    if(action!=='undo')showReceipt(result);return result;
  }
  undo?.addEventListener('click',async()=>{undo.disabled=true;try {await send('undo',{event_id:receipt.event_id});sessionStorage.removeItem(receiptKey);message.textContent='Undone';location.reload();}catch(e){message.textContent=e.message;}finally{undo.disabled=false;}});
  root.querySelectorAll('[data-bw-open]').forEach(b=>b.addEventListener('click',()=>{const dialog=document.getElementById(b.dataset.bwOpen);dialog?.showModal();if(b.dataset.bcFocus==='current_value'){const field=dialog?.querySelector('[name=current_value]');const folded=field?.closest?.('details');if(folded)folded.open=true;field?.focus();}}));
  root.querySelectorAll('[data-bw-close]').forEach(b=>b.addEventListener('click',()=>b.closest('dialog')?.close()));
  root.querySelectorAll('form[data-bc-action]').forEach(form=>form.addEventListener('submit',async e=>{
    e.preventDefault();const group=form.closest('[data-bc-save-group]')||form;
    if(group.dataset.bcSaving==='true')return;
    group.dataset.bcSaving='true';
    const buttons=[...group.querySelectorAll('button')].map(button=>({button,disabled:button.disabled})),status=form.querySelector('[data-bc-form-message]');buttons.forEach(({button})=>button.disabled=true);
    if(status)status.textContent='Saving';
    try {
      const action=form.dataset.bcAction,identity=JSON.parse(form.dataset.identity||'{}');
      let data;
      if(action==='photo') {data=new FormData(form);Object.entries(identity).forEach(([k,v])=>data.append(k,v));}
      else {
        const values=Object.fromEntries(new FormData(form));
        if(form.querySelector('[data-bc-flags]'))values.flags=[...form.querySelectorAll('[name=flags]:checked')].map(c=>c.value);
        data=action==='save'?{...identity,values}:{...identity,...values};
      }
      if(action==='lot'){
        const chosen=mainSelection();
        if(chosen.entity!=='stock'||!chosen.ids.length)throw new Error('Select loose stock for this lot');data.ids=chosen.ids;
      }
      const result=await send(action,data,action==='photo');
      if(action==='archive')location.href=root.dataset.backUrl||location.pathname;
      else if(result.url)location.href=result.url;
      else location.reload();
    }catch(error){if(status)status.textContent=error.message+' · Try again';}
    finally{buttons.forEach(({button,disabled})=>button.disabled=disabled);delete group.dataset.bcSaving;}
  }));
  root.querySelectorAll('[data-bc-photo-file]').forEach(input=>input.addEventListener('change',()=>{
    const name=input.closest('.bc-photo-picker')?.querySelector('[data-bc-photo-name]');
    if(name)name.textContent=input.files?.[0]?.name||'No file chosen';
  }));
  const lists=[];let mainSelection=()=>({ids:[]});
  root.querySelectorAll('[data-bc-list]').forEach((list,index)=>{
    const container=list.querySelector('[data-bc-rows]'); if(!container)return;
    const source=list.querySelector('[data-bc-records]'),virtual=!!source;
    let nodes=[...container.querySelectorAll('[data-bc-row]')];
    const records=virtual?decodeRecords(JSON.parse(source.textContent)):nodes.map((node,i)=>({...JSON.parse(node.dataset.record||'{}'),node,index:i}));
    const search=list.querySelector('[data-bc-search]'),sort=list.querySelector('[data-bc-sort]'),direction=list.querySelector('[data-bc-direction]'),group=list.querySelector('[data-bc-group]');
    const filterControls=[...list.querySelectorAll('[data-bc-filter]')],chips=list.querySelector('[data-bc-chips]'),count=list.querySelector('[data-bc-count]'),panel=list.querySelector('[data-bc-panel]');
    let inventory='parts';
    const picks=[...list.querySelectorAll('[data-bc-pick]')],groupPicks=[...list.querySelectorAll('[data-bc-group-pick]')];
    // Quick chips (Parts, kit 7a) set one of a small family of filters; All clears the family.
    const quick=[...list.querySelectorAll('[data-bc-quick]')],quickKeys=[...new Set(quick.map(b=>b.dataset.bcQuick.split(':')[0]).filter(Boolean))];
    const tabs=[...list.querySelectorAll('[data-bc-tab]')],statusButtons=[...list.querySelectorAll('[data-bc-status]')];
    const more=list.querySelector('[data-bc-more]'),loaded=list.querySelector('[data-bc-loaded]');let limit=60,selecting=false;
    /* Paging (4.8d): optional, switched on per list by data-bc-page-size. The main list saves its page with its scroll offset so Back returns to the same page. */
    const pageSize=Math.max(0,Math.floor(Number(list.dataset?.bcPageSize))||0);let page=1;const pager=pageSize?buildPager():null;
    function buildPager(){
      const nav=document.createElement('nav'),prev=document.createElement('button'),next=document.createElement('button'),numbers=document.createElement('div'),text=document.createElement('p');
      nav.className='bc-pager';nav.hidden=true;nav.setAttribute('aria-label','Pages');nav.dataset.bcPager='';
      const goTo=n=>{page=n;render();const first=container.querySelector('[data-bc-row]');if(first&&typeof first.scrollIntoView==='function'&&list.hasAttribute('data-bc-main'))first.scrollIntoView({block:'start'});};
      // Page buttons are rebuilt on every render: focus returns to the current page when the activated button is gone or disabled.
      const focusCurrent=()=>[...numbers.children].find(c=>c.getAttribute&&c.getAttribute('aria-current')==='page')?.focus({preventScroll:true});
      for(const [b,label,delta] of [[prev,'Previous',-1],[next,'Next',1]]){b.type='button';b.className='bc-page-step bc-page-'+(delta<0?'prev':'next');b.textContent=label;b.setAttribute('aria-label',label+' page');b.addEventListener('click',()=>{goTo(page+delta);if(b.disabled)focusCurrent();});}
      numbers.className='bc-page-numbers';
      text.className='mono';text.dataset.bcPageText='';
      nav.append(prev,numbers,next,text);container.after(nav);return {nav,prev,next,numbers,text,goTo,focusCurrent};
    }
    // The visible range, for example "16 to 30 of 412".
    const rangeText=total=>total?((page-1)*pageSize+1)+' to '+Math.min(total,page*pageSize)+' of '+total:'';
    // First, last and current page with their neighbours; a single skipped page shows as its number, longer gaps as an ellipsis.
    function pageItems(pages){
      const wanted=[...new Set([1,page-1,page,page+1,pages].filter(n=>n>=1&&n<=pages))].sort((a,b)=>a-b),items=[];
      wanted.forEach((n,i)=>{if(i){const gap=n-wanted[i-1];if(gap===2)items.push(n-1);else if(gap>2)items.push('…');}items.push(n);});
      return items;
    }
    const visibleSlice=rows=>pageSize?rows.slice((page-1)*pageSize,page*pageSize):(!search&&!sort?rows:rows.slice(0,limit));
    function updatePager(total){
      if(!pager)return;const pages=Math.max(1,Math.ceil(total/pageSize));
      pager.nav.hidden=pages<2;pager.text.textContent=rangeText(total);pager.prev.disabled=page<=1;pager.next.disabled=page>=pages;
      pager.numbers.replaceChildren(...pageItems(pages).map(n=>{
        if(n==='…'){const gap=document.createElement('span');gap.className='bc-page-gap';gap.textContent='…';gap.setAttribute('aria-hidden','true');return gap;}
        const b=document.createElement('button');b.type='button';b.textContent=String(n);b.setAttribute('aria-label','Page '+n);
        b.className='bc-page-number'+(n!==1&&n!==pages&&n!==page?' bc-page-neighbour':'');
        if(n===page){b.setAttribute('aria-current','page');b.disabled=false;}
        b.addEventListener('click',()=>{pager.goTo(n);pager.focusCurrent();});return b;
      }));
      if(more)more.hidden=true;if(loaded)loaded.textContent='';
    }
    const key=listStateKey(index);let saved;
    try {saved=JSON.parse(sessionStorage.getItem(key));}catch(_){}
    filterControls.filter(c=>c.hasAttribute('data-bc-options')).forEach(c=>{
      [...new Set(records.map(r=>String(r[c.dataset.bcFilter]||'')).filter(Boolean))].sort().forEach(value=>{const o=document.createElement('option');o.value=value;o.textContent=value;c.append(o);});
    });
    if(!saved && list.querySelector('[data-bc-inventory-rows]') && sort)sort.value='missing';
    if(saved) {if(search)search.value=saved.query||'';if(sort)sort.value=saved.sort||'number';if(direction)direction.value=saved.direction||'asc';if(group)group.value=saved.group||'';filterControls.forEach(c=>c.value=saved.filters?.[c.dataset.bcFilter]||'');limit=saved.limit||60;if(saved.view)container.dataset.view=saved.view;}
    if(pageSize && saved?.page && list.hasAttribute('data-bc-main'))page=Math.max(1,Math.floor(Number(saved.page))||1);
    if(!saved && list.dataset?.bcDefaultGroup && group)group.value=list.dataset.bcDefaultGroup;
    // A grouping the list does not offer (Lot on Sets and the Wishlist) falls back to None.
    if(group && group.value && group.options?.length && ![...group.options].some(o=>o.value===group.value))group.value='';
    const params=new URLSearchParams(location.search);
    if(tabs.length){const requested=params.get('inventory')||saved?.filters?.inventory;if(tabs.some(t=>t.dataset.bcTab===requested))inventory=requested;}
    filterControls.forEach(c=>{if(params.has(c.dataset.bcFilter))c.value=params.get(c.dataset.bcFilter);});
    function filters(){return {...Object.fromEntries(filterControls.map(c=>[c.dataset.bcFilter,c.value])),...(tabs.length && inventory!=='extras'?{inventory}:{})};}
    function selection(){if(virtual)return selectedInstances(records.map(r=>({checked:r.selected,entity:r.entity,ids:r.ids})));return selectedInstances([...list.querySelectorAll('[data-bc-selected]')].map(c=>({checked:c.checked,hidden:c.closest('[data-bc-row]').hidden,entity:c.dataset.entity,ids:JSON.parse(c.value)})));}
    if(virtual)mainSelection=selection;
    function selectionCount(){const n=list.querySelector('[data-bc-selected-count]');if(n){try{n.textContent=selection().ids.length+' selected';}catch(e){n.textContent=e.message;}}}
    function saveState(){
      sessionStorage.setItem(key,JSON.stringify({query:search?.value,sort:sort?.value,direction:direction?.value,group:group?.value,filters:{...filters(),...(tabs.length?{inventory}:{})},limit,view:container.dataset.view,page:pageSize&&list.hasAttribute('data-bc-main')?page:undefined,scroll:window.scrollY}));
    }
    const canFilter=()=>inventory!=='extras';
    function render(reset=false) {
      if(reset){limit=60;page=1;}
      const extras=list.querySelector('[data-bc-tab-extras]'),inventoryPanel=list.querySelector('[data-bc-tab-inventory]');
      if(extras)extras.hidden=inventory!=='extras';
      if(inventoryPanel)inventoryPanel.hidden=inventory==='extras';
      const figureHeading=list.querySelector('[data-bc-figure-heading]'),partProgress=list.querySelector('[aria-label="Copy progress"]');
      if(figureHeading)figureHeading.hidden=inventory!=='figures';
      if(partProgress)partProgress.hidden=inventory!=='parts';
      list.dataset.inventory=inventory;
      tabs.forEach(t=>t.setAttribute('aria-pressed',String(t.dataset.bcTab===inventory)));
      if(inventory==='extras'){
        if(panel){panel.hidden=true;panel.removeAttribute('aria-modal');}
        list.querySelectorAll('[data-bc-filters]').forEach(b=>b.setAttribute('aria-expanded','false'));
        saveState();
        return;
      }
      const result=filterRows(records,search?.value||'',filters(),sort?sort.value:'index',direction?.value,group?.value);
      if(pageSize)page=Math.min(Math.max(1,page),Math.max(1,Math.ceil(result.length/pageSize)));
      const focused=document.activeElement,focusedRow=focused?.closest?.('[data-bc-row]');
      const sections=inventorySections(result),split=inventory!=='figures' && !!list.querySelector('[data-bc-missing]') && sections.missing.length>0;
      const displayed=visibleSlice(split?[...sections.missing,...sections.present]:result); // one array for retention and render
      if(virtual){
        const matching=new Set(result),shown=new Set(displayed);
        records.forEach(r=>{if(!matching.has(r))r.selected=false;if(r.node && !shown.has(r))r.node.remove();});
        nodes=[];
      }
      else nodes.forEach(n=>n.hidden=true);container.querySelectorAll('[data-bc-group-heading]').forEach(n=>n.remove());
      const missingSection=list.querySelector('[data-bc-missing]'),presentSection=list.querySelector('[data-bc-present]'),missingRows=list.querySelector('[data-bc-missing-rows]'),presentRows=list.querySelector('[data-bc-present-rows]');
      // #33 (frame 1d): the first three present lines show inline above "Show all N present parts".
      const presentInline=list.querySelector('[data-bc-present-inline]'),inlinePresent=new Set(split&&presentInline?displayed.filter(r=>Number(r.missing||0)+Number(r.damaged||0)+Number(r.parts_missing||0)===0).slice(0,3):[]);
      if(presentInline)presentInline.hidden=!inlinePresent.size;
      if(missingSection)missingSection.hidden=!split;
      if(missingSection){const label='Missing '+(inventory==='figures'?'minifigures':'parts');missingSection.setAttribute('aria-label',label);}
      if(presentSection){presentSection.hidden=!split || sections.present.length<=inlinePresent.size;list.querySelector('[data-bc-present-summary]').textContent='Show all '+sections.present.length+(sections.present.some(r=>r.missing_recorded===false)?' other ':' present ')+(inventory==='figures'?'minifigures':'parts');}
      const basis=root.querySelector('[data-bc-price-basis]');if(basis && list.hasAttribute('data-bc-main'))basis.textContent=priceBasis(result);
      let previous;const groupCounts=new Map();
      if(group?.value)result.forEach(r=>{const k=groupValue(r,group.value)||'Not recorded';groupCounts.set(k,(groupCounts.get(k)||0)+1);});
      displayed.forEach(r=>{
        if(group?.value) {const name=groupValue(r,group.value)||'Not recorded';if(name!==previous){const h=document.createElement('h3');h.dataset.bcGroupHeading='';const control=filterControls.find(c=>c.dataset.bcFilter===group.value);const headingLabel=control?[...control.options].find(o=>o.value===name)?.textContent||name:name;h.textContent=headingLabel;const n=groupCounts.get(name)||0,noun=singularNoun(root.dataset.type);h.append(Object.assign(document.createElement('span'),{className:'bc-group-count',textContent:' · '+n+' '+(n===1?noun:listNoun(root.dataset.type))}));if(group.value==='lot'&&name!=='null'&&root.dataset.lotBase){const open=document.createElement('a');open.className='bc-group-open';open.textContent='Open';open.setAttribute('aria-label','Open lot '+headingLabel);open.href=root.dataset.lotBase.replace('LOT',encodeURIComponent(name));h.append(open);}container.append(h);previous=name;}}
        const node=virtual?(r.node ||= buildRow(r,root.dataset,selecting,selectionCount)):r.node;
        if(virtual){const check=node.querySelector('[data-bc-selected]');if(check)check.checked=r.selected;const label=node.querySelector('.bc-selection');if(label)label.hidden=!selecting;}
        node.hidden=false;const destination=split?(Number(r.missing||0)+Number(r.damaged||0)+Number(r.parts_missing||0)>0?missingRows:inlinePresent.has(r)?presentInline:presentRows):container;destination.append(node);if(virtual)nodes.push(node);
        bindRow(node);
      });
      if(focusedRow && nodes.includes(focusedRow) && !focusedRow.hidden && document.activeElement!==focused)focused.focus({preventScroll:true});
      list.querySelectorAll('[data-bc-selected]').forEach(c=>{if(c.closest('[data-bc-row]').hidden)c.checked=false;});
      if(count){const countNoun=tabs.length?(inventory==='figures'?'minifigures':'parts'):listNoun(root.dataset.bcCollectionList!==undefined?root.dataset.type:''),noun=resultCount(result.length,countNoun);count.hidden=root.dataset.type==='S' && tabs.length>0;count.textContent=count.hidden?'':(pageSize&&result.length?rangeText(result.length):noun);if(pageSize&&result.length)count.setAttribute('aria-label',rangeText(result.length)+' '+countNoun);else count.removeAttribute('aria-label');}
      const summary=list.querySelector('[data-bc-missing-summary]');if(summary){summary.textContent=missingSummary(result);summary.hidden=!summary.textContent;}
      const apply=list.querySelector('[data-bc-apply]');if(apply)apply.textContent='Show '+result.length+' '+listNoun(root.dataset.type);if(loaded)loaded.textContent='Loaded '+Math.min(limit,result.length)+' of '+result.length;
      if(more)more.hidden=limit>=result.length;updatePager(result.length);
      const empty=list.querySelector('[data-bc-empty]');if(empty)empty.hidden=result.length>0;
      if(chips){chips.replaceChildren();const active=[...(search?.value?[{label:'Search: '+search.value,clear:()=>search.value=''}]:[]),...filterControls.filter(c=>c.value).map(c=>({label:c.parentElement.firstChild.textContent.trim()+': '+c.options[c.selectedIndex].textContent,clear:()=>c.value=''}))];active.forEach(a=>{const b=document.createElement('button');b.type='button';b.textContent=a.label+' ×';b.setAttribute('aria-label','Remove '+a.label);b.addEventListener('click',()=>{a.clear();render(true);});chips.append(b);});}
      picks.forEach(b=>b.setAttribute('aria-pressed',String(filters()[b.dataset.bcPick]===b.dataset.value)));
      groupPicks.forEach(b=>b.setAttribute('aria-pressed',String((group?.value||'')===b.dataset.bcGroupPick)));
      quick.forEach(b=>{const [k,v]=b.dataset.bcQuick.split(':');b.setAttribute('aria-pressed',String(k?filters()[k]===v:quickKeys.every(x=>!filters()[x])));});
      statusButtons.forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.bcStatus===(filters().status||''))));
      list.querySelectorAll('[data-bc-view]').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.bcView===container.dataset.view)));
      list.querySelectorAll('[data-bc-sort-pick]').forEach(b=>b.setAttribute('aria-pressed',String(sort?.value===b.dataset.bcSortPick)));
      list.querySelectorAll('[data-bc-order-pick]').forEach(b=>b.setAttribute('aria-pressed',String(direction?.value===b.dataset.bcOrderPick)));
      selectionCount();saveState();
    }
    const searchRender=debounce(()=>render(true),120);
    [...filterControls,search,sort,direction,group].filter(Boolean).forEach(c=>c.addEventListener(c===search?'input':'change',c===search?searchRender:()=>render(true)));
    const scrim=list.querySelector('[data-bc-sheet-scrim]');
    const sortPanel=list.querySelector('[data-bc-sort-panel]');
    function syncSheets(){if(scrim)scrim.hidden=(panel.hidden||desktop())&&(!sortPanel||sortPanel.hidden||desktop());}
    const desktop=()=>list.hasAttribute('data-bc-main') && typeof matchMedia==='function' && matchMedia('(min-width: 1024px)').matches;
    function togglePanel(){
      if(!canFilter())return;
      if(desktop()) {panel.hidden=false;panel.setAttribute('role','region');panel.removeAttribute('aria-modal');panel.querySelector('[data-bc-pick],select')?.focus();return;}
      panel.hidden=!panel.hidden;
      if(scrim && !panel.hidden && sortPanel){sortPanel.hidden=true;list.querySelectorAll('[data-bc-sort-open]').forEach(b=>b.setAttribute('aria-expanded','false'));}
      syncSheets();
      list.querySelectorAll('[data-bc-filters]').forEach(t=>t.setAttribute('aria-expanded',String(!panel.hidden)));
      panel.setAttribute('role','dialog');panel.setAttribute('aria-modal',String(!panel.hidden));
      if(!panel.hidden)panel.querySelector('button,select')?.focus();else list.querySelector('[data-bc-filters]')?.focus();
    }
    list.querySelectorAll('[data-bc-filters]').forEach(b=>b.addEventListener('click',togglePanel));
    if(panel&&desktop()){panel.hidden=false;panel.setAttribute('role','region');list.querySelectorAll('[data-bc-filters]').forEach(b=>b.setAttribute('aria-expanded','true'));}
    if(panel && typeof matchMedia==='function' && list.hasAttribute('data-bc-main'))matchMedia('(min-width: 1024px)').addEventListener?.('change',()=>{panel.hidden=!canFilter()||!desktop();panel.setAttribute('role',desktop()?'region':'dialog');panel.removeAttribute('aria-modal');list.querySelectorAll('[data-bc-filters]').forEach(b=>b.setAttribute('aria-expanded',String(!panel.hidden)));syncSheets();});
    list.querySelectorAll('[data-bc-sort-open]').forEach(b=>b.addEventListener('click',()=>{sortPanel.hidden=!sortPanel.hidden;if(scrim&&!sortPanel.hidden&&!desktop()){panel.hidden=true;list.querySelectorAll('[data-bc-filters]').forEach(b=>b.setAttribute('aria-expanded','false'));}syncSheets();if(scrim){sortPanel.setAttribute('role','dialog');sortPanel.setAttribute('aria-modal',String(!sortPanel.hidden&&!desktop()));}list.querySelectorAll('[data-bc-sort-open]').forEach(t=>t.setAttribute('aria-expanded',String(!sortPanel.hidden)));if(!sortPanel.hidden)(sortPanel.querySelector('[data-bc-sort-pick]')||sort)?.focus();else list.querySelector('[data-bc-sort-open]')?.focus();}));
    function closeSheets(){
      if(!desktop()){panel.hidden=true;panel.removeAttribute('aria-modal');list.querySelectorAll('[data-bc-filters]').forEach(b=>b.setAttribute('aria-expanded','false'));}
      if(sortPanel){sortPanel.hidden=true;sortPanel.removeAttribute('aria-modal');list.querySelectorAll('[data-bc-sort-open]').forEach(b=>b.setAttribute('aria-expanded','false'));}
      syncSheets();
    }
    scrim?.addEventListener('click',closeSheets);
    list.querySelector('[data-bc-apply]')?.addEventListener('click',()=>{closeSheets();list.querySelector('[data-bc-filters]')?.focus();});
    list.querySelectorAll('[data-bc-sort-pick]').forEach(b=>b.addEventListener('click',()=>{sort.value=b.dataset.bcSortPick;render(true);}));
    list.querySelectorAll('[data-bc-order-pick]').forEach(b=>b.addEventListener('click',()=>{direction.value=b.dataset.bcOrderPick;render(true);}));
    picks.forEach(b=>b.addEventListener('click',()=>{const control=filterControls.find(c=>c.dataset.bcFilter===b.dataset.bcPick);if(control)control.value=control.value===b.dataset.value?'':b.dataset.value;render(true);}));
    groupPicks.forEach(b=>b.addEventListener('click',()=>{if(group){group.value=b.dataset.bcGroupPick;render(true);}}));
    quick.forEach(b=>b.addEventListener('click',()=>{
      const setFilter=(k,v)=>{const control=filterControls.find(c=>c.dataset.bcFilter===k);if(control)control.value=v;};
      quickKeys.forEach(k=>setFilter(k,''));const [k,v]=b.dataset.bcQuick.split(':');if(k)setFilter(k,v);render(true);
    }));
    statusButtons.forEach(b=>b.addEventListener('click',()=>{const control=filterControls.find(c=>c.dataset.bcFilter==='status');if(control)control.value=b.dataset.bcStatus;render(true);}));
    tabs.forEach(b=>b.addEventListener('click',()=>{inventory=b.dataset.bcTab;render(true);const query=new URLSearchParams(location.search);query.set('inventory',inventory);try{window.history?.replaceState(null,'',location.pathname+'?'+query.toString()+ (location.hash||''));}catch(_){}}));
    list.querySelector('[data-bc-reset]')?.addEventListener('click',()=>{filterControls.forEach(c=>c.value='');if(search)search.value='';render(true);});
    viewSwitch(list,container,'bc',key,root.dataset.type);
    const reveal=()=>{limit+=60;render();};more?.addEventListener('click',reveal);
    if(more && 'IntersectionObserver' in window)new IntersectionObserver(entries=>{if(entries.some(e=>e.isIntersecting)&&!more.hidden)reveal();},{rootMargin:'300px'}).observe(more);
    list.querySelectorAll('[data-bc-select]').forEach(b=>b.addEventListener('click',()=>{selecting=!selecting;list.querySelectorAll('.bc-selection').forEach(n=>n.hidden=!selecting);list.querySelector('[data-bc-selection-bar]').hidden=!selecting;list.querySelectorAll('[data-bc-select]').forEach(x=>{if(x.getAttribute('role')==='switch')x.setAttribute('aria-checked',String(selecting));});if(!selecting){records.forEach(r=>r.selected=false);list.querySelectorAll('[data-bc-selected]').forEach(c=>c.checked=false);}selectionCount();}));
    list.querySelectorAll('[data-bc-selected]').forEach(c=>c.addEventListener('change',selectionCount));
    const bulkField=list.querySelector('[data-bc-bulk-field]'),bulkValue=list.querySelector('[data-bc-bulk-value]');
    bulkField?.addEventListener('change',()=>{
      const data=JSON.parse(list.querySelector('[data-bc-bulk-options]').textContent);let choices;
      if(bulkField.value==='condition')choices=[{value:'new',label:'New'},{value:'used',label:'Used'}];
      else choices=[{value:'',label:bulkField.value==='lot_id'?'No lot':'Not stored'},...(bulkField.value==='lot_id'?data.lots:data.storages).map(r=>({value:r.id,label:r.name||r.id}))];
      bulkValue.replaceChildren();choices.forEach(c=>{const o=document.createElement('option');o.value=c.value;o.textContent=c.label;bulkValue.append(o);});
    });
    async function bulk(action,button){button.disabled=true;try{const chosen=selection();if(!chosen.ids.length)throw new Error('Select an owned instance');if(chosen.entity==='wish'&&bulkField.value!=='condition'&&action!=='archive')throw new Error('Edit wish limits and quantities on the wish');if(chosen.entity==='copy'&&bulkField.value==='lot_id'&&action!=='archive')throw new Error('Only loose stock belongs to a lot');let value=bulkValue.value;if(chosen.entity==='wish'&&bulkField.value==='condition')value=value==='N'?'new':'used';const result=await send(action,{...chosen,values:action==='save'?{[bulkField.value]:value}:{}});if(result.url)location.href=result.url;else location.reload();}catch(e){message.textContent=e.message;}finally{button.disabled=false;}}
    list.querySelector('[data-bc-bulk-save]')?.addEventListener('click',e=>bulk('save',e.currentTarget));
    root.querySelector('[data-bc-bulk-archive]')?.addEventListener('click',e=>bulk('archive',e.currentTarget));
    const top=list.querySelector('[data-bc-top]');top?.addEventListener('click',()=>window.scrollTo({top:0,behavior:matchMedia('(prefers-reduced-motion: reduce)').matches?'instant':'smooth'}));
    window.addEventListener('scroll',()=>{if(top)top.hidden=window.scrollY<window.innerHeight*3;},{passive:true});
    window.addEventListener('pagehide',()=>{const data=JSON.parse(sessionStorage.getItem(key)||'{}');data.scroll=window.scrollY;sessionStorage.setItem(key,JSON.stringify(data));});
    function bindRow(n){if(n.dataset.bcKeyboard)return;n.dataset.bcKeyboard='true';n.addEventListener('keydown',e=>{if(e.target!==n)return;const visible=nodes.filter(x=>!x.hidden),i=visible.indexOf(n);if(e.key==='ArrowDown'||e.key==='ArrowUp'){e.preventDefault();visible[Math.max(0,Math.min(visible.length-1,i+(e.key==='ArrowDown'?1:-1)))]?.focus();}else if(e.key==='Enter')n.querySelector('[data-bc-item-link],a')?.click();});}
    try{render();}finally{list.removeAttribute('data-bc-pending');}if(saved?.scroll && list.hasAttribute('data-bc-main') && (!pageSize || (Number(saved.page)||1)===page))requestAnimationFrame(()=>window.scrollTo(0,saved.scroll));
    lists.push({list,search,panel,sortPanel,desktop,togglePanel,canFilter,syncSheets});

  });
  const lightbox=root.querySelector('#bc-lightbox'),full=root.querySelector('[data-bc-full-picture]'),caption=root.querySelector('[data-bc-caption]'),pictureButtons=[...root.querySelectorAll('[data-bw-lightbox]')];let pictures=pictureButtons,pictureIndex=0,zoom=1;
  function showPicture(index){if(!pictures.length)return;pictureIndex=(index+pictures.length)%pictures.length;zoom=1;full.src=pictures[pictureIndex].dataset.bwLightbox;full.alt=pictures[pictureIndex].dataset.caption||'';caption.textContent=full.alt;full.style.width='100%';}
  function openPicture(b){const group=b.closest('[data-bc-list],.bc-photos,.bc-detail-hero');pictures=group?[...group.querySelectorAll('[data-bw-lightbox]')]:[b];showPicture(pictures.indexOf(b));lightbox.showModal();}
  pictureButtons.forEach(b=>{if(!b.closest('[data-bc-main]'))b.addEventListener('click',()=>openPicture(b));});
  function changeZoom(delta){zoom=Math.max(1,Math.min(4,zoom+delta*.25));full.style.width=(zoom*100)+'%';}
  root.querySelectorAll('[data-bc-zoom]').forEach(b=>b.addEventListener('click',()=>changeZoom(Number(b.dataset.bcZoom))));
  root.querySelector('[data-bc-prev]')?.addEventListener('click',()=>showPicture(pictureIndex-1));root.querySelector('[data-bc-next]')?.addEventListener('click',()=>showPicture(pictureIndex+1));
  let pinch;lightbox?.addEventListener('touchstart',e=>{if(e.touches.length===2)pinch=Math.hypot(e.touches[0].clientX-e.touches[1].clientX,e.touches[0].clientY-e.touches[1].clientY);},{passive:true});
  lightbox?.addEventListener('touchmove',e=>{if(e.touches.length===2&&pinch){const distance=Math.hypot(e.touches[0].clientX-e.touches[1].clientX,e.touches[0].clientY-e.touches[1].clientY);changeZoom(distance>pinch?1:-1);pinch=distance;}},{passive:true});
  root.querySelectorAll('dialog').forEach(d=>d.addEventListener('click',e=>{const r=d.getBoundingClientRect();if(e.target===d&&(e.clientX<r.left||e.clientX>r.right||e.clientY<r.top||e.clientY>r.bottom))d.close();}));
  document.addEventListener('keydown',e=>{
    if(lightbox?.open){if(e.key==='ArrowLeft')showPicture(pictureIndex-1);if(e.key==='ArrowRight')showPicture(pictureIndex+1);if(e.key==='+')changeZoom(1);if(e.key==='-')changeZoom(-1);return;}
    if(e.key==='Escape'){lists.forEach(l=>{if(l.sortPanel&&!l.sortPanel.hidden){l.sortPanel.hidden=true;l.list.querySelectorAll('[data-bc-sort-open]').forEach(b=>b.setAttribute('aria-expanded','false'));l.list.querySelector('[data-bc-sort-open]')?.focus();}
      if(l.panel&&!l.panel.hidden&&!l.desktop()){l.panel.hidden=true;l.list.querySelectorAll('[data-bc-filters]').forEach(b=>b.setAttribute('aria-expanded','false'));l.list.querySelector('[data-bc-filters]')?.focus();}l.syncSheets();});return;}
    const activePanel=lists.map(l=>({...l,panel:l.sortPanel&&!l.sortPanel.hidden?l.sortPanel:l.panel})).find(l=>l.panel&&!l.panel.hidden);
    if(e.key==='Tab'&&activePanel&&typeof matchMedia==='function'&&matchMedia('(max-width: 1023px)').matches){
      const controls=[...activePanel.panel.querySelectorAll('button,input,select,textarea,a[href]')].filter(n=>!n.disabled&&!n.hidden&&(!n.getClientRects||n.getClientRects().length)),first=controls[0],last=controls.at(-1);
      if(e.shiftKey&&document.activeElement===first){e.preventDefault();last?.focus();}else if(!e.shiftKey&&document.activeElement===last){e.preventDefault();first?.focus();}
    }
    if(/INPUT|TEXTAREA|SELECT/.test(e.target.tagName)||document.querySelector('dialog[open]'))return;
    if(e.key==='/'){e.preventDefault();lists[0]?.search?.focus();}
    if(e.key.toLowerCase()==='f'&&lists[0]?.panel&&lists[0].canFilter()){e.preventDefault();if(lists[0].panel.hidden||lists[0].desktop())lists[0].togglePanel();}

  });
})();
// Fetch part prices (part-out value): queue a market price refresh for the parts that have none yet.
document.addEventListener?.('click',async event=>{
  const button=event.target.closest('[data-bc-fetch-prices]');
  if(!button)return;
  const root=document.getElementById('bw-collection'),status=button.closest('[data-bc-fetch-scope]')?.querySelector('[data-bc-fetch-status]');
  const items=JSON.parse(button.dataset.bcFetchPrices);
  button.disabled=true;
  try{
    const response=await fetch(button.dataset.refreshUrl,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({items,csrf_token:root.dataset.csrf})});
    const result=await response.json().catch(()=>({}));
    if(!response.ok)throw new Error(result.message||'Could not queue the price refresh');
    if(status)status.textContent=button.dataset.bcFetchNoun==='price'?'Fetching the price · reload in a few minutes':`Fetching prices for ${items.length} ${items.length===1?'part':'parts'} · reload in a few minutes`;
  }catch(error){button.disabled=false;if(status)status.textContent=error.message;}
});
