const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const sandbox={window:{},document:{querySelector:()=>null}};
vm.runInNewContext((fs.readFileSync('static/web/toni/formatting.js','utf8')+fs.readFileSync('static/web/toni/bw-ledger.js','utf8')),sandbox);
const {filterRows,payload}=sandbox.window.BrickLedger;
const rows=[{name:'Brick',number:'3004',colour:'Black',filterValue:'P',need:3,rank:0},{name:'Plate',number:'3020',colour:'White',filterValue:'P',need:6,rank:1},{name:'Figure',number:'abc',filterValue:'M',need:1,rank:2}];
assert.equal(filterRows(rows,'black','P','rank').length,1);
assert.equal(filterRows(rows,'','M','name')[0].name,'Figure');
assert.equal(filterRows(rows,'','','need')[0].name,'Plate');
assert.equal(filterRows(rows,'missing','','rank').length,0);
const controls={received:[{id:'7',value:'3'}],pairs:[{id:'8',value:'7'}],selections:[{entity:'copy',id:'c'}],allocations:[{line_id:7,target_type:'stock',quantity:0},{line_id:7,target_type:'copy',quantity:2}]};
assert.equal(payload('received',{},controls,{order_id:1}).counts[7],'3');
assert.equal(payload('save',{},controls).pairs[8],'7');
assert.equal(payload('move',{},controls).selections[0].entity,'copy');
assert.equal(payload('allocate',{},controls).chosen.length,1);
assert.equal(payload('allocate',{},controls).chosen[0].target_type,'copy');
console.log('Ledger runtime passed');
class Node {
  constructor(tag='div'){this.tagName=tag.toUpperCase();this.events={};this.dataset={};this.hidden=false;this.disabled=false;this.textContent='';this.attributes={};this.children=[];this.parentNode=null;this.attributeChanges=[];}
  click(){return this.trigger('click');}
  focus(){this.focused=true;}
  addEventListener(name,fn,capture=false){(this.events[name]??=[]).push({fn,capture});}
  querySelector(s){return this.nodes?.[s] || null;}
  querySelectorAll(s){return this.groups?.[s] || [];}
  setAttribute(k,v){this.attributes[k]=v;this.attributeChanges.push(['set',k,v]);}
  getAttribute(k){return this.attributes[k] ?? null;}
  removeAttribute(k){delete this.attributes[k];this.attributeChanges.push(['remove',k]);}
  append(...nodes){for(const node of nodes){node.remove();node.parentNode=this;this.children.push(node);}}
  remove(){if(this.parentNode){this.parentNode.children=this.parentNode.children.filter(node=>node!==this);this.parentNode=null;}}
  replaceChildren(...nodes){for(const node of [...this.children])node.remove();this.append(...nodes);}
  closest(selector){return selector==='.bc-picture,.bw-picture'?this.parentNode:null;}
  async trigger(name='click',extra={}){for(const {fn} of this.events[name] || [])await fn({preventDefault(){},currentTarget:this,...extra});}
}
const form=new Node(),button=new Node(),status=new Node(),message=new Node(),allocation=new Node(),undo=new Node();
form.dataset={action:'allocate',context:JSON.stringify({order_id:9})};form.values={};allocation.dataset={allocation:JSON.stringify({line_id:7,target_type:'stock'})};allocation.value='2';
form.nodes={'[data-form-message]':status,'[data-storage="7"]':{value:'box'},'[data-lot="7"]':{value:'lot'}};form.groups={button:[button],'[data-allocation]':[allocation]};
undo.dataset={undoEvent:'42'};
const retry=new Node(),notice=new Node();notice.hidden=true;
form.requestSubmit=()=>form.trigger('submit');
const root=new Node();root.dataset={csrf:'secret',url:'/workbench/orders/action/ACTION'};root.nodes={'[data-message]':message,'[data-retry]':retry,'[data-notice]':notice};root.groups={'form[data-action]':[form],'[data-undo-event]':[undo]};
const doc=new Node();doc.querySelector=()=>root;
doc.createElement=tag=>new Node(tag);
const tile=new Node(),img=new Node('img');tile.dataset.itemNo='3004';img.setAttribute('src','/manage/images/404');tile.append(img);
root.groups['.bw-picture img']=[img];
class FormDataMock {constructor(form){this.values={...form.values};}*[Symbol.iterator](){yield* Object.entries(this.values);}set(k,v){this.values[k]=v;}}
let calls=[],navigations=[],fail=true;
const live={window:{},document:doc,FormData:FormDataMock,location:{href:'/order/9',assign(url){navigations.push(url);},reload(){navigations.push('reload');}},fetch:async(url,options)=>{calls.push({url,data:JSON.parse(options.body)});return {ok:!fail,json:async()=>fail?{message:'Received quantity changed · review the allocation'}:{message:'Saved',event_id:42}};}};
vm.runInNewContext(fs.readFileSync('static/web/toni/images.js','utf8'),live);
vm.runInNewContext((fs.readFileSync('static/web/toni/formatting.js','utf8')+fs.readFileSync('static/web/toni/bw-ledger.js','utf8')),live);
(async()=>{
  assert.equal(doc.events.error.length,1);assert.equal(doc.events.error[0].capture,true);
  // Native error events reach document capture before the detached target's listeners.
  for(const attempt of [1,2]){
    const screen=`Ledger picture failure ${attempt}`;
    await assert.doesNotReject(async()=>{await doc.trigger('error',{target:img});await img.trigger('error',{target:img});},screen);
    assert.equal(img.parentNode,null,screen);assert.equal(tile.children.length,3,screen);
    assert.equal(tile.children[0].textContent,'3004',screen);
    assert.equal(tile.children.filter(node=>node.textContent==='No image').length,1,screen);
    const retry=tile.children[2];assert.equal(retry.textContent,'Retry',screen);assert.equal(retry.type,'button',screen);
    img.attributeChanges=[];await retry.trigger();
    assert.deepEqual(tile.children,[img],screen);assert.equal(img.parentNode,tile,screen);
    assert.equal(img.getAttribute('src'),'/manage/images/404',screen);
    assert.deepEqual(img.attributeChanges,[['remove','src'],['set','src','/manage/images/404']],screen);
  }
  console.log('Shared ledger missing-picture tile, item number and Retry passed');
  await form.trigger('submit');assert.equal(navigations.length,0);assert.equal(allocation.value,'2');assert.equal(button.disabled,false);assert.match(status.textContent,/Received quantity changed/);
  assert.equal(notice.hidden,false);assert.equal(retry.hidden,false);
  fail=false;await retry.trigger();assert.equal(navigations[0],'/order/9');assert.equal(calls[1].data.csrf_token,'secret');assert.equal(calls[1].data.order_id,9);assert.equal(calls[1].data.chosen[0].target_type,'stock');assert.equal(calls[1].data.chosen[0].storage_id,'box');assert.equal(calls[1].data.chosen[0].lot_id,'lot');
  await undo.trigger();assert.equal(calls[2].url,'/workbench/orders/action/undo');assert.equal(calls[2].data.event_id,42);assert.equal(navigations[1],'reload');
  fail=true;await undo.trigger();assert.equal(navigations.length,2);assert.equal(undo.disabled,false);
  const beforeRetry=calls.length;await retry.trigger();assert.equal(calls.length,beforeRetry+1);assert.equal(calls.at(-1).url,'/workbench/orders/action/undo');assert.equal(navigations.length,2);
  root.dataset.url='/workbench/storage/action/ACTION';
  form.dataset={action:'archive',context:JSON.stringify({id:'box'})};
  form.groups={button:[button]};form.values={move_to_unstored:'yes'};
  fail=false;await form.trigger('submit');
  assert.equal(calls.at(-1).url,'/workbench/storage/action/archive');
  assert.equal(calls.at(-1).data.id,'box');assert.equal(calls.at(-1).data.move_to_unstored,'yes');
  form.values={};await form.trigger('submit');assert.equal(calls.at(-1).data.move_to_unstored,undefined);
  fail=true;form.values={move_to_unstored:'yes'};const count=navigations.length;
  await form.trigger('submit');assert.equal(navigations.length,count);
  assert.equal(form.values.move_to_unstored,'yes');assert.equal(button.disabled,false);
  console.log('Ledger save, failure, archive and Undo runtime passed');
})().catch(error=>{console.error(error);process.exitCode=1;});

