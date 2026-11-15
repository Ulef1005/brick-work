const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const sandbox={window:{},document:{querySelector:()=>null}};
vm.runInNewContext(fs.readFileSync('static/web/toni/bw-labels.js','utf8'),sandbox);
const {state,selected,capacity}=sandbox.window.BrickLabels;
const rows=[{id:'a',checked:false},{id:'b',checked:false},{id:'c',checked:false}];
assert.equal(selected(rows,'all').filter(r=>r.checked).length,3);
assert.equal(selected(selected(rows,'all'),'clear').filter(r=>r.checked).length,0);
assert.equal(selected(rows,'toggle','b').filter(r=>r.checked)[0].id,'b');
assert.equal(rows.some(r=>r.checked),false);
for(const phase of ['ready','loading','error','downloading'])assert.equal(state(['a','b','c'],'a4-21',0,phase).phase,phase);
assert.equal(state([],'a4-21').pages,0);
assert.equal(state(['a','b','c'],'a4-21').download,'Download PDF');
assert.equal(state(Array.from({length:22},(_,i)=>String(i)),'a4-21').pages,2);
assert.equal(state(['a','a','b'],'tape-62').download,'Download 2 PNG');
assert.equal(state(['a'],'tape-62').pages,1);
assert.equal(capacity('a4-14'),14);
assert.equal(state(['a'],'a4-21',0,'error').download,'Download PDF');
console.log('Storage label selection and dialog states passed');

// Run the real event handlers with a tiny DOM and queued fetch responses.
class Element {
  constructor(dataset={}){this.dataset=dataset;this.listeners={};this.children=[];this.hidden=false;this.disabled=false;this.textContent='';this.value='';}
  addEventListener(name,fn){this.listeners[name]=fn;}
  async fire(name){return this.listeners[name]?.({currentTarget:this});}
  append(...nodes){this.children.push(...nodes);}
  replaceChildren(...nodes){this.children=[...nodes];}
  setAttribute(key,value){this[key]=value;}
  removeAttribute(key){delete this[key];}
  remove(){}
  click(){}
  closest(){return this.parent;}
}
const elements={};
const get=key=>elements[key] ||= new Element();
const boxes=Array.from({length:22},(_,i)=>{const e=new Element({labelId:`bin${i}`,labelName:`Box ${i}`});e.checked=false;e.parent=new Element();return e;});
const dialog=get('[data-label-dialog]');dialog.dataset.base='/workbench/storage/labels/OUTPUT';
dialog.querySelector=get;
const closeButtons=[new Element(),new Element()];
dialog.querySelectorAll=()=>closeButtons;
dialog.showModal=()=>dialog.open=true;
dialog.close=()=>{dialog.open=false;dialog.fire('close');};
get('[data-label-layout]').value='a4-21';
const root=new Element();root.querySelector=get;root.querySelectorAll=()=>boxes;
const replies=[],requests=[];
const context={window:{location:{search:''}},URLSearchParams,URL:{createObjectURL:()=> 'blob:synthetic',revokeObjectURL:()=>{}},setTimeout:fn=>fn(),
  document:{querySelector:()=>root,createTextNode:text=>({textContent:text}),createElement:()=>new Element(),body:new Element()},
  fetch:async url=>{requests.push(url);const reply=replies.shift();if(reply instanceof Error)throw reply;return reply||{ok:true,blob:async()=>({})};}};
vm.runInNewContext(fs.readFileSync('static/web/toni/bw-labels.js','utf8'),context);
const flush=async()=>{for(let i=0;i<10;i++)await Promise.resolve();};
(async()=>{
  await get('[data-label-select]').fire('click');
  assert.equal(get('[data-label-select]').textContent,'Done');
  assert.equal(boxes.every(b=>!b.parent.hidden),true);
  await get('[data-label-all]').fire('click');
  assert.equal(get('[data-label-open]').textContent,'Print labels · 22');
  await get('[data-label-clear]').fire('click');
  assert.equal(get('[data-label-open]').disabled,true);
  boxes.slice(0,3).forEach(b=>b.checked=true);await boxes[0].fire('change');
  assert.equal(get('[data-label-open]').textContent,'Print labels · 3');
  replies.push(new Error('offline'));
  await get('[data-label-open]').fire('click');await flush();
  assert.equal(dialog.open,true);
  assert.equal(get('[data-label-download]').textContent,'Retry');
  assert.match(get('[data-label-status]').textContent,/Nothing was changed/);
  await get('[data-label-download]').fire('click');await flush();
  assert.equal(get('[data-label-download]').textContent,'Download PDF');
  assert.equal(get('[data-label-preview]').hidden,false);
  assert.equal(get('[data-label-chips]').children.length,3);
  await get('[data-label-chips]').children[0].children[1].fire('click');await flush();
  assert.equal(get('[data-label-total]').textContent,'2 labels');
  await get('[data-label-all]').fire('click');await get('[data-label-open]').fire('click');await flush();
  assert.equal(get('[data-label-sheets]').textContent,'22 labels · 2 sheets');
  assert.equal(get('[data-label-pager]').hidden,false);
  await get('[data-label-next]').fire('click');await flush();
  assert.equal(get('[data-label-page]').textContent,'2 of 2');
  assert.equal(get('[data-label-next]').disabled,true);
  assert.match(requests.at(-1),/page=1/);
  get('[data-label-layout]').value='tape-62';await get('[data-label-layout]').fire('change');await flush();
  assert.equal(get('[data-label-download]').textContent,'Download 22 PNG');
  replies.push({ok:false});await get('[data-label-download]').fire('click');
  assert.equal(get('[data-label-download]').textContent,'Retry');
  await get('[data-label-download]').fire('click');
  assert.match(requests.at(-1),/\/download\?/);
  assert.equal(get('[data-label-download]').textContent,'Download 22 PNG');
  await closeButtons[0].fire('click');assert.equal(dialog.open,false);
  await get('[data-label-select]').fire('click');
  assert.equal(boxes.every(b=>b.parent.hidden),true);
  console.log('Storage label DOM flow, failures, retry, chips, pages and tape passed');
})().catch(error=>{console.error(error);process.exitCode=1;});
