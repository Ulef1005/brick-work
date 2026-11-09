const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const context={window:{},document:{addEventListener(){}}};
vm.runInNewContext(fs.readFileSync(require('node:path').join(__dirname,'../static/web/toni/bw-admin.js'),'utf8'),context);
const rows=[{dataset:{name:'Shelf B',count:'4'}},{dataset:{name:'Attic',count:'0'}},{dataset:{name:'Shelf A',count:'2'}}];
const container={querySelectorAll:()=>rows,appendChild(row){rows.splice(rows.indexOf(row),1);rows.push(row);}};
const fields={'[data-bw-search]':{value:''},'[data-bw-filter]':{value:'all'},'[data-bw-sort]':{value:'name'},'[data-bw-count]':{},'[data-bw-rows]':container};
const list={querySelector:key=>fields[key]};
context.window.BrickAdminList(list);
assert.deepEqual(rows.map(r=>r.dataset.name),['Attic','Shelf A','Shelf B']);
fields['[data-bw-filter]'].value='used';fields['[data-bw-sort]'].value='count';context.window.BrickAdminList(list);
assert.equal(rows[0].dataset.name,'Shelf B');assert.equal(rows.find(r=>r.dataset.name==='Attic').hidden,true);
assert.equal(fields['[data-bw-count]'].textContent,'2 values');
fields['[data-bw-search]'].value='<script>';context.window.BrickAdminList(list);
assert.equal(fields['[data-bw-count]'].textContent,'0 values');
console.log('Brick Work admin runtime passed');
assert.equal(context.window.BrickAdminReorder('bricklink, rebrickable, manual',1,-1),'rebrickable, bricklink, manual');
assert.equal(context.window.BrickAdminReorder('bricklink, rebrickable',0,-1),'bricklink, rebrickable');
fields['[data-bw-search]'].value='';fields['[data-bw-filter]'].value='attention';rows[0].dataset.state='waiting_for_budget';context.window.BrickAdminList(list);
assert.equal(fields['[data-bw-count]'].textContent,'1 values');
let ready,cleanup,poll,options,instance,submitted=false;
const fetched=[];let cleared=false;
const config={dataset:{url:'/manage/add/jobs/0',csrf:'admin-csrf'}};
const panelRoot={dataset:{importJob:'42',importState:'failed',importSnapshot:JSON.stringify([{name:'inventory',state:'failed',source:'bricklink',error:'Safe failure',count:0,total:1}])}};
const integration={navigator:{onLine:true},setTimeout(fn){poll=fn;return 1;},clearTimeout(){cleared=true;},async fetch(url){fetched.push(url);return {ok:true,async json(){return {events:[{job_id:42,state:'done'}]};}};},window:{
 BrickImportProgress:class{constructor(root,transport,opts){options=opts;instance=this;this.updates=[];this.jobId=opts.jobId;assert.equal(transport.connected,true);transport.on('import_progress',data=>this.update(data));}
 update(data){this.updates.push(data);}destroy(){this.destroyed=true;}},
 addEventListener(event,fn){assert(['pagehide','pageshow'].includes(event));if(event==='pagehide')cleanup=fn;}},document:{
 addEventListener(event,fn){ready=fn;},querySelector(selector){return selector==='[data-jobs-live]'?null:config;},
 querySelectorAll(selector){return selector==='[data-import-job]'?[panelRoot]:[];},
 createElement(tag){return {children:[],appendChild(el){this.children.push(el);},submit(){submitted=true;}};},
 body:{appendChild(form){this.form=form;}}}};
