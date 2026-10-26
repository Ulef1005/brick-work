// UI-lists: set card layout (kit 1c), Parts table cells (7a), By lot grouping, quick chips, group-by picks, select switch (12i).
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
class Node {
 constructor(){this.events={};this.attrs={};this.dataset={};this.nodes={};this.groups={};this.children=[];this.value='';this.hidden=false;this.disabled=false;this.textContent='';this.style={};this.options=[];this.tagName='DIV';this.className='';}
 addEventListener(n,f){this.events[n]=f;}
 matches(s){return s.split(',').some(selector=>{const m=selector.match(/^\[data-([a-z-]+)\]$/);return m?Object.hasOwn(this.dataset,m[1].replace(/-([a-z])/g,(_,c)=>c.toUpperCase())):selector.startsWith('.')?this.className.split(' ').includes(selector.slice(1)):this.tagName===selector.toUpperCase();});}
 querySelector(s){return this.nodes[s]||this.querySelectorAll(s)[0]||null;}
 querySelectorAll(s){return this.groups[s]||this.children.flatMap(n=>[...(n.matches(s)?[n]:[]),...n.querySelectorAll(s)]);}
 closest(s){return this.matches(s)?this:this.parentElement?.closest(s);}
 append(...nodes){for(const n of nodes){n.parentElement=this;this.children=this.children.filter(c=>c!==n);this.children.push(n);if(n.tagName==='OPTION')this.options.push(n);}}
 replaceChildren(...nodes){this.children=[];this.options=[];this.append(...nodes);}
 setAttribute(k,v){this.attrs[k]=String(v);}
 getAttribute(k){return Object.hasOwn(this.attrs,k)?this.attrs[k]:null;}
 removeAttribute(k){delete this.attrs[k];}
 get selectedIndex(){return this.options.findIndex(o=>o.value===this.value);}
 hasAttribute(k){return k==='data-bc-main';}
 remove(){this.removed=true;if(this.parentElement)this.parentElement.children=this.parentElement.children.filter(n=>n!==this);this.parentElement=null;}
 focus(){}
 after(n){this.afterNode=n;n.parentElement=this.parentElement;}
 async trigger(n='click',extra={}){return this.events[n]?.({preventDefault(){},currentTarget:this,target:this,...extra});}
}
const texts=node=>[node.textContent,...node.children.flatMap(texts)].filter(Boolean);
function load(records,{kind='P',pageSize=15,defaultGroup='',groupOptions=null,saved=null,detail=false}={}){
 const list=new Node(),container=new Node(),search=new Node(),sort=new Node(),direction=new Node(),group=new Node(),source=new Node(),count=new Node();
 sort.value='number';direction.value='asc';
 list.dataset.bcPageSize=String(pageSize);if(defaultGroup)list.dataset.bcDefaultGroup=defaultGroup;
 const defaults={type:kind,quantity:1,entity:'stock',ids:['x'],condition:['used'],status:[''],storage:['null'],place:['null'],flags:[],lot:['null'],lot_links:[],tags:[]};
 const full=records.map((r,i)=>({...defaults,number:'n'+String(i).padStart(3,'0'),name:'Name '+i,...r}));
 const fields=[...new Set(full.flatMap(Object.keys))];
 source.textContent=JSON.stringify({fields,rows:full.map(r=>Object.fromEntries(fields.flatMap((k,i)=>r[k]===undefined?[]:[[i,r[k]]])))});
 const control=(name,options)=>{const c=new Node();c.dataset.bcFilter=name;c.parentElement={firstChild:{textContent:name}};c.options=options.map(o=>({value:o,textContent:o||'All'}));return c;};
 const problem=control('problem',['','damaged','missing']),lot=control('lot',['','any','null','lot-1','lot-2']);
 lot.options=[{value:'',textContent:'All'},{value:'any',textContent:'In a lot'},{value:'null',textContent:'No lot'},{value:'lot-1',textContent:'Lot 1'},{value:'lot-2',textContent:'Lot 2'}];
 const picks=['','lot'].map(v=>{const b=new Node();b.tagName='BUTTON';b.dataset.bcGroupPick=v;return b;});
 const quick=[['',''],['problem:damaged',''],['lot:any',''],['lot:null','']].map(([v])=>{const b=new Node();b.tagName='BUTTON';b.dataset.bcQuick=v;return b;});
 const apply=new Node(),toggle=new Node(),cancel=new Node(),bar=new Node();toggle.setAttribute('role','switch');toggle.dataset.bcSelect='';cancel.dataset.bcSelect='';
 list.nodes={'[data-bc-rows]':container,'[data-bc-records]':source,'[data-bc-search]':search,'[data-bc-sort]':sort,'[data-bc-direction]':direction,'[data-bc-count]':count,'[data-bc-group]':group,'[data-bc-apply]':apply,'[data-bc-selection-bar]':bar};
 list.groups={'[data-bc-filter]':[problem,lot],'[data-bc-group-pick]':picks,'[data-bc-quick]':quick,'[data-bc-select]':[toggle,cancel]};
 const root=new Node();root.dataset={bcCollectionList:'',saveUrl:'/x/ACTION',csrf:'c',type:kind,editable:'true',itemBase:'/i/0',imageBase:'/img/0',lotBase:'/lots/LOT',wishBase:'/w/0',unresolvedUrl:'/u'};root.groups={'[data-bc-list]':[list]};if(detail)delete root.dataset.bcCollectionList;
 const doc=new Node();doc.querySelector=s=>s==='#bw-collection'?root:null;doc.createElement=tag=>{const n=new Node();n.tagName=tag.toUpperCase();return n;};
 const stored=new Map();if(saved)stored.set('bw-collection-list:/collection/'+kind+':0',JSON.stringify(saved));
 const basis=new Node();root.nodes['[data-bc-price-basis]']=basis;if(groupOptions)group.options=groupOptions.map(value=>({value}));
 const context={window:{addEventListener(){},scrollY:0,scrollTo(){},history:{replaceState(){}}},document:doc,sessionStorage:{getItem:k=>stored.get(k)||null,setItem:(k,v)=>stored.set(k,v),removeItem:k=>stored.delete(k)},location:{pathname:'/collection/'+kind,search:'',reload(){}},URLSearchParams,requestAnimationFrame:f=>f(),fetch:async()=>({})};
 vm.runInNewContext(fs.readFileSync('static/web/toni/images.js','utf8'),context);
 vm.runInNewContext(fs.readFileSync('static/web/toni/formatting.js','utf8')+fs.readFileSync('static/web/toni/bw-collection.js','utf8'),context);
 return {basis,container,group,picks,quick,problem,lot,count,apply,toggle,cancel,bar,root,api:context.window.BrickCollection,rows:()=>container.querySelectorAll('[data-bc-row]'),headings:()=>container.querySelectorAll('[data-bc-group-heading]')};
}
(async()=>{
 // Kit 1c set card: subline "theme / sub-theme · year", pill left and price right, gap count and date below, tags last.
 const {api,root}=load([{}],{kind:'S'});
 const set=api.decodeRecords({fields:['type','number','name','theme','subtheme','year','entity','ids','status','quantity','price','defects','tags','lot_links','flags'],rows:[{0:'S',1:'6080-1',2:"King's Castle",3:'Castle',4:'Lion Knights',5:1984,6:'copy',7:['c1'],8:['',''],9:2,10:['EUR','189.00','2026-10-08',true,'€189.00','8 Oct'],11:'5 missing',12:['Display','Gift'],13:[],14:[]}]})[0];
 const card=api.buildRow(set,root.dataset,false,()=>{});
 assert.ok(texts(card).includes('Castle / Lion Knights · 1984'),'theme and sub-theme precede the year');
 const foot=card.querySelector('.bc-card-foot'),main=foot.children[0],sub=foot.children[1],tags=foot.children[2];
 assert.equal(main.className,'bc-foot-main');assert.deepEqual(texts(main),['Not checked','€189.00']);
 assert.ok(texts(card).every(t=>t!=='Unknown'),'one label for the unknown state');
 assert.equal(main.children[0].children.length,1,'identical unknown statuses collapse into one pill');
 assert.equal(main.children[0].children[0].className,'bc-status unknown');
 assert.equal(sub.className,'bc-foot-sub');assert.deepEqual(texts(sub),['2 copies · 5 missing','8 Oct · stale']);
 assert.equal(tags.className,'bc-tags');assert.deepEqual(tags.children.map(t=>t.textContent),['Display','Gift']);
 const bare=api.buildRow(api.decodeRecords({fields:['type','number','year','entity','ids','status'],rows:[{0:'S',1:'x-1',2:1973,3:'copy',4:['c'],5:['incomplete']}]})[0],root.dataset,false,()=>{});
 assert.ok(texts(bare).includes('1973'));assert.ok(texts(bare).includes('no sales'));assert.equal(bare.querySelector('.bc-tags'),null);
 // Wishes keep the plain foot and never take a sub-theme.
 // Parts table cells (kit 7a).
 const P=load([{}],{kind:'P'});
 const part=P.api.decodeRecords({fields:['type','number','name','colour','quantity','damaged','missing','in_sets','lot_links','price','entity','ids'],rows:[{0:'P',1:'3004',2:'Brick 1 x 2',3:'Black',4:30,5:2,6:1,7:4,8:[['lot-1','Lot 1']],9:['EUR','0.08','2026-10-08',false,'€0.08','8 Oct'],10:'stock',11:['s']}]})[0];
 const row=P.api.buildRow(part,P.root.dataset,false,()=>{});
 const cells=row.children.filter(c=>c.className.split(' ').includes('bc-cell'));
 assert.equal(cells.length,4);
 assert.deepEqual(cells.map(c=>c.className.split(' ')[1]),['bc-cell-damaged','bc-cell-lot','bc-cell-price','bc-cell-qty']);
 assert.deepEqual(texts(cells[0]),['Damaged or missing ','2 damaged','1 missing']);assert.deepEqual(texts(cells[1]),['Lot ','Lot 1']);
 assert.equal(cells[1].children[1].href,'/lots/lot-1');
 assert.deepEqual(texts(cells[2]),['Used price ','€0.08','8 Oct']);assert.deepEqual(texts(cells[3]),['Quantity ','×30','4 in sets']);
 assert.equal(row.querySelector('.bc-identity-top').children[0].textContent,'Black');
 const loose=P.api.buildRow(P.api.decodeRecords({fields:['type','number','quantity','entity','ids'],rows:[{0:'P',1:'x',2:3,3:'stock',4:['s']}]})[0],P.root.dataset,false,()=>{});
 assert.deepEqual(loose.children.filter(c=>c.className.split(' ').includes('bc-cell')).map(texts).map(t=>t.join(' ')),['No damaged pieces','No lot —','Used price  no sales','Quantity  ×3']);
 // Filters: lot "any" and groupValue.
 const rows=[{number:'a',lot:['null']},{number:'b',lot:['lot-1']},{number:'c',lot:['null','lot-2']}];
 assert.deepEqual(api.filterRows(rows,'',{lot:'any'}).map(r=>r.number),['b','c']);
 assert.deepEqual(api.filterRows(rows,'',{lot:'null'}).map(r=>r.number),['a','c']);
 assert.equal(api.groupValue({lot:['null','lot-2']},'lot'),'lot-2');assert.equal(api.groupValue({lot:['null']},'lot'),'null');assert.equal(api.groupValue({lot:[]},'lot'),'');
 assert.deepEqual(api.filterRows(rows,'',{},'number','asc','lot').map(r=>r.number),['b','c','a'],'lots sort by name, rows without a lot last');
 // By lot grouping with counts, Open links and the Flat toggle.
 const parts=[...Array.from({length:3},(_,i)=>({lot:['lot-1'],lot_links:[['lot-1','Lot 1']],damaged:i?0:1})),{lot:['lot-2'],lot_links:[['lot-2','Lot 2']]},{},{}];
 const h=load(parts,{defaultGroup:'lot'});
 assert.equal(h.group.value,'lot','default grouping is By lot');
 const heads=h.headings();assert.deepEqual(heads.map(x=>x.textContent),['Lot 1','Lot 2','No lot']);
 assert.deepEqual(heads.map(x=>x.children[0].textContent),[' · 3 parts',' · 1 part',' · 2 parts']);
 assert.equal(heads[0].children[1].href,'/lots/lot-1');assert.equal(heads[0].children[1].getAttribute('aria-label'),'Open lot Lot 1');assert.equal(heads[2].children.length,1,'no Open link without a lot');
 assert.equal(h.picks[0].getAttribute('aria-pressed'),'false');assert.equal(h.picks[1].getAttribute('aria-pressed'),'true');
 await h.picks[0].trigger();assert.equal(h.group.value,'');assert.equal(h.headings().length,0);assert.equal(h.picks[0].getAttribute('aria-pressed'),'true');
 await h.picks[1].trigger();assert.equal(h.group.value,'lot');assert.equal(h.headings().length,3);
 // Quick chips: All clears the family; each chip sets one filter.
 assert.equal(h.quick[0].getAttribute('aria-pressed'),'true');
 await h.quick[1].trigger();assert.equal(h.problem.value,'damaged');assert.equal(h.count.textContent,'1 to 1 of 1');
 assert.deepEqual(h.quick.map(b=>b.getAttribute('aria-pressed')),['false','true','false','false']);
 await h.quick[2].trigger();assert.equal(h.problem.value,'');assert.equal(h.lot.value,'any');assert.equal(h.count.textContent,'1 to 4 of 4');
 await h.quick[3].trigger();assert.equal(h.lot.value,'null');assert.equal(h.count.textContent,'1 to 2 of 2');
 await h.quick[0].trigger();assert.equal(h.lot.value,'');assert.equal(h.count.textContent,'1 to 6 of 6');
 assert.equal(h.apply.textContent,'Show 6 parts');
 // Select mode switch mirrors the state.
 await h.toggle.trigger();assert.equal(h.toggle.getAttribute('aria-checked'),'true');assert.equal(h.bar.hidden,false);
 await h.cancel.trigger();assert.equal(h.toggle.getAttribute('aria-checked'),'false');assert.equal(h.bar.hidden,true);
 // Pages keep the filters: 20 damaged parts over two pages.
 const many=load(Array.from({length:40},(_,i)=>({damaged:i%2}))),next=many.container.afterNode.children.find(c=>c.className.includes('bc-page-next'));
 await many.quick[1].trigger();assert.equal(many.count.textContent,'1 to 15 of 20');
 await next.trigger();assert.equal(many.count.textContent,'16 to 20 of 20');assert.equal(many.problem.value,'damaged');assert.equal(many.rows().length,5);
 // Detail pages carry the item's type on the root: the count names the list's own noun, never that type's.
 const det=load([{},{}],{kind:'M',detail:true});assert.equal(det.count.getAttribute('aria-label'),'1 to 2 of 2 results');
 // Price basis wording comes from the whole filtered list, not the current page.
 const priced=Array.from({length:30},(_,i)=>i>=20?{price:['EUR','1.00','2026-10-08',false,'€1.00','8 Oct'],price_basis:['used','sold','bricklink']}:{});
 const pb=load(priced,{kind:'S'});
 assert.equal(pb.basis.textContent,' · prices are used averages from BrickLink');
 const nextBtn=pb.container.afterNode.children.find(c=>c.className.includes('bc-page-next'));await nextBtn.trigger();
 assert.equal(pb.basis.textContent,' · prices are used averages from BrickLink');
 // Group headings use the list noun ("booklets" on Instructions).
 const ins=load([{lot:['lot-1'],lot_links:[['lot-1','Lot 1']]},{lot:['lot-1'],lot_links:[['lot-1','Lot 1']]}],{kind:'I',defaultGroup:'lot'});
 assert.equal(ins.headings()[0].children[0].textContent,' · 2 booklets');
 // A saved grouping the list does not offer falls back to None.
 const sets=load([{}],{kind:'S',groupOptions:['','theme','storage'],saved:{group:'lot'}});assert.equal(sets.group.value,'');
 const keeps=load([{}],{kind:'S',groupOptions:['','theme','storage'],saved:{group:'theme'}});assert.equal(keeps.group.value,'theme');
 console.log('lists runtime ok');
})().catch(e=>{console.error(e);process.exit(1);});
