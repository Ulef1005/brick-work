/* 12i desktop Options menu: builds Group by and Select from the panel's View controls and drives them. */
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
class Node {
 constructor(tag='div',dataset={}){this.tagName=tag.toUpperCase();this.dataset=dataset;this.events={};this.children=[];this.attrs={};this.hidden=false;this.textContent='';this.className='';this.parent=null;}
 addEventListener(k,f){this.events[k]=f;}
 setAttribute(k,v){this.attrs[k]=String(v);}
 getAttribute(k){return this.attrs[k]??null;}
 append(...n){n.forEach(c=>{c.parent=this;this.children.push(c);});}
 replaceChildren(){this.children=[];}
 all(){return this.children.flatMap(c=>[c,...c.all()]);}
 querySelectorAll(s){return this.all().filter(n=>n.is(s));}
 querySelector(s){return this.querySelectorAll(s)[0]||null;}
 is(s){if(s==='button')return this.tagName==='BUTTON';if(s==='[aria-checked=true]')return this.attrs['aria-checked']==='true';if(s==='[data-bc-select][role=switch]')return 'bcSelect' in this.dataset&&this.attrs.role==='switch';if(s==='select[data-bc-group]')return this.tagName==='SELECT'&&'bcGroup' in this.dataset;const m=s.match(/^\[data-([a-z-]+)\]$/);if(m)return m[1].replace(/-([a-z])/g,(_,c)=>c.toUpperCase()) in this.dataset;if(s.startsWith('.'))return this.className.split(' ').includes(s.slice(1));return false;}
 closest(s){return this.is(s)?this:this.parent?.closest(s)??null;}
 contains(n){return n===this||this.all().includes(n);}
 click(){this.clicked=(this.clicked||0)+1;if(this.events.click)this.events.click({});}
 focus(){doc.activeElement=this;}
}
const list=new Node('div',{bcList:''}),wrap=new Node('div',{bcOptionsWrap:''}),open=new Node('button',{bcOptionsOpen:''}),menu=new Node('div',{bcOptionsMenu:''});
menu.hidden=true;wrap.append(open,menu);
const view=new Node('div');view.className='bc-filter-group bc-view-group';
const select=new Node('select',{bcGroup:''});select.value='theme';
const picks=[['','None'],['theme','Theme'],['storage','Storage']].map(([v,l])=>{const b=new Node('button',{bcGroupPick:v});b.textContent=l;return b;});
const sw=new Node('button',{bcSelect:''});sw.setAttribute('role','switch');sw.setAttribute('aria-checked','false');
sw.events.click=()=>sw.setAttribute('aria-checked',String(sw.getAttribute('aria-checked')!=='true'));
picks.forEach(p=>p.events.click=()=>{select.value=p.dataset.bcGroupPick;});
view.append(...picks,sw);list.append(wrap,view,select);
const docEvents={};const doc={activeElement:null,querySelectorAll:s=>s==='[data-bc-options-wrap]'?[wrap]:[],createElement:t=>new Node(t),addEventListener:(k,f)=>docEvents[k]=f};
vm.runInNewContext(fs.readFileSync('static/web/toni/bw-options-menu.js','utf8'),{document:doc});
open.events.click();
assert.equal(menu.hidden,false);assert.equal(open.getAttribute('aria-expanded'),'true');
assert.equal(menu.children[0].textContent,'Group by · Theme');
const items=menu.querySelectorAll('button');
assert.deepEqual(items.map(b=>b.textContent),['Select','None','Theme','Storage']);
assert.equal(doc.activeElement.textContent,'Theme');            // focus starts on the checked group
items[3].events.click();                                          // Storage
assert.equal(select.value,'storage');assert.equal(menu.hidden,true);assert.equal(doc.activeElement,open);
open.events.click();
assert.equal(menu.children[0].textContent,'Group by · Storage');
menu.querySelectorAll('button')[0].events.click();               // Select mode on
assert.equal(sw.getAttribute('aria-checked'),'true');
open.events.click();
assert.equal(menu.querySelectorAll('button')[0].getAttribute('aria-checked'),'true');
let prevented=false;menu.events.keydown({key:'Escape',preventDefault(){prevented=true;}});
assert.ok(prevented);assert.equal(menu.hidden,true);
open.events.click();docEvents.click({target:new Node()});assert.equal(menu.hidden,true);
console.log('Options menu: group by, select mode, focus and closing passed');
