/* Admin lists and the existing import_progress observer. Writes use normal forms. */
(() => {
 function updateList(list) {
  const query = (list.querySelector('[data-bw-search]')?.value || '').toLowerCase();
  const filter = list.querySelector('[data-bw-filter]')?.value || 'all';
  const sort = list.querySelector('[data-bw-sort]')?.value || 'name';
  const container = list.querySelector('[data-bw-rows]');
  const rows = [...container.querySelectorAll('[data-bw-row]')].filter(row => !row.closest || row.closest('[data-bw-list]') === list);
  rows.sort((a,b) => sort === 'count' ? Number(b.dataset.count)-Number(a.dataset.count) : a.dataset.name.localeCompare(b.dataset.name));
  let visible = 0;
  for (const row of rows) {
   const used = Number(row.dataset.count)>0;
   row.hidden = !row.dataset.name.toLowerCase().includes(query) || (filter==='used'&&!used) || (filter==='unused'&&used) || (filter==='attention'&&!['failed','waiting_for_budget','to_check','unmatched'].includes(row.dataset.state)) || (filter==='done'&&row.dataset.state!=='done');
   if (!row.hidden) visible++;
   container.appendChild(row);
  }
  const count = list.querySelector('[data-bw-count]');
  if (count) count.textContent = `${visible} ${list.dataset?.noun || "values"}`;
  const chips = list.querySelector('[data-bw-chips]');
  if (chips) {
   chips.replaceChildren();
   for (const [selector, value, reset] of [['[data-bw-search]',query,''],['[data-bw-filter]',filter,'all']]) {
    if (!value || value === 'all') continue;
    const chip=document.createElement('button');chip.type='button';
    chip.textContent=`${value} · Remove`;chip.setAttribute('aria-label',`Remove filter: ${value}`);
    chip.addEventListener('click',()=>{list.querySelector(selector).value=reset;updateList(list);list.querySelector(selector).focus();});
    chips.appendChild(chip);
   }
  }
 }
 window.BrickAdminList = updateList;
 function reorder(value,index,offset) {
  const sources=value.split(',').map(s=>s.trim()).filter(Boolean);
  const target=index+offset;
  if (target>=0 && target<sources.length) [sources[index],sources[target]]=[sources[target],sources[index]];
  return sources.join(', ');
 }
 window.BrickAdminReorder = reorder;
 function priorityEditor(editor) {
  const input=editor.querySelector('[data-priority-input]');
  const list=editor.querySelector('[data-priority-list]');
  function render() {
   list.replaceChildren();
   const sources=input.value.split(',').map(s=>s.trim()).filter(Boolean);
   sources.forEach((source,index)=>{
    const row=document.createElement('li');
    const name=document.createElement('span');name.textContent=source;row.appendChild(name);
    for (const [label,offset] of [['Move up',-1],['Move down',1]]) {
     const button=document.createElement('button');button.type='button';button.textContent=label;
     button.setAttribute('aria-label',`${source}, ${label.toLowerCase()}`);
     button.disabled=index+offset<0||index+offset>=sources.length;
     button.addEventListener('click',()=>{input.value=reorder(input.value,index,offset);render();input.focus();});
     row.appendChild(button);
    }
    list.appendChild(row);
   });
  }
  input.addEventListener('input',render);render();
 }
 /* Key entry: Test and save stays off until every field holds a value; Clear and the pill follow the typing. */
 function keyState(values) {
  const filled = values.filter(v => String(v).trim() !== '');
  return {complete: values.length > 0 && filled.length === values.length, any: filled.length > 0};
 }
 window.BrickKeyState = keyState;
 function keyForm(form) {
  const inputs = [...form.querySelectorAll('[data-key-input]')];
  const submit = form.querySelector('[data-key-submit]');
  const clear = form.querySelector('[data-key-clear]');
  const pill = form.closest('[data-key-card]')?.querySelector('[data-key-pill]');
  const text = pill?.querySelector('[data-key-text]');
  const show = (tone, label) => { if (!pill) return; pill.className = 'bk-pill bk-' + tone; text.textContent = label; };
  function render() {
   const state = keyState(inputs.map(input => input.value));
   submit.disabled = !state.complete;
   if (clear) clear.hidden = !state.any;
   if (state.any) show('neutral', 'Not saved'); else show(pill?.dataset.keyTone || 'neutral', pill?.dataset.keyRest || 'Not set');
  }
  inputs.forEach(input => input.addEventListener('input', render));
  form.addEventListener('reset', () => setTimeout(render, 0));
  form.addEventListener('submit', () => setTimeout(() => { submit.disabled = true; submit.textContent = 'Testing...'; show('warning', 'Testing'); }, 0));
  render();
 }
 window.BrickKeyForm = keyForm;
 document.addEventListener('DOMContentLoaded', () => {
  document.querySelectorAll('[data-key-form]').forEach(keyForm);
  document.querySelectorAll('img[data-bw-fallback]').forEach(img => {
   const replace = () => { const tile = document.createElement('span'); tile.className = 'bw-no-image bw-booklet-pic'; tile.textContent = 'No image'; img.replaceWith(tile); };
   if (img.complete && img.naturalWidth === 0 && img.src) replace(); else img.addEventListener('error', replace, {once: true});
  });
  document.querySelectorAll('[data-priority-editor]').forEach(priorityEditor);
  document.querySelectorAll('[data-bw-list]').forEach(list => {
   list.querySelectorAll('input,select').forEach(input => input.addEventListener('input',()=>updateList(list)));
   updateList(list);
  });
  const config = document.querySelector('[data-bw-jobs]');
  if (!config || !window.BrickImportProgress) return;
  const listeners = new Map();
  const channel = {connected:navigator.onLine,
   on(event,fn){if(!listeners.has(event))listeners.set(event,new Set());listeners.get(event).add(fn);},
   off(event,fn){listeners.get(event)?.delete(fn);}};
  const dispatch=(event,data)=>listeners.get(event)?.forEach(fn=>fn(data));
  const panels = [...document.querySelectorAll('[data-import-job]')].map(el => {
   const panel = new window.BrickImportProgress(el,channel,{
   jobId:Number(el.dataset.importJob),
   retry(job,step) {
    const form = document.createElement('form'); form.method='post';
    for (const [name,value] of Object.entries({job,step,csrf_token:config.dataset.csrf})) {
     const field = document.createElement('input'); field.type='hidden';field.name=name;field.value=value;form.appendChild(field);
    }
    document.body.appendChild(form);form.submit();return true;
   }
  });
   const steps=JSON.parse(el.dataset.importSnapshot||'[]');
   const completed=steps.filter(s=>s.state==='done').length;
   for (const step of steps) {
    const state=step.state==='waiting_for_budget'?'waiting':step.state==='queued'||step.state==='running'?'started':step.state;
    panel.update({job_id:Number(el.dataset.importJob),step:step.name,source:step.source,state,
     count:step.count,total:step.total,total_steps:steps.length,completed_steps:completed,
     job_state:el.dataset.importState,error:step.error,retry:state==='failed',
     message:step.error||(el.dataset.pictureRefresh==='true'?`Downloading images · ${step.count} of ${step.total} · ${step.state.replaceAll('_',' ')}`:`${step.name.replaceAll('_',' ')} · ${step.state.replaceAll('_',' ')}`)});
   }
   if (el.dataset.importState==='done') panel.update({job_id:Number(el.dataset.importJob),step:null,state:'done',
    total_steps:steps.length,completed_steps:completed,count:1,total:1,job_state:'done',message:el.dataset.pictureRefresh==='true'?`Downloading images · ${steps[0].count} of ${steps[0].total} · complete`:'Import complete'});
   return panel;
  });
  const poll=async()=>{
   channel.connected=navigator.onLine;
   if(!channel.connected)return;
   await Promise.all(panels.map(async panel=>{
    try {
     const response=await fetch(config.dataset.url.replace(/0$/,String(panel.jobId)),{cache:'no-store'});
     if(response.ok)(await response.json()).events.forEach(event=>dispatch('import_progress',event));
    }catch{ /* The saved snapshot stays visible until the next poll. */ }
   }));
  };
  const timer=setInterval(poll,3000);
  window.addEventListener('pagehide',()=>{clearInterval(timer);panels.forEach(p=>p.destroy());},{once:true});
 });
})();

// A long synchronous form (catalogue load): show a busy state until the page reloads.
(typeof document.querySelectorAll === 'function' ? document.querySelectorAll('form[data-busy-form]') : []).forEach((form) => form.addEventListener('submit', (event) => {
  if (form.getAttribute('aria-busy') === 'true') { event.preventDefault(); return; }
  form.setAttribute('aria-busy', 'true');
  const button = form.querySelector('button[data-busy-label]');
  if (button) {
    button.textContent = button.dataset.busyLabel;
    // Disable after the submit has been collected, so the form still posts.
    setTimeout(() => { button.disabled = true; }, 0);
  }
  const note = form.querySelector('[data-busy-note]');
  if (note) note.hidden = false;
}));
