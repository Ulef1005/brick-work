const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
class Node {
 constructor(){this.events={};this.attrs={};this.dataset={};this.nodes={};this.groups={};this.children=[];this.value='';this.hidden=false;this.disabled=false;this.textContent='';this.style={};this.options=[];this.tagName='DIV';}
 addEventListener(n,f){this.events[n]=f;}
 matches(s){return s.split(',').some(selector=>{const m=selector.match(/^\[data-([a-z-]+)\]$/);return m?Object.hasOwn(this.dataset,m[1].replace(/-([a-z])/g,(_,c)=>c.toUpperCase())):selector.startsWith('.')?this.className===selector.slice(1):this.tagName===selector.toUpperCase();});}
 querySelector(s){return this.nodes[s]||this.querySelectorAll(s)[0]||null;}
 querySelectorAll(s){return this.groups[s]||this.children.flatMap(n=>[...(n.matches(s)?[n]:[]),...n.querySelectorAll(s)]);}
 closest(s){return this.matches(s)?this:this.parentElement?.closest(s);}
 append(...nodes){for(const n of nodes){if(n===doc.activeElement||n.querySelectorAll('input').includes(doc.activeElement))doc.activeElement=null;if(n.parentElement)n.parentElement.children=n.parentElement.children.filter(c=>c!==n);n.parentElement=this;this.children=this.children.filter(c=>c!==n);this.children.push(n);if(n.tagName==='OPTION')this.options.push(n);}}
 replaceChildren(...nodes){this.children=[];this.options=[];this.append(...nodes);}
 setAttribute(k,v){this.attrs[k]=String(v);}
 getAttribute(k){return Object.hasOwn(this.attrs,k)?this.attrs[k]:null;}
 removeAttribute(k){delete this.attrs[k];}
 get selectedIndex(){return this.options.findIndex(o=>o.value===this.value);}
 hasAttribute(k){return Object.hasOwn(this.attrs,k)||(k.startsWith('data-')&&Object.hasOwn(this.dataset,k.slice(5).replace(/-([a-z])/g,(_,c)=>c.toUpperCase())));}
 remove(){this.removed=true;if(this.parentElement)this.parentElement.children=this.parentElement.children.filter(n=>n!==this);this.parentElement=null;}
 focus(){this.focused=true;doc.activeElement=this;}
 async trigger(n='click',extra={}){if(n==='error')doc.events.error?.({target:this});return this.events[n]?.({preventDefault(){},currentTarget:this,target:this,...extra});}
}
Node.prototype.after=function(n){this.afterNode=n;n.parentElement=this.parentElement;};
let doc;
// Invented DOM fixture: the real collection script, without browser or sockets.
function setup({stored=new Map(),copy='one',blocked=false,count=76}={}) {
 doc=new Node();
 const root=new Node(),list=new Node(),container=new Node(),search=new Node(),sort=new Node(),direction=new Node(),actions=new Node();
 root.dataset={editable:'false'};sort.value='number';direction.value='asc';
 const sections=['Bricks','Tiles','Other'].map((name,index)=>{
  const element=new Node(),button=new Node(),body=new Node(),rows=new Node();
  element.dataset={bcPartSection:name,bcDefaultOpen:index===0?'false':'true'};
  element.nodes={'[data-bc-section-toggle]':button,'[data-bc-section-body]':body,'[data-bc-section-rows]':rows};
  body.append(rows);element.append(button,body);container.append(element);
  const size=[count,25,1][index];
  for(let i=0;i<size;i++){
   const node=new Node();node.dataset={bcRow:'',record:JSON.stringify({type:'P',part_group:name,number:String(1000+i),name:name+' part '+i,colour:i<10?'Black':'White',quantity:1,missing:0})};rows.append(node);
  }
  return {element,button,body,rows,pager:()=>rows.afterNode,visible:()=>rows.children.filter(n=>!n.hidden)};
 });
 const expand=new Node(),collapse=new Node(),colour=new Node();expand.dataset.bcSections='expand';collapse.dataset.bcSections='collapse';colour.dataset.bcFilter='colour';colour.options=[{value:'',textContent:'All'},{value:'Black',textContent:'Black'}];colour.parentElement={firstChild:{textContent:'Colour'}};
 list.nodes={'[data-bc-rows]':container,'[data-bc-inventory-rows]':container,'[data-bc-search]':search,'[data-bc-sort]':sort,'[data-bc-direction]':direction,'[data-bc-section-actions]':actions};
 list.groups={'[data-bc-part-section]':sections.map(s=>s.element),'[data-bc-sections]':[expand,collapse],'[data-bc-filter]':[colour]};list.append(container);
 root.groups={'[data-bc-list]':[list]};
 doc=new Node();doc.querySelector=s=>s==='#bw-collection'?root:null;doc.createElement=tag=>{const n=new Node();n.tagName=tag.toUpperCase();return n;};
 const session=new Map();
 const context={window:{addEventListener(){},scrollY:0},document:doc,location:{pathname:'/collection/item/1',search:'?copy='+copy},URLSearchParams,requestAnimationFrame:f=>f(),sessionStorage:{getItem:k=>session.get(k)||null,setItem:(k,v)=>session.set(k,v)},localStorage:{getItem:k=>{if(blocked)throw Error('unavailable');return stored.get(k)||null;},setItem:(k,v)=>{if(blocked)throw Error('unavailable');stored.set(k,v);}}};
 vm.runInNewContext(fs.readFileSync('static/web/toni/formatting.js','utf8')+fs.readFileSync('static/web/toni/bw-collection.js','utf8'),context);
 return {sections,search,sort,direction,colour,expand,collapse,actions,stored};
}
const text=s=>s.pager().children.find(n=>n.tagName==='P').textContent;
const next=s=>s.pager().children.find(n=>n.className==='bc-page-step bc-page-next');
const numbers=s=>s.pager().children.find(n=>n.className==='bc-page-numbers').children;
(async()=>{
 const h=setup(),[bricks,tiles,other]=h.sections;
 assert.equal(bricks.body.hidden,true);assert.equal(tiles.body.hidden,false);assert.equal(h.actions.hidden,false);
 assert.equal(bricks.button.getAttribute('aria-expanded'),'false');
 assert.equal(bricks.visible().length,25);assert.equal(tiles.visible().length,25);assert.equal(other.visible().length,1);
 assert.equal(text(bricks),'1–25 of 76');assert.equal(text(tiles),'1–25 of 25');assert.equal(text(other),'1–1 of 1');assert.equal(next(tiles).hidden,true);
 await bricks.button.trigger();assert.equal(bricks.body.hidden,false);
 await next(bricks).trigger();assert.equal(text(bricks),'26–50 of 76');assert.equal(text(tiles),'1–25 of 25');
 await numbers(bricks).find(n=>n.textContent==='4').trigger();assert.equal(text(bricks),'76–76 of 76');assert.equal(bricks.visible().length,1);assert.equal(next(bricks).disabled,true);
 h.colour.value='Black';await h.colour.trigger('change');assert.equal(text(bricks),'1–10 of 10');assert.equal(bricks.visible().length,10);
 h.colour.value='';await h.colour.trigger('change');
 h.direction.value='desc';await h.direction.trigger('change');h.sort.value='number';await h.sort.trigger('change');assert.equal(JSON.parse(bricks.visible()[0].dataset.record).number,'1075');
 h.search.value='Tiles';await h.search.trigger('input');assert.equal(bricks.element.hidden,true);assert.equal(tiles.element.hidden,false);assert.equal(other.element.hidden,true);
 h.search.value='';await h.search.trigger('input');assert.equal(bricks.element.hidden,false);
 await h.collapse.trigger();assert.ok(h.sections.every(s=>s.body.hidden));
 const remembered=setup({stored:h.stored});assert.ok(remembered.sections.every(s=>s.body.hidden));
 await remembered.expand.trigger();assert.ok(remembered.sections.every(s=>!s.body.hidden));
 const revisit=setup({stored:h.stored});assert.ok(revisit.sections.every(s=>!s.body.hidden));
 const another=setup({stored:h.stored,copy:'two'});assert.equal(another.sections[0].body.hidden,true);
 const unavailable=setup({blocked:true});await unavailable.expand.trigger();await unavailable.collapse.trigger();assert.ok(unavailable.sections.every(s=>s.body.hidden));
 const many=setup({count:326}).sections[0];assert.deepEqual(numbers(many).map(n=>n.textContent),['1','2','…','14']);
 for(let i=0;i<4;i++)await next(many).trigger();
 assert.deepEqual(numbers(many).map(n=>n.textContent),['1','…','4','5','6','…','14']);
 console.log('part groups runtime ok');
})().catch(error=>{console.error(error);process.exit(1);});
