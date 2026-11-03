/* The page controller runs against a minimal DOM and mocked HTTP/socket seams. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
class Element {
 constructor(tag='div') {this.tagName=tag.toUpperCase();this.children=[];this.events={};this.style={};this.dataset={};this.value='';this.hidden=false;this.checked=false;this.disabled=false;this.attributes={};this.files=[];this.textContent='';}
 append(...children) {this.children.push(...children);}
 prepend(...children) {this.children.unshift(...children);}
 replaceChildren(...children) {this.children=[...children];}
 replaceWith() {}
 setAttribute(k,v) {this.attributes[k]=v;}
 removeAttribute(k) {delete this.attributes[k];}
 addEventListener(k,fn) {(this.events[k] ||= []).push(fn);}
 focus() {document.activeElement=this;}
 showModal() {this.open=true;}
 close() {this.open=false;(this.events.close || []).forEach(fn=>fn());}
 querySelector(selector) {if(selector==='h2')return this.heading ||= new Element('h2');if(selector==='.bw-import-progress')return this.progress ||= new Element();return this.children.find(c=>c.tagName===selector.toUpperCase()) || new Element();}
 async trigger(event='click') {const args={key:'',preventDefault(){}};for(const fn of this.events[event] || [])await fn(args);await flush();}
}
const names=['wishlist-target','map-wanted','candidate-search','candidate-filter','candidate-sort','candidate-chips','candidate-count','unresolved-search','unresolved-filter','unresolved-sort','unresolved-chips','unresolved-count','colour-dialog','colour-search','colour-filter','colour-sort','colour-count','colour-list','colour-chips','colour-close','message','queued','review','search','sort','results','result-count','chips','review-rows','review-search','review-filter','review-sort','review-count','review-chips','confirm','intake','candidates','candidate-list','review-panel','unresolved','unresolved-list','paste','file','photo','keep','jobs','job-list','overall','progress-template','undo','back','again','review-clear'];
const nodes=Object.fromEntries(names.map(n=>[n,new Element(n.includes('search')?'input':'div')]));
nodes['wishlist-target'].value='gifts';nodes['map-wanted'].checked=true;nodes.sort.value='number';nodes['candidate-sort'].value='score';nodes['unresolved-sort'].value='number';nodes['review-sort'].value='number';nodes['progress-template'].content={cloneNode(){return new Element();}};
const radios={type:['set','minifigure','part','instructions','box','gear','book','catalog'],where:['owned','loose','wishlist'],mode:['search','paste','file','photo']};
const groups=Object.fromEntries(Object.entries(radios).map(([k,list])=>[k,list.map((v,i)=>Object.assign(new Element('input'),{value:v,checked:i===0}))]));
const root=new Element();root.dataset={wishlists:JSON.stringify([{id:'default',name:'Wishlist'},{id:'gifts',name:'Gifts'}]),url:'/manage/add',csrf:'csrf',colours:JSON.stringify([{color_id:11,name:'Synthetic blue',rgb:'ABCDEF'}]),socketPath:'/socket.io',socketNamespace:'/test'};
root.querySelector=s=>{
 const data=s.match(/^\[data-([^\]]+)\]$/);if(data)return nodes[data[1]];
 const radio=s.match(/input\[name=["']?(\w+)["']?\](?::checked|\[value=([^\]]+)\])/);if(radio)return radio[2]?groups[radio[1]].find(r=>r.value===radio[2]):groups[radio[1]].find(r=>r.checked);
 throw Error('Unknown selector '+s);
};
root.querySelectorAll=s=>{const m=s.match(/input\[name=(\w+)\]/);if(m)return groups[m[1]];return [];};
const document={querySelector:s=>s==='#bw-add'?root:null,createElement:tag=>new Element(tag),activeElement:new Element('body'),addEventListener(){}};
const window={addEventListener(){}};
let searchCount=1, requests=[], responseMode='search', confirmCalls=0, retryCalls=0;
const item={item_id:7,kind:'set',number:'123-1',label:'123-1',name:'Synthetic <set>',type_name:'Set',quantity:1,where:'owned',condition:'used',completeness:'',decision:'',owned:0,wished:false,color_id:null};
const unknown={item_id:null,unknown:true,kind:'set',number:'99999-9',label:'99999-9',name:'99999-9',type_name:'Set',quantity:1,where:'owned',condition:'used',completeness:'',decision:'',owned:0,wished:false,color_id:null,offers:{unidentified:true,fetch:{available:false,why:'Add a Rebrickable key in Tools & Admin first'},help:'Not in the catalogue · add a key'}};
const flush=()=>new Promise(resolve=>setImmediate(resolve));
const fetch=async(url,opts={})=>{
 const body=opts.body?JSON.parse(opts.body):null;requests.push({url,body});
 if(url.includes('/search?'))return {ok:true,json:async()=>({count:searchCount,items:[{...item}]})};
 if(url.endsWith('/review'))return {ok:true,json:async()=>({token:'signed-review',items:responseMode==='unknown'?[{...unknown}]:[{...item,score:.9}],unresolved:[],candidates:responseMode==='photo'})};
 if(url.endsWith('/confirm')){confirmCalls++;return {ok:true,json:async()=>({batch:'batch',receipts:[{job_id:42,label:item.label,name:item.name}]})};}
 if(url.endsWith('/retry')){retryCalls++;return {ok:true,json:async()=>({})};}
 if(url.endsWith('/undo'))return {ok:true,json:async()=>({message:'Undone'})};
 if(url.includes('/jobs/'))return {ok:true,json:async()=>({events:[{job_id:42,step:null,state:'done',completed_steps:6,total_steps:6,message:'Import complete'}]})};
 throw Error('Unexpected request '+url);
};
window.BrickImportProgress=class {constructor(root,channel,opts){Object.assign(this,{root,channel,...opts});this.syncButton=()=>{};channel.on('import_progress',()=>{});}destroy(){}};
const context={window,document,navigator:{onLine:true},fetch,URLSearchParams,FormData:class{},setTimeout,clearTimeout,setInterval:()=>1,clearInterval,location:{}};
vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../static/web/toni/formatting.js'),'utf8'),context);
vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../static/web/toni/bw-add.js'),'utf8'),context);
(async()=>{
 await flush();
 // P4: an empty search shows no catalogue list and makes no search request.
 assert.equal(requests.filter(r=>r.url.includes('/search?')).length,0);assert.equal(nodes.results.children.length,0);
 nodes.search.value='castle';await nodes.search.trigger('input');await new Promise(r=>setTimeout(r,200));await flush();
 assert.ok(requests.at(-1).url.includes('q=castle'));assert.equal(nodes.results.children.length,1);
 nodes.search.value='';await nodes.search.trigger('input');await new Promise(r=>setTimeout(r,200));await flush();
 assert.equal(nodes.results.children.length,0);assert.equal(nodes.chips.children.length,0);
 nodes.search.value='castle';await nodes.search.trigger('input');await new Promise(r=>setTimeout(r,200));await flush();
 groups.type[0].checked=false;groups.type[1].checked=true;await groups.type[1].trigger('change');
 assert.ok(requests.at(-1).url.includes('type=minifigure'));
 await nodes.chips.children.at(-1).trigger();
 assert.ok(requests.at(-1).url.includes('type=set'));
 assert.equal(window.BrickAdd.words(1),'1 item');assert.equal(window.BrickAdd.words(3),'3 items');assert.equal(window.BrickAdd.ink('FFFFFF'),'#1A1816');assert.equal(window.BrickAdd.ink('000000'),'#FAFAF8');
 assert.equal(window.BrickAdd.filterRows([item,{...item,number:'200',label:'200',name:'Other',owned:1}],'','duplicates','number').length,1);
 searchCount=400;await nodes.chips.children.at(-1).trigger();
 assert.equal(nodes['result-count'].hidden,false);assert.equal(nodes['result-count'].textContent,'First 1 of 400 results');
 searchCount=1;await nodes.chips.children.at(-1).trigger();assert.equal(nodes['result-count'].hidden,true);
 assert.equal(confirmCalls,0);
 const result=nodes.results.children[0];assert.equal(result.children[1].children[1].textContent,'Synthetic\u00a0<set>'); // Text, never HTML; last words kept together.
 // Select is a toggle that only marks the item for review (Ulf, 2026-10-28: "Add to list" read as adding to the collection).
 const select=result.children.at(-1);assert.equal(select.textContent,'Select');assert.equal(nodes.review.disabled,true);assert.equal(nodes.queued.textContent,'Nothing selected yet');
 await select.trigger();assert.equal(select.textContent,'Selected');assert.equal(select.attributes['aria-pressed'],'true');assert.equal(nodes.queued.textContent,'1 selected');
 await select.trigger();assert.equal(select.textContent,'Select');assert.equal(nodes.review.textContent,'Review 0 items');assert.equal(nodes.review.disabled,true);
 await select.trigger();assert.equal(nodes.review.textContent,'Review 1 item');assert.equal(nodes.review.disabled,false);
 await nodes.review.trigger();assert.equal(confirmCalls,0);assert.equal(nodes['review-panel'].hidden,false);assert.equal(nodes['review-rows'].children.length,1);
 assert.equal(nodes.confirm.textContent,'Add 1 item to the collection');
 // Filtering the view keeps the proposal; confirm still includes all reviewed rows.
 nodes['review-search'].value='no match';await nodes['review-search'].trigger('input');assert.equal(nodes['review-rows'].children.length,0);
 await nodes.confirm.trigger();assert.equal(confirmCalls,1);const sent=requests.find(r=>r.url.endsWith('/confirm')).body;assert.equal(sent.token,'signed-review');assert.equal(sent.items.length,1);assert.equal(sent.csrf_token,'csrf');assert.equal(nodes.jobs.hidden,false);
 await nodes.undo.trigger();assert.equal(nodes.message.textContent,'Undone');
 // An unknown number shows both offers and is not added until one is chosen; nothing is auto-chosen.
 await nodes.back.trigger();responseMode='unknown';nodes['review-search'].value='';await nodes.review.trigger();assert.equal(nodes['review-panel'].hidden,false);assert.equal(confirmCalls,1);
 let row=nodes['review-rows'].children[0].children;let choice=row.at(-1);assert.ok(choice.children[0].textContent.startsWith('Not in the catalogue'));
 const chipBox=choice.children.at(-1);assert.deepEqual(chipBox.children.map(b=>b.children[0].textContent),['Fetch from Rebrickable','Add as unidentified','Skip']);
 assert.equal(chipBox.children[0].disabled,true);assert.equal(chipBox.children[0].children[1].textContent,'needs a Rebrickable key');assert.equal(nodes.confirm.disabled,true);
 await chipBox.children[1].trigger();assert.equal(chipBox.children[1].attributes['aria-pressed'],'true');assert.equal(nodes.confirm.disabled,false);
 await nodes.confirm.trigger();assert.equal(confirmCalls,2);assert.equal(requests.filter(r=>r.url.endsWith('/confirm')).at(-1).body.items[0].decision,'unidentified');
 // A photo offers candidates and none is auto-accepted, even when there is only one; the choice and Keep photo travel with the confirm.
 await nodes.back.trigger();responseMode='photo';await nodes.review.trigger();assert.equal(nodes.candidates.hidden,false);assert.equal(confirmCalls,2);
 await nodes['candidate-list'].children[0].children.at(-1).trigger();assert.equal(nodes['review-panel'].hidden,false);assert.equal(confirmCalls,2);
 nodes.keep.checked=true;await nodes.confirm.trigger();assert.equal(confirmCalls,3);const photoSent=requests.filter(r=>r.url.endsWith('/confirm')).at(-1).body;assert.equal(photoSent.candidate,0);assert.equal(photoSent.keep_photo,true);
 responseMode='search';nodes['review-search'].value='';item.kind='part';item.type_name='Part';item.name='Synthetic part';item.where='wishlist';item.wished_colors=[11];
 await nodes.review.trigger();const identity=nodes['review-rows'].children[0].children[0].children[0];await identity.children.at(-1).trigger();assert.equal(nodes['colour-dialog'].open,true);assert.equal(nodes['colour-list'].children.length,1);
 const colour=nodes['colour-list'].children[0];assert.equal(colour.textContent,'Synthetic blue');assert.equal(colour.style.background,'#ABCDEF');await colour.trigger();assert.equal(nodes['colour-dialog'].open,false);const choices=nodes['review-rows'].children[0].children.at(-1);assert.ok(choices.children[0].textContent.includes('Already on Wishlist'));assert.equal(choices.children.at(-1).children[1].textContent,'Add to the wished quantity');assert.equal(nodes.confirm.disabled,true);assert.equal(nodes.confirm.textContent,'1 needs a choice');
 const wishChoice=choices.children.at(-1);wishChoice.value='another';await wishChoice.trigger('change');assert.equal(nodes.confirm.disabled,false);assert.equal(nodes.confirm.textContent,'Add 1 item to the wishlist');await nodes.confirm.trigger();assert.equal(requests.filter(r=>r.url.endsWith('/confirm')).at(-1).body.items[0].color_id,11);
 // Changing lists recomputes duplicates in the preview; Any survives confirmation.
 item.list_id='default';item.color_id=11;item.condition='any';item.wished_by_list={default:[11]};
 await nodes.review.trigger();
 let cells=nodes['review-rows'].children[0].children;
 assert.ok(cells.at(-1).children[0].textContent.includes('Already on Wishlist'));
 const listChoice=cells[3].children[1];listChoice.value='gifts';await listChoice.trigger('change');
 cells=nodes['review-rows'].children[0].children;assert.equal(cells.at(-1).children.length,1);
 await nodes.confirm.trigger();const listSent=requests.filter(r=>r.url.endsWith('/confirm')).at(-1).body.items[0];assert.equal(listSent.list_id,'gifts');assert.equal(listSent.condition,'any');
 assert.equal(requests.filter(r=>r.url.endsWith('/review')).at(-1).body.list_id,'gifts');
 // Wishlist links open a prefilled paste intake without starting a search or a write.
 groups.mode.forEach(r=>r.checked=r.value==='paste');nodes.paste.value='bl-figure';
 const modePanels=['search','paste','file','photo'].map(mode=>Object.assign(new Element(),{dataset:{mode}}));
 const queryAll=root.querySelectorAll;root.querySelectorAll=s=>s==='[data-mode]'?modePanels:queryAll(s);
 const beforePrefill=requests.length;
 vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../static/web/toni/bw-add.js'),'utf8'),context);
 assert.equal(nodes.review.textContent,'Review 1 item');
 assert.deepEqual(modePanels.map(p=>p.hidden),[true,false,true,true]);
 assert.equal(requests.length,beforePrefill);
 console.log('Brick Work Add runtime: review guard, safe identity text, filters, the unknown-number offers, explicit photo choice, confirm and Undo passed');
})().catch(error=>{console.error(error);process.exitCode=1;});
