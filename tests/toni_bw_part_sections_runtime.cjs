const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
// Invented DOM fixture: the real section script (order list, pull list), without a browser.
class Node {
 constructor(){this.events={};this.dataset={};this.hidden=false;this.open=false;this.children=[];this.parent=null;this.id='';}
 addEventListener(n,f){this.events[n]=f;}
 add(...nodes){for(const n of nodes){n.parent=this;this.children.push(n);}return this;}
 all(){return this.children.flatMap(n=>[n,...n.all()]);}
 querySelectorAll(s){return this.all().filter(n=>n.is(s));}
 querySelector(s){return this.querySelectorAll(s)[0]||null;}
 is(s){const m=s.match(/^\[data-([a-z-]+)\]$/);if(m)return Object.hasOwn(this.dataset,m[1].replace(/-([a-z])/g,(_,c)=>c.toUpperCase()));const i=s.match(/^\[id="(.*)"\]$/);if(i)return this.id===i[1];return this.tag===s;}
 closest(s){return this.is(s)?this:this.parent?.closest(s)||null;}
 click(extra={}){let prevented=false;this.events.click?.({preventDefault(){prevented=true;},...extra});return prevented;}
}
function page({stored=new Map(),hash='',blocked=false,key='all',names=['Bricks','Plates','Other'],open=[true,true,true]}={}) {
 const scope=new Node(),actions=new Node(),expand=new Node(),collapse=new Node(),root=new Node();
 scope.dataset={bwSections:'',bwSectionsKey:key};actions.dataset={bwSectionsActions:''};actions.hidden=true;
 expand.dataset.bwSectionsAll='expand';collapse.dataset.bwSectionsAll='collapse';actions.add(expand,collapse);scope.add(actions);
 const sections=names.map((name,i)=>{const s=new Node(),head=new Node(),line=new Node();s.dataset.bwSection=name;s.open=open[i];head.tag='summary';line.id='l-'+i+'-0';s.add(head,line);scope.add(s);return {s,head,line};});
 root.add(scope);
 const context={window:{},document:{querySelectorAll:q=>root.querySelectorAll(q)},location:{pathname:'/collection/lots/1/pull/5',hash},decodeURIComponent,
  localStorage:{getItem:k=>{if(blocked)throw Error('unavailable');return stored.get(k)||null;},setItem:(k,v)=>{if(blocked)throw Error('unavailable');stored.set(k,v);}}};
 vm.runInNewContext(fs.readFileSync('static/web/toni/bw-part-sections.js','utf8'),context);
 return {scope,actions,expand,collapse,sections,context,stored};
}
const flip=sec=>{sec.head.click();sec.s.open=!sec.s.open;};          // the click handler runs first, then the browser's own toggle
// the actions show once the script runs, and only then
let p=page();
assert.equal(p.actions.hidden,false);
assert.equal(typeof p.context.window.bwPartSections,'function');
// the server's open state is the default; a choice is remembered per page and key, and the next visit starts from it
flip(p.sections[1]);assert.equal(p.sections[1].s.open,false);
const again=page({stored:p.stored});assert.deepEqual(again.sections.map(x=>x.s.open),[true,false,true]);
const other=page({stored:p.stored,key:'bl'});assert.deepEqual(other.sections.map(x=>x.s.open),[true,true,true]);
// Collapse all / Expand all: every section, remembered, and the link does not navigate
assert.equal(p.collapse.click(),true);assert.ok(p.sections.every(x=>!x.s.open));
assert.ok(page({stored:p.stored}).sections.every(x=>!x.s.open));
assert.equal(p.expand.click(),true);assert.ok(p.sections.every(x=>x.s.open));
assert.ok(page({stored:p.stored}).sections.every(x=>x.s.open));
// a section the server draws closed (a complete group) starts closed; an opened one is remembered; a remembered choice beats the server's
const server=page({open:[true,false,false]});assert.deepEqual(server.sections.map(x=>x.s.open),[true,false,false]);
flip(server.sections[2]);assert.deepEqual(page({stored:server.stored,open:[true,false,false]}).sections.map(x=>x.s.open),[true,false,true]);
// a link to a line inside a closed section opens that section, without remembering it
const linked=page({open:[false,false,false],hash:'#l-1-0'});assert.deepEqual(linked.sections.map(x=>x.s.open),[false,true,false]);
assert.equal(linked.stored.size,0);
// a hash that does not parse (a hand-edited or bookmarked link) never stops the tools from showing
const broken=page({open:[true,true,true],hash:'#100%'});assert.equal(broken.actions.hidden,false);assert.ok(broken.sections.every(x=>x.s.open));
// a browser that keeps nothing still toggles and expands
const blocked=page({blocked:true});flip(blocked.sections[0]);assert.equal(blocked.sections[0].s.open,false);blocked.expand.click();assert.ok(blocked.sections.every(x=>x.s.open));
// no sections: nothing to show
const none=page({names:[]});assert.equal(none.actions.hidden,true);
console.log('part sections runtime ok');
