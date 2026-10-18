const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
// CSS contract complements the migration-fixture rendered-HTML test. This is
// intentionally not a browser geometry check; ui-check remains the visual gate.
const planningCSS=fs.readFileSync('static/web/toni/bw-planning.css','utf8').replace(/\/\*[\s\S]*?\*\//g,'');
const [desktopCSS,phoneCSS]=planningCSS.split('@media(max-width:767.98px)');
function declarations(css,selector){
 const rule=[...css.matchAll(/([^{}]+)\{([^{}]*)\}/g)].find(m=>m[1].trim().split(/,\s*/).includes(selector));
 assert.ok(rule,`Missing layout rule: ${selector}`);
 return Object.fromEntries(rule[2].trim().split(';').filter(Boolean).map(d=>d.split(':').map(v=>v.trim())));
}
for(const selector of ['#bw-planning [hidden]','#bw-planning [data-bp-message]:empty','#bw-planning details:not([open]) > :not(summary)']){
 assert.equal(declarations(desktopCSS,selector).display,'none!important');
}
assert.doesNotMatch(planningCSS,/display\s*:\s*contents|(?:^|;)\s*order\s*:/);
assert.equal(declarations(desktopCSS,'.bp-wishlist')['grid-template-columns'],'repeat(5,minmax(0,1fr))');
assert.equal(declarations(phoneCSS,'.bp-wishlist')['grid-template-columns'],'repeat(2,minmax(0,1fr))');
assert.equal(declarations(desktopCSS,'.bp-identity .bc-picture').width,'56px');
assert.equal(declarations(desktopCSS,'.bp-ratio-track i').background,'var(--tw-accent)');
const collectionCSS=fs.readFileSync('static/web/toni/bw-collection.css','utf8');
assert.match(collectionCSS,/grid-template-columns:minmax\(0,1fr\) 44px 44px/);
assert.match(collectionCSS,/:is\(#bw-collection,#bw-planning,#bw-check-choices\) \.bc-toolbar button/);
const sharedCSS=fs.readFileSync('static/web/toni/toni.css','utf8');
const primary=declarations(sharedCSS,'button.bw-primary');
assert.equal(primary.background,'var(--tw-accent)');assert.equal(primary.color,'var(--bw-action-ink)');assert.equal(primary['min-height'],'var(--tw-hit-lg)');
class Node {
 constructor(){this.events={};this.dataset={};this.value='';this.hidden=false;this.disabled=false;this.textContent='';this.children=[];}
 addEventListener(name,fn){this.events[name]=fn;}
 querySelector(selector){return this.nodes?.[selector]||null;}
 querySelectorAll(selector){return this.groups?.[selector]||[];}
 append(n){this.children.push(n);}
 replaceChildren(){this.children=[];}
 setAttribute(k,v){this[k]=v;}
 focus(){this.focused=true;}
 async trigger(name='click',extra={}){return this.events[name]?.({preventDefault(){},target:{tagName:'BODY'},...extra});}
}
const message=new Node(),undo=new Node(),pin=new Node(),refresh=new Node(),archive=new Node(),search=new Node(),sort=new Node(),order=new Node(),panel=new Node(),toggle=new Node(),filterControl=new Node();
filterControl.dataset.bpFilter='type';filterControl.closest=()=>({firstChild:{textContent:'Type'}});filterControl.selectedOptions=[{textContent:'Parts'}];
search.closest=()=>null;sort.value='number';order.value='asc';panel.hidden=true;panel.nodes={'button, input, select':new Node()};
pin.dataset={bpPin:'copy',pinned:'false'};refresh.dataset.bpRefresh='["P","3004"]';archive.dataset.bpArchive='7';
const root=new Node();root.dataset={csrf:'token',screen:'prices',saveUrl:'/planning/action/ACTION',collectionUrl:'/collection/save/ACTION'};
const rows=[{type:'P',number:'3004',name:'Brick',colour:'Red',pinned:'0',rank:2,gap:4,cost:'12',max:'40',collection:['owned'],stale:'true'},{type:'S',number:'20',name:'Set',colour:'',pinned:'1',rank:4,gap:1,cost:'2',max:null,collection:['wanted'],stale:'false'}];
const nodes=rows.map(r=>{const n=new Node();n.nodes={'[data-bp-selected]':Object.assign(new Node(),{checked:false})};n.tagName='ARTICLE';n.closest=()=>n;n.dataset.record=JSON.stringify(r);return n;});
const count=new Node(),chips=new Node(),empty=new Node(),container=new Node();root.nodes={'[data-bp-search]':search,'[data-bp-sort]':sort,'[data-bp-order]':order,'#bp-filters':panel,'[data-bp-message]':message,'[data-bp-undo]':undo,'[data-bp-count]':count,'[data-bp-chips]':chips,'[data-bp-empty]':empty,'[data-bp-rows]':container};root.groups={'[data-bp-row]':nodes,'[data-bp-filter]':[filterControl],'[data-bp-filters]':[toggle],'[data-bp-pin]':[pin],'[data-bp-refresh]':[refresh],'[data-bp-archive]':[archive]};
const sortPanel=new Node(),sortToggle=new Node(),sortDone=new Node();sortPanel.hidden=true;sortPanel.nodes={'button, input, select':sort};
root.nodes['[data-bp-sort-panel]']=sortPanel;root.groups['[data-bp-sort-open]']=[sortToggle,sortDone];
const condition=new Node(),ownership=new Node();condition.dataset.bpFilter='condition';ownership.dataset.bpFilter='collection';
for(const [control,label] of [[condition,'Condition'],[ownership,'Collection']]){control.closest=()=>({firstChild:{textContent:label}});control.selectedOptions=[{textContent:label}];}
root.groups['[data-bp-filter]'].push(condition,ownership);
const picks=[['condition',''],['condition','used'],['condition','new'],['collection','owned']].map(([key,value])=>{const b=new Node();b.dataset={bpPick:key,value};return b;});root.groups['[data-bp-pick]']=picks;
const lookup=new Node(),lookupQuery=new Node(),jumpInput=new Node(),jumpDialog=new Node(),lookupButton=new Node();
lookup.nodes={button:lookupButton};root.nodes['[data-bp-lookup]']=lookup;root.nodes['[data-bp-lookup-query]']=lookupQuery;
const doc=new Node();doc.querySelector=()=>root;doc.getElementById=id=>id==='jump-query'?jumpInput:jumpDialog;doc.createElement=()=>new Node();
let calls=[],reloads=0,fail=false,confirmed=false;const saved={};
let opened=null;
const context={window:{adminShell:{open(dialog,button){opened={dialog,button};}},confirm:()=>confirmed},document:doc,sessionStorage:{getItem:k=>saved[k]||null,setItem:(k,v)=>saved[k]=v,removeItem:k=>delete saved[k]},URLSearchParams,location:{pathname:'/planning/wishlist',search:'',reload(){reloads++;}},fetch:async(url,options)=>{calls.push({url,data:JSON.parse(options.body)});return {ok:!fail,json:async()=>fail?{message:'Not saved · retry'}:{event_id:42,message:'Saved'}};}};
const exportButton=new Node();exportButton.disabled=true;exportButton.textContent='Export selected \u00b7 BrickLink XML';root.nodes['[data-bp-export]']=exportButton;
let checkedCount=0;Object.defineProperty(root.groups,'[data-bp-selected]:checked',{get:()=>[...nodes.filter(n=>n.querySelector('[data-bp-selected]').checked),...Array.from({length:checkedCount},()=>new Node())]});
doc.querySelector=selector=>selector==='#bw-planning'?root:null;
vm.runInNewContext(fs.readFileSync('static/web/toni/formatting.js','utf8')+fs.readFileSync('static/web/toni/bw-collection.js','utf8')+fs.readFileSync('static/web/toni/bw-planning.js','utf8'),context);
const api=context.window.BrickPlanning;
assert.equal(api.filter(rows,'red',{},'number').length,1);
assert.equal(api.filter(rows,'',{collection:'wanted'},'number')[0].number,'20');
assert.equal(api.filter(rows,'',{stale:'true'},'number')[0].number,'3004');
assert.equal(api.filter(rows,'',{},'rank')[0].number,'20');
assert.equal(api.filter(rows,'',{},'max',true)[0].number,'3004');
const under=[{type:'S',number:'1',name:'A',colour:'',under:'over',undermax:'30'},{type:'S',number:'2',name:'B',colour:'',under:'under',undermax:'-20'},{type:'S',number:'3',name:'C',colour:'',under:'differs',undermax:null},{type:'S',number:'4',name:'D',colour:'',under:'under',undermax:'-5'}];
assert.deepEqual(api.filter(under,'',{under:'under'},'undermax').map(r=>r.number),['2','4']);
assert.deepEqual(api.filter(under,'',{under:'differs'},'undermax').map(r=>r.number),['3']);
assert.deepEqual(api.filter(under,'',{},'undermax').map(r=>r.number),['2','4','1','3']);
assert.equal(api.filter(rows,'',{},'cost')[0].number,'20');
(async()=>{
 assert.equal(count.textContent,'2 results');
 assert.equal(picks[0]['aria-pressed'],'true');
 await picks[3].trigger();assert.equal(ownership.value,'owned');assert.equal(count.textContent,'1 result');assert.equal(picks[3]['aria-pressed'],'true');
 await chips.children[0].trigger();assert.equal(ownership.value,'');assert.equal(count.textContent,'2 results');
 condition.value='used';await condition.trigger('change');assert.equal(picks[1]['aria-pressed'],'true');
 await picks[2].trigger();assert.equal(condition.value,'new');await picks[0].trigger();assert.equal(condition.value,'');
 await sortToggle.trigger();assert.equal(sortPanel.hidden,false);assert.equal(sort.focused,true);
 await toggle.trigger();assert.equal(sortPanel.hidden,true);assert.equal(panel.hidden,false);
 const firstFocus=new Node(),lastFocus=new Node();firstFocus.getClientRects=lastFocus.getClientRects=()=>[{}];
 panel.groups={'button, input, select, a[href]':[firstFocus,lastFocus]};context.window.matchMedia=()=>({matches:true});
 doc.activeElement=lastFocus;await doc.trigger('keydown',{key:'Tab',target:{tagName:'BUTTON'}});assert.equal(firstFocus.focused,true);
 doc.activeElement=firstFocus;await doc.trigger('keydown',{key:'Tab',shiftKey:true,target:{tagName:'BUTTON'}});assert.equal(lastFocus.focused,true);
 await doc.trigger('keydown',{key:'Escape'});assert.equal(panel.hidden,true);assert.equal(toggle.focused,true);
 await sortToggle.trigger();await sortDone.trigger();assert.equal(sortPanel.hidden,true);assert.equal(sortToggle.focused,true);

 await doc.trigger('keydown',{key:'ArrowDown',target:nodes[1]});assert.equal(nodes[0].focused,true);
 const anchor=new Node();anchor.click=()=>anchor.clicked=true;nodes[0].nodes['.bp-identity a']=anchor;
 await doc.trigger('keydown',{key:'Enter',target:nodes[0]});assert.equal(anchor.clicked,true);
 nodes.forEach(n=>n.querySelector('[data-bp-selected]').checked=true);
 sort.value='cost';await sort.trigger('change');assert.ok(nodes.every(n=>n.querySelector('[data-bp-selected]').checked));
 search.value='red';await search.trigger('input');
 assert.equal(nodes[0].querySelector('[data-bp-selected]').checked,true);assert.equal(nodes[1].querySelector('[data-bp-selected]').checked,false);assert.equal(count.textContent,'1 result');assert.equal(nodes[1].hidden,true);assert.equal(chips.children.length,1);
 // Review 1: rows filtered away are unticked and the export button follows.
 assert.equal(exportButton.disabled,false);assert.equal(exportButton.textContent,'Export 1 \u00b7 BrickLink XML');
 await chips.children[0].trigger();assert.equal(count.textContent,'2 results');
 await toggle.trigger();assert.equal(panel.hidden,false);await doc.trigger('keydown',{key:'Escape'});assert.equal(panel.hidden,true);assert.equal(toggle.focused,true);
 fail=true;await pin.trigger();assert.equal(message.textContent,'Not saved · retry');assert.equal(pin.disabled,false);assert.equal(reloads,0);
 fail=false;await pin.trigger();assert.equal(calls[1].data.csrf_token,'token');assert.equal(calls[1].data.pinned,true);assert.equal(undo.hidden,false);assert.equal(reloads,1);
 await undo.trigger();assert.equal(calls[2].url,'/planning/action/undo');assert.equal(calls[2].data.event_id,42);assert.equal(reloads,2);
 // P3: Export is disabled until a row is selected and names the count.
 nodes.forEach(n=>n.querySelector('[data-bp-selected]').checked=false);await root.trigger('change',{target:{matches:s=>s==='[data-bp-selected]'}});
 assert.equal(exportButton.disabled,true);assert.equal(exportButton.textContent,'Export selected \u00b7 BrickLink XML');
 checkedCount=3;await root.trigger('change',{target:{matches:s=>s==='[data-bp-selected]'}});
 assert.equal(exportButton.disabled,false);assert.equal(exportButton.textContent,'Export 3 \u00b7 BrickLink XML');
 checkedCount=0;await root.trigger('change',{target:{matches:s=>s==='[data-bp-selected]'}});
 assert.equal(exportButton.disabled,true);assert.equal(exportButton.textContent,'Export selected \u00b7 BrickLink XML');
 // Review 1: tick one row, filter it away, the button is disabled again.
 nodes.forEach(n=>n.querySelector('[data-bp-selected]').checked=false);nodes[1].querySelector('[data-bp-selected]').checked=true;
 search.value='red';await search.trigger('input');
 assert.equal(nodes[1].querySelector('[data-bp-selected]').checked,false);assert.equal(exportButton.disabled,true);assert.equal(exportButton.textContent,'Export selected \u00b7 BrickLink XML');
 search.value='';await search.trigger('input');
 await archive.trigger();assert.equal(calls.length,3);confirmed=true;await archive.trigger();await new Promise(setImmediate);assert.equal(calls[3].url,'/collection/save/archive');assert.equal(calls[3].data.ids[0],7);
// The same switch and session key used by Collection preserve other list state.
const grid=new Node(),listView=new Node();grid.dataset.bpView='grid';listView.dataset.bpView='list';
root.groups['[data-bp-view]']=[grid,listView];container.dataset.view='grid';
const viewKey=context.window.BrickCollection.listStateKey();
saved[viewKey]=JSON.stringify({view:'list',query:'preserved'});
context.window.BrickCollection.viewSwitch(root,container,'bp',viewKey);
assert.equal(container.dataset.view,'list');assert.equal(listView['aria-pressed'],'true');
grid.trigger();assert.equal(container.dataset.view,'grid');assert.equal(grid['aria-pressed'],'true');
assert.equal(JSON.parse(saved[viewKey]).query,'preserved');
assert.equal(JSON.parse(saved[viewKey]).view,'grid');
root.dataset.screen='wishlist';search.trigger('input');assert.equal(count.textContent,'2 items');
filterControl.value='S';search.trigger('input');assert.equal(count.textContent,'1 items');
filterControl.value='';search.value='no match';await search.trigger('input');assert.equal(count.textContent,'0 items');
// Missing Collection must not stop wishlist initialization, search or actions.
context.window.BrickCollection=undefined;
vm.runInNewContext(fs.readFileSync('static/web/toni/bw-planning.js','utf8'),context);
assert.equal(count.textContent,'0 items');assert.equal(empty.hidden,false);
search.value='red';await search.trigger('input');assert.equal(count.textContent,'1 items');
const beforeAction=calls.length;await pin.trigger();assert.equal(calls.length,beforeAction+1);
// The full record list owns the noun, including empty and set-only wishlists.
root.groups['[data-bp-row]']=[];search.value='';
vm.runInNewContext(fs.readFileSync('static/web/toni/bw-planning.js','utf8'),context);
assert.equal(count.textContent,'0 items');assert.equal(empty.hidden,false);
root.groups['[data-bp-row]']=[nodes[1]];
vm.runInNewContext(fs.readFileSync('static/web/toni/bw-planning.js','utf8'),context);
assert.equal(count.textContent,'1 sets');search.value='no match';await search.trigger('input');assert.equal(count.textContent,'0 sets');
 console.log('Brick Work Planning runtime passed');
})().catch(e=>{console.error(e);process.exitCode=1;});
