const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
class Node {
 constructor(){this.events={};this.dataset={};this.nodes={};this.groups={};this.children=[];this.value='';this.hidden=false;this.disabled=false;this.textContent='';this.style={};this.options=[];this.tagName='DIV';}
 addEventListener(n,f){this.events[n]=f;}
 matches(s){return s.split(',').some(selector=>{const m=selector.match(/^\[data-([a-z-]+)\]$/);return m?Object.hasOwn(this.dataset,m[1].replace(/-([a-z])/g,(_,c)=>c.toUpperCase())):selector.startsWith('.')?this.className===selector.slice(1):this.tagName===selector.toUpperCase();});}
 querySelector(s){return this.nodes[s]||this.querySelectorAll(s)[0]||null;}
 querySelectorAll(s){return this.groups[s]||this.children.flatMap(n=>[...(n.matches(s)?[n]:[]),...n.querySelectorAll(s)]);}
 closest(s){return this.matches(s)?this:this.parentElement?.closest(s);}
 append(...nodes){for(const n of nodes){if(n===doc.activeElement||n.querySelectorAll('input').includes(doc.activeElement))doc.activeElement=null;n.parentElement=this;this.children=this.children.filter(c=>c!==n);this.children.push(n);if(n.tagName==='OPTION')this.options.push(n);}}
 replaceChildren(...nodes){this.children=[];this.options=[];this.append(...nodes);}
 setAttribute(k,v){this[k]=v;}
 getAttribute(k){return this[k];}
 removeAttribute(k){delete this[k];}
 get selectedIndex(){return this.options.findIndex(o=>o.value===this.value);}
 hasAttribute(k){return k==='data-bc-main';}
 remove(){this.removed=true;if(this.parentElement)this.parentElement.children=this.parentElement.children.filter(n=>n!==this);this.parentElement=null;}
 focus(){this.focused=true;doc.activeElement=this;}
 async trigger(n='click',extra={}){if(n==='error')doc.events.error?.({target:this});return this.events[n]?.({preventDefault(){},currentTarget:this,target:this,...extra});}
}
const message=new Node(),undo=new Node(),form=new Node(),formStatus=new Node(),save=new Node();
form.dataset={bcAction:'save',identity:JSON.stringify({entity:'copy',ids:['copy']})};form.values={note:'A private note',condition:'U'};form.nodes={'[data-bc-form-message]':formStatus};form.groups={button:[save]};
const list=new Node(),container=new Node(),search=new Node(),sort=new Node(),direction=new Node(),count=new Node(),loaded=new Node(),more=new Node(),panel=new Node(),chips=new Node(),filters=new Node(),reset=new Node();sort.value='number';direction.value='asc';panel.hidden=true;
const records=Array.from({length:130},(_,i)=>({type:'P',name:'Part '+i,number:String(i),quantity:i,colour:i%2?'Black':'White',entity:'stock',ids:i===0?['first','second']:['id-'+i],condition:['U'],status:['I'],storage:['null'],place:['null'],flags:['Checked'],lot:['null'],category:'Plate',theme:'City',year:2020,stock:['loose'],image:i===1?7:null}));
const source=new Node(),fields=Object.keys(records[0]);source.textContent=JSON.stringify({fields,rows:records.map(r=>Object.fromEntries(fields.map((k,i)=>[i,r[k]])))});
list.nodes={'[data-bc-rows]':container,'[data-bc-records]':source,'[data-bc-search]':search,'[data-bc-sort]':sort,'[data-bc-direction]':direction,'[data-bc-count]':count,'[data-bc-panel]':panel,'[data-bc-chips]':chips,'[data-bc-more]':more,'[data-bc-loaded]':loaded,'[data-bc-reset]':reset};list.groups={'[data-bc-filters]':[filters]};
const controlValues={type:'P',condition:'U',status:'I',storage:'null',place:'null',flags:'Checked',lot:'null',duplicates:'false',stock:'loose',category:'Plate',theme:'City',year:'2020',colour:'Black',problem:'damaged'};
const controls=Object.entries(controlValues).map(([field,value])=>{const c=new Node();c.dataset.bcFilter=field;c.parentElement={firstChild:{textContent:field}};c.options=[{value:'',textContent:'All'},{value,textContent:value},{value:'nonmatching',textContent:'nonmatching'}];return c;});list.groups['[data-bc-filter]']=controls;
const bulkSave=new Node(),bulkField=new Node(),bulkValue=new Node(),select=new Node(),bar=new Node(),group=new Node(),view=new Node();view.dataset.bcView='list';
bulkField.value='storage_id';bulkValue.value='store';
Object.assign(list.nodes,{'[data-bc-bulk-save]':bulkSave,'[data-bc-bulk-field]':bulkField,'[data-bc-bulk-value]':bulkValue});list.groups['[data-bc-select]']=[select];list.groups['[data-bc-view]']=[view];list.nodes['[data-bc-selection-bar]']=bar;list.nodes['[data-bc-group]']=group;
const wishForm=new Node();wishForm.dataset={bcAction:'save',identity:JSON.stringify({entity:'wish',ids:[183]})};wishForm.values={condition:'used'};
const photoPicker=new Node(),photoInput=new Node(),photoName=new Node();
photoPicker.className='bc-photo-picker';photoPicker.nodes={'[data-bc-photo-name]':photoName};photoInput.parentElement=photoPicker;
const doc=new Node();
const conditionGroup=new Node();conditionGroup.dataset.bcSaveGroup='';
const conditionForms=['new','used','any'].map(value=>{
 const f=value==='used'?wishForm:new Node();f.dataset={...wishForm.dataset};f.values={condition:value};
 const button=new Node();button.tagName='BUTTON';f.append(button);conditionGroup.append(f);return f;
});
const conditionButtons=conditionGroup.querySelectorAll('button');
const root=new Node();root.dataset={bcCollectionList:'',saveUrl:'/collection/save/ACTION',csrf:'csrf',type:'P',editable:'true',itemBase:'/collection/item/TYPE/NUMBER',wishBase:'/collection/wishes/0',imageBase:'/manage/images/0',lotBase:'/collection/lot/LOT',unresolvedUrl:'/manage/unresolved',backUrl:'/collection/sets'};root.nodes={'[data-bc-message]':message,'[data-bc-undo]':undo};root.groups={'[data-bc-photo-file]':[photoInput],'form[data-bc-action]':[form,...conditionForms],'[data-bc-list]':[list]};
doc.querySelector=s=>s==='#bw-collection'?root:null;doc.createElement=tag=>{const n=new Node();n.tagName=tag.toUpperCase();return n;};
let observe;
let tabUrl='';
let calls=[],fail=false,reloads=0,stored=new Map(),merged=false;
const context={IntersectionObserver:class{constructor(callback){observe=callback;}observe(){}},window:{history:{replaceState(state,title,url){tabUrl=url;}},IntersectionObserver:true,addEventListener(){},scrollY:0,scrollTo(...args){this.scrolled=args;},innerHeight:900},document:doc,sessionStorage:{getItem:k=>stored.get(k)||null,setItem:(k,v)=>stored.set(k,v),removeItem:k=>stored.delete(k)},location:{pathname:'/collection/P',search:'',reload(){reloads++;}},URLSearchParams,FormData:class {constructor(f){this.entries=Object.entries(f.values);} [Symbol.iterator](){return this.entries[Symbol.iterator]();}},requestAnimationFrame:f=>f(),fetch:async(url,options)=>{calls.push({url,data:JSON.parse(options.body)});return {ok:!fail,json:async()=>fail?{message:'Not saved'}:(merged?{event_id:56,message:'Merged into existing stock',url:'/collection/item/P/bl-part?colour=11&stock=destination'}:{event_id:55,message:'Saved'})};}};
const sortOpen=new Node(),sortPanel=new Node(),statusAll=new Node(),statusIncomplete=new Node();
statusAll.dataset.bcStatus='';statusIncomplete.dataset.bcStatus='I';sortPanel.hidden=true;
list.nodes['[data-bc-sort-panel]']=sortPanel;list.groups['[data-bc-sort-open]']=[sortOpen];list.groups['[data-bc-status]']=[statusAll,statusIncomplete];
const inventoryList=new Node(),inventoryRows=new Node(),inventoryCount=new Node(),inventoryExtras=new Node(),inventoryPanel=new Node();inventoryExtras.hidden=true;
const figureHeading=new Node(),partProgress=new Node(),inventoryMissing=new Node(),inventoryPresent=new Node(),missingFigureRows=new Node(),presentFigureRows=new Node(),presentSummary=new Node();
const inventoryTabs=['parts','figures','extras'].map(value=>{const n=new Node();n.dataset.bcTab=value;return n;});
for(const type of ['P','M','?']){const n=new Node();n.dataset={bcRow:'',record:JSON.stringify({type,number:type,missing:type==='M'?1:0})};inventoryRows.append(n);}
inventoryList.nodes={'[data-bc-missing]':inventoryMissing,'[data-bc-present]':inventoryPresent,'[data-bc-missing-rows]':missingFigureRows,'[data-bc-present-rows]':presentFigureRows,'[data-bc-present-summary]':presentSummary,'[data-bc-figure-heading]':figureHeading,'[aria-label="Copy progress"]':partProgress,'[data-bc-rows]':inventoryRows,'[data-bc-count]':inventoryCount,'[data-bc-tab-extras]':inventoryExtras,'[data-bc-tab-inventory]':inventoryPanel};inventoryList.groups['[data-bc-tab]']=inventoryTabs;
for(const key of ['search','sort','direction'])inventoryList.nodes['[data-bc-'+key+']']=new Node();
root.groups['[data-bc-list]'].push(inventoryList);
// 4.9a: a list without search or sort controls (part and figure Matching) shows every row, never a silent 60-row cut.
const matchList=new Node(),matchRows=new Node(),matchNodes=Array.from({length:100},(_,i)=>{const n=new Node();n.dataset={bcRow:'',record:JSON.stringify({type:'S',number:String(i)})};matchRows.append(n);return n;});
matchList.nodes={'[data-bc-rows]':matchRows};root.groups['[data-bc-list]'].push(matchList);
// The Info pencil, Edit's Delete entry, and estimate use the same dialog controller.
const editDialog=new Node(),deleteDialog=new Node(),estimateInput=new Node();
editDialog.showModal=()=>{editDialog.open=true;};deleteDialog.showModal=()=>{deleteDialog.open=true;};
editDialog.nodes['[name=current_value]']=estimateInput;
const pencil=new Node(),deleteEntry=new Node(),estimateEntry=new Node(),keep=new Node();
pencil.dataset.bwOpen='bc-edit';deleteEntry.dataset.bwOpen='bc-delete';estimateEntry.dataset={bwOpen:'bc-edit',bcFocus:'current_value'};
keep.dataset.bwClose='';keep.closest=()=>deleteDialog;deleteDialog.close=()=>{deleteDialog.open=false;};
root.groups['[data-bw-open]']=[pencil,deleteEntry,estimateEntry];root.groups['[data-bw-close]']=[keep];
doc.getElementById=id=>({'bc-edit':editDialog,'bc-delete':deleteDialog})[id];
vm.runInNewContext(fs.readFileSync('static/web/toni/images.js','utf8'),context);
vm.runInNewContext((fs.readFileSync('static/web/toni/formatting.js','utf8')+fs.readFileSync('static/web/toni/bw-collection.js','utf8')),context);
pencil.trigger();assert.equal(editDialog.open,true);
deleteEntry.trigger();assert.equal(deleteDialog.open,true);
keep.trigger();assert.equal(deleteDialog.open,false);assert.equal(editDialog.open,true);
const folded={open:false};estimateInput.closest=selector=>selector==='details'?folded:null;
estimateEntry.trigger();assert.equal(doc.activeElement,estimateInput);assert.equal(folded.open,true,'4.9a: a folded estimate opens before it takes focus');
const api=context.window.BrickCollection;
assert.equal(matchNodes.filter(n=>!n.hidden).length,100,'4.9a: 100 matches all stay visible');
assert.deepEqual(matchNodes.map(n=>n.dataset.record).slice(0,3),[0,1,2].map(i=>JSON.stringify({type:'S',number:String(i)})));
// 4.9a: a list without a sort control (part and figure Matching) keeps the server order.
assert.deepEqual(api.filterRows([{number:'9',index:0},{number:'1',index:1},{number:'5',index:2}],'',{},'index','asc').map(r=>r.number),['9','1','5']);
assert.deepEqual(api.filterRows([{number:'9',index:0},{number:'1',index:1}],'',{},'number','asc').map(r=>r.number),['1','9']);
function texts(n){return [n.textContent,...n.children.flatMap(texts)].filter(Boolean);}
for(const name of ['Named part','']){
 const row=api.buildRow({...records[1],name,number:'3022',theme:'',category:'',year:1968,missing:0,damaged:1,defects:'1 damaged',lot_links:[]},root.dataset,false,()=>{});
 const values=texts(row);assert.equal(values.filter(t=>t==='3022').length,1);assert.equal(values.filter(t=>t==='1968').length,1);assert.ok(!values.some(t=>t.startsWith(' · ')));assert.ok(!values.some(t=>t.includes('0 missing')));assert.ok(values.includes('1 damaged'));
}
for(const type of ['S','wish','P']){
 const row=api.buildRow({...records[1],entity:'wish',quantity:3,missing:0,defects:'3 wanted',lot_links:[]},{...root.dataset,type},false,()=>{});
 const values=texts(row);assert.equal(values.filter(t=>t==='3 wanted').length,1);assert.ok(!values.some(t=>t.includes('missing')||t.includes('loose')||t.includes('Unknown')));
}
{ // 4.9d w6: a wish card shows its recorded maximum, or says it is not recorded.
 const withMax=api.buildRow({...records[1],entity:'wish',quantity:3,missing:0,defects:'3 wanted',max_price:'€48.00',lot_links:[]},root.dataset,false,()=>{});
 const without=api.buildRow({...records[1],entity:'wish',quantity:3,missing:0,defects:'3 wanted',lot_links:[]},root.dataset,false,()=>{});
 assert.ok(texts(withMax).includes('Your max price')&&texts(withMax).includes('€48.00'));assert.ok(texts(without).includes('Not recorded'));
 const plain=api.buildRow({...records[1],max_price:'€48.00',lot_links:[]},root.dataset,false,()=>{});assert.ok(!texts(plain).includes('Your max price'));
}
const priced=api.buildRow({...records[1],price:['EUR','12.5144','2026-10-08',true,'€12.51','8 Oct'],lot_links:[]},root.dataset,false,()=>{});
assert.ok(texts(priced).includes('€12.51'));assert.ok(texts(priced).includes('8 Oct · stale'));
assert.equal(api.filterRows([{type:'P'},{type:'M'},{type:'?'},{type:'I'},{type:'O'}],'',{inventory:'figures'}).length,2);
assert.equal(api.filterRows([{status:['']},{status:['C']}],'',{status:'unknown'}).length,1);
const sample=[{name:'Plate',number:'3020',colour:'Black',quantity:12,missing:2,condition:['N','U'],storage:['null'],duplicates:true},{name:'Brick',number:'3004',colour:'White',quantity:4,damaged:1,condition:['U'],duplicates:false}];
assert.equal(api.filterRows(sample,'black').length,1);
assert.equal(api.filterRows(sample,'',{condition:'N',storage:'null'})[0].number,'3020');
assert.equal(api.filterRows(sample,'',{duplicates:'true'}).length,1);
assert.equal(api.filterRows(sample,'',{problem:'damaged'})[0].number,'3004');
assert.equal(api.filterRows(sample,'',{},'quantity','desc')[0].quantity,12);
assert.equal(api.filterRows(sample,'',{},'missing')[0].missing,2);
assert.throws(()=>api.selectedInstances([{checked:true,entity:'copy',ids:['a']},{checked:true,entity:'stock',ids:['b']}]),/one instance type/);
assert.equal(api.selectedInstances([{checked:true,hidden:true,entity:'stock',ids:['b']}]).ids.length,0);
assert.equal(count.textContent,'130 parts');assert.equal(loaded.textContent,'Loaded 60 of 130');assert.equal(container.querySelectorAll('[data-bc-row]').length,60);
(async()=>{
 assert.equal(context.window.BrickCollection.resultCount(1),'1 result');
 assert.equal(context.window.BrickCollection.resultCount(0),'0 results');
 assert.equal(context.window.BrickCollection.resultCount(2),'2 results');
 photoInput.files=[{name:'Castle.jpg'}];await photoInput.trigger('change');assert.equal(photoName.textContent,'Castle.jpg');
 photoInput.files=[];await photoInput.trigger('change');assert.equal(photoName.textContent,'No file chosen');
 photoInput.parentElement=null;await photoInput.trigger('change');photoInput.parentElement=photoPicker;
 delete photoPicker.nodes['[data-bc-photo-name]'];await photoInput.trigger('change');photoPicker.nodes['[data-bc-photo-name]']=photoName;
 assert.equal(figureHeading.hidden,true);assert.equal(partProgress.hidden,false);
 root.dataset.type='S';await inventoryTabs[1].trigger();
 assert.equal(inventoryCount.hidden,true);assert.equal(inventoryCount.textContent,'');
 assert.equal(figureHeading.hidden,false);assert.equal(partProgress.hidden,true);
 assert.equal(inventoryRows.children.filter(n=>!n.hidden).length,2);
 assert.equal(inventoryMissing.hidden,true);assert.equal(inventoryPresent.hidden,true);
 assert.ok(inventoryRows.children.filter(n=>!n.hidden).every(n=>n.parentElement===inventoryRows),'present and missing figures remain inline');
 root.dataset.type='P';await inventoryTabs[0].trigger();
 assert.equal(inventoryCount.textContent,'1 parts');await inventoryTabs[1].trigger();assert.equal(inventoryCount.textContent,'2 minifigures');assert.equal(inventoryTabs[1]['aria-pressed'],'true');
 await inventoryTabs[2].trigger();assert.equal(inventoryCount.textContent,'2 minifigures');assert.equal(inventoryExtras.hidden,false);assert.equal(inventoryPanel.hidden,true);assert.equal(inventoryTabs[2]['aria-pressed'],'true');assert.ok(tabUrl.endsWith('?inventory=extras'));await inventoryTabs[0].trigger();assert.equal(inventoryExtras.hidden,true);assert.equal(inventoryPanel.hidden,false);assert.equal(inventoryCount.textContent,'1 parts');

 await sortOpen.trigger();assert.equal(sortPanel.hidden,false);await sortOpen.trigger();assert.equal(sortPanel.hidden,true);
 await statusIncomplete.trigger();assert.equal(controls.find(c=>c.dataset.bcFilter==='status').value,'I');assert.equal(statusIncomplete['aria-pressed'],'true');
 await statusAll.trigger();assert.equal(controls.find(c=>c.dataset.bcFilter==='status').value,'');
 const cached=container.querySelectorAll('[data-bc-row]')[1],image=cached.querySelector('img'),check=cached.querySelector('[data-bc-selected]');
 check.focus();search.value='Black';await search.trigger('input');
 assert.ok(container.children.includes(cached));assert.equal(cached.querySelector('img'),image);assert.equal(doc.activeElement,check);
 search.value='';await search.trigger('input');assert.equal(container.querySelectorAll('[data-bc-row]')[1],cached);
 observe([{isIntersecting:true}]);assert.equal(container.querySelectorAll('[data-bc-row]').length,120);
 await more.trigger();assert.equal(more.hidden,true);assert.equal(container.querySelectorAll('[data-bc-row]').length,130);
 search.value='Black';await search.trigger('input');assert.equal(count.textContent,'65 parts');assert.equal(loaded.textContent,'Loaded 60 of 65');
 assert.equal(chips.children[0].textContent,'Search: Black ×');await chips.children[0].trigger();assert.equal(search.value,'');assert.equal(count.textContent,'130 parts');
 await filters.trigger();assert.equal(panel.hidden,false);await doc.trigger('keydown',{key:'Escape',target:{tagName:'SELECT'}});assert.equal(panel.hidden,true);await filters.trigger();await filters.trigger();assert.equal(panel.hidden,true);
 fail=true;await form.trigger('submit');assert.equal(formStatus.textContent,'Not saved · Try again');assert.equal(form.values.note,'A private note');assert.equal(save.disabled,false);assert.equal(reloads,0);
 fail=false;await form.trigger('submit');assert.equal(calls[1].data.values.note,'A private note');assert.equal(calls[1].data.csrf_token,'csrf');assert.equal(undo.hidden,false);assert.equal(message.textContent,'Saved · Undo');assert.equal(reloads,1);
 await undo.trigger();assert.equal(calls[2].data.event_id,55);assert.equal(calls[2].url,'/collection/save/undo');assert.equal(stored.has('bw-collection-receipt'),false);assert.equal(reloads,2);
 merged=true;await form.trigger('submit');assert.equal(context.location.href,'/collection/item/P/bl-part?colour=11&stock=destination');assert.equal(message.textContent,'Merged into existing stock · Undo');assert.equal(reloads,2);
 await select.trigger();const selected=container.querySelector('[data-bc-selected]');selected.checked=true;await selected.trigger('change');await more.trigger();await view.trigger();assert.equal(container.querySelector('[data-bc-selected]').checked,true);sort.value='quantity';direction.value='desc';await sort.trigger('change');assert.equal(container.querySelector('[data-bc-selected]').checked,false);context.location.href='';await bulkSave.trigger();assert.equal(context.location.href,'/collection/item/P/bl-part?colour=11&stock=destination');assert.deepEqual(calls.at(-1).data.ids,['first','second']);assert.equal(calls.at(-1).data.values.storage_id,'store');assert.equal(bulkSave.disabled,false);assert.equal(message.textContent,'Merged into existing stock · Undo');assert.equal(reloads,2);
 search.value='Black';await search.trigger('input');search.value='';await search.trigger('input');assert.equal(container.querySelector('[data-bc-selected]').checked,false);
 group.value='colour';await group.trigger('change');assert.equal(container.querySelectorAll('[data-bc-group-heading]').length,1);await more.trigger();assert.equal(container.querySelectorAll('[data-bc-group-heading]').length,2);
 sort.value='quantity';direction.value='desc';await direction.trigger('change');group.value='';await group.trigger('change');assert.equal(container.querySelector('[data-bc-item-link]').children[0].children[1].textContent,'Part\u00a0129');
 await more.trigger();await view.trigger();const state=JSON.parse(stored.get('bw-collection-list:/collection/P:0'));assert.equal(state.limit,120);assert.equal(state.sort,'quantity');assert.equal(state.direction,'desc');assert.equal(state.view,'list');
 container.replaceChildren();
 state.query='White';state.filters={condition:'U'};state.scroll=321;stored.set('bw-collection-list:/collection/P:0',JSON.stringify(state));
 vm.runInNewContext((fs.readFileSync('static/web/toni/formatting.js','utf8')+fs.readFileSync('static/web/toni/bw-collection.js','utf8')),context);assert.equal(search.value,'White');assert.equal(count.textContent,'65 parts');assert.equal(container.querySelectorAll('[data-bc-row]').length,65);assert.equal(context.window.scrolled[1],321);
 assert.equal(controls.find(c=>c.dataset.bcFilter==='condition').value,'U');
 await reset.trigger();
 for(const c of controls){c.value='nonmatching';await c.trigger('change');assert.equal(count.textContent,'0 parts',c.dataset.bcFilter);assert.equal(chips.children[0].textContent,c.dataset.bcFilter+': nonmatching ×');await chips.children[0].trigger();assert.equal(count.textContent,'130 parts');}
 const visible=container.querySelectorAll('[data-bc-row]');await visible[0].trigger('keydown',{key:'ArrowDown'});assert.equal(visible[1].focused,true);
 const unsafe=api.decodeRecords({fields:['type','number','name'],rows:[{0:'P',1:'x',2:'<img src=x onerror=alert(1)>'}]})[0];
 const escaped=api.buildRow(unsafe,root.dataset,false,()=>{});assert.equal(escaped.querySelector('[data-bc-item-link]').children[0].children[1].textContent,api.nowrapTail(unsafe.name));assert.equal(escaped.querySelectorAll('img').length,0);
 const withImage=api.buildRow({...unsafe,image:4},root.dataset,false,()=>{}),img=withImage.querySelector('img');assert.equal(img.src,'/manage/images/4?w=320');await img.trigger('error');assert.equal(withImage.querySelector('.bc-picture').children[1].textContent,'No image');await withImage.querySelector('.bc-picture').children[2].trigger();assert.equal(withImage.querySelector('img'),img);
 for(const [field,value] of Object.entries({type:'P',condition:'N',status:'C',storage:'null',place:'null',flags:'Checked',lot:'null',duplicates:'true',stock:'loose',category:'Plate',theme:'City',year:'2020',colour:'Black'})){
   const r={...sample[0],type:'P',status:['C'],place:['null'],flags:['Checked'],lot:['null'],stock:['loose'],category:'Plate',theme:'City',year:2020};assert.equal(api.filterRows([r],'',{[field]:value}).length,1,field);assert.equal(api.filterRows([r],'',{[field]:'nonmatching'}).length,0,field);
 }
 let wide=true,resize;
 inventoryList.hasAttribute=()=>false;
 context.matchMedia=query=>({matches:query.includes('min-width')?wide:!wide,addEventListener(name,callback){resize=callback;}});
 vm.runInNewContext((fs.readFileSync('static/web/toni/formatting.js','utf8')+fs.readFileSync('static/web/toni/bw-collection.js','utf8')),context);
 assert.equal(panel.hidden,false);assert.equal(panel.role,'region');await filters.trigger();assert.equal(panel.hidden,false);
 wide=false;resize();assert.equal(panel.hidden,true);await filters.trigger();assert.equal(panel.hidden,false);assert.equal(panel.role,'dialog');assert.equal(panel['aria-modal'],'true');
 await filters.trigger();assert.equal(panel.hidden,true);assert.equal(filters.focused,true);
 wide=true;resize();assert.equal(panel.hidden,false);assert.equal(panel.role,'region');
 context.location.search='?inventory=extras';vm.runInNewContext((fs.readFileSync('static/web/toni/formatting.js','utf8')+fs.readFileSync('static/web/toni/bw-collection.js','utf8')),context);assert.equal(inventoryPanel.hidden,true);assert.equal(inventoryExtras.hidden,false);assert.equal(inventoryTabs[2]['aria-pressed'],'true');context.location.search='';await inventoryTabs[0].trigger();
 // Review regressions use the inventory as the first list, matching detail pages.
 root.groups['[data-bc-list]']=[inventoryList];
 const inventorySearch=inventoryList.nodes['[data-bc-search]'],inventorySort=inventoryList.nodes['[data-bc-sort]'],inventoryDirection=inventoryList.nodes['[data-bc-direction]'];
 const inventoryFilters=new Node(),inventoryFilterPanel=new Node(),inventoryControl=new Node(),inventoryGroup=new Node(),inventoryMore=new Node();
 inventoryControl.tagName='SELECT';inventoryControl.dataset.bcFilter='condition';inventoryControl.value='U';inventoryFilterPanel.append(inventoryControl);inventoryFilterPanel.hidden=true;
 inventoryList.nodes['[data-bc-panel]']=inventoryFilterPanel;inventoryList.nodes['[data-bc-group]']=inventoryGroup;inventoryList.nodes['[data-bc-more]']=inventoryMore;
 inventoryList.groups['[data-bc-filters]']=[inventoryFilters];inventoryList.groups['[data-bc-filter]']=[inventoryControl];
 context.location.pathname='/collection/item/S/review';context.location.search='?stock=copy&tag=a&tag=b';context.location.hash='#inventory';
 context.window.history.replaceState=(state,title,url)=>{tabUrl=url;context.location.search=url.slice(url.indexOf('?')).split('#')[0];};
 const rebuild=()=>vm.runInNewContext((fs.readFileSync('static/web/toni/formatting.js','utf8')+fs.readFileSync('static/web/toni/bw-collection.js','utf8')),context);
 rebuild();
 inventorySearch.value='M';await inventorySearch.trigger('input');await inventoryTabs[1].trigger();
 assert.equal(tabUrl,'/collection/item/S/review?stock=copy&tag=a&tag=b&inventory=figures#inventory');
 const inventoryKey='bw-collection-list:/collection/item/S/review?stock=copy&tag=a&tag=b:0';
 assert.equal(JSON.parse(stored.get(inventoryKey)).query,'M');
 inventorySearch.value='';rebuild();assert.equal(inventorySearch.value,'M');assert.equal(inventoryTabs[1]['aria-pressed'],'true');
 // Other query parameters still isolate saved state.
 context.location.search='?stock=other&tag=a&tag=b&inventory=figures';rebuild();assert.equal(inventorySearch.value,'M');
 assert.equal(JSON.parse(stored.get('bw-collection-list:/collection/item/S/review?stock=other&tag=a&tag=b:0')).query,'M');
 inventorySearch.value='other search';await inventorySearch.trigger('input');
 context.location.search='?stock=copy&tag=a&tag=b&inventory=figures';rebuild();assert.equal(inventorySearch.value,'M');
 // A rejected URL update still switches both panels and pressed state.
 context.window.history.replaceState=()=>{throw new Error('History unavailable');};
 await inventoryTabs[2].trigger();assert.equal(inventoryExtras.hidden,false);assert.equal(inventoryPanel.hidden,true);assert.equal(inventoryTabs[2]['aria-pressed'],'true');
 await inventoryTabs[0].trigger();assert.equal(inventoryExtras.hidden,true);assert.equal(inventoryPanel.hidden,false);assert.equal(inventoryTabs[0]['aria-pressed'],'true');
 // Extras saves exactly the same state fields as the inventory branch.
 inventorySort.value='quantity';inventoryDirection.value='desc';inventoryGroup.value='type';inventoryRows.dataset.view='list';context.window.scrollY=456;
 await inventorySearch.trigger('input');await inventoryMore.trigger();
 const normalState=JSON.parse(stored.get(inventoryKey));assert.equal(normalState.limit,120);
 await inventoryTabs[2].trigger();const extrasState=JSON.parse(stored.get(inventoryKey));
 assert.deepEqual(extrasState,{...normalState,filters:{...normalState.filters,inventory:'extras'},limit:60});
 assert.equal(extrasState.group,'type');assert.equal(extrasState.view,'list');assert.equal(extrasState.scroll,456);
 inventoryGroup.value='';inventoryRows.dataset.view='';context.location.search='?stock=copy&tag=a&tag=b&inventory=extras';rebuild();
 assert.equal(inventoryGroup.value,'type');assert.equal(inventoryRows.dataset.view,'list');assert.equal(inventoryTabs[2]['aria-pressed'],'true');
 // Entering Extras closes an open sheet; clicks and f never focus hidden controls.
 wide=false;await inventoryTabs[0].trigger();await inventoryFilters.trigger();assert.equal(inventoryFilterPanel.hidden,false);assert.equal(doc.activeElement,inventoryControl);
 inventoryTabs[2].focus();await inventoryTabs[2].trigger();assert.equal(inventoryFilterPanel.hidden,true);assert.equal(inventoryFilters['aria-expanded'],'false');
 await inventoryFilters.trigger();assert.equal(inventoryFilterPanel.hidden,true);assert.equal(doc.activeElement,inventoryTabs[2]);
 let prevented=false;await doc.trigger('keydown',{key:'f',target:{tagName:'BUTTON'},preventDefault(){prevented=true;}});
 assert.equal(prevented,false);assert.equal(inventoryFilterPanel.hidden,true);assert.equal(doc.activeElement,inventoryTabs[2]);
 // Desktop initialization and breakpoint changes must also keep Extras closed.
 inventoryList.hasAttribute=()=>true;wide=true;rebuild();assert.equal(inventoryFilterPanel.hidden,true);assert.equal(inventoryFilters['aria-expanded'],'false');
 resize();await inventoryFilters.trigger();await doc.trigger('keydown',{key:'f',target:{tagName:'BUTTON'}});assert.equal(inventoryFilterPanel.hidden,true);assert.equal(doc.activeElement,inventoryTabs[2]);
 wide=false;resize();await inventoryTabs[0].trigger();await doc.trigger('keydown',{key:'f',target:{tagName:'BUTTON'}});assert.equal(inventoryFilterPanel.hidden,false);assert.equal(doc.activeElement,inventoryControl);
 // All condition segments lock together until success or failure resolves.
 const originalFetch=context.fetch;let finishSave;
 context.fetch=(...args)=>{const response=originalFetch(...args);return new Promise(resolve=>{finishSave=()=>resolve(response);});};
 merged=false;
 for(const rejected of [false,true]){
  fail=rejected;const before=calls.length;
  const pending=conditionForms[0].trigger('submit');
  assert.ok(conditionButtons.every(b=>b.disabled));assert.equal(save.disabled,false);
  await wishForm.trigger('submit');assert.equal(calls.length,before+1);
  assert.equal(calls.at(-1).data.values.condition,'new');
  finishSave();await pending;assert.ok(conditionButtons.every(b=>!b.disabled));
 }
 context.fetch=originalFetch;fail=false;
 await wishForm.trigger('submit');assert.equal(calls.at(-1).url,'/collection/save/save');assert.deepEqual(calls.at(-1).data.values,{condition:'used'});assert.equal(calls.at(-1).data.entity,'wish');assert.deepEqual(calls.at(-1).data.ids,[183]);
 console.log('Brick Work collection runtime passed');
// Run 2: data claims follow the actual displayed records, including filtering.
assert.equal(api.priceBasis([]),'');
assert.equal(api.priceBasis([{price:['EUR','12'],price_basis:['U','sold','bricklink']}]),' · prices are used averages from BrickLink');
assert.equal(api.priceBasis([{price:[],price_basis:['N','stock','bricklink']}]),' · prices are new listings from BrickLink');
assert.equal(api.priceBasis([{price:[],price_basis:['U','sold','bricklink']},{price:[],price_basis:['U','sold','rebrickable']}]),' · prices are used averages from mixed sources');
const gaps=api.inventorySections([{number:'damaged',missing:0,damaged:2},{number:'missing',missing:1},{number:'present',missing:0},{number:'unchecked'}]);
assert.equal(api.priceBasis([{price:[],price_basis:['U','sold','bricklink']},{price:[],price_basis:['N','sold','bricklink']}]),' · prices have mixed bases from BrickLink');
assert.deepEqual(Array.from(gaps.missing,r=>r.number),['damaged','missing']);
assert.deepEqual(Array.from(api.inventorySections([{missing:0},{missing:null}]).missing),[]);
assert.equal(api.filterRows([{flags:['Display','Box present']},{flags:['Display']}],'',{tag:'Display',has:'Box present'}).length,1);
assert.equal(api.filterRows([{number:'damaged',damaged:2},{number:'missing',missing:1}],'',{},'missing')[0].number,'damaged');

// Real button listeners map kit chips onto the same canonical select state.
const run2Picks=['condition','status','tag','has'].map((key,i)=>{const n=new Node();n.dataset={bcPick:key,value:['U','I','Display','Box present'][i]};return n;});
for(const key of ['tag','has']){
 const c=new Node();c.dataset.bcFilter=key;c.parentElement={firstChild:{textContent:key}};
 c.options=[{value:'',textContent:'All'},{value:key==='tag'?'Display':'Box present',textContent:key}];controls.push(c);
}
root.groups['[data-bc-list]']=[list,inventoryList];
list.groups['[data-bc-pick]']=run2Picks;
stored.clear();context.location.search='';
vm.runInNewContext((fs.readFileSync('static/web/toni/formatting.js','utf8')+fs.readFileSync('static/web/toni/bw-collection.js','utf8')),context);
for(const pick of run2Picks){
 pick.trigger();assert.equal(controls.find(c=>c.dataset.bcFilter===pick.dataset.bcPick).value,pick.dataset.value);
 assert.equal(pick['aria-pressed'],'true');pick.trigger();assert.equal(pick['aria-pressed'],'false');
}

// Reparenting keeps missing rows first and present rows under the disclosure;
// tabs/search retain the same record set. The server owns chart presence.
const missingSection=new Node(),missingRows=new Node(),presentSection=new Node(),presentRows=new Node(),presentSummary=new Node();
Object.assign(inventoryList.nodes,{'[data-bc-inventory-rows]':inventoryRows,'[data-bc-missing]':missingSection,'[data-bc-missing-rows]':missingRows,'[data-bc-present]':presentSection,'[data-bc-present-rows]':presentRows,'[data-bc-present-summary]':presentSummary});
inventoryList.nodes['[data-bc-search]'].value='';inventoryControl.value='';
const partRows=Array.from({length:3},(_,i)=>{const n=new Node();n.dataset={bcRow:'',record:JSON.stringify({type:'P',number:String(i),missing:i===0?1:0,damaged:i===1?1:0})};return n;});
// 4.6o: inventory rebuild moves the server's card text without changing it.
partRows[0].textContent='Plate 2 × 4 Trans-Clear 3020 needs 1 · 1 missing';
inventoryRows.groups['[data-bc-row]']=partRows;
const chart=new Node();chart.dataset.bcPriceHistory='';root.append(chart);
stored.clear();vm.runInNewContext((fs.readFileSync('static/web/toni/formatting.js','utf8')+fs.readFileSync('static/web/toni/bw-collection.js','utf8')),context);
assert.equal(missingSection.hidden,false);assert.equal(presentSection.hidden,false);assert.equal(presentSummary.textContent,'Show all 1 present parts');
assert.equal(missingRows.children[0].textContent,'Plate 2 × 4 Trans-Clear 3020 needs 1 · 1 missing');assert.equal(missingRows.children.length,2);assert.ok(presentRows.children.includes(partRows[2]));
assert.ok(root.querySelector('[data-bc-price-history]')===chart);
inventoryList.nodes['[data-bc-search]'].value='2';inventoryList.nodes['[data-bc-search]'].trigger('input');
assert.equal(missingSection.hidden,true);assert.equal(presentSection.hidden,true);assert.equal(partRows[2].hidden,false);
assert.ok(root.querySelector('[data-bc-price-history]')===chart);
chart.remove();inventoryTabs[1].trigger();assert.equal(missingSection['aria-label'],'Missing minifigures');inventoryTabs[0].trigger();assert.equal(missingSection['aria-label'],'Missing parts');assert.equal(root.querySelector('[data-bc-price-history]'),null);
partRows[2].dataset.record=JSON.stringify({type:'P',number:'2',missing:0,missing_recorded:false});
stored.clear();inventoryList.nodes['[data-bc-search]'].value='';context.location.search='';
vm.runInNewContext((fs.readFileSync('static/web/toni/formatting.js','utf8')+fs.readFileSync('static/web/toni/bw-collection.js','utf8')),context);
assert.equal(presentSummary.textContent,'Show all 1 other parts');
// #33 (1d): the first three present lines show inline above the disclosure; the rest stay in it.
const presentInline=new Node();inventoryList.nodes['[data-bc-present-inline]']=presentInline;
const fiveRows=Array.from({length:5},(_,i)=>{const n=new Node();n.dataset={bcRow:'',record:JSON.stringify({type:'P',number:'p'+i,missing:i===0?1:0})};return n;});
inventoryRows.groups['[data-bc-row]']=fiveRows;stored.clear();
vm.runInNewContext((fs.readFileSync('static/web/toni/formatting.js','utf8')+fs.readFileSync('static/web/toni/bw-collection.js','utf8')),context);
assert.equal(presentInline.hidden,false);assert.deepEqual(presentInline.children.filter(n=>fiveRows.includes(n)),[fiveRows[1],fiveRows[2],fiveRows[3]]);
assert.ok(presentRows.children.includes(fiveRows[4]));assert.equal(presentSection.hidden,false);assert.equal(presentSummary.textContent,'Show all 4 present parts');
delete inventoryList.nodes['[data-bc-present-inline]'];inventoryRows.groups['[data-bc-row]']=partRows;
// Visible kit controls receive focus; canonical hidden selects cannot trap Tab.
root.groups['[data-bc-list]']=[list];stored.clear();
run2Picks[0].tagName='BUTTON';panel.append(run2Picks[0]);
const hiddenSelect=new Node();hiddenSelect.tagName='SELECT';hiddenSelect.getClientRects=()=>[];panel.append(hiddenSelect);
context.matchMedia=q=>({matches:q.includes('min-width'),addEventListener(){}});
vm.runInNewContext((fs.readFileSync('static/web/toni/formatting.js','utf8')+fs.readFileSync('static/web/toni/bw-collection.js','utf8')),context);
await filters.trigger();assert.equal(doc.activeElement,run2Picks[0]);
context.matchMedia=q=>({matches:q.includes('max-width'),addEventListener(){}});
await doc.trigger('keydown',{key:'Tab',target:run2Picks[0]});assert.equal(doc.activeElement,run2Picks[0]);
// 4.7d: real sheet events share one scrim and one canonical filter state.
root.groups['[data-bc-list]']=[list];stored.clear();
const sheetScrim=new Node(),applySets=new Node(),summaryNode=new Node(),sortChoice=new Node(),orderChoice=new Node();
sheetScrim.hidden=true;sortChoice.dataset.bcSortPick='used_price';orderChoice.dataset.bcOrderPick='desc';
list.nodes['[data-bc-sheet-scrim]']=sheetScrim;list.nodes['[data-bc-apply]']=applySets;list.nodes['[data-bc-missing-summary]']=summaryNode;
list.groups['[data-bc-sort-pick]']=[sortChoice];list.groups['[data-bc-order-pick]']=[orderChoice];sortPanel.append(sortChoice,orderChoice);
context.matchMedia=q=>({matches:q.includes('max-width'),addEventListener(){}});
context.location.pathname='/collection/sets';root.dataset.type='S';
source.textContent=JSON.stringify({fields:['type','number','name','missing_parts','missing_figures','quantity','duplicates'],rows:[{0:'S',1:'7286-1',2:'Transport',3:15,5:1},{0:'S',1:'2260-1',2:'Dragon',3:1,4:2,5:2,6:true}]});
const copiesControl=new Node(),copiesPick=new Node();copiesControl.dataset.bcFilter='duplicates';copiesControl.parentElement={firstChild:{textContent:'Copies'}};
copiesControl.options=[{value:'',textContent:'All'},{value:'true',textContent:'Several'},{value:'false',textContent:'One'}];
copiesPick.dataset={bcPick:'duplicates',value:'true'};
list.groups['[data-bc-filter]']=[...controls.filter(c=>c.dataset.bcFilter!=='duplicates'),copiesControl];list.groups['[data-bc-pick]']=[copiesPick];
search.value='';sort.value='number';controls.forEach(c=>c.value='');panel.hidden=true;sortPanel.hidden=true;
vm.runInNewContext((fs.readFileSync('static/web/toni/formatting.js','utf8')+fs.readFileSync('static/web/toni/bw-collection.js','utf8')),context);
assert.equal(summaryNode.textContent,'Missing in view: 15 parts in 7286-1 · 1 part, 2 figs in 2260-1');
assert.equal(applySets.textContent,'Show 2 sets');
await copiesPick.trigger();assert.equal(count.textContent,'1 sets');assert.equal(copiesControl.value,'true');assert.equal(copiesPick['aria-pressed'],'true');
assert.equal(summaryNode.textContent,'Missing in view: 1 part, 2 figs in 2260-1');
await reset.trigger();assert.equal(applySets.textContent,'Show 2 sets');assert.equal(copiesControl.value,'');assert.equal(copiesPick['aria-pressed'],'false');
search.value='Dragon';await search.trigger('input');assert.equal(applySets.textContent,'Show 1 sets');assert.equal(summaryNode.textContent,'Missing in view: 1 part, 2 figs in 2260-1');
search.value='absent';await search.trigger('input');assert.equal(summaryNode.hidden,true);assert.equal(applySets.textContent,'Show 0 sets');
await filters.trigger();assert.equal(sheetScrim.hidden,false);assert.equal(panel.hidden,false);
await applySets.trigger();assert.equal(panel.hidden,true);assert.equal(sheetScrim.hidden,true);
await sortOpen.trigger();assert.equal(sortPanel.hidden,false);assert.equal(panel.hidden,true);assert.equal(sheetScrim.hidden,false);assert.equal(sortPanel['aria-modal'],'true');
await sortChoice.trigger();assert.equal(sort.value,'used_price');assert.equal(sortChoice['aria-pressed'],'true');
await orderChoice.trigger();assert.equal(direction.value,'desc');assert.equal(orderChoice['aria-pressed'],'true');
await doc.trigger('keydown',{key:'Escape',target:sortChoice});assert.equal(sortPanel.hidden,true);assert.equal(sheetScrim.hidden,true);
await sortOpen.trigger();await filters.trigger();assert.equal(sortPanel.hidden,true);assert.equal(panel.hidden,false);assert.equal(sheetScrim.hidden,false);
await sheetScrim.trigger();assert.equal(panel.hidden,true);assert.equal(sortPanel.hidden,true);assert.equal(sheetScrim.hidden,true);
root.dataset.type='P';
console.log('Brick Work run 2 filters, inventory sections and chart preservation passed');
// Group first, then unpriced last: one heading per theme with Used price sort.
 {
  const g=api.filterRows([{number:'a1',theme:'A',price:['EUR','5']},{number:'b1',theme:'B',price:['EUR','1']},{number:'a2',theme:'A'},{number:'a3',theme:'A',price:['EUR','2']}],'',{},'used_price','asc','theme');
  assert.deepEqual(g.map(r=>r.number),['a3','a1','a2','b1']);
  assert.equal(g.filter((r,i)=>i===0||r.theme!==g[i-1].theme).length,2);
 }
 // Detail-page lists take their noun from the list, not the page's item type.
 {
  const detailRoot=root.dataset,saved=detailRoot.bcCollectionList;
  delete detailRoot.bcCollectionList;detailRoot.type='M';
  const matching=new Node(),matchingRows=new Node(),matchingCount=new Node();
  for(const type of ['S','S','S']){const n=new Node();n.dataset={bcRow:'',record:JSON.stringify({type,number:type,missing:type==='M'?1:0})};matchingRows.append(n);}
  matching.nodes={'[data-bc-rows]':matchingRows,'[data-bc-count]':matchingCount};
  for(const key of ['search','sort','direction'])matching.nodes['[data-bc-'+key+']']=new Node();
  root.groups['[data-bc-list]']=[matching];
  context.location.pathname='/collection/item/M/fig';context.location.search='';context.location.hash='';
  vm.runInNewContext((fs.readFileSync('static/web/toni/formatting.js','utf8')+fs.readFileSync('static/web/toni/bw-collection.js','utf8')),context);
  assert.equal(matchingCount.textContent,'3 results');
  detailRoot.bcCollectionList=saved;detailRoot.type='S';
  vm.runInNewContext((fs.readFileSync('static/web/toni/formatting.js','utf8')+fs.readFileSync('static/web/toni/bw-collection.js','utf8')),context);
  assert.equal(matchingCount.textContent,'3 sets');
 }
})().catch(e=>{console.error(e);process.exitCode=1;});