vm.runInNewContext(fs.readFileSync(require('node:path').join(__dirname,'../static/web/toni/bw-admin.js'),'utf8'),integration);
ready();assert.equal(poll,undefined);                           // no live job area (the old page shape): nothing is scheduled
assert.equal(instance.updates[0].state,'failed');assert.equal(instance.updates[0].job_id,42);
assert.equal(options.retry(42,'inventory'),true);assert(submitted);assert.equal(integration.document.body.form.children.find(f=>f.name==='csrf_token').value,'admin-csrf');
(async()=>{assert.deepEqual(fetched,[]);cleanup();assert(cleared);console.log('Brick Work admin polling and retry passed');})().catch(error=>{console.error(error);process.exitCode=1;});
// #218: the Jobs page swaps in its own job area while a job or bulk action is open, keeps an open failure list open, backs off when
// nothing changes, skips a swap while focus is inside the job area, and looks once a minute when everything has settled.
(async()=>{
 const node=(attrs={},html='')=>({dataset:{...attrs},children:[],childNodes:[],innerHTML:html,replaceChildren(...kids){this.children=kids;this.innerHTML=kids.join('');},setAttribute(k,v){this[k]=v;},contains(n){return n===this||this.children.includes(n);}});
 const state={job:'running'},rows=node({},'r0'),batches=node({},'b0'),shown=node(),details=node();let mounted=0,destroyed=0,fetches=0,next,wait;
 let freshRows='r1r2';
 const panelEl={dataset:{importJob:'7',importState:'running',importSnapshot:JSON.stringify([{name:'inventory',state:'done',count:1,total:1},{name:'pictures',state:'running',count:3,total:9},{name:'market_price',state:'queued',count:0,total:0}])}};
 const live={querySelector:k=>({'[data-jobs-batches]':batches,'[data-jobs-shown-slot]':shown,'[data-bw-rows]':rows,'#batch-1 details':details})[k]||null,
  querySelectorAll:k=>k==='[data-state]'?[node({state:state.job})]:k==='[data-import-job]'?[panelEl]:k==='details[open]'?[{closest:()=>({id:'batch-1'})}]:[]};
 const slot=html=>({childNodes:[...html.match(/[a-z]\d/g)||[]],innerHTML:html});
 const updates=[];
 const env={navigator:{onLine:true},CSS:{escape:x=>x},setTimeout(fn,ms){next=fn;wait=ms;return 2;},clearTimeout(){},
  async fetch(url,opts){fetches++;assert.equal(url,'https://brickwork.example/manage/jobs');assert.equal(opts.cache,'no-store');return {ok:true,async text(){return '<html>';}};},
  DOMParser:class{parseFromString(){return {querySelector:k=>k==='[data-jobs-live]'?{querySelector:s=>({'[data-jobs-batches]':slot('b1'),'[data-jobs-shown-slot]':slot(''),'[data-bw-rows]':slot(freshRows)})[s]}:null};}},
  window:{location:{href:'https://brickwork.example/manage/jobs'},addEventListener(){},
   BrickImportProgress:class{constructor(){mounted++;}update(d){updates.push(d);}destroy(){destroyed++;}}},
  document:{visibilityState:'visible',activeElement:null,addEventListener(e,fn){if(e==='DOMContentLoaded')env.ready=fn;},querySelector:k=>k==='[data-bw-jobs]'?{dataset:{csrf:'x'}}:k==='[data-jobs-live]'?live:null,
   querySelectorAll:()=>[],createElement:()=>({})}};
 env.window.CSS=env.CSS;env.window.DOMParser=env.DOMParser;
 vm.runInNewContext(fs.readFileSync(require('node:path').join(__dirname,'../static/web/toni/bw-admin.js'),'utf8'),env);
 env.ready();assert.equal(mounted,1);assert.equal(wait,5000);
 assert.equal(updates.at(-1).step,'pictures');                       // the active step is replayed last, so the bar shows its 3 of 9
 await next();
 assert.equal(fetches,1);assert.deepEqual(rows.children,['r1','r2']);assert.deepEqual(batches.children,['b1']);
 assert.equal(destroyed,1);assert.equal(mounted,2);assert.equal(details.open,'');assert.equal(wait,5000);
 await next();assert.equal(fetches,2);assert.equal(mounted,2);assert.equal(wait,10000);   // nothing changed: no swap, the wait doubles
 await next();await next();await next();assert.equal(wait,60000);                           // and stops at a minute
 freshRows='r3';await next();assert.deepEqual(rows.children,['r3']);assert.equal(wait,5000);   // a change brings it back to 5 s
 env.document.activeElement=rows.children[0];const before=fetches;await next();assert.equal(fetches,before);   // focus in the job area: no swap
 env.document.activeElement=null;
 env.document.visibilityState='hidden';const hidden=fetches;await next();assert.equal(fetches,hidden);   // a hidden tab does not poll
 env.document.visibilityState='visible';state.job='done';await next();assert.equal(wait,60000);           // settled: once a minute
 console.log('Brick Work Jobs page live refresh passed');
})().catch(error=>{console.error(error);process.exitCode=1;});
// Instruction files has no toolbar on short lists, and only search on long lists.
const instructionFields={'[data-bw-rows]':container};
const instructionList={dataset:{noun:'files'},querySelector:key=>instructionFields[key]};
context.window.BrickAdminList(instructionList);
assert(rows.every(row=>!row.hidden));
instructionFields['[data-bw-search]']={value:'shelf b'};
instructionFields['[data-bw-count]']={};
context.window.BrickAdminList(instructionList);
assert.equal(instructionFields['[data-bw-count]'].textContent,'1 files');
assert.equal(rows.find(row=>!row.hidden).dataset.name,'Shelf B');
instructionFields['[data-bw-search]'].value='';
context.window.BrickAdminList(instructionList);
assert(rows.every(row=>!row.hidden));
console.log('Instruction files optional toolbar and search passed');

