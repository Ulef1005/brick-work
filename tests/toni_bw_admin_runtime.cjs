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
const integration={navigator:{onLine:true},setInterval(fn){poll=fn;return 1;},clearInterval(){cleared=true;},async fetch(url){fetched.push(url);return {ok:true,async json(){return {events:[{job_id:42,state:'done'}]};}};},window:{
 BrickImportProgress:class{constructor(root,transport,opts){options=opts;instance=this;this.updates=[];this.jobId=opts.jobId;assert.equal(transport.connected,true);transport.on('import_progress',data=>this.update(data));}
 update(data){this.updates.push(data);}destroy(){this.destroyed=true;}},
 addEventListener(event,fn){assert.equal(event,'pagehide');cleanup=fn;}},document:{
 addEventListener(event,fn){ready=fn;},querySelector(selector){return config;},
 querySelectorAll(selector){return selector==='[data-import-job]'?[panelRoot]:[];},
 createElement(tag){return {children:[],appendChild(el){this.children.push(el);},submit(){submitted=true;}};},
 body:{appendChild(form){this.form=form;}}}};
vm.runInNewContext(fs.readFileSync(require('node:path').join(__dirname,'../static/web/toni/bw-admin.js'),'utf8'),integration);
ready();assert.equal(typeof poll,'function');
assert.equal(instance.updates[0].state,'failed');assert.equal(instance.updates[0].job_id,42);
assert.equal(options.retry(42,'inventory'),true);assert(submitted);assert.equal(integration.document.body.form.children.find(f=>f.name==='csrf_token').value,'admin-csrf');
(async()=>{await poll();assert.deepEqual(fetched,['/manage/add/jobs/42']);assert.equal(instance.updates.at(-1).state,'done');cleanup();assert(instance.destroyed);assert(cleared);console.log('Brick Work admin polling and retry passed');})().catch(error=>{console.error(error);process.exitCode=1;});
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
