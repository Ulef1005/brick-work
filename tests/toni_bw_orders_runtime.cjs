const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const code=fs.readFileSync('static/web/toni/bw-orders.js','utf8');
class Node {
  constructor(tag='div'){this.tagName=tag.toUpperCase();this.events={};this.dataset={};this.children=[];this.hidden=false;this.value='';this.attributes={};this.parentElement={firstChild:{textContent:'Sort'}};}
  addEventListener(type,fn){(this.events[type]??=[]).push(fn);}
  async trigger(type='click',extra={}){for(const fn of this.events[type]||[])await fn({preventDefault(){},stopPropagation(){},target:this,...extra});}
  dispatchEvent(e){this.trigger(e.type);}
  querySelector(s){return this.nodes?.[s]||null;}
  querySelectorAll(s){return this.groups?.[s]||[];}
  setAttribute(k,v){this.attributes[k]=v;}
  append(...nodes){this.children.push(...nodes);}
  replaceChildren(){this.children=[];}
  after(node){this.afterNode=node;}
  focus(){this.focused=true;}
  contains(node){return node===this||this.children.includes(node);}
}
const root=new Node(),doc=new Node();doc.querySelector=()=>root;doc.createElement=tag=>new Node(tag);doc.createTextNode=text=>({textContent:text});
const mark=new Node(),received=new Node(),chip=new Node(),row=new Node(),stepLabel=new Node(),stepInput=new Node('input'),progress=new Node(),bar=new Node();bar.style={};progress.dataset={ordered:'7'};chip.dataset={ordered:'7'};row.nodes={'.order-count-state':chip};received.closest=()=>row;stepInput.min='0';stepInput.max='7';stepInput.value='2';stepLabel.nodes={input:stepInput};stepInput.before=n=>{stepInput.minus=n};stepInput.after=n=>{stepInput.plus=n};received.max='7';received.value='2';
const reset=new Node(),form=new Node(),article=new Node(),gap=new Node('input'),stock=new Node('input');
gap.dataset={allocation:JSON.stringify({line_id:1,target_type:'copy',copy_id:'c',target:'part',target_id:'p'}),gapNeed:'3'};gap.max='2';stock.dataset={allocation:JSON.stringify({line_id:1,target_type:'stock'})};stock.max='2';
article.groups={'[data-allocation]':[gap,stock]};form.groups={'[data-rows]>article':[article]};
const select=new Node('select');select.options=[{value:'rank',textContent:'Saved order',selected:true},{value:'name',textContent:'Name',selected:false}];select.selectedIndex=0;select.value='rank';
const drop=new Node(),file=new Node('input'),filename=new Node();file.files=[];drop.nodes={'input':file,'[data-file-name]':filename};
const load=new Node(),placed=new Node(),status=new Node();
root.dataset={url:'/workbench/orders/action/ACTION',csrf:'token'};
root.nodes={'[data-progress]':progress,'[data-bar]':bar,'[data-mark-received]':mark,'form[data-action="allocate"]':form,'[data-reset-suggestion]':reset,'[data-load-orders]':load,'[data-placed-message]':status,'[data-placed-orders]':placed};
root.groups={'select':[select],'[data-received]':[received],'[data-drop]':[drop],'.order-stepper':[stepLabel]};
const calls=[],navigations=[];let fail=false;
const sandbox={window:{},document:doc,Event:class {constructor(type){this.type=type;}},location:{assign:url=>navigations.push(url)},fetch:async(url,options)=>{
 const data=JSON.parse(options.body);calls.push({url,data});
 if(url.endsWith('placed'))return {ok:true,json:async()=>({orders:[{number:'1',store:'Existing',date:'',imported:true},{number:'2',store:'New',date:'2026-10-01',imported:false}]})};
 return {ok:!fail,json:async()=>fail?{message:'Network unavailable'}:{url:'/order/2'}};
}};
vm.runInNewContext(code,sandbox);
const {suggest}=sandbox.window.BrickOrders;
assert.deepEqual(JSON.parse(JSON.stringify(suggest([{available:2,gaps:[{key:'p',need:3}]},{available:5,gaps:[{key:'p',need:3}]}]))),[{gaps:[2],stock:0},{gaps:[1],stock:4}]);
assert.deepEqual(JSON.parse(JSON.stringify(suggest([{available:0,gaps:[]},{available:4,gaps:[]}]))),[{gaps:[],stock:0},{gaps:[],stock:4}]);
(async()=>{
 assert.equal(gap.value,2);assert.equal(stock.value,0);
 gap.value='0';await reset.trigger();assert.equal(gap.value,2);
 await mark.trigger();assert.equal(received.value,'7');assert.equal(chip.textContent,'Complete');assert.equal(progress.textContent,'7 of 7 pieces counted');assert.equal(bar.style.width,'100%');
 await stepInput.minus.trigger();assert.equal(stepInput.value,'1');await stepInput.plus.trigger();await stepInput.plus.trigger();assert.equal(stepInput.value,'3');stepInput.value='0';await stepInput.trigger('input');
 received.value='3';await stepInput.trigger('input');assert.equal(chip.textContent,'4 short');
 assert.equal(select.hidden,true);const box=select.afterNode,opener=box.children[0],menu=box.children[1];
 await opener.trigger();assert.equal(menu.hidden,false);assert.equal(opener.attributes['aria-expanded'],'true');
 await menu.children[1].trigger();assert.equal(select.value,'name');assert.equal(menu.hidden,true);assert.equal(opener.focused,true);
 await opener.trigger();await box.trigger('keydown',{key:'Escape'});assert.equal(menu.hidden,true);
 await drop.trigger('drop',{dataTransfer:{files:[{name:'order.xml'}]}});assert.equal(file.files[0].name,'order.xml');assert.equal(filename.textContent,'order.xml');
 await load.trigger();assert.equal(load.disabled,false);assert.equal(placed.children[0].children[0].disabled,true);
 const checkbox=placed.children[1].children[0],submit=placed.children[2];assert.equal(submit.textContent,'Import selected orders');checkbox.checked=true;await checkbox.trigger('change');
 assert.equal(submit.textContent,'Import 1 order');assert.equal(submit.className,'primary');
 fail=true;await submit.trigger();assert.equal(checkbox.checked,true);assert.equal(submit.disabled,false);assert.match(status.textContent,/Retry/);assert.equal(navigations.length,0);
 fail=false;await submit.trigger();assert.equal(checkbox.checked,false);assert.equal(checkbox.disabled,true);assert.equal(navigations[0],'/order/2');assert.equal(calls.at(-1).data.number,'2');assert.equal(calls.at(-1).data.csrf_token,'token');
 console.log('Orders suggestions, mark received, custom select, XML drop, placed checkboxes and import retry passed');
})().catch(error=>{console.error(error);process.exitCode=1;});