{ // 4.9e: a failed booklet picture becomes the No image tile.
 let ready; const img={complete:false,naturalWidth:0,src:'/x',listeners:{},addEventListener(e,f){this.listeners[e]=f;},replaceWith(t){this.replaced=t;}};
 const tile={}; const doc={addEventListener(e,f){ready=f;},createElement:()=>tile,querySelector:()=>null,querySelectorAll:s=>s==='img[data-bw-fallback]'?[img]:[]};
 vm.runInNewContext(fs.readFileSync(require('node:path').join(__dirname,'../static/web/toni/bw-admin.js'),'utf8'),{window:{},document:doc});
 ready(); assert.equal(img.replaced,undefined); img.listeners.error();
 assert.equal(img.replaced,tile); assert.equal(tile.textContent,'No image'); assert.match(tile.className,/bw-no-image/);
 console.log('Brick Work admin booklet picture fallback passed');
}
{
 // 12l: key entry. Test and save needs every field, Clear and the pill follow the typing.
 const ctx={window:{},document:{addEventListener(){}}};
 vm.runInNewContext(fs.readFileSync(require('node:path').join(__dirname,'../static/web/toni/bw-admin.js'),'utf8'),ctx);
 assert.deepEqual({...ctx.window.BrickKeyState([])},{complete:false,any:false});
 assert.deepEqual({...ctx.window.BrickKeyState(['','  '])},{complete:false,any:false});
 assert.deepEqual({...ctx.window.BrickKeyState(['abc',''])},{complete:false,any:true});
 assert.deepEqual({...ctx.window.BrickKeyState(['abc',' d '])},{complete:true,any:true});
 const handlers={};
 const mk=()=>({value:'',listeners:{},addEventListener(e,fn){this.listeners[e]=fn;}});
 const inputs=[mk(),mk()];
 const submit={disabled:false,textContent:'Test and save'};const clear={hidden:false};
 const text={textContent:'Not set'};const pill={className:'bk-pill bk-neutral',dataset:{keyTone:'neutral',keyRest:'Not set'},querySelector:()=>text};
 const form={querySelectorAll:()=>inputs,querySelector:s=>s==='[data-key-submit]'?submit:clear,closest:()=>({querySelector:()=>pill}),addEventListener(e,fn){handlers[e]=fn;}};
 ctx.window.BrickKeyForm(form);
 assert.equal(submit.disabled,true);assert.equal(clear.hidden,true);assert.equal(text.textContent,'Not set');
 inputs[0].value='aaaaaaaa';inputs[0].listeners.input();
 assert.equal(submit.disabled,true);assert.equal(clear.hidden,false);assert.equal(text.textContent,'Not saved');
 inputs[1].value='bbbbbbbb';inputs[1].listeners.input();
 assert.equal(submit.disabled,false);assert.equal(pill.className,'bk-pill bk-neutral');
 inputs.forEach(i=>i.value='');inputs[0].listeners.input();
 assert.equal(submit.disabled,true);assert.equal(clear.hidden,true);assert.equal(text.textContent,'Not set');
 console.log('Brick Work admin key entry passed');
}
