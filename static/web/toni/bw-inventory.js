(() => {
  'use strict';
  const nowrapTail = window.BrickFormatting.nowrapTail;
  const partName = name => nowrapTail(typeof name === 'string' ? name.replace(/ x /g, ' × ') : name);   // the frame writes a part's size with ×
  const root = document.querySelector('#bw-inventory');
  if (!root) return;
  const node = key => root.querySelector(`[data-${key}]`);
  const all = selector => Array.from(root.querySelectorAll(selector));
  const colours = JSON.parse(root.dataset.colours), queue = [];
  const STATUS = { verified: ['Ready', ''], review: ['To review', 'dash'], error: ['Unidentified', 'inv-tag-danger'], pending: ['Recognizing', 'dash'] };
  const COMMON_COLOURS = ['Light Bluish Gray', 'Dark Bluish Gray', 'White', 'Black', 'Tan', 'Red'];
  let active = null, stream = null, startCall = 0, pendingPiece = null, saving = false, undoing = false, receipt = null, batchPieces = [];
  let endpoint = 'parts', queueFilter = '', queueSort = 'piece', destination = 'loose', condition = 'U', cameraId = '', lotId = '', storageId = '';
  const el = (tag, text, cls) => { const n = document.createElement(tag); if (text !== undefined) n.textContent = text; if (cls) n.className = cls; return n; };
  let messages = 0;  // counts message() calls: a late camera check must not overwrite what the person did meanwhile (#313)
  const message = (text, kind = 'info') => { messages++; node('message').textContent = text; node('notice').dataset.kind = kind; node('notice').hidden = !text && node('undo').hidden; };
  function button(text, action, cls) { const n = el('button', text, cls); n.type = 'button'; n.addEventListener('click', action); return n; }
  const pressed = (nodes, key, value) => nodes.forEach(n => { const on = n.dataset[key] === value; n.setAttribute('aria-pressed', String(on)); n.classList.toggle('on', on); });
  // scan-tile stays on the tile beside the kit's: the shell's container rule and the demo shim name it
  function tile(image, name, number, cls, retry = true) { const n = el('div', undefined, 'tile scan-tile' + (cls ? ' ' + cls : '')); if (image) { const i = el('img'); i.src = image; i.dataset.full = image.replace(/\?w=\d+$/, ''); i.alt = name; i.addEventListener('error',()=>n.replaceChildren(el('span','Image did not load'),...(retry?[button('Retry',()=>{i.src=image;n.replaceChildren(i);})]:[]))); n.append(i); } else {n.className+=' inv-no-image';n.append(el('span', 'Part picture'));} return n; }
  const image = c => c.image ? `/manage/images/${c.image}?w=640` : null;
  function swatch(n, c) {
    if (!/^[0-9a-f]{6}$/i.test(c.rgb || '')) return;
    n.style.backgroundColor = '#' + c.rgb;
    const channels = c.rgb.match(/../g).map(v => { const x = parseInt(v,16)/255; return x <= .04045 ? x/12.92 : ((x+.055)/1.055)**2.4; });
    n.style.color = channels[0]*.2126 + channels[1]*.7152 + channels[2]*.0722 > .45 ? '#1A1816' : '#FAFAF8';
  }
  function swatchButton(c, chosen, action) {
    const b = button(undefined, action, 'inv-swatch');
    const dot = el('i');
    dot.setAttribute('aria-hidden', 'true');
    if (/^[0-9a-f]{6}$/i.test(c.rgb || '')) dot.style.backgroundColor = '#' + c.rgb;
    b.append(dot, document.createTextNode(c.name || `Unknown colour · ${c.color_id}`));
    b.setAttribute('aria-pressed', String(chosen));
    return b;
  }
  function quickColours(owned, chosenId) {
    const list = [], seen = new Set();
    const add = c => { if (c && !seen.has(c.color_id)) { seen.add(c.color_id); list.push(c); } };
    COMMON_COLOURS.forEach(name => add(colours.find(r => r.name === name)));
    (owned?.colours || []).forEach(o => add(colours.find(r => r.color_id === o.color_id)));
    if (!list.length) colours.slice(0, 6).forEach(add);
    const top = list.slice(0, 8);
    const chosen = chosenId != null ? colours.find(r => r.color_id === chosenId) : null;
    if (chosen && !top.some(c => c.color_id === chosen.color_id)) return top.length >= 8 ? [...top.slice(0, 7), chosen] : [...top, chosen];
    return top;
  }
  function segment(options, current, set, label) {
    const group = el('div', undefined, 'seg'); group.setAttribute('role', 'group'); group.setAttribute('aria-label', label);
    const buttons = options.map(([value, text]) => { const b = button(text, () => { set(value); buttons.forEach(x => { const on = x.value === value; x.setAttribute('aria-pressed', String(on)); x.classList.toggle('on', on); }); }); b.value = value; const on = value === current; b.setAttribute('aria-pressed', String(on)); b.classList.toggle('on', on); return b; });
    group.append(...buttons); return group;
  }
  function statusTag(piece) { const [text, cls] = STATUS[piece.pending ? 'pending' : piece.status]; return el('span', text, 'tag' + (cls ? ' ' + cls : '')); }
  function chip(c) { const n = el('span', c.name || `Colour ${c.color_id}`, 'chip inv-chip'); swatch(n, c); return n; }
  function listControls(rows, render, name, defaultSort='name') {
    const wrapper=el('div',undefined,'inv-stack'), toolbar=el('div',undefined,'inv-toolbar'), search=el('input'), chips=el('div',undefined,'inv-chips'), count=el('p',undefined,'mono inv-note'), content=el('div',undefined,name==='colours'?'scan-colours':'inv-options');
    let filterValue='', sortValue=defaultSort;
    search.type='search';search.className='input inv-search';search.placeholder=`Search ${name}`;search.setAttribute('aria-label',`Search ${name}`);
    const update=()=>{const selected=rows.filter(r=>`${r.name||'Unknown colour'} ${r.item_no??r.color_id}`.toLowerCase().includes(search.value.toLowerCase())&&(!filterValue||r.image || (name==='colours' && r.rgb)));selected.sort((a,b)=>sortValue==='score'?b.score-a.score:sortValue==='number'?String(a.item_no??a.color_id).localeCompare(String(b.item_no??b.color_id),undefined,{numeric:true}):(a.name||'').localeCompare(b.name||''));content.replaceChildren(...selected.map(render));count.textContent=`${selected.length} ${name}`;chips.replaceChildren();if(search.value)chips.append(button(`${search.value} ×`,()=>{search.value='';update();}));};
    const filters=segment([['','All'],['image','With image']],'',v=>{filterValue=v;update();},`Filter ${name}`);
    const sorts=segment([['name','Name'],['number','Number'],...(defaultSort==='score'?[['score','Score']]:[])],defaultSort,v=>{sortValue=v;update();},`Sort ${name}`);
    search.addEventListener('input',update);
    toolbar.append(search,filters,sorts);toolbar.hidden=rows.length<=6;
    wrapper.append(toolbar,chips,count,content);update();return wrapper;
  }
  function blocked() {
    if (pendingPiece) { message('Still identifying the last piece · wait a moment, then take the next photo', 'error'); return true; }
    if (saving) { message('Saving the batch · wait a moment', 'error'); return true; }
    return false;
  }
  const reviewVisible = () => root.dataset.view === 'review' || Boolean(window.matchMedia?.('(min-width:1024px)')?.matches);
  function emptyState(text) { const n = el('div', undefined, 'inv-empty'); n.append(el('p', text)); return n; }
  function setView(view) { root.dataset.view = view; pressed(all('[data-tab]'), 'tab', view); }
  function quantityStepper(piece, onChange) {
    const wrap = el('div', undefined, 'step inv-qty'), qty = el('input');
    qty.type = 'number'; qty.min = '1'; qty.max = '9999'; qty.value = piece.quantity; qty.setAttribute('aria-label', 'Quantity');
    const set = v => { piece.quantity = Math.min(9999, Math.max(1, Number(v) || 1)); qty.value = piece.quantity; piece.status = 'review'; renderQueue(); onChange(); };
    qty.addEventListener('change', () => set(qty.value));
    const minus = button('−', () => set(piece.quantity - 1)), plus = button('+', () => set(piece.quantity + 1));
    minus.setAttribute('aria-label', 'Decrease quantity'); plus.setAttribute('aria-label', 'Increase quantity');
    wrap.append(minus, qty, plus); return wrap;
  }
  function showReview(piece) {
    active = piece; const out = node('review'); out.replaceChildren();
    if (!piece) { out.append(emptyState('Take a picture or add a saved photo to begin.')); setView('capture'); return; }
    setView('review');
    const position = `Piece ${queue.indexOf(piece) + 1} of ${queue.length}`;
    const c = piece.candidates[piece.index];
    const headRow = el('div', undefined, 'inv-review-head');
    if (piece.pending) { headRow.append(el('h2', position), el('span', 'Recognizing', 'inv-review-sub')); out.append(headRow, tile(null, 'Piece', null, 'inv-big'), button('Delete picture', () => remove(piece), 'inv-link inv-link-muted')); return; }
    if (!c) {
      const banner = el('p', piece.error || 'Nothing identified · try another photo', 'inv-banner');
      const retake = button('Retake', () => { remove(piece); node('file').click(); }, 'btn inv-primary');
      headRow.append(el('h2', position), el('span', 'Not recognised', 'inv-review-sub'));
      out.append(headRow, tile(piece.photo, 'Your photo', null, 'inv-big'), banner, retake, button('Delete picture', () => remove(piece), 'inv-link inv-link-muted'));
      return;
    }
    const colour = colours.find(r=>r.color_id===piece.colour);
    const best = el('div', undefined, 'inv-best'); best.append(el('span', 'Reference · best match', 'lbl'), tile(image(c),c.name,c.item_no));
    const photo = el('div', undefined, 'inv-photo'); photo.append(el('span', 'Your photo', 'lbl'), tile(piece.photo, 'Your photo'));
    const reference = el('div', undefined, 'scan-reference'); reference.append(best, photo);
    const meta = el('div', undefined, 'inv-part-meta'); meta.append(el('h3', partName(c.name)), el('div', `${c.item_no} · ${colour ? colour.name : 'Choose a colour'} · ${c.score.toFixed(2)} match`, 'mono inv-part-sub'));
    headRow.append(el('h2', position), el('span', 'Confirm the part, then pick the colour', 'inv-review-sub'));
    out.append(headRow, reference, meta);
    const owned=c.owned_summary;
    if(owned){const box=el('p',owned.text,'inv-owned');if(owned.needed_count){const a=el('a',`Fills a gap in ${owned.needed_count} ${owned.needed_count===1?'copy':'copies'} · Matchmaker`,'inv-owned-need');a.href='/workbench/matcher';box.append(' · ',a);}out.append(box);}
    const pickColour = id => { piece.colour = id; piece.status = 'review'; showReview(piece); renderQueue(); };
    const swatchRow = el('div', undefined, 'inv-swatch-row');
    swatchRow.append(...quickColours(owned, piece.colour).map(r => swatchButton(r, r.color_id === piece.colour, () => pickColour(r.color_id))));
    const choices=listControls(colours,r=>swatchButton(r,r.color_id===piece.colour,()=>pickColour(r.color_id)),'colours');
    choices.hidden = true;
    const more = button('More colours', () => { choices.hidden = !choices.hidden; more.setAttribute('aria-expanded', String(!choices.hidden)); }, 'inv-link inv-more-colours');
    more.setAttribute('aria-expanded', 'false'); more.dataset.moreColours = '';
    const colourBlock = el('div', undefined, 'inv-stack'); const colourHead = el('div', undefined, 'inv-split'); colourHead.append(el('h3', 'Colour · you choose', 'lbl'), more); colourBlock.append(colourHead, swatchRow, choices);
    const confirmText=()=>colour?`Confirm · ${colour.name} ×${piece.quantity}${piece.sticker?' · sticker':''}`:'Choose a colour';
    const confirm=button(confirmText(),()=>{piece.status='verified';renderQueue();const next=queue.find(p=>p.status==='review');showReview(next || piece);});confirm.disabled=!colour;confirm.className='btn inv-primary';confirm.dataset.confirm='';
    // #201: the print on a part is a clue to the set that only the person can read; the sticker itself is chosen on the lot page after saving
    const sticker = el('label', undefined, 'inv-switch-row'), toggle = el('span', undefined, 'sw' + (piece.sticker === true ? ' on' : '')), box = el('input');
    box.type = 'checkbox'; box.setAttribute('role', 'switch'); box.checked = piece.sticker === true; box.dataset.sticker = '';
    box.addEventListener('change', () => { piece.sticker = box.checked; toggle.classList.toggle('on', box.checked); confirm.textContent = confirmText(); renderResults(); });
    toggle.append(box);
    sticker.append(toggle, el('span', 'Has a sticker', 'inv-switch-title'));
    const qtyRow = el('div', undefined, 'inv-qty-row'); qtyRow.append(quantityStepper(piece, () => { confirm.textContent = confirmText(); }), sticker);
    const links = el('div', undefined, 'inv-split'); links.append(button('Delete picture',()=>remove(piece),'inv-link inv-link-muted'), el('span','Enter · confirm · 1 to 9 · choose a candidate','mono inv-note'));
    const alternatives=piece.candidates.map((candidate,i)=>({...candidate,index:i})).filter(c=>c.index!==piece.index);
    if (alternatives.length) {
      const block = el('div', undefined, 'inv-stack'); block.append(el('h3', 'Other possibilities', 'lbl'));
      block.append(listControls(alternatives,candidate=>{const b=button('',()=>{piece.index=candidate.index;piece.colour=null;piece.status='review';showReview(piece);renderQueue();});b.className='scan-alternative';const identity=el('span',undefined,'inv-grow');identity.append(el('span',partName(candidate.name),'inv-name'),el('span',`${candidate.index+1} · ${candidate.item_no}`,'mono inv-note'));b.append(tile(image(candidate),candidate.name,candidate.item_no,'',false),identity,el('span',candidate.score.toFixed(2),'mono inv-score'));return b;},'possibilities','score'));
      out.append(block);
    }
    out.append(colourBlock, qtyRow, confirm, links);
  }
  function drop(piece) {const at=queue.indexOf(piece);if(at<0)return false;queue.splice(at,1);URL.revokeObjectURL(piece.photo);release(piece);return true;}
  function release(piece) {if(pendingPiece!==piece)return;piece.abort?.abort();pendingPiece=null;node('capture').disabled=false;}
  function remove(piece) {if(!drop(piece))return;showReview(queue.find(p=>p.status==='review'));renderQueue();}
  function emptyQueue() {queue.slice().forEach(drop);showReview(null);renderQueue();}
  function identity(piece) {
    const c=piece.candidates[piece.index], colour=colours.find(r=>r.color_id===piece.colour), box=el('div',undefined,'identity');
    box.append(el('span',`Piece ${queue.indexOf(piece)+1}${c?.item_no ? ' · ' + c.item_no : ''}`,'mono inv-note'),el('span',c?.name ? partName(c.name) : (piece.pending ? 'Recognizing' : (piece.error || 'Unidentified')),'inv-name'));
    if (colour) box.append(chip(colour)); else if (piece.pending) box.append(el('span', 'being read', 'inv-being-read')); return box;
  }
  function queueRow(piece) {
    const c=piece.candidates[piece.index], r=button('',()=>showReview(piece),'scan-row'), wrap=el('div',undefined,'inv-queue-row');
    r.append(tile(c ? image(c) : null,c?.name||'Unidentified',c?.item_no,'',false),identity(piece),statusTag(piece));
    const del=button('',()=>remove(piece),'inv-delete');del.setAttribute('aria-label',`Delete piece ${queue.indexOf(piece)+1}`);wrap.append(r,del);return wrap;
  }
  function resultRow(piece, label) {
    const c=piece.candidates[piece.index], colour=colours.find(r=>r.color_id===piece.colour), r=el('div',undefined,'scan-row'), box=el('div',undefined,'identity'), meta=el('div',undefined,'inv-result-meta-row');
    box.append(el('span',c?.name ? partName(c.name) : 'Unidentified','inv-name'));
    if(colour)meta.append(chip(colour));
    meta.append(el('span',`${c?.item_no ? c.item_no + ' · ' : ''}×${piece.quantity}${piece.sticker?' · sticker':''}`,'mono inv-result-meta'));
    box.append(meta);r.append(tile(c ? image(c) : null,c?.name||'Unidentified',c?.item_no),box);if(label)r.append(el('span',label,'tag'));return r;
  }
  function renderResults() {
    const done = queue.filter(p => p.status === 'verified');
    node('results-total').textContent = done.length; node('results-count').textContent = done.length;
    node('results-list').replaceChildren(...(done.length ? done.map(p => resultRow(p, 'Confirmed')) : [emptyState('Nothing confirmed yet · confirm a piece to add it here')]));
  }
  function renderQueue() {
    node('total').textContent=queue.length;node('queue-count').textContent=queue.length;node('queue').replaceChildren();node('chips').replaceChildren();
    node('slot').textContent=`Piece ${queue.length+1}`;
    const q=node('search').value.toLowerCase();
    const pieces=queue.filter(p=>(!queueFilter||p.status===queueFilter)&&JSON.stringify(p.candidates).toLowerCase().includes(q));
    if(queueSort==='name')pieces.sort((a,b)=>(a.candidates[a.index]?.name||'').localeCompare(b.candidates[b.index]?.name||''));
    if(node('search').value)node('chips').append(button(`${node('search').value} ×`,()=>{node('search').value='';renderQueue();}));
    if(queueFilter)node('chips').append(button(`${STATUS[queueFilter][0]} ×`,()=>setQueueFilter('')));
    node('toolbar').hidden=queue.length<4;node('queue-actions').hidden=!queue.length;
    node('count').textContent=queue.length>3?`${pieces.length} pieces`:'';
    if(!queue.length){node('queue').append(emptyState('No pieces queued · take a picture or add a saved photo'));}
    else if(!pieces.length){node('queue').append(emptyState('No pieces match · clear the search or filter'));}
    else node('queue').append(...pieces.map(queueRow));
    renderResults();
  }
  function setQueueFilter(value) {queueFilter=value;pressed(all('[data-filter]'),'filter',value);renderQueue();}
  async function request(path, body, signal) { const reply=await fetch(root.dataset.url+'/'+path,{signal,method:'POST',body:body instanceof FormData?body:JSON.stringify({...body,csrf_token:root.dataset.csrf}),headers:body instanceof FormData?{}:{'Content-Type':'application/json'}});const data=await reply.json();if(!reply.ok){if(data.unresolved?.length){const link=el('a','To check · Tools & Admin → Unresolved figures');link.href='/manage/unresolved';node('unresolved').replaceChildren(link);}throw Error(data.error||'Could not save · try again');}return data; }
  async function detect(file) {
    if(blocked())return;
    if(queue.length>=6){message('Queue full · review or remove a piece','error');return;}
    const piece={photo:URL.createObjectURL(file),candidates:[],index:0,colour:null,quantity:1,status:'review',pending:true,abort:typeof AbortController==='function'?new AbortController():null};queue.push(piece);pendingPiece=piece;message('Identifying piece…');node('capture').disabled=true;renderQueue();showReview(piece);
    try {const form=new FormData();form.append('file',file);form.append('csrf_token',root.dataset.csrf);form.append('endpoint',endpoint);const reply=await request('detect',form,piece.abort?.signal);if(!queue.includes(piece))return;piece.candidates=reply.candidates;piece.token=reply.token;message(active===piece?'Choose a colour, then confirm':'');if(reply.unresolved.length){const link=el('a','To check · Tools & Admin → Unresolved figures');link.href='/manage/unresolved';node('message').append(link);} }
    catch(e){if(queue.includes(piece)){piece.status='error';piece.error=e.message;message(e.message,'error');}}
    finally {piece.pending=false;release(piece);if(queue.includes(piece)){if(active===piece){const view=root.dataset.view;showReview(piece);if(view!=='review')setView(view);}}else if(!pendingPiece&&node('message').textContent==='Identifying piece…')message('');renderQueue();}
  }
  function pickCamera(id, label) { cameraId = id; node('camera-label').textContent = label; }
  function listPicker(toggle, list, options, choose) {
    list.replaceChildren(...options);
    for (const o of options) o.addEventListener('click', () => { choose(o); list.hidden = true; toggle.setAttribute('aria-expanded', 'false'); });
  }
  function toggleList(toggle, list) { list.hidden = !list.hidden; toggle.setAttribute('aria-expanded', String(!list.hidden)); }
  async function cameras() {
    const seen=messages;
    const devices=await navigator.mediaDevices.enumerateDevices();let selected=cameraId;try{selected=selected||localStorage.getItem('bw-camera')||'';}catch(e){}
    const inputs=devices.filter(d=>d.kind==='videoinput');
    const options=inputs.map((d,i)=>{const o=button(d.label||`Camera ${i+1}`,()=>{});o.setAttribute('role','option');o.value=d.deviceId;return o;});
    listPicker(node('camera'),node('camera-list'),options,o=>{pickCamera(o.value,o.textContent);try{localStorage.setItem('bw-camera',o.value);}catch(e){}start();});
    const chosen=options.find(o=>o.value===selected)||options[0];
    if(chosen)pickCamera(chosen.value,chosen.textContent);else{pickCamera('','No camera');if(messages===seen)message('No camera · add a saved photo','error');}
  }
  function captureLabel() { node('capture').textContent = stream?.active ? 'Take picture' : 'Enable camera'; }
  async function start() {
    const call=++startCall;let mine=null;
    try {
      if(stream){stream.getTracks().forEach(t=>t.stop());stream=null;}
      const id=cameraId;
      mine=await navigator.mediaDevices.getUserMedia({video:id?{deviceId:{exact:id}}:{facingMode:'environment'},audio:false});
      if(call!==startCall){mine.getTracks().forEach(t=>t.stop());return;}
      stream=mine;node('video').srcObject=mine;
      const used=mine.getVideoTracks?.()[0]?.getSettings?.().deviceId;if(used)cameraId=used;
      await cameras();message('Place one piece inside the guide');
    } catch(e) {
      if(mine)mine.getTracks().forEach(t=>t.stop());
      if(call===startCall){stream=null;message('No camera · allow camera access or add a saved photo','error');}
    }
    if(call===startCall)captureLabel();
  }
  function capture() {if(blocked())return;if(!stream?.active || !node('video').videoWidth){message('No camera · start the camera or add a saved photo','error');return;}const canvas=el('canvas');canvas.width=node('video').videoWidth;canvas.height=node('video').videoHeight;canvas.getContext('2d').drawImage(node('video'),0,0);canvas.toBlob(blob=>{if(blob)detect(blob);else message('This photo could not be read','error');},'image/jpeg',.9);}
  const lotName = () => node('new-fields').hidden ? (all('[data-lot-option]').find(o => o.dataset.value === lotId)?.dataset.name || '') : node('lot-name').value;
  function batchLabel(){
    node('cancel').disabled=saving;
    const qty=batchPieces.reduce((n,p)=>n+p.quantity,0), lot=destination==='lot', fresh=!node('new-fields').hidden;
    node('save').textContent=lot?(fresh?`Create lot and add ${qty}`:`Add ${qty} to ${lotName()||'lot'}`):`Add ${qty} to loose parts`;
    node('lot-fields').hidden=!lot;pressed(all('[data-dest]'),'dest',destination);pressed(all('[data-condition]'),'condition',condition);
    node('lot-existing').hidden=fresh;node('new-lot').textContent=fresh?'Choose an existing lot':'New lot';node('new-lot').setAttribute('aria-expanded',String(fresh));
    node('save').disabled=saving || (lot && (fresh?!node('lot-name').value.trim():!lotId));
  }
  function openBatch(){
    if(saving)return;
    batchPieces=queue.filter(p=>p.status==='verified');
    if(!batchPieces.length){message('Confirm a piece and choose a colour first','error');return;}
    node('batch-title').textContent=`Add ${batchPieces.reduce((n,p)=>n+p.quantity,0)} pieces to inventory?`;
    const left=queue.length-batchPieces.length;node('left-out').textContent=left?`${left} uncertain ${left===1?'piece is':'pieces are'} left out`:'';
    node('batch-rows').replaceChildren(...batchPieces.map(p=>resultRow(p)));node('batch-error').textContent='';node('batch-error').hidden=true;batchLabel();node('batch').showModal();
  }
  node('results').addEventListener('click',openBatch);
  function bindLotOption(o){o.addEventListener('click',()=>{lotId=o.dataset.value;node('lot-label').textContent=o.textContent;node('lot-list').hidden=true;node('lot').setAttribute('aria-expanded','false');batchLabel();});}
  function addLotOption(lot, quantity){
    const o=el('button',`${lot.name} · ${lot.created_date || 'Date unknown'} · ${quantity} parts`);o.type='button';o.setAttribute('role','option');o.dataset.lotOption='';o.dataset.value=lot.id;o.dataset.name=lot.name;bindLotOption(o);node('lot-list').append(o);
  }
  function resetNewLot(){node('lot-name').value='';node('note').value='';storageId='';node('storage-label').textContent='No place';node('new-fields').hidden=true;}
  node('save').addEventListener('click',async()=>{
    if(saving)return;
    const sending=batchPieces.slice(), lot=destination==='lot', fresh=lot&&!node('new-fields').hidden, quantity=sending.reduce((n,p)=>n+p.quantity,0);
    saving=true;batchLabel();
    try{
      const data=await request('save',{pieces:sending.map(p=>({token:p.token,chosen:{...p.candidates[p.index],color_id:p.colour,quantity:p.quantity,sticker:p.sticker===true}})),destination:lot?'lot':'loose',condition,keep_photos:node('keep').checked,lot_id:lot&&!fresh?lotId:null,new_lot:fresh?{name:node('lot-name').value,note:node('note').value,storage_id:storageId}:null});
      receipt=data.event;sending.forEach(drop);
      if(fresh){if(data.lot)addLotOption(data.lot,quantity);resetNewLot();}
      saving=false;node('batch').close();node('undo').hidden=false;message(data.message,'success');showReview(null);renderQueue();
    }catch(e){message(e.message,'error');node('batch-error').textContent=e.message;node('batch-error').hidden=false;}
    finally{saving=false;batchLabel();}
  });
  node('undo').addEventListener('click',async()=>{if(undoing)return;undoing=true;node('undo').disabled=true;try{const data=await request('undo',{event:receipt});message(data.message,'success');node('undo').hidden=true;}catch(e){message(e.message,'error');}finally{undoing=false;node('undo').disabled=false;}});
  node('cancel').addEventListener('click',()=>{if(!saving)node('batch').close();});node('batch').addEventListener('cancel',e=>{if(saving)e.preventDefault();});node('batch').addEventListener('close',()=>node('results').focus());
  node('new-lot').addEventListener('click',()=>{node('new-fields').hidden=!node('new-fields').hidden;batchLabel();});
  all('[data-dest]').forEach(n=>n.addEventListener('click',()=>{destination=n.dataset.dest;batchLabel();}));
  all('[data-condition]').forEach(n=>n.addEventListener('click',()=>{condition=n.dataset.condition;batchLabel();}));
  all('[data-endpoint]').forEach(n=>n.addEventListener('click',()=>{endpoint=n.dataset.endpoint;pressed(all('[data-endpoint]'),'endpoint',endpoint);}));
  all('[data-filter]').forEach(n=>n.addEventListener('click',()=>setQueueFilter(n.dataset.filter)));
  all('[data-sort]').forEach(n=>n.addEventListener('click',()=>{queueSort=n.dataset.sort;pressed(all('[data-sort]'),'sort',queueSort);renderQueue();}));
  node('lot').addEventListener('click',()=>toggleList(node('lot'),node('lot-list')));
  all('[data-lot-option]').forEach(bindLotOption);
  node('storage').addEventListener('click',()=>toggleList(node('storage'),node('storage-list')));
  all('[data-storage-option]').forEach(o=>o.addEventListener('click',()=>{storageId=o.dataset.value;node('storage-label').textContent=o.dataset.name;node('storage-list').hidden=true;node('storage').setAttribute('aria-expanded','false');}));
  node('lot-name').addEventListener('input',batchLabel);
  all('[data-tab]').forEach(n=>n.addEventListener('click',()=>{setView(n.dataset.tab);renderQueue();}));
  node('search').addEventListener('input',renderQueue);
  node('start-review').addEventListener('click',()=>showReview(queue.find(p=>p.status==='review')||queue[0]));
  node('empty-queue').addEventListener('click',emptyQueue);
  node('camera').addEventListener('click',()=>toggleList(node('camera'),node('camera-list')));
  node('capture').addEventListener('click',()=>stream?.active?capture():start());node('file').addEventListener('change',()=>{const file=node('file').files[0];if(file)detect(file);node('file').value='';});
  node('drop').addEventListener('dragover',e=>{e.preventDefault();node('drop').classList.add('scan-drop');});node('drop').addEventListener('dragleave',()=>node('drop').classList.remove('scan-drop'));node('drop').addEventListener('drop',e=>{e.preventDefault();node('drop').classList.remove('scan-drop');if(e.dataTransfer.files[0])detect(e.dataTransfer.files[0]);});
  document.addEventListener('keydown',e=>{if(['INPUT','SELECT','TEXTAREA'].includes(document.activeElement?.tagName)||node('batch').open)return;const pageFocus=!document.activeElement||document.activeElement.tagName==='BODY'||document.activeElement===node('review');if(e.code==='Space'&&pageFocus){e.preventDefault();capture();}else if(e.key==='Enter'&&pageFocus&&reviewVisible()&&active?.colour!=null){e.preventDefault();node('review').querySelector('[data-confirm]')?.click();}else if(/^[1-9]$/.test(e.key)&&active&&queue.includes(active)&&!active.pending&&reviewVisible()&&active.candidates[Number(e.key)-1]&&Number(e.key)-1!==active.index){active.index=Number(e.key)-1;active.colour=null;active.status='review';showReview(active);renderQueue();}});
  window.addEventListener('pagehide',()=>{startCall++;if(stream){stream.getTracks().forEach(t=>t.stop());stream=null;}captureLabel();});
  if(navigator.mediaDevices){const seenFirst=messages;cameras().catch(()=>{if(messages===seenFirst)message('No camera · add a saved photo','error');});navigator.mediaDevices.addEventListener?.('devicechange',()=>cameras().catch(()=>{}));}else message('No camera · add a saved photo','error');
  captureLabel();renderQueue();
})();