// The shared list renderer pages the whole list, and clamps after filtering.
{
  const list=new Node(),container=new Node(),search=new Node('input'),filter=new Node('select'),sort=new Node('select'),count=new Node(),chips=new Node(),filters=new Node(),panel=new Node();
  search.value='';filter.value='';sort.value='rank';panel.hidden=true;
  const rows=Array.from({length:17},(_,i)=>{const row=new Node();row.dataset={name:'Part '+i,number:String(i),filterValue:i<2?'M':'P'};return row;});
  container.groups={'[data-row]':rows};container.append(...rows);
  list.nodes={'[data-rows]':container,'[data-search]':search,'[data-filter]':filter,'[data-sort]':sort,'[data-count]':count,'[data-chips]':chips,'[data-filters]':filters,'[data-filter-panel]':panel};
  const pagedRoot=new Node();pagedRoot.dataset={pageSize:'15'};pagedRoot.nodes={'[data-message]':new Node()};pagedRoot.groups={'[data-list]':[list]};
  const pagedDoc=new Node();pagedDoc.querySelector=()=>pagedRoot;pagedDoc.createElement=tag=>new Node(tag);
  vm.runInNewContext(fs.readFileSync('static/web/toni/formatting.js','utf8')+fs.readFileSync('static/web/toni/bw-ledger.js','utf8'),{window:{},document:pagedDoc});
  const pager=list.children.at(-1),previous=pager.children[0],position=pager.children[1],next=pager.children[2];
  assert.equal(rows.filter(row=>!row.hidden).length,15);assert.equal(previous.disabled,true);assert.equal(position.textContent,'1 of 2');
  next.trigger();assert.equal(rows.filter(row=>!row.hidden).length,2);assert.equal(next.disabled,true);assert.equal(position.textContent,'2 of 2');
  filter.value='M';filter.trigger('change');assert.equal(rows.filter(row=>!row.hidden).length,2);assert.equal(pager.hidden,true);assert.equal(chips.children.length,1);
  chips.children[0].trigger();assert.equal(rows.filter(row=>!row.hidden).length,15);assert.equal(filter.value,'');
  console.log('Ledger 15-row pager, filter clamping and removable chips passed');
}
