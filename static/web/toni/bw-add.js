/* Add proposals stay in this page; only the explicit confirm sends collection writes. */
(() => {
 'use strict';
 const words = n => `${n} ${n === 1 ? 'item' : 'items'}`;
 const ink = rgb => {
  if (!/^[0-9a-f]{6}$/i.test(rgb || '')) return 'var(--tw-text)';
  const c = [0, 2, 4].map(i => parseInt(rgb.slice(i, i + 2), 16) / 255).map(v => v <= .04045 ? v / 12.92 : ((v + .055) / 1.055) ** 2.4);
  return .2126 * c[0] + .7152 * c[1] + .0722 * c[2] > .45 ? '#1A1816' : '#FAFAF8';
 };
 const filterRows = (rows, query, type, sort) => rows.filter(r => `${r.label || r.number} ${r.name}`.toLowerCase().includes(query.toLowerCase()) &&
  (!type || (type === 'duplicates' ? r.owned || r.wished || r.batchDuplicate : r.kind === type))).sort((a, b) => String(sort === 'name' ? a.name : a.number || a.label).localeCompare(String(sort === 'name' ? b.name : b.number || b.label)));
 window.BrickAdd = {words, ink, filterRows};
 const root = document.querySelector('#bw-add');
 if (!root) return;
 const $ = name => root.querySelector(`[data-${name}]`);
 const el = (tag, text, className) => { const e = document.createElement(tag); if (text !== undefined) e.textContent = text; if (className) e.className = className; return e; };
 const colours = JSON.parse(root.dataset.colours);
 const value = name => root.querySelector(`input[name="${name}"]:checked`).value;
 const message = text => { $('message').textContent = text; };
 let queued = [], proposal = null, rows = [], token = '', candidate = null, batch = null, busy = false, searchTimer, searchVersion = 0, jobTimer, monitors = [];
 const api = async (path, data) => {
  const options = data ? {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({...data, csrf_token:root.dataset.csrf})} : {};
  const response = await fetch(root.dataset.url + path, options);
  const result = await response.json();
  if (!response.ok) throw Error(result.error || 'Could not save · try again');
  return result;
 };
 const guarded = async (button, action) => {
  if (busy) return;
  busy = true; button.disabled = true; button.setAttribute('aria-busy', 'true'); message('');
  try { await action(); } catch (error) { message(error.message || 'Could not continue · try again'); }
  finally {busy = false; button.disabled = false; button.removeAttribute('aria-busy');}
 };
 const countQueue = () => { $('queued').textContent = `${words(queued.length)} in the list`; $('review').textContent = `Review ${words(value('mode') === 'search' ? queued.length : value('mode') === 'paste' ? $('paste').value.split('\n').filter(l => l.trim()).length : 0)}`; };
 const picture = row => {
  if (!row.image) return el('span', 'No image', 'bw-add-picture bw-add-no-image');
  const img = el('img', undefined, 'bw-add-picture'); const full = `/manage/images/${row.image}`; img.src = full + '?w=320'; img.srcset = `${full}?w=320 320w, ${full}?w=640 640w`; img.sizes = '160px'; img.dataset.full = full; img.alt = row.name; img.loading = 'lazy';
  img.addEventListener('error', () => img.replaceWith(el('span','No image','bw-add-picture bw-add-no-image')), {once:true});
  return img;
 };
 const identity = row => {
  const wrap = el('div', undefined, 'bw-add-item'); wrap.append(picture(row));
  const text = el('div', undefined, 'identity');
  const colour = colours.find(c => String(c.color_id) === String(row.color_id));
  if (colour) {const chip = el('span', colour.name || 'Unknown colour', 'bw-add-colour'); chip.style.background = /^[0-9a-f]{6}$/i.test(colour.rgb || '') ? '#' + colour.rgb : 'var(--tw-surface-2)'; chip.style.color = ink(colour.rgb); text.append(chip);}
  text.append(el('span',row.label || row.number,'mono'), el('strong',window.BrickFormatting.nowrapTail(row.name)));
  if (row.to_check) {const a = el('a','To check · Unresolved figures'); a.href = '/manage/unresolved'; text.append(a);}
  wrap.append(text); return wrap;
 };
 const chip = (target, label, clear) => {const b = el('button',label + ' ×'); b.type='button'; b.addEventListener('click',clear); target.append(b);};
 const runSearch = async () => {
  const version = ++searchVersion;
  const query = $('search').value;
  if (!query.trim()) {
   $('results').replaceChildren(); $('chips').replaceChildren();
   $('result-count').textContent = 'Search the catalogue by number or name'; $('result-count').hidden = false;
   return;
  }
  try {
   const result = await api(`/search?${new URLSearchParams({type:value('type'),q:query,sort:$('sort').value})}`);
   if (version !== searchVersion) return;
   $('results').replaceChildren(); const truncated = result.count > result.items.length;
   $('result-count').textContent = truncated ? `First ${result.items.length} of ${result.count} results` : `${result.count} results`;
   $('result-count').hidden = !(truncated || (query && result.count === 0));
   $('chips').replaceChildren();
   if (query) chip($('chips'),query,() => {$('search').value=''; runSearch();});
   chip($('chips'),value('type'),() => {root.querySelector('input[name=type][value=set]').checked=true;runSearch();});
   result.items.forEach(row => { const wrap = identity(row); const button = el('button','Add to list'); button.type='button'; button.addEventListener('click',() => {queued.push({item_id:row.item_id,color_id:row.color_id ?? null,quantity:1}); countQueue(); button.textContent='Added';}); wrap.append(button); $('results').append(wrap); });
  } catch (error) {if(version === searchVersion) message(error.message);}
 };
 const choose = (options, current, label, update) => {
  const select = el('select'); select.setAttribute('aria-label',label);
  options.forEach(([key, name]) => {const option=el('option',name);option.value=key;select.append(option);});select.value=current == null ? '' : String(current);
  select.addEventListener('change',() => update(select.value));return select;
 };
 const confirmCount = () => {const n=rows.filter(r => r.decision !== 'skip' && !(r.offers && !r.decision)).length;$('confirm').textContent=`Add ${words(n)}`;$('confirm').disabled=n===0;};
 let colourRow=null, colourOpener=null;
 const renderColours=()=>{
  const query=$('colour-search').value.toLowerCase(), filter=$('colour-filter').value;
  const selected=colours.filter(c=>`${c.name || 'Unknown colour'} ${c.color_id}`.toLowerCase().includes(query) && (!filter || /^[0-9a-f]{6}$/i.test(c.rgb || ''))).sort((a,b)=>$('colour-sort').value==='id'?a.color_id-b.color_id:String(a.name).localeCompare(String(b.name)));
  $('colour-count').textContent=`${selected.length} results`;$('colour-list').replaceChildren();$('colour-chips').replaceChildren();
  if(query)chip($('colour-chips'),query,()=>{$('colour-search').value='';renderColours();});
  if(filter)chip($('colour-chips'),'With colour data',()=>{$('colour-filter').value='';renderColours();});
  selected.forEach(c=>{const chosen=String(colourRow?.color_id)===String(c.color_id);const button=el('button',`${c.name || 'Unknown colour · '+c.color_id}${chosen?' · ✓':''}`,'bw-add-colour-choice');button.type='button';button.setAttribute('aria-pressed',String(chosen));
   button.style.background=/^[0-9a-f]{6}$/i.test(c.rgb || '')?'#'+c.rgb:'var(--tw-surface-2)';button.style.color=ink(c.rgb);
   button.addEventListener('click',()=>{colourRow.color_id=c.color_id;$('colour-dialog').close();renderReview();$('review-panel').querySelector('h2').focus();});$('colour-list').append(button);
  });
 };
 ['colour-search','colour-filter','colour-sort'].forEach(name=>$(name).addEventListener(name==='colour-search'?'input':'change',renderColours));
 $('colour-close').addEventListener('click',()=>$('colour-dialog').close());
 $('colour-dialog').addEventListener('close',()=>colourOpener?.focus());
 const renderReview = () => {
  $('review-rows').replaceChildren();
  const seen=new Set(); rows.forEach(r=>{const key=JSON.stringify([r.item_id ?? r.number,r.color_id ?? null,r.where==='wishlist' ? r.list_id || 'default' : null]);r.batchDuplicate=seen.has(key);seen.add(key);if(r.wished_by_list && r.where==='wishlist')r.wished=(r.wished_by_list[r.list_id || 'default'] || []).includes(r.color_id ?? null);else if(r.wished_colors)r.wished=r.wished_colors.includes(r.color_id ?? null);});
  const query=$('review-search').value, type=$('review-filter').value;
  const visible=filterRows(rows,query,type,$('review-sort').value);
  $('review-count').textContent=`${visible.length} results · ${words(rows.length)} to review`;
  $('review-chips').replaceChildren();
  if(query) chip($('review-chips'),query,() => {$('review-search').value='';renderReview();});
  if(type) chip($('review-chips'),type,() => {$('review-filter').value='';renderReview();});
  visible.forEach(row => {
   const tr=el('tr');const cell=content => {const td=el('td');if(typeof content==='string') td.textContent=content;else td.append(content);tr.append(td);return td;};
   const id=identity(row);
   if(row.kind==='part') {
    const button=el('button',row.color_id == null ? 'Choose a colour' : 'Change colour');button.type='button';button.className='bw-add-colour';
    button.addEventListener('click',()=>{colourRow=row;colourOpener=button;renderColours();$('colour-dialog').showModal();$('colour-search').focus();});id.append(button);
   }
   cell(id);cell(row.type_name);
   const qty=el('input');qty.type='number';qty.min='1';qty.max='9999';qty.value=row.quantity;qty.setAttribute('aria-label',`Quantity for ${row.label || row.number}`);qty.addEventListener('input',()=>{row.quantity=qty.value;});cell(qty);
   const destination=cell(choose([['owned','Owned'],['loose','Loose'],['wishlist','Wishlist']],row.where,`Where for ${row.label || row.number}`,v=>{row.where=v;renderReview();}));
   if(row.where==='wishlist'){
    const lists=JSON.parse(root.dataset.wishlists || '[]');
    const opts=lists.map(l=>[l.id,l.name]);if(row.list_id?.startsWith('new-bl:'))opts.push([row.list_id,row.list_name+' · create on confirm']);
    destination.append(choose(opts,row.list_id || 'default',`Wishlist for ${row.label || row.number}`,v=>{row.list_id=v;row.decision='';renderReview();}));
    (row.import_notes || []).forEach(note=>id.append(el('p',note,'secondary mono')));
    if(row.note)id.append(el('p',row.note,'secondary'));
   }
   cell(choose(row.where==='wishlist'?[['used','Used'],['new','New'],['any','Any']]:row.where==='loose'?[['used','Used'],['new','New'],['damaged','Damaged']]:[['used','Used'],['new','New']],row.condition,`Condition for ${row.label || row.number}`,v=>{row.condition=v;}));
   if(row.kind==='set' && row.where==='owned')cell(choose([['','Unknown · from checks'],['sealed','Sealed'],['complete','Complete'],['incomplete','Incomplete']],row.completeness,`Completeness for ${row.label || row.number}`,v=>{row.completeness=v;}));else cell('·');
   const offers=row.offers;
   const choice=cell(choose(offers ? [['','Choose'],['unidentified','Add as unidentified'],...(offers.fetch ? [['fetch','Fetch from Rebrickable' + (offers.fetch.available ? '' : ' (needs a key)')]] : []),['skip','Skip']]
    : [['','Choose'],['another',row.where==='wishlist' ? 'Add to the wished quantity' : 'Add another copy'],['skip','Skip']],row.decision,`Choice for ${row.label || row.number}`,v=>{row.decision=v;confirmCount();}));
   if(offers){choice.prepend(el('p',offers.help,'notice'));if(offers.fetch && !offers.fetch.available)choice.append(el('p',offers.fetch.why,'secondary'));}
   if(row.owned || row.wished || row.batchDuplicate)choice.prepend(el('p',`${row.owned ? `Already owned · ${row.owned}` : ''}${row.owned && row.wished ? ' · ' : ''}${row.wished ? 'Already on Wishlist' : ''}${row.batchDuplicate ? ' · Repeated in this list' : ''}`,'notice'));
   $('review-rows').append(tr);
  }); confirmCount();
 };
 const showReview = selected => {
  rows=selected.map(r=>({...r})); const seen=new Set();rows.forEach(r=>{const key=JSON.stringify([r.item_id ?? r.number,r.color_id ?? null,r.where==='wishlist' ? r.list_id || 'default' : null]);r.batchDuplicate=seen.has(key);seen.add(key);});
  $('intake').hidden=true;$('candidates').hidden=true;$('review-panel').hidden=false; renderReview();$('review-panel').querySelector('h2').tabIndex=-1;$('review-panel').querySelector('h2').focus();
 };
 const renderCandidates=()=>{
  const query=$('candidate-search').value,type=$('candidate-filter').value,sort=$('candidate-sort').value;
  const selected=filterRows(proposal.items,query,type,sort==='name'?'name':'number');if(sort==='score')selected.sort((a,b)=>b.score-a.score);
  $('candidate-count').textContent=`${selected.length} results`;$('candidate-list').replaceChildren();$('candidate-chips').replaceChildren();
  if(query)chip($('candidate-chips'),query,()=>{$('candidate-search').value='';renderCandidates();});
  if(type)chip($('candidate-chips'),type,()=>{$('candidate-filter').value='';renderCandidates();});
  selected.forEach(row=>{const index=proposal.items.indexOf(row),wrap=identity(row);wrap.append(el('span',`${row.score} match`,'mono'));const b=el('button','Choose');b.type='button';b.addEventListener('click',()=>{candidate=index;showReview([row]);});wrap.append(b);$('candidate-list').append(wrap);});
 };
 const renderUnresolved=()=>{
  const query=$('unresolved-search').value.toLowerCase(),filter=$('unresolved-filter').value,sort=$('unresolved-sort').value;
  const selected=proposal.unresolved.filter(r=>`${r.number} ${r.reason}`.toLowerCase().includes(query)&&(!filter||r.reason.toLowerCase().includes(filter))).sort((a,b)=>String(a[sort]).localeCompare(String(b[sort])));
  $('unresolved-list').replaceChildren();$('unresolved-count').textContent=`${selected.length} results`;$('unresolved-chips').replaceChildren();
  if(query)chip($('unresolved-chips'),query,()=>{$('unresolved-search').value='';renderUnresolved();});
  if(filter)chip($('unresolved-chips'),filter,()=>{$('unresolved-filter').value='';renderUnresolved();});
  selected.forEach(r=>$('unresolved-list').append(el('li',`${r.number} · ${r.reason}`)));
 };
 ['candidate-search','candidate-filter','candidate-sort'].forEach(name=>$(name).addEventListener(name==='candidate-search'?'input':'change',renderCandidates));
 ['unresolved-search','unresolved-filter','unresolved-sort'].forEach(name=>$(name).addEventListener(name==='unresolved-search'?'input':'change',renderUnresolved));
 $('review').addEventListener('click',()=>guarded($('review'),async()=>{
  const mode=value('mode');const data={type:value('type'),where:value('where'),mode,list_id:root.querySelector('[data-wishlist-target]')?.value || 'default',map_wanted_ids:root.querySelector('[data-map-wanted]')?.checked!==false};
  if(mode==='search')data.items=queued;
  if(mode==='paste')data.text=$('paste').value;
  let result;
  if(mode==='file' || mode==='photo') {
   const file=$(mode).files[0];if(!file)throw Error(mode==='photo'?'Choose a photo':'Choose a file');
   const form=new FormData();Object.entries({...data,csrf_token:root.dataset.csrf}).forEach(([k,v])=>form.append(k,v));form.append('file',file);
   const response=await fetch(root.dataset.url+'/review',{method:'POST',body:form});result=await response.json();if(!response.ok)throw Error(result.error || 'Could not read input');
  }else result=await api('/review',data);
  proposal=result;token=result.token;candidate=null;
  $('unresolved').hidden=!result.unresolved.length;renderUnresolved();
  if(result.candidates && result.items.length) {
   $('candidate-list').replaceChildren();$('candidates').hidden=false;
   renderCandidates();
  }else if(result.items.length)showReview(result.items);else message('No resolved items · check the unresolved lines');
 }));
 const listeners=new Map();
 // HTTP snapshots repair missed broadcasts, including imports finished before connection.
 const channel={connected:navigator.onLine,on(event,fn){if(!listeners.has(event))listeners.set(event,new Set());listeners.get(event).add(fn);},off(event,fn){listeners.get(event)?.delete(fn);}};
 const dispatch=(event,data)=>listeners.get(event)?.forEach(fn=>fn(data));
 window.addEventListener('online',()=>{channel.connected=true;dispatch('connect');});window.addEventListener('offline',()=>{channel.connected=false;dispatch('disconnect');});
 const progress=new Map();
 const updateOverall=()=>{
  const vals=[...progress.values()];const done=vals.reduce((n,r)=>n+(Number(r.completed_steps)||0),0),total=vals.reduce((n,r)=>n+(Number(r.total_steps)||0),0);
  const bar=$('overall').querySelector('[data-import-bar]');$('overall').querySelector('[data-import-fill]').style.width=`${total?100*done/total:0}%`;bar.setAttribute('aria-valuenow',String(total?100*done/total:0));
  $('overall').querySelector('[data-import-message]').textContent=`${vals.filter(r=>r.job_state==='done'||r.state==='done'&&r.step==null).length} of ${monitors.length} imports complete`;
 };
 channel.on('import_progress',data=>{if(progress.has(data.job_id)){progress.set(data.job_id,data);updateOverall();}});
 const poll=async()=>{await Promise.all(monitors.map(async m=>{try{const result=await api(`/jobs/${m.jobId}`);result.events.forEach(e=>dispatch('import_progress',e));}catch{message('Progress could not be loaded · Jobs keeps the imports');}}));};
 $('confirm').addEventListener('click',()=>guarded($('confirm'),async()=>{
  const result=await api('/confirm',{token,items:rows,candidate,keep_photo:$('keep').checked});batch=result.batch;
  $('review-panel').hidden=true;$('intake').hidden=true;$('jobs').hidden=false;$('job-list').replaceChildren();$('undo').disabled=false;$('undo').hidden=false;
  message(`Added ${words(result.receipts.length)}`);monitors.forEach(m=>m.destroy());monitors=[];progress.clear();
  result.receipts.forEach(r=>{
   const section=el('section',undefined,'panel');section.append(el('h3',`${r.label || r.name}${r.label && r.name && r.label !== r.name ? ' · ' + r.name : ''}`));
   if(r.fetch_job)section.append(el('p','Fetching this set from Rebrickable · the copy is added when the job is done','secondary'));
   const cloned=$('progress-template').content.cloneNode(true);section.append(cloned);$('job-list').append(section);
   const jobId=r.job_id || r.fetch_job;progress.set(jobId,{completed_steps:0,total_steps:r.fetch_job ? 1 : 6});
   const monitor=new window.BrickImportProgress(section.querySelector('.bw-import-progress'),channel,{jobId,retry:(job,step)=>{
    api(`/jobs/${job}/retry`,{step}).then(()=>{monitor.pending=false;monitor.syncButton();poll();}).catch(error=>{monitor.pending=false;monitor.syncButton();message(error.message);});return true;
   }});monitors.push(monitor);
  });$('overall').hidden=monitors.length<2;updateOverall();await poll();clearInterval(jobTimer);jobTimer=setInterval(poll,3000);
 }));
 $('undo').addEventListener('click',()=>guarded($('undo'),async()=>{const result=await api('/undo',{batch});message(result.message);$('undo').hidden=true;}));
 $('back').addEventListener('click',()=>{$('review-panel').hidden=true;$('intake').hidden=false;});
 $('again').addEventListener('click',()=>{location.href=root.dataset.url;});
 root.querySelectorAll('input[name=mode]').forEach(input=>input.addEventListener('change',()=>{root.querySelectorAll('[data-mode]').forEach(e=>e.hidden=e.dataset.mode!==value('mode'));countQueue();}));
 root.querySelectorAll('input[name=type]').forEach(input=>input.addEventListener('change',()=>{runSearch();}));
 $('search').addEventListener('input',()=>{clearTimeout(searchTimer);searchTimer=setTimeout(runSearch,120);});$('sort').addEventListener('change',runSearch);
 $('paste').addEventListener('input',countQueue);
 ['review-search','review-filter','review-sort'].forEach(name=>$(name).addEventListener(name==='review-search'?'input':'change',renderReview));
 $('review-clear').addEventListener('click',()=>{$('review-search').value='';$('review-filter').value='';renderReview();});
 root.querySelectorAll('.bw-add-drop').forEach(zone=>{
  zone.addEventListener('dragover',event=>{event.preventDefault();zone.classList.add('dragging');});zone.addEventListener('dragleave',()=>zone.classList.remove('dragging'));
  zone.addEventListener('drop',event=>{event.preventDefault();zone.classList.remove('dragging');zone.querySelector('input').files=event.dataTransfer.files;});
 });
 document.addEventListener('keydown',event=>{if(event.key==='/'&&!['INPUT','TEXTAREA','SELECT'].includes(document.activeElement.tagName)){event.preventDefault();$('search').focus();}});
 window.addEventListener('pagehide',()=>{clearInterval(jobTimer);monitors.forEach(m=>m.destroy());});
 root.querySelectorAll('[data-mode]').forEach(e=>e.hidden=e.dataset.mode!==value('mode'));
 countQueue();
 if(value('mode')==='search')runSearch();
})();
