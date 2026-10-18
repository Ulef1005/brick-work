const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
class Node {
 constructor(){this.events={};this.dataset={};this.value='';this.hidden=false;this.disabled=false;this.textContent='';}
 addEventListener(name,fn){this.events[name]=fn;}
 querySelector(selector){return this.nodes?.[selector] || null;}
 querySelectorAll(selector){return this.groups?.[selector] || [];}
 async trigger(name='click',extra={}){return this.events[name]?.({preventDefault(){},currentTarget:this,...extra});}
}
const message=new Node(), undo=new Node(),status=new Node(),button=new Node();
const form=new Node();form.dataset={action:'booklets'};form.elements={quantity:{value:'2'},text:{value:'6081\n7286-1'}};form.nodes={'[data-form-message]':status};form.groups={button:[button]};
const found=new Node(),foundStatus=new Node(),badge=new Node(),remaining=new Node(),card=new Node(),assignment=new Node();
assignment.dataset={assignment:'6'};assignment.value='3';assignment.max='3';
card.nodes={'[data-badge]':badge,'[data-remaining]':remaining};card.dataset={need:3};
const dialog={closed:false,close(){this.closed=true;}};
found.dataset={action:'found',identity:JSON.stringify({item_type:'P',item_no:'3020',color_id:11})};
found.elements={quantity:{value:'3'},destination:{value:'set'}};
found.nodes={'[data-form-message]':foundStatus};found.groups={button:[new Node()],'[data-assignment]':[assignment]};
found.closest=selector=>selector==='dialog'?dialog:card;
const root=new Node();root.dataset={mode:'matcher',csrf:'token',url:'/workbench/save/ACTION'};root.nodes={'[data-message]':message,'[data-undo]':undo};root.groups={'form[data-action]':[form,found]};
const doc=new Node();doc.querySelector=()=>root;
let calls=[],reloads=0,fail=false;
const context={window:{},document:doc,location:{reload(){reloads++;}},fetch:async(url,options)=>{calls.push({url,data:JSON.parse(options.body)});return {ok:!fail,json:async()=>fail?{message:'Changed · try again'}:{event_id:42,message:'Saved'}};}};
vm.runInNewContext((fs.readFileSync('static/web/toni/formatting.js','utf8')+fs.readFileSync('static/web/toni/bw-workbench.js','utf8')),context);
const api=context.window.BrickWorkbench;
assert.equal(api.filterRows([{filterValue:'Light Bluish Gray',rank:0}], '', 'Light Bluish Gray', 'rank').length,1);
assert.equal(api.step(0,-1,5),0);assert.equal(api.step(5,1,5),5);
assert.equal(api.filterRows([{filterValue:'P M',rank:0}], '', 'M', 'rank').length,1);
assert.equal(api.filterRows([{filterValue:'P M',rank:0}], '', 'I', 'rank').length,0);
const rows=[{name:'Plate',number:'3020',colour:'Black',need:3,filterValue:'P',rank:0},{name:'Brick',number:'3004',colour:'Red',need:8,filterValue:'P',rank:1},{name:'Booklet',number:'6081-1',filterValue:'I',rank:2}];
assert.equal(api.filterRows(rows,'black','P','number').length,1);
assert.equal(api.filterRows(rows,'','P','need')[0].number,'3004');
assert.equal(api.filterRows(rows,'','I','rank')[0].name,'Booklet');
// #52: the set list pages 15 at a time.
assert.equal(api.PAGE,15);assert.equal(api.rangeText(40,2),'16 to 30 of 40');assert.equal(api.rangeText(40,3),'31 to 40 of 40');
assert.equal(api.clampPage(40,9),3);assert.equal(api.clampPage(0,2),1);
assert.deepEqual([...api.pageItems(3,1)],[1,2,3]);assert.deepEqual([...api.pageItems(10,5)],[1,'…',4,5,6,'…',10]);
(async()=>{
 fail=true;await form.trigger('submit');assert.equal(status.textContent,'Changed · try again');assert.equal(form.elements.text.value,'6081\n7286-1');assert.equal(button.disabled,false);assert.equal(reloads,0);
 fail=false;await form.trigger('submit');assert.equal(reloads,1);assert.equal(undo.hidden,false);assert.equal(calls[1].data.csrf_token,'token');assert.equal(calls[1].data.quantity,'2');
 await found.trigger('submit');assert.equal(calls[2].url,'/workbench/save/found');assert.equal(calls[2].data.assignments['6'],'3');assert.equal(badge.textContent,'3 found');assert.equal(assignment.max,0);assert.equal(assignment.value,0);assert.equal(dialog.closed,true);assert.equal(reloads,1);
 await undo.trigger();await new Promise(setImmediate);assert.equal(calls[3].url,'/workbench/save/undo');assert.equal(calls[3].data.event_id,42);assert.equal(reloads,2);
 await doc.trigger('keydown',{key:'z',target:{tagName:'BODY'}});await new Promise(setImmediate);assert.equal(calls[4].data.event_id,42);
 console.log('Brick Work workbench runtime passed');
})().catch(error=>{console.error(error);process.exitCode=1;});
// Selection mode applies to the complete snapshot, including filtered-out rows.
{
 const selection=new Node(),all=new Node(),choose=new Node(),next=new Node(),copies=[new Node(),new Node()];
 const r=new Node();r.dataset={mode:'picker'};
 r.nodes={'[data-message]':new Node(),'[data-undo]':new Node(),'[data-selection]':selection,'[data-all]':all,'[data-none]':choose,'[data-continue]':next};
 r.groups={'input[name=copy]':copies};
 for(const node of [all,choose])node.setAttribute=(key,value)=>{node[key]=value;};
 const d=new Node();d.querySelector=()=>r;
 vm.runInNewContext((fs.readFileSync('static/web/toni/formatting.js','utf8')+fs.readFileSync('static/web/toni/bw-workbench.js','utf8')),{window:{},document:d});
 assert.ok(copies.every(c=>c.checked));assert.equal(next.textContent,'Continue · 2 sets');
 choose.trigger();assert.ok(copies.every(c=>!c.checked));assert.equal(choose['aria-pressed'],'true');
 copies[0].checked=true;copies[0].trigger('change');assert.equal(next.textContent,'Continue · 1 set');
 all.trigger();assert.ok(copies.every(c=>c.checked));assert.equal(all['aria-pressed'],'true');
 copies[0].checked=true;copies[1].checked=false;
 vm.runInNewContext((fs.readFileSync('static/web/toni/formatting.js','utf8')+fs.readFileSync('static/web/toni/bw-workbench.js','utf8')),{window:{},document:d});
 assert.deepEqual(copies.map(c=>c.checked),[true,false]);assert.equal(next.textContent,'Continue · 1 set');
 assert.equal(all['aria-pressed'],'false');assert.equal(choose['aria-pressed'],'true');
}
// Reordering changes DOM/submission order, including with the keyboard drag handle.
{
 const ranking=new Node(),summary=new Node(),r=new Node(),d=new Node();
 r.dataset={mode:'matcher'};r.nodes={'[data-message]':new Node(),'[data-undo]':new Node(),'[data-rank-keys]':ranking,'[data-rank-summary]':summary};d.querySelector=()=>r;
 const make=(key,label,checked,disabled=false)=>{
  const row=new Node(),input=new Node();
  row.dataset={rankKey:key};input.checked=checked;input.disabled=disabled;
  row.nodes={input,'label span':{textContent:label},'[data-rank-position]':new Node(),'[data-drag]':new Node()};
  Object.defineProperty(row,'nextSibling',{get(){return ranking.children[ranking.children.indexOf(row)+1] || null;}});return row;
 };
 const storage=make('storage','Storage',true),colour=make('colour','Colour',true),category=make('category','Category',false),size=make('size','Size',false,true);
 ranking.children=[storage,colour,category,size];ranking.insertBefore=(row,target)=>{ranking.children=ranking.children.filter(n=>n!==row);const i=target?ranking.children.indexOf(target):ranking.children.length;ranking.children.splice(i,0,row);};
 vm.runInNewContext((fs.readFileSync('static/web/toni/formatting.js','utf8')+fs.readFileSync('static/web/toni/bw-workbench.js','utf8')),{window:{},document:d});
 assert.equal(summary.textContent,'Storage, then colour');
 const original=ranking.children.slice();
 size.nodes['[data-drag]'].trigger('keydown',{key:'ArrowUp'});
 assert.deepEqual(ranking.children,original);
 size.trigger('dragstart',{dataTransfer:{setData(){throw Error('Unavailable Size dragged');}}});colour.trigger('drop');
 assert.deepEqual(ranking.children,original);
 category.trigger('dragstart',{dataTransfer:{setData(){}}});size.trigger('drop');
 assert.deepEqual(ranking.children,original);
 // A reason also prevents moving a row independently of the toggle state.
 size.nodes.input.disabled=false;size.nodes['[aria-disabled="true"]']=size.nodes['[data-drag]'];
 size.nodes['[data-drag]'].trigger('keydown',{key:'ArrowUp'});
 assert.deepEqual(ranking.children,original);size.nodes.input.disabled=true;
 colour.nodes['[data-drag]'].trigger('keydown',{key:'ArrowUp'});assert.equal(ranking.children[0],colour);assert.equal(summary.textContent,'Colour, then storage');
 colour.nodes['[data-drag]'].trigger('keydown',{key:'ArrowDown'});assert.equal(ranking.children[1],colour);
 colour.nodes['[data-drag]'].trigger('keydown',{key:'ArrowUp'});
 category.nodes.input.checked=true;category.nodes.input.trigger('change');assert.equal(category.nodes['[data-rank-position]'].textContent,'3');
 category.trigger('dragstart',{dataTransfer:{setData(){}}});colour.trigger('drop');assert.equal(ranking.children[0],category);assert.equal(summary.textContent,'Category, then colour, then storage');
 size.nodes.input.checked=true;size.nodes.input.trigger('change');assert.ok(!summary.textContent.includes('size'));
 for(const row of ranking.children)row.nodes.input.checked=false;size.nodes.input.trigger('change');assert.equal(summary.textContent,'Default order');
}
// Pick progress, filtering and one responsive form, including inline saves.
{
 const r=new Node(),d=new Node(),list=new Node(),container=new Node(),search=new Node(),filter=new Node(),sort=new Node(),chips=new Node(),back=new Node(),skip=new Node();
 r.dataset={mode:'picker',csrf:'token',url:'/workbench/save/ACTION'};list.dataset={list:'parts'};sort.value='rank';filter.options=[{},{}];sort.focus=()=>{};chips.replaceChildren=()=>{};chips.append=()=>{};
 list.nodes={'[data-rows]':container,'[data-search]':search,'[data-filter]':filter,'[data-sort]':sort,'[data-count]':new Node(),'[data-chips]':chips,'[data-filters]':new Node(),'[data-filter-panel]':new Node(),'[data-sort-toggle]':new Node(),'[data-sort-panel]':new Node()};
 list.nodes['[data-sort-toggle]'].setAttribute=(key,value)=>{list.nodes['[data-sort-toggle]'][key]=value;};list.nodes['[data-sort-panel]'].hidden=true;
 const doneSort=new Node();doneSort.setAttribute=(key,value)=>{doneSort[key]=value;};list.groups={'[data-sort-toggle]':[list.nodes['[data-sort-toggle]'],doneSort]};
 const filterToggle=list.nodes['[data-filters]'],doneFilter=new Node();
 filterToggle.setAttribute=(key,value)=>{filterToggle[key]=value;};doneFilter.setAttribute=(key,value)=>{doneFilter[key]=value;};filter.focus=()=>{};
 list.groups['[data-filters]']=[filterToggle,doneFilter];list.nodes['[data-filter-panel]'].hidden=true;
 const direction=new Node();direction.value='asc';list.nodes['[data-direction]']=direction;
 let isDesktop=true,mediaListener,calls=[];
 const cards=[0,1].map(index=>{
  const card=new Node(),selector=new Node(),dialog=new Node(),details=new Node(),form=new Node(),quantity=new Node(),count=new Node(),set=new Node(),loose=new Node(),only=new Node(),assign=new Node(),quantityLabel=new Node(),assignments=new Node(),opener=new Node(),close=new Node();
  card.dataset={name:index?'Brick':'Plate',number:String(3020+index),filterValue:'Black',colour:'Black'};
  count.value=quantity.value='2';assign.value='2';assign.max='2';assign.dataset={assignment:String(index+10)};set.checked=true;
  form.dataset={action:'found',identity:JSON.stringify({item_type:'P',item_no:card.dataset.number,color_id:11})};form.elements={quantity,destination:{value:'set'}};
  form.nodes={'[data-selector-count]':new Node(),'[data-quantity]':quantityLabel,'.bw-assignments':assignments,'input[name=destination]':set,'input[value="set"]':set,'input[value="loose"]':loose,'input[value="list"]':only,'[data-form-message]':new Node()};
  const choices=[set,loose,only].map(input=>({querySelector:()=>input,classList:{toggle(){}}}));
  form.groups={'[data-assignment]':[assign],'input[name=destination]':[set,loose,only],'.bw-destination':choices,button:[new Node()]};
  form.closest=sel=>sel==='dialog'?(isDesktop?null:dialog):card;assign.closest=()=>form;
  const decrement=new Node();decrement.dataset={step:'-1'};decrement.parentNode={querySelector:()=>assign};decrement.closest=()=>form;card.decrement=decrement;
  selector.closest=()=>card;selector.nodes={form,'[data-selector-close]':close};
  details.insertBefore=node=>{node.parentNode=details;};dialog.append=node=>{node.parentNode=dialog;};dialog.close=()=>{dialog.open=false;};dialog.nodes={form};
  opener.click=()=>{dialog.open=true;};set.focus=()=>{};
  card.nodes={'[data-part-position]':new Node(),'[data-part-progress]':new Node(),'[data-selector]':selector,'[data-mobile-selector]':dialog,'.bw-picker-details':details,'[data-found-count]':count,'[data-open]':opener,'form[data-action="found"]':form,'[data-badge]':new Node(),'[data-remaining]':new Node()};
  card.focus=()=>card.trigger('focus');
  return card;
 });
 container.groups={'[data-row]':cards};container.children=[...cards];container.append=node=>{container.children=container.children.filter(n=>n!==node);container.children.push(node);};
 r.nodes={'[data-message]':new Node(),'[data-back]':back,'[data-skip]':skip,'[data-pick]':list};
 r.groups={'[data-assignment]':cards.flatMap(c=>c.nodes['form[data-action="found"]'].groups['[data-assignment]']),'[data-step]':cards.map(c=>c.decrement),'[data-list]':[list],'[data-selector]':cards.map(c=>c.nodes['[data-selector]']),'form[data-action]':cards.map(c=>c.nodes['form[data-action="found"]'])};
 r.querySelector=selector=>selector==='dialog[open]'?cards.map(c=>c.nodes['[data-mobile-selector]']).find(n=>n.open)||null:r.nodes[selector]||null;d.querySelector=()=>r;
 d.createElement=()=>{const n=new Node();n.setAttribute=()=>{};return n;};
 const context={window:{},document:d,matchMedia:()=>({get matches(){return isDesktop;},addEventListener(type,fn){mediaListener=fn;}}),fetch:async(url,options)=>{calls.push(JSON.parse(options.body));return {ok:true,json:async()=>({event_id:99})};}};
 vm.runInNewContext((fs.readFileSync('static/web/toni/formatting.js','utf8')+fs.readFileSync('static/web/toni/bw-workbench.js','utf8')),context);
 filterToggle.trigger();assert.equal(list.nodes['[data-filter-panel]'].hidden,false);assert.equal(doneFilter['aria-expanded'],'true');
 doneFilter.trigger();assert.equal(list.nodes['[data-filter-panel]'].hidden,true);assert.equal(filterToggle['aria-expanded'],'false');
 list.nodes['[data-sort-toggle]'].trigger();assert.equal(list.nodes['[data-sort-panel]'].hidden,false);
 assert.equal(list.nodes['[data-sort-toggle]']['aria-expanded'],'true');assert.equal(doneSort['aria-expanded'],'true');
 doneSort.trigger();assert.equal(list.nodes['[data-sort-panel]'].hidden,true);
 assert.equal(list.nodes['[data-sort-toggle]']['aria-expanded'],'false');assert.equal(doneSort['aria-expanded'],'false');
 direction.value='desc';direction.trigger('change');assert.equal(cards[1].hidden,false);direction.value='asc';direction.trigger('change');assert.equal(cards[0].hidden,false);
 assert.equal(cards.filter(c=>!c.hidden).length,1);assert.equal(cards[0].nodes['[data-part-position]'].textContent,'Part 1 of 2');
 assert.equal(cards[0].nodes['[data-selector]'].parentNode,cards[0].nodes['.bw-picker-details']);
 skip.trigger();assert.equal(cards[1].hidden,false);assert.equal(cards[1].nodes['[data-part-position]'].textContent,'Part 2 of 2');
 back.trigger();assert.equal(cards[0].hidden,false);
 const form=cards[0].nodes['form[data-action="found"]'];
 assert.equal(form.nodes['[data-quantity]'].hidden,true);
 assert.equal(Number(form.nodes['[data-selector-count]'].textContent),2);
 const counter=cards[0].nodes['[data-found-count]'];counter.value='5';counter.trigger('input');assert.equal(Number(form.nodes['[data-selector-count]'].textContent),5);
 form.elements.quantity.value='4';form.elements.quantity.trigger('input');assert.equal(Number(form.nodes['[data-selector-count]'].textContent),4);
 form.nodes['input[value="set"]'].trigger('change');assert.equal(Number(form.nodes['[data-selector-count]'].textContent),2);
 cards[0].decrement.trigger();assert.equal(Number(form.nodes['[data-selector-count]'].textContent),1);
 const allocated=form.groups['[data-assignment]'][0];allocated.value='2';allocated.trigger('input');assert.equal(Number(form.nodes['[data-selector-count]'].textContent),2);
 let prevented=false;d.trigger('keydown',{key:'Enter',target:{tagName:'BUTTON'},preventDefault(){prevented=true;}});assert.equal(prevented,false);
 d.trigger('keydown',{key:'2',target:{tagName:'INPUT',type:'radio'}});assert.equal(form.nodes['input[value="loose"]'].checked,true);
 form.elements.destination.value='loose';form.nodes['input[value="loose"]'].trigger('change');assert.equal(form.nodes['[data-quantity]'].hidden,false);assert.equal(form.nodes['.bw-assignments'].hidden,true);
 form.elements.destination.value='set';form.nodes['input[value="set"]'].trigger('change');
 isDesktop=false;mediaListener();assert.equal(cards[0].nodes['[data-selector]'].parentNode,cards[0].nodes['[data-mobile-selector]']);
 d.trigger('keydown',{key:'Enter',target:{tagName:'BODY'}});assert.equal(cards[0].nodes['[data-mobile-selector]'].open,true);
 form.elements.destination.value='list';d.trigger('keydown',{key:'3',target:{tagName:'BODY'}});assert.equal(form.nodes['input[value="list"]'].checked,true);
 cards[0].nodes['[data-selector]'].nodes['[data-selector-close]'].trigger();assert.equal(cards[0].nodes['[data-mobile-selector]'].open,false);
 isDesktop=true;mediaListener();assert.equal(cards[0].nodes['[data-selector]'].parentNode,cards[0].nodes['.bw-picker-details']);
 search.value='Brick';search.trigger('input');assert.equal(list.nodes['[data-count]'].textContent,'1 result');assert.equal(cards[1].nodes['[data-part-position]'].textContent,'Part 1 of 1');
 search.value='';search.trigger('input');
 // A desktop count shortcut must keep the set payload equal to its copy allocations.
 const extra=new Node();extra.value='1';extra.max='1';extra.dataset={assignment:'other-copy'};
 form.groups['[data-assignment]'].push(extra);
 form.elements.destination.value='set';form.nodes['input[value="set"]'].trigger('change');
 d.trigger('keydown',{key:'4',target:{tagName:'BODY'}});
 d.trigger('keydown',{key:'Enter',target:{tagName:'BODY'}});
 assert.equal(Number(form.elements.quantity.value),3);
 assert.ok(r.nodes['[data-message]'].textContent.includes('copy assignments'));
 (async()=>{await form.trigger('submit');assert.equal(calls[0].destination,'set');assert.equal(Number(calls[0].quantity),Object.values(calls[0].assignments).reduce((sum,n)=>sum+Number(n),0));assert.equal(Number(calls[0].quantity),3);assert.equal(cards[1].hidden,false);assert.equal(cards[0].nodes['[data-badge]'].textContent,'3 found');})().catch(error=>{console.error(error);process.exitCode=1;});
}

// Selected picker error pages omit Undo; history and keyboard wiring still initialise.
{
 const r=new Node(),d=new Node(),message=new Node(),historyUndo=new Node();
 r.dataset={mode:'picker',url:'/workbench/save/ACTION'};
 historyUndo.dataset={undoEvent:'71'};
 r.nodes={'[data-message]':message};r.groups={'[data-undo-event]':[historyUndo]};d.querySelector=()=>r;
 const requests=[];
 vm.runInNewContext((fs.readFileSync('static/web/toni/formatting.js','utf8')+fs.readFileSync('static/web/toni/bw-workbench.js','utf8')),{
  window:{},document:d,location:{reload(){}},fetch:async(url,options)=>{requests.push(JSON.parse(options.body));return {ok:true,json:async()=>({})};}
 });
 assert.equal(typeof d.events.keydown,'function');
 d.trigger('keydown',{key:'m',target:{tagName:'BODY'}});
 assert.equal(message.textContent,'Still missing · count unchanged');
 (async()=>{await historyUndo.trigger();assert.equal(requests[0].event_id,'71');})().catch(error=>{console.error(error);process.exitCode=1;});
}
