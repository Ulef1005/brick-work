/* Exercise the wishlist controller's forms, receipt, failure and download seams. */
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
class Node {
 constructor(dataset={}){this.dataset=dataset;this.events={};this.nodes={};this.groups={};this.children=[];this.hidden=false;this.disabled=false;this.value='';}
 addEventListener(k,f){this.events[k]=f;}
 querySelector(s){return this.nodes[s] || null;}
 querySelectorAll(s){return this.groups[s] || [];}
 append(n){this.children.push(n);}
 replaceChildren(){this.children=[];}
 showModal(){this.open=true;}
 close(){this.open=false;}
 closest(){return sheet;}
 click(){this.clicked=true;}
}
const message=new Node(),undo=new Node(),count=new Node(),summary=new Node(),content=new Node(),sheet=new Node(),open=new Node({wlOpen:'lists'}),close=new Node();
const create=new Node({wlAction:'save'}),transfer=new Node({wlAction:'transfer'}),exp=new Node({wlExportUrl:'/planning/wishlists/all/export.FORMAT'});
create.values={name:'Gifts',bricklink_id:''};transfer.values={list_id:'gifts'};exp.values={format:'csv',kind:'parts'};
for(const form of [create,transfer,exp])form.nodes.button=new Node();
const root=new Node({wlUrl:'/planning/wishlists/ACTION',csrf:'csrf'}),bar=new Node(),clear=new Node();
root.nodes={'[data-wl-message]':message,'[data-wl-undo]':undo,'[data-wl-count]':count,'[data-wl-export]':exp,'[data-wl-summary]':summary,'[data-wl-summary-content]':content};
root.nodes['[data-wl-selection]']=bar;root.nodes['[data-wl-clear]']=clear;
root.groups={'[data-wl-open]':[open],'[data-wl-close]':[close],'form[data-wl-action]':[create,transfer]};
let selected=[{value:'1',checked:true},{value:'2',checked:true}];const events={},requests=[],storage=new Map([['bw-wishlists-receipt','41']]);
let fail=false,reloads=0,download;
const document={querySelector:s=>root.querySelector(s),querySelectorAll:s=>s==='[data-wl-root]'?[root]:s==='[data-wl-selected]:checked'?selected.filter(c=>c.checked):root.querySelectorAll(s),getElementById:()=>sheet,addEventListener:(k,f)=>events[k]=f,createElement:()=>{const n=new Node();download=n;return n;}};
const context={document,sessionStorage:{getItem:k=>storage.get(k),setItem:(k,v)=>storage.set(k,v),removeItem:k=>storage.delete(k)},location:{reload:()=>reloads++},FormData:class{constructor(form){return Object.entries(form.values);}},Blob:class{},URL:{createObjectURL:()=> 'blob:download',revokeObjectURL(){}},setTimeout:f=>f(),fetch:async(url,options)=>{
 requests.push({url,body:options?JSON.parse(options.body):null});
 if(!options)return {ok:true,json:async()=>({filename:'wishlist.csv',mimetype:'text/csv',content:'Part,Color,Quantity\r\nrb,4,2\r\n',summary:{exported:1,omitted:[{item_no:'other',reason:'Missing mapping'}],notes:[]}})};
 return {ok:!fail,json:async()=>fail?{message:'An item already exists'}:{event_id:42}};
}};
vm.runInNewContext(fs.readFileSync('static/web/toni/bw-wishlists.js','utf8'),context);
const flush=()=>new Promise(r=>setImmediate(r));
async function submit(form,value=''){form.events.submit({preventDefault(){},target:form,submitter:Object.assign(form.nodes.button,{value})});await flush();}
(async()=>{
 assert.equal(undo.hidden,false);assert.equal(message.textContent,'Saved · Undo');
 open.events.click();assert.equal(sheet.open,true);close.events.click();assert.equal(sheet.open,false);
 await submit(create);assert.equal(requests.at(-1).body.values.name,'Gifts');assert.equal(requests.at(-1).body.values.bricklink_id,null);assert.equal(requests.at(-1).body.csrf_token,'csrf');assert.equal(reloads,1);
 assert.equal(count.textContent,'2 selected');assert.equal(bar.hidden,false);
 events.change({target:{matches:s=>s==='[data-wl-selected]'}});assert.equal(count.textContent,'2 selected');
 await submit(transfer,'true');assert.deepEqual(requests.at(-1).body.ids,[1,2]);assert.equal(requests.at(-1).body.copy,true);
 fail=true;await submit(transfer,'false');assert.equal(message.textContent,'An item already exists');assert.equal(transfer.nodes.button.disabled,false);assert.equal(reloads,2);
 clear.events.click();assert.equal(count.textContent,'0 selected');assert.equal(bar.hidden,true);
 selected[0].checked=true;events.change({target:{matches:s=>s==='[data-wl-selected]'}});assert.equal(count.textContent,'1 selected');assert.equal(bar.hidden,false);
 events.change({target:{matches:()=>false}});
 fail=false;await submit(exp);assert.equal(requests.at(-1).url,'/planning/wishlists/all/export.csv?summary=true&kind=parts');assert.equal(summary.hidden,false);assert.equal(content.children[1].textContent,'other · Missing mapping');assert.equal(download.download,'wishlist.csv');assert.equal(download.clicked,true);
 undo.events.click();await flush();assert.equal(requests.at(-1).body.event_id,41);assert.equal(storage.has('bw-wishlists-receipt'),false);
 console.log('Brick Work wishlists runtime passed');
})().catch(e=>{console.error(e);process.exitCode=1;});
