const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
class Element {
 constructor(tag='div'){this.tagName=tag.toUpperCase();this.children=[];this.events={};this.dataset={};this.style={};this.value='';this.hidden=false;this.disabled=false;this.checked=false;this.textContent='';this.classList={add(){},remove(){}};}
 append(...n){this.children.push(...n.map(c=>typeof c==='string'?{textContent:c,children:[]}:c));}replaceChildren(...n){this.children=n;}setAttribute(k,v){this[k]=v;}addEventListener(k,v){this.events[k]=v;}async fire(k,e={}){return this.events[k]?.(e);}click(){if(!this.disabled)return this.fire('click');}focus(){}showModal(){this.open=true;}close(){this.open=false;this.fire('close');}querySelector(s){if(s==='[data-confirm]')return this.children.find(n=>n.dataset?.confirm!==undefined);return null;}
}
const text=n=>[n.textContent||'',...(n.children||[]).map(text)].join(' ');
const keys=['unresolved','message','notice','camera','camera-label','camera-list','drop','video','capture','file','slot','review','queue','queue-count','toolbar','queue-actions','search','chips','count','total','results','results-count','results-total','results-list','start-review','empty-queue','batch','batch-title','batch-error','left-out','batch-rows','lot-fields','lot-existing','lot','lot-label','lot-list','new-lot','new-fields','lot-name','storage','storage-label','storage-list','note','keep','save','cancel','undo'];
function setup(navigator){
 const nodes=Object.fromEntries(keys.map(k=>[k,new Element()]));nodes.keep.checked=true;nodes['new-fields'].hidden=true;nodes.notice.hidden=true;nodes.undo.hidden=true;['camera-list','lot-list','storage-list'].forEach(k=>{nodes[k].hidden=true;});nodes.search.value='';
 const groups={};const group=(attr,values)=>{groups[attr]=values.map(v=>{const n=new Element('button');n.dataset[attr]=v;return n;});};
 group('tab',['capture','queue','review','results']);group('dest',['loose','lot']);group('condition',['U','N']);group('endpoint',['parts','figs']);group('filter',['','verified','review','error']);group('sort',['piece','name']);
 groups['lot-option']=['7'].map(v=>{const n=new Element('button');n.dataset.value=v;n.dataset.name='Pile A';n.textContent='Pile A · Oct 2024 · 128 parts';return n;});
 groups['storage-option']=['','3'].map(v=>{const n=new Element('button');n.dataset.value=v;n.dataset.name=v?'Drawer 2':'No place';return n;});
 const root=new Element();root.dataset={url:'/workbench/part-to-inventory',csrf:'csrf',colours:JSON.stringify([{color_id:11,name:'Synthetic blue',rgb:'ABCDEF'}])};
 root.querySelector=s=>nodes[s.match(/data-([^\]]+)/)[1]];
 root.querySelectorAll=s=>groups[s.match(/data-([^\]]+)/)[1]]||[];
 const document={querySelector:()=>root,createElement:t=>new Element(t),createTextNode:t=>({textContent:t,children:[]}),activeElement:new Element('body'),events:{},addEventListener(k,v){this.events[k]=v;}};
 const window={events:{},addEventListener(k,v){this.events[k]=v;}};
 class FormData {constructor(){this.values={};}append(k,v){this.values[k]=v;}}
 const env={calls:[],fail:false,errorMessage:'Offline · retry',detectFails:false};
 const context={document,window,navigator,FormData,AbortController,URL:{createObjectURL:()=> 'blob:photo',revokeObjectURL(){}},fetch:async(url,options)=>{env.calls.push({url,options});if(url.endsWith('/detect')){if(env.gate)await env.gate;if(env.detectFails)return{ok:false,json:async()=>({error:'Brickognize found no match for this piece.'})};return{ok:true,json:async()=>({token:'signed',unresolved:[],candidates:[{item_type:'P',item_no:'bl-part',name:'Part',score:.91,image:7},{item_type:'P',item_no:'alternative',name:'Other',score:.8}]})};}if(url.endsWith('/save')&&env.saveGate)await env.saveGate;if(url.endsWith('/undo')&&env.undoGate)await env.undoGate;if(env.fail)return{ok:false,json:async()=>({error:env.errorMessage})};return{ok:true,json:async()=>({event:42,message:url.endsWith('/undo')?'Undone':'Receipts saved. Batch added.',lot:url.endsWith('/save')?{id:'new1',name:'Pile B',created_date:'2026-10-16'}:undefined})};}};
 vm.runInNewContext((fs.readFileSync('static/web/toni/formatting.js','utf8')+fs.readFileSync('static/web/toni/bw-inventory.js','utf8')),context);
 return {nodes,groups,document,env,window,root};
}
const tick=()=>new Promise(r=>setImmediate(r));
async function flow(){
 const {nodes,groups,document,env}=setup({});
 const calls=env.calls;
 assert.match(nodes.message.textContent,/No camera/);assert.equal(nodes.notice.dataset.kind,'error');assert.equal(nodes.notice.hidden,false);
 assert.equal(nodes.capture.textContent,'Enable camera');assert.equal(nodes.slot.textContent,'Piece 1');
 assert.match(text(nodes.queue),/No pieces queued/);assert.match(text(nodes['results-list']),/Nothing confirmed yet/);assert.equal(nodes.toolbar.hidden,true);
 document.activeElement=new Element('button');let prevented=false;document.events.keydown({code:'Space',preventDefault(){prevented=true;}});assert.equal(prevented,false);
 document.activeElement=new Element('body');document.events.keydown({code:'Space',preventDefault(){prevented=true;}});assert.ok(prevented);assert.match(nodes.message.textContent,/start the camera/);
 await nodes.capture.click();assert.match(nodes.message.textContent,/No camera/);
 // Recognizing state shows while the request is open.
 nodes.file.files=[{}];const pending=nodes.file.fire('change');
 assert.match(text(nodes.queue),/Recognizing/);assert.match(text(nodes.review),/Recognizing/);assert.equal(nodes.capture.disabled,true);assert.equal(nodes.slot.textContent,'Piece 2');
 await pending;await tick();
 assert.match(text(nodes.review),/1 to 9/);assert.match(text(nodes.review),/Piece 1 of 1/);assert.match(text(nodes.review),/Confirm the part, then pick the colour/);
 assert.doesNotMatch(text(nodes.review),/(?:^|[\s(\[·])[-−–—]\d/);
 assert.equal(nodes.total.textContent,1);assert.equal(nodes.review.querySelector('[data-confirm]').disabled,true);assert.equal(nodes.review.querySelector('[data-confirm]').textContent,'Choose a colour');
 const reference=()=>nodes.review.children[2];
 assert.equal(reference().children[0].children[1].children[0].src,'/manage/images/7?w=640');
 assert.equal(reference().children[1].children[1].children[0].src,'blob:photo');
 const best=()=>reference().children[0].children[2].textContent;
 assert.equal(best(),'Part');
 document.activeElement=new Element('input');document.events.keydown({key:'2'});assert.equal(best(),'Part');
 document.activeElement=new Element('button');document.events.keydown({key:'2'});assert.equal(best(),'Other');assert.equal(nodes.review.querySelector('[data-confirm]').disabled,true);
 const colourBlock=()=>nodes.review.children.find(n=>n.children[0]?.textContent==='Colour · you choose');
 const chips=()=>colourBlock().children[1].children[3];
 assert.equal(chips().className,'scan-colours');assert.equal(colourBlock().children[1].children[0].hidden,true);
 await chips().children[0].click();
 assert.equal(nodes.review.querySelector('[data-confirm]').disabled,false);assert.equal(nodes.review.querySelector('[data-confirm]').textContent,'Confirm · Synthetic blue ×1');
 const stepper=()=>nodes.review.children.find(n=>n.children[0]?.textContent==='Quantity').children[1];
 await stepper().children[2].click();assert.equal(nodes.review.querySelector('[data-confirm]').textContent,'Confirm · Synthetic blue ×2');
 await stepper().children[0].click();await stepper().children[0].click();assert.equal(stepper().children[1].value,1);
 prevented=false;document.events.keydown({key:'Enter',preventDefault(){prevented=true;}});assert.equal(prevented,false);
 document.activeElement=nodes.review;document.events.keydown({key:'Enter',preventDefault(){}});
 assert.match(text(nodes.queue),/Ready/);assert.match(text(nodes['results-list']),/Confirmed/);assert.equal(nodes['results-total'].textContent,1);assert.equal(nodes['queue-actions'].hidden,false);
 await groups.filter[2].click();assert.match(text(nodes.queue),/No pieces match/);assert.match(text(nodes.chips),/To review ×/);
 await groups.filter[0].click();assert.match(text(nodes.queue),/Part|Other/);
 nodes.search.value='zzz';await nodes.search.fire('input');assert.match(text(nodes.queue),/No pieces match/);nodes.search.value='';await nodes.search.fire('input');
 await groups.tab[1].click();assert.equal(groups.tab[1]['aria-pressed'],'true');
 await nodes.results.click();assert.equal(nodes.batch.open,true);assert.match(nodes['batch-title'].textContent,/Add 1 pieces to inventory/);
 assert.equal(nodes.save.textContent,'Add 1 to loose parts');
 await groups.dest[1].click();assert.equal(nodes['lot-fields'].hidden,false);assert.equal(nodes.save.disabled,true);assert.equal(nodes.save.textContent,'Add 1 to lot');
 await nodes.lot.click();assert.equal(nodes['lot-list'].hidden,false);
 await groups['lot-option'][0].click();assert.equal(nodes['lot-list'].hidden,true);assert.equal(nodes['lot-label'].textContent,'Pile A · Oct 2024 · 128 parts');assert.equal(nodes.save.textContent,'Add 1 to Pile A');assert.equal(nodes.save.disabled,false);
 await nodes['new-lot'].click();assert.equal(nodes['new-fields'].hidden,false);assert.equal(nodes['lot-existing'].hidden,true);assert.equal(nodes.save.textContent,'Create lot and add 1');assert.equal(nodes.save.disabled,true);
 nodes['lot-name'].value='Pile B';await nodes['lot-name'].fire('input');assert.equal(nodes.save.disabled,false);
 await groups['storage-option'][1].click();assert.equal(nodes['storage-label'].textContent,'Drawer 2');
 await nodes['new-lot'].click();assert.equal(nodes['new-fields'].hidden,true);
 await groups.condition[1].click();
 env.fail=true;await nodes.save.click();assert.equal(nodes.batch.open,true);assert.match(nodes['batch-error'].textContent,/Offline/);assert.equal(nodes['batch-error'].hidden,false);assert.equal(nodes.save.disabled,false);assert.equal(nodes.notice.dataset.kind,'error');
 env.errorMessage='This batch expired after an hour · identify the pieces again';await nodes.save.click();assert.equal(nodes['batch-error'].textContent,env.errorMessage);assert.equal(nodes.batch.open,true);
 document.events.keydown({key:'1'});assert.equal(best(),'Other');
 env.fail=false;await nodes.save.click();assert.equal(nodes.batch.open,false);assert.equal(nodes.total.textContent,0);assert.equal(nodes.undo.hidden,false);assert.equal(nodes.notice.dataset.kind,'success');
 const saved=JSON.parse(calls.find(c=>c.url.endsWith('/save')).options.body);assert.equal(saved.pieces[0].chosen.color_id,11);assert.equal(saved.pieces[0].chosen.item_no,'alternative');assert.equal(saved.keep_photos,true);assert.equal(saved.lot_id,'7');assert.equal(saved.condition,'N');assert.equal(saved.destination,'lot');
 await nodes.undo.click();assert.equal(nodes.undo.hidden,true);assert.equal(nodes.message.textContent,'Undone');
 env.detectFails=true;await nodes.file.fire('change');await tick();
 assert.match(text(nodes.review),/Not recognised/);assert.match(text(nodes.review),/Brickognize found no match/);assert.match(text(nodes.review),/Retake/);assert.match(text(nodes.queue),/Unidentified/);
 const retake=nodes.review.children.find(n=>n.textContent==='Retake');await retake.click();assert.equal(nodes.total.textContent,0);
 env.detectFails=false;await groups.endpoint[1].click();assert.equal(groups.endpoint[1]['aria-pressed'],'true');
 await nodes.file.fire('change');await tick();assert.equal(calls.filter(c=>c.url.endsWith('/detect')).pop().options.body.values.endpoint,'figs');
 for(let i=0;i<5;i++){await nodes.file.fire('change');await tick();}
 const before=calls.length;await nodes.file.fire('change');assert.equal(calls.length,before);assert.match(nodes.message.textContent,/Queue full/);
 await nodes['empty-queue'].click();assert.equal(nodes.total.textContent,0);assert.match(text(nodes.review),/Take a picture or add a saved photo to begin/);
 // A tile retry button is never nested inside a row button.
 await nodes.file.fire('change');await tick();
 const nested=n=>(n.children||[]).some(c=>c.tagName==='BUTTON'||nested(c));
 const row=nodes.queue.children[0].children[0];assert.equal(row.tagName,'BUTTON');assert.equal(nodes.queue.children[0].children[1].tagName,'BUTTON');
 const rowTile=row.children[0];rowTile.children[0].events.error();assert.match(text(rowTile),/Image did not load/);assert.equal(nested(row),false);
 document.activeElement=new Element('button');document.events.keydown({key:'2'});
 const altBlock=nodes.review.children.find(n=>n.children[0]?.textContent==='Other possibilities');
 const altRow=altBlock.children[1].children[3].children[0];altRow.children[0].children[0].events.error();assert.equal(nested(altRow),false);
 // Delete during a pending detect: the late result is dropped and nothing else is removed.
 let release;env.gate=new Promise(r=>{release=r;});
 const late=nodes.file.fire('change');assert.equal(nodes.total.textContent,2);
 const stale=nodes.review.children.find(n=>n.textContent==='Delete picture');await stale.click();assert.equal(nodes.total.textContent,1);
 assert.equal(nodes.capture.disabled,false);
 // The lock is free: a new detect starts before the first request resolves.
 const second=nodes.file.fire('change');assert.equal(nodes.total.textContent,2);assert.equal(nodes.capture.disabled,true);
 release();await late;await second;await tick();env.gate=null;
 assert.equal(nodes.total.textContent,2);assert.equal(nodes.capture.disabled,false);
 const findButton=(n,t)=>n.textContent===t&&n.tagName==='BUTTON'?n:(n.children||[]).map(c=>findButton(c,t)).find(Boolean);
 await findButton(nodes.review,'Delete picture').click();assert.equal(nodes.total.textContent,1);
 assert.equal(nodes.total.textContent,1);assert.doesNotMatch(text(nodes.review),/Piece 0 of 0/);assert.match(text(nodes.review),/Piece 1 of 1/);assert.equal(nodes.capture.disabled,false);
 await stale.click();assert.equal(nodes.total.textContent,1);
 // Empty queue during a pending detect.
 env.gate=new Promise(r=>{release=r;});const late2=nodes.file.fire('change');await nodes['empty-queue'].click();release();await late2;await tick();env.gate=null;
 assert.equal(nodes.total.textContent,0);assert.match(text(nodes.review),/Take a picture or add a saved photo to begin/);
}
async function cameraFlow(){
 let started=0;
 const navigator={mediaDevices:{enumerateDevices:async()=>[{kind:'videoinput',deviceId:'a',label:'Rear camera'},{kind:'videoinput',deviceId:'b',label:'Front camera'},{kind:'audioinput',deviceId:'c',label:'Mic'}],getUserMedia:async()=>{started++;return{active:true,getTracks:()=>[{stop(){}}]};},addEventListener(){}}};
 const {nodes}=setup(navigator);await tick();
 assert.equal(nodes['camera-label'].textContent,'Rear camera');assert.equal(nodes['camera-list'].children.length,2);assert.equal(nodes.capture.textContent,'Enable camera');
 await nodes.camera.click();assert.equal(nodes['camera-list'].hidden,false);assert.equal(nodes.camera['aria-expanded'],'true');
 await nodes['camera-list'].children[1].click();await tick();
 assert.equal(nodes['camera-list'].hidden,true);assert.equal(nodes['camera-label'].textContent,'Front camera');assert.equal(started,1);assert.equal(nodes.capture.textContent,'Take picture');
}
async function cameraErrorFlow(){
 let stopped=0,enumerations=0;
 const navigator={mediaDevices:{enumerateDevices:async()=>{if(++enumerations>1)throw Error('denied');return[{kind:'videoinput',deviceId:'a',label:'Rear camera'}];},getUserMedia:async()=>({active:true,getTracks:()=>[{stop(){stopped++;}}]}),addEventListener(){}}};
 const {nodes}=setup(navigator);await tick();
 await nodes.capture.click();
 assert.equal(stopped,1);assert.equal(nodes.capture.textContent,'Enable camera');assert.match(nodes.message.textContent,/No camera/);
}
async function overlappingStartFlow(){
 const streams=[];let enumerations=0,failFirst;
 const navigator={mediaDevices:{enumerateDevices:async()=>{enumerations++;if(enumerations===2)return new Promise((_,rej)=>{failFirst=rej;});return[{kind:'videoinput',deviceId:'a',label:'Rear camera'},{kind:'videoinput',deviceId:'b',label:'Front camera'}];},getUserMedia:async()=>{const s={stopped:0,active:true};s.getTracks=()=>[{stop(){s.stopped++;}}];streams.push(s);return s;},addEventListener(){}}};
 const {nodes}=setup(navigator);await tick();
 const first=nodes.capture.click();await tick();assert.equal(streams.length,1);
 await nodes['camera-list'].children[1].click();await tick();
 assert.equal(streams.length,2);assert.equal(streams[0].stopped>=1,true);assert.equal(nodes.capture.textContent,'Take picture');
 failFirst(Error('denied'));await first;await tick();
 assert.equal(streams[1].stopped,0);assert.equal(nodes.capture.textContent,'Take picture');assert.doesNotMatch(nodes.message.textContent,/allow camera access/);
}
const findButton=(n,t)=>n.textContent===t&&n.tagName==='BUTTON'?n:(n.children||[]).map(c=>findButton(c,t)).find(Boolean);
async function pick(ctx){ // detect a piece, choose the first colour, leave it unconfirmed
 const {nodes}=ctx;nodes.file.files=[{}];await nodes.file.fire('change');await tick();
 const block=nodes.review.children.find(n=>n.children[0]?.textContent==='Colour · you choose');await block.children[1].children[3].children[0].click();
}
const confirmPiece=async ctx=>{await ctx.nodes.review.querySelector('[data-confirm]').click();};
async function hardeningFlow(){
 // 1. Save works on a snapshot; Cancel and Escape are ignored while saving; late edits survive.
 let ctx=setup({}),{nodes,groups,document,env,window,root}=ctx;
 await pick(ctx);await confirmPiece(ctx);await pick(ctx);
 await nodes.results.click();assert.equal(nodes.batch.open,true);
 let release;env.saveGate=new Promise(r=>{release=r;});
 const saving=nodes.save.click();assert.equal(nodes.save.disabled,true);assert.equal(nodes.cancel.disabled,true);
 await nodes.cancel.click();assert.equal(nodes.batch.open,true);
 let prevented=false;nodes.batch.fire('cancel',{preventDefault(){prevented=true;}});assert.equal(prevented,true);
 const title=nodes['batch-title'].textContent;await nodes.results.click();assert.equal(nodes['batch-title'].textContent,title);
 // 3. A photo or Space during the save is refused with a message, not thrown away silently.
 const calls=env.calls.length;await nodes.file.fire('change');assert.match(nodes.message.textContent,/Saving the batch/);assert.equal(env.calls.length,calls);
 document.activeElement=new Element('body');document.events.keydown({code:'Space',preventDefault(){}});assert.match(nodes.message.textContent,/Saving the batch/);
 // Edits made while saving: confirm the second piece.
 const block=nodes.review.children.find(n=>n.children[0]?.textContent==='Colour · you choose');await block.children[1].children[3].children[0].click();await confirmPiece(ctx);
 release();await saving;await tick();env.saveGate=null;
 const sent=JSON.parse(env.calls.find(c=>c.url.endsWith('/save')).options.body);assert.equal(sent.pieces.length,1);
 assert.equal(nodes.total.textContent,1);assert.equal(nodes.batch.open,false);assert.equal(nodes['results-total'].textContent,1);
 // 9. A new lot is added to the list and the fields reset.
 await nodes.results.click();await groups.dest[1].click();await nodes['new-lot'].click();nodes['lot-name'].value='Pile B';nodes.note.value='n';await nodes['lot-name'].fire('input');await groups['storage-option'][1].click();
 await nodes.save.click();await tick();
 assert.equal(nodes['new-fields'].hidden,true);assert.equal(nodes['lot-name'].value,'');assert.equal(nodes.note.value,'');assert.equal(nodes['storage-label'].textContent,'No place');
 const added=nodes['lot-list'].children;assert.match(added[added.length-1].textContent,/Pile B · 2026-10-16 · 1 parts/);assert.equal(added[added.length-1].dataset.value,'new1');
 // 6. Undo is disabled while its request runs.
 env.undoGate=new Promise(r=>{release=r;});const u1=nodes.undo.click();assert.equal(nodes.undo.disabled,true);const n0=env.calls.length;await nodes.undo.click();assert.equal(env.calls.length,n0);
 release();await u1;assert.equal(nodes.undo.disabled,false);assert.equal(nodes.undo.hidden,true);env.undoGate=null;
 // 3. Save is allowed while a piece is recognising; recognising is refused with a message while one is pending.
 ctx=setup({});({nodes,groups,document,env,window,root}=ctx);
 await pick(ctx);await confirmPiece(ctx);
 env.gate=new Promise(r=>{release=r;});nodes.file.files=[{}];const pending=nodes.file.fire('change');
 await nodes.file.fire('change');assert.match(nodes.message.textContent,/Still identifying/);assert.equal(env.calls.filter(c=>c.url.endsWith('/detect')).length,2);
 await nodes.results.click();await nodes.save.click();await tick();assert.equal(env.calls.filter(c=>c.url.endsWith('/save')).length,1);
 release();await pending;await tick();env.gate=null;
 // 7. A finished recognition does not pull the user away from another piece or tab.
 ctx=setup({});({nodes,groups,document,env,window,root}=ctx);
 await pick(ctx);await confirmPiece(ctx);
 env.gate=new Promise(r=>{release=r;});nodes.file.files=[{}];let p2=nodes.file.fire('change');
 await nodes.queue.children[0].children[0].click();assert.match(text(nodes.review),/Piece 1 of 2/);
 release();await p2;await tick();env.gate=null;assert.match(text(nodes.review),/Piece 1 of 2/);
 env.gate=new Promise(r=>{release=r;});p2=nodes.file.fire('change');await groups.tab[1].click();assert.equal(root.dataset.view,'queue');
 release();await p2;await tick();env.gate=null;assert.equal(root.dataset.view,'queue');
 // 4. Digit keys: ignored when equal to the current choice and when the review is not visible.
 ctx=setup({});({nodes,groups,document,env,window,root}=ctx);
 await pick(ctx);await confirmPiece(ctx);assert.match(text(nodes.queue),/Ready/);
 document.activeElement=new Element('body');document.events.keydown({key:'1'});assert.match(text(nodes.queue),/Ready/);
 await groups.tab[1].click();document.events.keydown({key:'2'});assert.match(text(nodes.queue),/Ready/);
 window.matchMedia=()=>({matches:true});document.events.keydown({key:'2'});assert.doesNotMatch(text(nodes.queue),/Ready/);
 // 5. Typing a quantity does not rebuild the review, so the next Confirm click lands.
 ctx=setup({});({nodes,groups,document,env,window,root}=ctx);
 await pick(ctx);const confirmBefore=nodes.review.querySelector('[data-confirm]');
 const qtyInput=nodes.review.children.find(n=>n.children[0]?.textContent==='Quantity').children[1].children[1];qtyInput.value='3';await qtyInput.fire('change');
 assert.equal(nodes.review.querySelector('[data-confirm]'),confirmBefore);assert.match(confirmBefore.textContent,/×3/);
 await confirmBefore.click();assert.match(text(nodes.queue),/Ready/);
 // 10. Per-row delete sits outside the row button.
 await nodes.queue.children[0].children[1].click();assert.equal(nodes.total.textContent,0);
}
async function cameraRestoreFlow(){
 const streams=[];
 const navigator={mediaDevices:{enumerateDevices:async()=>[{kind:'videoinput',deviceId:'a',label:'Rear camera'},{kind:'videoinput',deviceId:'b',label:'Front camera'}],getUserMedia:async()=>{const s={stopped:0,active:true};s.getTracks=()=>[{stop(){s.stopped++;}}];s.getVideoTracks=()=>[{getSettings:()=>({deviceId:'b'})}];streams.push(s);return s;},addEventListener(){}}};
 const {nodes,window}=setup(navigator);await tick();
 await nodes.capture.click();await tick();
 // 8. The picker shows the camera the stream is actually using.
 assert.equal(nodes['camera-label'].textContent,'Front camera');assert.equal(nodes.capture.textContent,'Take picture');
 // 2. After a page-cache restore the stream is gone and the main button starts the camera again.
 window.events.pagehide();assert.equal(streams[0].stopped,1);assert.equal(nodes.capture.textContent,'Enable camera');
 await nodes.capture.click();await tick();assert.equal(streams.length,2);assert.equal(nodes.capture.textContent,'Take picture');
 streams[1].active=false;await nodes.capture.click();await tick();assert.equal(streams.length,3);
}
(async()=>{await hardeningFlow();await cameraRestoreFlow();await flow();await cameraFlow();await cameraErrorFlow();await overlappingStartFlow();console.log('Part to Inventory runtime passed');})().catch(e=>{console.error(e);process.exitCode=1;});