// Display-only name spacing preserves the original filter and sort records.
for(const name of ['Brick 1 x 2','Brick 2 x 4','Brick 1 x 1 x 3','Brick 1']){
 const row=api.buildRow({...records[1],name,lot_links:[]},root.dataset,false,()=>{});
 assert.ok(texts(row).includes(api.nowrapTail(name)));
 assert.equal(name.includes('\u00a0'),false);
}
assert.equal(api.nowrapTail('Brick 1 x 2'),'Brick 1\u00a0x\u00a02');
const dimensional=[{name:'Brick 1 x 6',number:'6'},{name:'Brick 1 x 2',number:'2'}];
assert.equal(api.filterRows(dimensional,'Brick 1 x 2')[0].number,'2');
assert.deepEqual(api.filterRows(dimensional,'',{},'name').map(r=>r.number),['2','6']);
for(const [file,global] of [['bw-workbench','BrickWorkbench'],['bw-checker','BrickChecker']]){
 const other={window:{},document:{querySelector(){return null;},addEventListener(){}}};
 vm.runInNewContext((fs.readFileSync('static/web/toni/formatting.js','utf8')+fs.readFileSync('static/web/toni/'+file+'.js','utf8')),other);
 assert.equal(other.window[global].nowrapTail('Brick 1 x 2'),api.nowrapTail('Brick 1 x 2'));
}

