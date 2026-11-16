const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
class Node{
 constructor(){this.events={};this.dataset={};this.hidden=false;this.textContent='';}
 addEventListener(k,v){this.events[k]=v;}
 setAttribute(k,v){this[k]=v;}
}
const filters=new Node(),panel=new Node();panel.hidden=true;
const form=new Node(),results=new Node(),status=new Node(),retry=new Node(),clear=new Node(),root=new Node();
form.elements={type:{value:'all'}};
root.dataset.url='/collection/item/1/supersets?color=4';
const nodes={'[data-found-form]':form,'[data-found-results]':results,'[data-found-status]':status,'[data-found-retry]':retry,'[data-found-clear]':clear,'[data-found-filters]':filters,'#found-type':panel};
root.querySelector=k=>nodes[k];
let requests=[],pending=[],fail=false;
let scheduled;
const ctx={setTimeout:fn=>{scheduled=fn;return 1;},clearTimeout:()=>{scheduled=null;},module:{exports:{}},document:{querySelectorAll:()=>[]},location:{href:'http://example.test/collection/item/1'},URL,FormData:class{forEach(fn){fn(form.elements.type.value,'type');}},
 fetch:(url)=>{requests.push(String(url));if(fail)return Promise.resolve({ok:false});return new Promise(resolve=>pending.push(resolve));}};
vm.runInNewContext(fs.readFileSync('static/web/toni/bw-found-in.js','utf8'),ctx);
(async()=>{
 const {load}=ctx.module.exports.mount(root);
 filters.events.click();assert.equal(panel.hidden,false);assert.equal(filters['aria-expanded'],'true');
 filters.events.click();assert.equal(panel.hidden,true);
 form.events.input({target:{name:'q'}});assert.equal(typeof scheduled,'function');
 scheduled();assert.equal(requests.length,1);
 pending[0]({ok:true,text:async()=>'<p>search</p>'});
 await new Promise(resolve=>setImmediate(resolve));requests=[];pending=[];
 const first=load(15);assert.match(status.textContent,/Loading/);assert.match(requests[0],/offset=15/);
 form.elements.type.value='minifigures';
 const second=load(0);assert.equal(clear.textContent,'Minifigures only ×');
 pending[1]({ok:true,text:async()=>'<p>latest</p>'});await second;
 pending[0]({ok:true,text:async()=>'<p>stale</p>'});await first;
 assert.equal(results.innerHTML,'<p>latest</p>');
 fail=true;await load(30);assert.equal(retry.hidden,false);assert.match(status.textContent,/Retry/);assert.equal(results['aria-busy'],'false');
 fail=false;const attempt=retry.events.click();assert.match(requests.at(-1),/offset=30/);
 pending.at(-1)({ok:true,text:async()=>'<p>retry</p>'});
 await new Promise(resolve=>setImmediate(resolve));
 assert.equal(results.innerHTML,'<p>retry</p>');

 const wish=new Node();wish.dataset.foundWish='42';wish.disabled=false;wish.replaceWith=node=>{wish.replacement=node;};
 const collection=new Node();collection.dataset={saveUrl:'/collection/ACTION',csrf:'test-csrf'};
 ctx.document.getElementById=()=>collection;ctx.document.createElement=()=>new Node();
 let sent;
 ctx.fetch=async(url,options)=>{sent={url,body:JSON.parse(options.body)};return {ok:true,json:async()=>({message:'Added to wishlist'})};};
 await root.events.click({target:{closest:selector=>selector==='[data-found-wish]'?wish:null}});
 assert.equal(sent.url,'/collection/wish');assert.equal(sent.body.item_id,42);assert.equal(sent.body.csrf_token,'test-csrf');
 assert.equal(wish.replacement.textContent,'On wishlist');
 wish.replacement=null;wish.disabled=false;
 ctx.fetch=async()=>{throw new Error('offline');};
 await root.events.click({target:{closest:selector=>selector==='[data-found-wish]'?wish:null}});
 assert.equal(wish.disabled,false);assert.match(status.textContent,/Could not add/);
 console.log('Found in runtime passed');
})().catch(error=>{console.error(error);process.exitCode=1;});
