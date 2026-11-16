/* Candidates are inert until a confirmed tick list is posted. */
(() => {
 'use strict';
 const LIMIT=20*1024*1024;
 const names={rebrickable:'Rebrickable',peeron:'Peeron',official:'Official'};
 let officialLimit=500*1024*1024;
 const fileLimit=c=>c.source==='official'?officialLimit:LIMIT;
 const available=c=>!c.file_id&&(c.size==null||c.size<=fileLimit(c));
 const profiles={AT:['Europe','English'],DE:['Europe','German'],GB:['Europe','English'],UK:['Europe','English'],FR:['Europe','French'],US:['North America','English'],CA:['North America','English'],AU:['Oceania','English']};
 const languages={en:'english',de:'german',fr:'french'};
 const locales={AT:'en-gb',DE:'de-de',GB:'en-gb',UK:'en-gb',FR:'fr-fr',US:'en-us',CA:'en-ca',AU:'en-au'};
 const matches=(c,region)=>{if(c.source==='official')return c.region===(locales[region]||'en-us');const [area,language]=profiles[region]||[region,null],spoken=(c.language||'').toLowerCase();return (!c.region||[region.toLowerCase(),area.toLowerCase(),'any','worldwide',...(['UK','GB'].includes(region)?['uk','gb']:[])].includes(c.region.toLowerCase()))&&(!language||!spoken||(languages[spoken]||spoken)===language.toLowerCase());};
 const defaults=(files,region)=>{let used=0;return files.filter(c=>{if(!available(c)||c.size==null||used+c.size>officialLimit||!(c.source==='peeron'?files.length===1:matches(c,region)))return false;used+=c.size;return true;}).map(c=>c.id);};
 const total=files=>({count:files.length,bytes:files.reduce((n,c)=>n+(c.size||0),0),unknown:files.some(c=>c.size==null)});
 const mb=n=>`${(n/1024/1024).toFixed(n?1:0)} MB`;
 class Selection {
  constructor(region){this.region=region;this.touched=new Map();this.checked=new Set();this.groups=[];}
  update(groups){this.groups=groups;this.retick();}
  retick(region=this.region){this.region=region;this.checked=new Set();let used=0;for(const g of this.groups){const preset=new Set(defaults(g.candidates,region));for(const c of g.candidates)if(available(c)&&(this.touched.has(c.id)?this.touched.get(c.id):preset.has(c.id)&&used+(c.size||0)<=officialLimit)){this.checked.add(c.id);used+=c.size||0;}}}
  touch(id,checked){this.touched.set(id,checked);this.retick();}
  files(){return this.groups.flatMap(g=>g.candidates).filter(c=>this.checked.has(c.id));}
 }
 window.BrickInstructions={defaults,total,Selection,available,matches};
 const root=document.querySelector('#bw-instructions');if(!root)return;
 officialLimit=Number(root.dataset.officialLimit)||officialLimit;
 const $=name=>root.querySelector(`[data-if-${name}]`);
 const editable=root.dataset.edit==='yes';
 let region=root.dataset.region;
 try{region=localStorage.getItem('bw-instruction-region')||region;}catch{}
 const selection=new Selection(region);
 const regionInput=$('region');
 if(!Array.from(regionInput.options).some(o=>o.value===region)){const option=document.createElement('option');option.value=region;option.textContent=region;regionInput.append(option);}
 regionInput.value=region;
 const el=(tag,text,cls)=>{const e=document.createElement(tag);if(text!=null)e.textContent=text;if(cls)e.className=cls;return e;};
 let jobs=root.dataset.jobs?root.dataset.jobs.split(',').map(Number):[],download=null,timer=null,queueMessage='';
 const say=text=>{$('message').textContent=text;};
 const api=async(data)=>{const r=await fetch(root.dataset.url,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({...data,csrf_token:root.dataset.csrf})});const answer=await r.json();if(!r.ok)throw Error(answer.error||'Could not queue instructions');return answer;};
 const saveURL=()=>{const u=new URL(location.href);u.searchParams.delete('item');if(jobs.length)u.searchParams.set('jobs',jobs.join(','));if(download)u.searchParams.set('download',download);else u.searchParams.delete('download');history.replaceState(null,'',u);};
 const render=()=>{
  const query=$('search').value.toLowerCase(),filter=$('filter').value,sort=$('sort').value;
  $('groups').replaceChildren();$('summary').replaceChildren();
  let groups=[...selection.groups];if(sort==='name')groups.sort((a,b)=>a.name.localeCompare(b.name));
  for(const g of groups){
   const group=el('section',null,'if-group'),identity=el('header',null,'if-identity');identity.append(el('span',g.born_key||'Unidentified set','mono'),el('strong',g.name));group.append(identity);
   let visible=0;
   for(const c of g.candidates){
    if(!`${g.born_key} ${g.name} ${c.title} ${names[c.source]}`.toLowerCase().includes(query)||filter&&(filter==='available'?!available(c):c.source!==filter))continue;
    visible++;
    const row=el('div',null,'if-file'),label=el('label',null,'if-control');
    if(editable){const tick=el('input');tick.type='checkbox';tick.value=c.id;tick.checked=selection.checked.has(c.id);tick.disabled=!available(c);tick.addEventListener('change',()=>{selection.touch(c.id,tick.checked);render();});label.append(tick);}
    label.append(el('strong',c.booklets>1?`Booklet ${c.booklet} of ${c.booklets}`:c.title));
    const meta=el('div',null,'if-meta');meta.append(el('span',names[c.source]||c.source,'if-source'),el('span',`${c.language||'Any language'}${c.region?' · '+c.region:''}`),el('span',c.size==null?'Size unknown':mb(c.size),'mono'));
    row.append(label,meta);
    if(!available(c))row.append(el('p',c.file_id?'Already have this file':`Over ${mb(fileLimit(c))}`,'if-muted'));
    group.append(row);
   }
   if(g.error)group.append(el('p',g.error,'notice'));
   if(g.error&&g.sources_tried.length&&editable){const retry=el('button','Retry sources');retry.type='button';retry.addEventListener('click',()=>find({item_ids:[g.item_id]}));group.append(retry);}
   if(!g.candidates.length){group.append(el('strong',g.state==='queued'||g.state==='running'?'Looking for PDFs':'No PDF found'));if(g.sources_tried.length)group.append(el('p','Looked in '+g.sources_tried.map(s=>names[s]||s).join(', ')+'.'));}
   if(visible||!g.candidates.length||g.error)$('groups').append(group);
   const ticked=g.candidates.filter(c=>selection.checked.has(c.id));const sum=total(ticked);
   $('summary').append(el('p',`${g.name} · ${sum.count} · ${mb(sum.bytes)}${sum.unknown?' + unknown':''}`));
  }
  const sum=total(selection.files());$('total').textContent=`${sum.count} files ticked · ${mb(sum.bytes)}${sum.unknown?' + unknown sizes':''}`;
  $('count').textContent=`${selection.groups.length} sets · ${selection.groups.flatMap(g=>g.candidates).length} files found`;
  if(editable){$('download').textContent=`Download ${sum.count} files`;$('download').disabled=!sum.count;$('hint').textContent=sum.count?'Nothing is downloaded before you choose Download.':'Tick at least one file.';}
 };
 const poll=async()=>{
  clearTimeout(timer);
  try{
   const query=new URLSearchParams({jobs:jobs.join(',')});if(download)query.set('download',download);
   const response=await fetch(root.dataset.url+'/status?'+query);if(!response.ok)throw Error();const data=await response.json();
   selection.update(data.groups);render();
   const searching=data.groups.some(g=>['queued','running','waiting_for_budget'].includes(g.state));
   if(!download)say(queueMessage||(searching?`Looked up ${data.groups.filter(g=>g.state==='done').length} of ${jobs.length} sets`:''));
   let running=false;
   if(data.download){const job=data.download;running=['queued','running','waiting_for_budget'].includes(job.state);const done=job.steps.filter(s=>s.state==='done').length,failed=job.steps.filter(s=>s.state==='failed').length;
    $('heading').textContent=job.state==='done'?`${done} files added`:failed?`${done} files added · ${failed} failed`:job.state==='waiting_for_budget'?'Waiting for the source':`Downloading · ${done} of ${job.steps.length} files`;
    $('bar').max=job.steps.length;$('bar').value=done;$('files').replaceChildren();
    for(const step of job.steps){const c=selection.groups.flatMap(g=>g.candidates).find(c=>c.id===Number(step.name));const row=el('div',null,'if-file');row.append(el('strong',c?c.title:`File ${step.name}`),el('span',`${step.state==='done'?'Finished':step.state==='queued'?'Not started':step.state.replaceAll('_',' ')}${step.error?' · '+step.error:''}`));$('files').append(row);}
    if(editable){$('retry').hidden=!failed||job.owner_alive;const remaining=job.steps.filter(s=>['queued','waiting_for_budget'].includes(s.state)).length;$('cancel').hidden=!remaining;$('cancel').textContent=`Cancel ${remaining} not started`;}
   }
   if(searching||running)timer=setTimeout(poll,1000);
  }catch{say('No network · progress could not be loaded. Your job is kept.');const retry=el('button','Retry connection');retry.type='button';retry.addEventListener('click',()=>{retry.remove();poll();});$('message').append(retry);}
 };
 const results=()=>{if($('choose'))$('choose').hidden=true;$('results').hidden=false;};
 const find=async(options)=>{
  say('Looking for PDFs');
  try{const result=await api({action:'find',region:selection.region,...options});jobs=result.jobs;queueMessage=result.message||'';download=null;selection.touched.clear();results();saveURL();if(!jobs.length){selection.update([]);render();say(result.message);return;}await poll();}
  catch(error){say(error.message);}
 };
 regionInput.addEventListener('change',()=>{selection.retick(regionInput.value);try{localStorage.setItem('bw-instruction-region',regionInput.value);}catch{}render();});
 for(const name of ['search','filter','sort'])$(name).addEventListener(name==='search'?'input':'change',render);
 if(editable){
  $('choose').addEventListener('submit',e=>{e.preventDefault();find({mode:$('choose').elements.mode.value,numbers:$('choose').elements.numbers.value});});
  $('all').addEventListener('click',()=>{for(const g of selection.groups)for(const c of g.candidates)if(available(c))selection.touched.set(c.id,true);selection.retick();render();});
  $('clear').addEventListener('click',()=>{for(const g of selection.groups)for(const c of g.candidates)selection.touched.set(c.id,false);selection.retick();render();});
  $('change').addEventListener('click',()=>{$('choose').hidden=false;$('results').hidden=true;clearTimeout(timer);});
  $('download').addEventListener('click',async()=>{const ids=[...selection.checked];if(!ids.length)return;$('download').disabled=true;try{const result=await api({action:'download',candidate_ids:ids});download=result.download;saveURL();$('results').hidden=true;$('progress').hidden=false;await poll();}catch(error){say(error.message);render();}});
  $('cancel').addEventListener('click',async()=>{try{await api({action:'cancel',job_ids:[download]});await poll();}catch(error){say(error.message);}});
  $('retry').addEventListener('click',async()=>{try{const response=await fetch(`/manage/add/jobs/${download}/retry`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({csrf_token:root.dataset.csrf})});if(!response.ok)throw Error();$('retry').hidden=true;await poll();}catch{say('Could not retry · check your connection');}});
 }
 // Move the region control in the DOM: phone header, desktop summary.
 const regionLabel=regionInput.parentElement,slot=el('div');root.querySelector('.if-steps').after(slot);
 const moveRegion=()=>{(matchMedia('(max-width:700px)').matches?slot:root.querySelector('.if-summary')).prepend(regionLabel);};moveRegion();window.addEventListener('resize',moveRegion);
 const initialDownload=new URL(location.href).searchParams.get('download');if(initialDownload&&/^\d+$/.test(initialDownload)){download=Number(initialDownload);$('progress').hidden=false;}
 if(jobs.length){results();if(download)$('results').hidden=true;poll();}else if(editable&&/^\d+$/.test(root.dataset.item)){find({item_ids:[Number(root.dataset.item)]});}
})();