// 4.7d: compact facts retain identity and recompute over the full filtered view.
const summaryRows=[{number:'7286-1',name:'Transport',missing_parts:15},{number:'2260-1',name:'Dragon',missing_parts:1,missing_figures:2},{number:'done'}];
assert.equal(api.missingSummary(summaryRows),'Missing in view: 15 parts in 7286-1 · 1 part, 2 figs in 2260-1');
assert.equal(api.missingSummary(api.filterRows(summaryRows,'Dragon')),'Missing in view: 1 part, 2 figs in 2260-1');
assert.equal(api.missingSummary(api.filterRows(summaryRows,'done')),'');
// 49b: Instructions and Parts open as rows on a phone, the grid stays one tap away; Sets and wide screens keep the grid.
for(const [type,narrow,expected] of [['I',true,'list'],['P',true,'list'],['S',true,'grid'],['I',false,'grid']]){
 const box={dataset:{view:'grid'}},btn={dataset:{bcView:'grid'},setAttribute(){},addEventListener(){}};
 const saveMatch=context.matchMedia;context.matchMedia=q=>({matches:narrow&&q.includes('max-width: 767px'),addEventListener(){}});
 api.viewSwitch({querySelectorAll:()=>[btn]},box,'bc','k-'+type+narrow,type);context.matchMedia=saveMatch;
 assert.equal(box.dataset.view,expected);
}
// 49b: 84 incomplete sets stay one short line (first three, then a count).
const manyRows=Array.from({length:84},(_,i)=>({number:(100+i)+'-1',missing_parts:i+1}));
assert.equal(api.missingSummary(manyRows),'Missing in view: 1 part in 100-1 · 2 parts in 101-1 · 3 parts in 102-1 · and 81 more');
assert.ok(api.missingSummary(manyRows).length<120);
assert.equal(api.listNoun('I'),'booklets');assert.equal(api.listNoun('P'),'parts');assert.equal(api.resultNoun('I'),'instructions');
for(const [kind,noun] of Object.entries({S:'sets',M:'minifigures',P:'parts',I:'instructions',O:'boxes',G:'gear'}))assert.equal(api.resultNoun(kind),noun);
for(const available of [true,false]){
 const row=api.buildRow({...records[1],pdf_available:available,lot_links:[]},{...root.dataset,type:'I'},false,()=>{});
 assert.ok(texts(row).includes(available?'PDF available':'No PDF'));
}
assert.deepEqual(api.filterRows([{number:'expensive',price:['EUR','100']},{number:'cheap',price:['EUR','9']}],'',{},'used_price').map(r=>r.number),['cheap','expensive']);

for(const direction of ['asc','desc'])assert.equal(api.filterRows([{number:'none'},{number:'zero',price:['EUR','0']},{number:'priced',price:['EUR','2']}],'',{},'used_price',direction).at(-1).number,'none');
const dimensionPart={...records[1],name:'Bracket 1 x 2 - 1 x 2 Inverted',lot_links:[]};
assert.ok(texts(api.buildRow(dimensionPart,root.dataset,false,()=>{})).includes('Bracket 1 x 2 · 1 x 2\u00a0Inverted'));
assert.equal(dimensionPart.name,'Bracket 1 x 2 - 1 x 2 Inverted');
// The search box renders once per pause (120 ms), not once per key.
{
  const fired=[];let pending=null,cleared=0;
  context.setTimeout=(fn,ms)=>{pending={fn,ms};return 1;};context.clearTimeout=()=>{cleared++;pending=null;};
  const typed=api.debounce(value=>fired.push(value),120);
  for(const key of ['b','br','bri','bric','brick'])typed(key);
  assert.deepEqual(fired,[]);assert.equal(pending.ms,120);assert.equal(cleared,5);
  pending.fn();assert.deepEqual(fired,['brick']);
  delete context.setTimeout;delete context.clearTimeout;
}
