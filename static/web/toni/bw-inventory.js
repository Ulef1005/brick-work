(() => {
  'use strict';
  const nowrapTail = window.BrickFormatting.nowrapTail;
  const root = document.querySelector('#bw-inventory');
  if (!root) return;
  const node = key => root.querySelector(`[data-${key}]`);
  const all = selector => Array.from(root.querySelectorAll(selector));
  const colours = JSON.parse(root.dataset.colours), queue = [];
  const STATUS = { verified: ['Ready', 'ok'], review: ['To review', 'queued'], error: ['Unidentified', 'warn'], pending: ['Recognizing', 'info'] };
  let active = null, stream = null, startCall = 0, pendingPiece = null, saving = false, undoing = false, receipt = null, batchPieces = [];
  let endpoint = 'parts', queueFilter = '', queueSort = 'piece', destination = 'loose', condition = 'U', cameraId = '', lotId = '', storageId = '';
  const el = (tag, text, cls) => { const n = document.createElement(tag); if (text !== undefined) n.textContent = text; if (cls) n.className = cls; return n; };
  const message = (text, kind = 'info') => { node('message').textContent = text; node('notice').dataset.kind = kind; node('notice').hidden = !text && node('undo').hidden; };
  function button(text, action, cls) { const n = el('button', text, cls); n.type = 'button'; n.addEventListener('click', action); return n; }
  const pressed = (nodes, key, value) => nodes.forEach(n => n.setAttribute('aria-pressed', String(n.dataset[key] === value)));
  function tile(image, name, number, cls, retry = true) { const n = el('div', undefined, 'scan-tile' + (cls ? ' ' + cls : '')); if (image) { const i = el('img'); i.src = image; i.dataset.full = image.replace(/\?w=\d+$/, ''); i.alt = name; i.addEventListener('error',()=>n.replaceChildren(el('span','Image did not load'),...(retry?[button('Retry',()=>{i.src=image;n.replaceChildren(i);})]:[]))); n.append(i); } else {n.className+=' scan-no-image';if(number)n.append(el('span',number,'mono'));n.append(el('span', 'No image'));} return n; }
  const image = c => c.image ? `/manage/images/${c.image}?w=640` : null;
  function swatch(n, c) {
    if (!/^[0-9a-f]{6}$/i.test(c.rgb || '')) return;
    n.style.backgroundColor = '#' + c.rgb;
    const channels = c.rgb.match(/../g).map(v => { const x = parseInt(v,16)/255; return x <= .04045 ? x/12.92 : ((x+.055)/1.055)**2.4; });
    n.style.color = channels[0]*.2126 + channels[1]*.7152 + channels[2]*.0722 > .45 ? '#1A1816' : '#FAFAF8';
  }
  function segment(options, current, set, label) {
    const group = el('div', undefined, 'inv-seg'); group.setAttribute('role', 'group'); group.setAttribute('aria-label', label);
    const buttons = options.map(([value, text]) => { const b = button(text, () => { set(value); buttons.forEach(x => x.setAttribute('aria-pressed', String(x.value === value))); }); b.value = value; b.setAttribute('aria-pressed', String(value === current)); return b; });
    group.append(...buttons); return group;
  }
  function statusPill(piece) { const [text, kind] = STATUS[piece.pending ? 'pending' : piece.status]; const pill = el('span', undefined, `inv-status inv-status-${kind}`); pill.append(el('i'), document.createTextNode(text)); return pill; }
  function chip(c) { const n = el('span', c.name || `Colour ${c.color_id}`, 'scan-swatch'); swatch(n, c); return n; }
  function listControls(rows, render, name, defaultSort='name') {
    const wrapper=el('div',undefined,'inv-stack'), toolbar=el('div',undefined,'inv-toolbar'), search=el('input'), chips=el('div',undefined,'inv-chips'), count=el('p',undefined,'mono inv-note'), content=el('div',undefined,name==='colours'?'scan-colours':'inv-options');
    let filterValue='', sortValue=defaultSort;
    search.type='search';search.placeholder=`Search ${name}`;search.setAttribute('aria-label',`Search ${name}`);
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
    const wrap = el('div', undefined, 'inv-qty'), qty = el('input');
    qty.type = 'number'; qty.min = '1'; qty.max = '9999'; qty.value = piece.quantity; qty.setAttribute('aria-label', 'Quantity');
    const set = v => { piece.quantity = Math.min(9999, Math.max(1, Number(v) || 1)); qty.value = piece.quantity; piece.status = 'review'; renderQueue(); onChange(); };
    qty.addEventListener('change', () => set(qty.value));
    const minus = button('', () => set(piece.quantity - 1), 'inv-step inv-step-minus'), plus = button('', () => set(piece.quantity + 1), 'inv-step inv-step-plus');
    minus.setAttribute('aria-label', 'Decrease quantity'); plus.setAttribute('aria-label', 'Increase quantity');
    wrap.append(minus, qty, plus); return wrap;
  }
  function showReview(piece) {
    active = piece; const out = node('review'); out.replaceChildren();
    if (!piece) { out.append(emptyState('Take a picture or add a saved photo to begin.')); setView('capture'); return; }
    setView('review');
    const position = `Piece ${queue.indexOf(piece) + 1} of ${queue.length}`;
    const c = piece.candidates[piece.index];
    if (piece.pending) { out.append(el('h2', position), el('p', 'Recognizing', 'secondary'), tile(null, 'Piece', null, 'inv-big'), button('Delete picture', () => remove(piece), 'inv-link')); return; }
    if (!c) {
      const banner = el('p', piece.error || 'Nothing identified · try another photo', 'inv-banner');
      const retake = button('Retake', () => { remove(piece); node('file').click(); }, 'button primary inv-primary');
      out.append(el('h2', position), el('p', 'Not recognised', 'secondary'), tile(piece.photo, 'Your photo', null, 'inv-big'), banner, retake, button('Delete picture', () => remove(piece), 'inv-link'));
      return;
    }
    const colour = colours.find(r=>r.color_id===piece.colour);
    const best = el('div', undefined, 'inv-best'); best.append(el('span', 'Reference · best match', 'inv-label'), tile(image(c),c.name,c.item_no), el('h3', nowrapTail(c.name)), el('span', `${c.item_no} · ${colour ? colour.name : 'Choose a colour'} · ${c.score.toFixed(2)} match`, 'mono inv-note'));
    const photo = el('div', undefined, 'inv-photo'); photo.append(el('span', 'Your photo', 'inv-label'), tile(piece.photo, 'Your photo'));
    const reference = el('div', undefined, 'scan-reference'); reference.append(best, photo);
    out.append(el('h2', position), el('p', 'Confirm the part, then pick the colour', 'secondary'), reference);
    // #45: what you already have of this part, across colours; an owned colour is one tap.
    const owned=c.owned_summary;
    if(owned){const box=el('div',undefined,'inv-owned');box.append(el('p',owned.text,'inv-owned-text'));
      const picks=el('div',undefined,'inv-owned-picks');
      (owned.colours||[]).slice(0,6).forEach(o=>{const known=colours.find(r=>r.color_id===o.color_id);if(!known)return;
        const b=button(`${known.name} · have ${o.quantity}`,()=>{piece.colour=o.color_id;piece.status='review';showReview(piece);renderQueue();});
        swatch(b,known);b.setAttribute('aria-pressed',String(o.color_id===piece.colour));picks.append(b);});
      if(picks.children.length)box.append(picks);
      if(owned.needed_count){const a=el('a',`Fills a gap in ${owned.needed_count} ${owned.needed_count===1?'copy':'copies'} · Matcher`,'inv-owned-need');a.href='/workbench/matcher';box.append(a);}
      out.append(box);}
    const alternatives=piece.candidates.map((candidate,i)=>({...candidate,index:i})).filter(c=>c.index!==piece.index);
    if (alternatives.length) {
      const block = el('div', undefined, 'inv-stack'); block.append(el('h3', 'Other possibilities', 'inv-label'));
      block.append(listControls(alternatives,candidate=>{const b=button('',()=>{piece.index=candidate.index;piece.colour=null;piece.status='review';showReview(piece);renderQueue();});b.className='scan-alternative';const identity=el('span',undefined,'inv-grow');identity.append(el('span',nowrapTail(candidate.name),'inv-name'),el('span',`${candidate.index+1} · ${candidate.item_no}`,'mono inv-note'));b.append(tile(image(candidate),candidate.name,candidate.item_no,'',false),identity,el('span',candidate.score.toFixed(2),'mono inv-score'));return b;},'possibilities','score'));
      out.append(block);
    }
    const choices=listControls(colours,c=>{const b=button(c.name||`Unknown colour · ${c.color_id}`,()=>{piece.colour=c.color_id;piece.status='review';showReview(piece);renderQueue();});swatch(b,c);b.setAttribute('aria-pressed',String(c.color_id===piece.colour));if(c.color_id===piece.colour)b.append(el('span',undefined,'inv-tick'));return b;},'colours');
    const colourBlock = el('div', undefined, 'inv-stack'); colourBlock.append(el('h3', 'Colour · you choose', 'inv-label'), choices);
    const confirmText=()=>colour?`Confirm · ${colour.name} ×${piece.quantity}`:'Choose a colour';
    const confirm=button(confirmText(),()=>{piece.status='verified';renderQueue();const next=queue.find(p=>p.status==='review');showReview(next || piece);});confirm.disabled=!colour;confirm.className='button primary inv-primary';confirm.dataset.confirm='';
    const qtyRow = el('div', undefined, 'inv-split'); qtyRow.append(el('span', 'Quantity', 'inv-label'), quantityStepper(piece, () => { confirm.textContent = confirmText(); }));
    const links = el('div', undefined, 'inv-split'); links.append(button('Delete picture',()=>remove(piece),'inv-link'));
    out.append(colourBlock, qtyRow, confirm, links, el('p','Enter · confirm · 1 to 9 · choose a candidate','mono inv-note'));
  }
  function drop(piece) {const at=queue.indexOf(piece);if(at<0)return false;queue.splice(at,1);URL.revokeObjectURL(piece.photo);release(piece);return true;}
  function release(piece) {if(pendingPiece!==piece)return;piece.abort?.abort();pendingPiece=null;node('capture').disabled=false;}
  function remove(piece) {if(!drop(piece))return;showReview(queue.find(p=>p.status==='review'));renderQueue();}
  function emptyQueue() {queue.slice().forEach(drop);showReview(null);renderQueue();}
  function identity(piece) {
    const c=piece.candidates[piece.index], colour=colours.find(r=>r.color_id===piece.colour), box=el('div',undefined,'identity');
    box.append(el('span',`Piece ${queue.indexOf(piece)+1}${c?.item_no ? ' · ' + c.item_no : ''}`,'mono inv-note'),el('span',c?.name ? nowrapTail(c.name) : (piece.pending ? 'Recognizing' : (piece.error || 'Unidentified')),'inv-name'));
    if (colour) box.append(chip(colour)); return box;
  }
  function queueRow(piece) {
    const c=piece.candidates[piece.index], r=button('',()=>showReview(piece),'scan-row'), wrap=el('div',undefined,'inv-queue-row');
    r.append(tile(c ? image(c) : null,c?.name||'Unidentified',c?.item_no,'',false),el('span',String(queue.indexOf(piece)+1),'inv-number mono'),identity(piece),statusPill(piece));
    const del=button('',()=>remove(piece),'inv-delete');del.setAttribute('aria-label',`Delete piece ${queue.indexOf(piece)+1}`);wrap.append(r,del);return wrap;
  }
  function resultRow(piece, label) {
    const c=piece.candidates[piece.index], r=el('div',undefined,'scan-row');
    r.append(tile(c ? image(c) : null,c?.name||'Unidentified',c?.item_no),identity(piece));
    const right=el('div',undefined,'inv-right');right.append(el('span',`×${piece.quantity}`,'mono inv-qty-text'));if(label){const pill=el('span',undefined,'inv-status inv-status-ok');pill.append(el('i'),document.createTextNode(label));right.append(pill);}
    r.append(right);return r;
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
    node('toolbar').hidden=!queue.length;node('queue-actions').hidden=!queue.length;
    node('count').textContent=queue.length?`${pieces.length} pieces`:'';
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
    const devices=await navigator.mediaDevices.enumerateDevices();let selected=cameraId;try{selected=selected||localStorage.getItem('bw-camera')||'';}catch(e){}
    const inputs=devices.filter(d=>d.kind==='videoinput');
    const options=inputs.map((d,i)=>{const o=button(d.label||`Camera ${i+1}`,()=>{});o.setAttribute('role','option');o.value=d.deviceId;return o;});
    listPicker(node('camera'),node('camera-list'),options,o=>{pickCamera(o.value,o.textContent);try{localStorage.setItem('bw-camera',o.value);}catch(e){}start();});
    const chosen=options.find(o=>o.value===selected)||options[0];
    if(chosen)pickCamera(chosen.value,chosen.textContent);else{pickCamera('','No camera');message('No camera · add a saved photo','error');}
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
      const data=await request('save',{pieces:sending.map(p=>({token:p.token,chosen:{...p.candidates[p.index],color_id:p.colour,quantity:p.quantity}})),destination:lot?'lot':'loose',condition,keep_photos:node('keep').checked,lot_id:lot&&!fresh?lotId:null,new_lot:fresh?{name:node('lot-name').value,note:node('note').value,storage_id:storageId}:null});
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
  if(navigator.mediaDevices){cameras().catch(()=>message('No camera · add a saved photo','error'));navigator.mediaDevices.addEventListener?.('devicechange',()=>cameras().catch(()=>{}));}else message('No camera · add a saved photo','error');
  captureLabel();renderQueue();
})();
