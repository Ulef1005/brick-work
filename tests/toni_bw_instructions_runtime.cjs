'use strict';
const assert=require('node:assert/strict');
const fs=require('node:fs'),vm=require('node:vm');
const context={window:{},document:{querySelector:()=>null}};
vm.runInNewContext(fs.readFileSync('static/web/toni/bw-instructions.js','utf8'),context);
const {Selection,total,defaults,available}=context.window.BrickInstructions;
const pdf=(id,source='rebrickable',region='AT',size=1024)=>({id,source,region,size,file_id:null});
const rows=[pdf(1),pdf(2,'rebrickable','US'),pdf(3,'peeron',null)];
assert.deepEqual(Array.from(defaults(rows,'AT')),[1]);
assert.deepEqual(Array.from(defaults([rows[2]],'AT')),[3]);
assert.deepEqual(Array.from(defaults([rows[2],pdf(4,'peeron',null)],'AT')),[]);
const model=new Selection('AT');model.update([{item_id:1,candidates:rows}]);
assert.deepEqual(Array.from(model.checked),[1]);
model.touch(1,false);model.touch(3,true);model.retick('US');
assert.deepEqual(Array.from(model.checked),[2,3]);
model.retick('AT');assert.deepEqual(Array.from(model.checked),[3]);
model.update([{item_id:1,candidates:rows},{item_id:2,candidates:[pdf(4)]}]);
assert.deepEqual(Array.from(model.checked),[3,4]);
assert.equal(total(model.files()).count,2);assert.equal(total(model.files()).bytes,2048);
assert.equal(total([pdf(5,'peeron',null,null)]).unknown,true);
assert.equal(available({...pdf(6),size:20*1024*1024+1}),false);
assert.equal(available({...pdf(6),file_id:1}),false);
model.update([{candidates:[{...pdf(3),file_id:1}]}]);assert.equal(model.checked.size,0);
console.log('Instruction tick list: region, touched ticks, scans, totals, disabled files and polling updates pass');

const big=[pdf(10,'official','de-de',348*1024*1024),pdf(11,'official','de-de',200*1024*1024),pdf(12,'official','de-de',501*1024*1024)];
assert.deepEqual(Array.from(defaults(big,'DE')),[10]);
assert.equal(available(big[2]),false);
assert.deepEqual(Array.from(defaults([pdf(13,'official','en-ca')],'CA')),[13]);
const across=new Selection('DE');across.update(big.slice(0,2).map(c=>({candidates:[c]})));
assert.deepEqual(Array.from(across.checked),[10]);

for(const country of ['UK','GB'])for(const candidateRegion of ['UK','GB','Europe'])assert.deepEqual(Array.from(defaults([pdf(20,'rebrickable',candidateRegion)],country)),[20]);

// Exercise the real find/poll handlers with a small DOM and deterministic replies.
(async()=>{
 const elements=new Map();
 const element=()=>({dataset:{},textContent:'',hidden:false,options:[],children:[],listeners:{},
  addEventListener(name,fn){this.listeners[name]=fn;},append(...items){this.children.push(...items);},
  prepend(){},after(){},replaceChildren(){this.children=[];},remove(){}});
 const get=name=>{if(!elements.has(name))elements.set(name,element());return elements.get(name);};
 get('region').options=[{value:'DE'}];get('region').parentElement=element();
 get('choose').elements={mode:{value:'all'},numbers:{value:''}};
 get('search').value='';get('filter').value='';get('sort').value='';
 const root=element();root.dataset={region:'DE',edit:'yes',jobs:'1',url:'/find'};
 root.querySelector=selector=>get(selector.match(/data-if-(.+)\]/)?.[1]||selector);
 let current='https://example.test/find?jobs=1&download=7';
 const job={state:'running',owner_alive:true,steps:[{name:'1',state:'failed',error:'Cancelled'}]};
 const context={window:{addEventListener(){}},document:{querySelector:()=>root,createElement:element},
  location:{get href(){return current;}},history:{replaceState(a,b,url){current=String(url);}},
  localStorage:{getItem:()=>null,setItem(){}},matchMedia:()=>({matches:false}),URL,URLSearchParams,
  setTimeout:()=>1,clearTimeout(){},fetch:async(url,options)=>({ok:true,json:async()=>options?{jobs:[2],message:'50 of 51 sets queued, run it again for the rest (1 remaining)'}:{groups:[],download:String(url).includes('download=')?job:null}})};
 vm.runInNewContext(fs.readFileSync('static/web/toni/bw-instructions.js','utf8'),context);
 await new Promise(resolve=>setImmediate(resolve));
 assert.equal(get('retry').hidden,true,'Retry must stay hidden while the download owner is alive');
 get('choose').listeners.submit({preventDefault(){}});
 await new Promise(resolve=>setImmediate(resolve));
 assert.equal(new URL(current).searchParams.has('download'),false,'A new find clears the previous download URL');
 assert.equal(get('message').textContent,'50 of 51 sets queued, run it again for the rest (1 remaining)');
 console.log('Instruction browser: live-owner retry and fresh search URL pass');
})().catch(error=>{console.error(error);process.exitCode=1;});
