const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
class Node {
 constructor(){this.events={};this.attrs={};this.dataset={};this.nodes={};this.groups={};this.children=[];this.value='';this.hidden=false;this.disabled=false;this.textContent='';this.style={};this.options=[];this.tagName='DIV';}
 addEventListener(n,f){this.events[n]=f;}
 matches(s){return s.split(',').some(selector=>{const m=selector.match(/^\[data-([a-z-]+)\]$/);return m?Object.hasOwn(this.dataset,m[1].replace(/-([a-z])/g,(_,c)=>c.toUpperCase())):selector.startsWith('.')?this.className===selector.slice(1):this.tagName===selector.toUpperCase();});}
 querySelector(s){return this.nodes[s]||this.querySelectorAll(s)[0]||null;}
 querySelectorAll(s){return this.groups[s]||this.children.flatMap(n=>[...(n.matches(s)?[n]:[]),...n.querySelectorAll(s)]);}
 closest(s){return this.matches(s)?this:this.parentElement?.closest(s);}
 append(...nodes){for(const n of nodes){if(n===doc.activeElement||n.querySelectorAll('input').includes(doc.activeElement))doc.activeElement=null;n.parentElement=this;this.children=this.children.filter(c=>c!==n);this.children.push(n);if(n.tagName==='OPTION')this.options.push(n);}}
 replaceChildren(...nodes){this.children=[];this.options=[];this.append(...nodes);}
 setAttribute(k,v){this.attrs[k]=String(v);}
 getAttribute(k){return Object.hasOwn(this.attrs,k)?this.attrs[k]:null;}
 removeAttribute(k){delete this.attrs[k];}
 get selectedIndex(){return this.options.findIndex(o=>o.value===this.value);}
 hasAttribute(k){return k==='data-bc-main';}
 remove(){this.removed=true;if(this.parentElement)this.parentElement.children=this.parentElement.children.filter(n=>n!==this);this.parentElement=null;}
 focus(){this.focused=true;doc.activeElement=this;}
 async trigger(n='click',extra={}){if(n==='error')doc.events.error?.({target:this});return this.events[n]?.({preventDefault(){},currentTarget:this,target:this,...extra});}
}
const message=new Node(),undo=new Node(),form=new Node(),formStatus=new Node(),save=new Node();
form.dataset={bcAction:'save',identity:JSON.stringify({entity:'copy',ids:['copy']})};form.values={note:'A private note',condition:'U'};form.nodes={'[data-bc-form-message]':formStatus};form.groups={button:[save]};
Node.prototype.after=function(n){this.afterNode=n;n.parentElement=this.parentElement;};
let doc;
// 4.8d: the shared list pager, switched on by data-bc-page-size (the Parts list only).
function makeList(count,pageSize,{missing=0,saved=null}={}){
 const list=new Node(),container=new Node(),search=new Node(),sort=new Node(),direction=new Node(),countNode=new Node(),loaded=new Node(),more=new Node(),group=new Node(),source=new Node();
 sort.value='number';direction.value='asc';group.value='';more.hidden=false;
 if(pageSize)list.dataset.bcPageSize=String(pageSize);
 const records=Array.from({length:count},(_,i)=>({type:'P',name:'Part '+i,number:String(1000+i),quantity:1,missing:i<missing?1:0,colour:i<20?'Black':'White',entity:'stock',ids:['id-'+i],condition:['U'],status:['I'],storage:['null'],place:['null'],flags:[],lot:['null'],lot_links:[]}));
 const fields=Object.keys(records[0]);source.textContent=JSON.stringify({fields,rows:records.map(r=>Object.fromEntries(fields.map((k,i)=>[i,r[k]])))});
 const colourFilter=new Node();colourFilter.dataset.bcFilter='colour';colourFilter.parentElement={firstChild:{textContent:'Colour'}};colourFilter.options=[{value:'',textContent:'All'},{value:'Black',textContent:'Black'},{value:'White',textContent:'White'}];
 list.nodes={'[data-bc-rows]':container,'[data-bc-records]':source,'[data-bc-search]':search,'[data-bc-sort]':sort,'[data-bc-direction]':direction,'[data-bc-count]':countNode,'[data-bc-more]':more,'[data-bc-loaded]':loaded,'[data-bc-group]':group};
 list.groups={'[data-bc-filter]':[colourFilter]};
 const missingSection=new Node(),presentSection=new Node(),missingRows=new Node(),presentRows=new Node(),summary=new Node();
 if(missing){Object.assign(list.nodes,{'[data-bc-missing]':missingSection,'[data-bc-present]':presentSection,'[data-bc-missing-rows]':missingRows,'[data-bc-present-rows]':presentRows,'[data-bc-present-summary]':summary});}
 const root=new Node();root.dataset={bcCollectionList:'',saveUrl:'/x/ACTION',csrf:'c',type:'P',editable:'false',itemBase:'/i/TYPE/NUMBER',imageBase:'/img/0',lotBase:'/l/LOT'};root.groups={'[data-bc-list]':[list]};
 doc=new Node();doc.querySelector=s=>s==='#bw-collection'?root:null;doc.createElement=tag=>{const n=new Node();n.tagName=tag.toUpperCase();return n;};
 const stored=new Map();if(saved)stored.set('bw-collection-list:/collection/P:0',JSON.stringify(saved));
 const context={window:{addEventListener(){},scrollY:0,scrollTo(x,y){this.scrolled.push(y);},scrolled:[],history:{replaceState(){}}},document:doc,sessionStorage:{getItem:k=>stored.get(k)||null,setItem:(k,v)=>stored.set(k,v),removeItem:k=>stored.delete(k)},location:{pathname:'/collection/P',search:'',reload(){}},URLSearchParams,requestAnimationFrame:f=>f(),fetch:async()=>({})};
 vm.runInNewContext(fs.readFileSync('static/web/toni/images.js','utf8'),context);
 vm.runInNewContext(fs.readFileSync('static/web/toni/formatting.js','utf8')+fs.readFileSync('static/web/toni/bw-collection.js','utf8'),context);
 const pager=container.afterNode||null,buttons=pager?pager.children.filter(c=>c.tagName==='BUTTON'):[],text=pager?pager.children.find(c=>c.tagName==='P'):null;
 return {context,missingRows,presentRows,list,container,search,sort,direction,group,countNode,more,loaded,colourFilter,pager,prev:buttons[0],next:buttons[1],text,stored,rows:()=>container.querySelectorAll('[data-bc-row]').length,headings:()=>container.querySelectorAll('[data-bc-group-heading]').map(h=>h.textContent)};
}
(async()=>{
 // 40 records, 15 per page.
 const h=makeList(40,15);
 assert.ok(h.pager,'pager built when data-bc-page-size is set');
 assert.equal(h.pager.tagName,'NAV');assert.equal(h.pager.getAttribute('aria-label'),'Pages');
 assert.equal(h.prev.textContent,'Previous');assert.equal(h.next.textContent,'Next');
 assert.equal(h.text.getAttribute('aria-live'),null);assert.equal(h.text.getAttribute('role'),null);
 assert.equal(h.rows(),15);assert.equal(h.countNode.textContent,'1 to 15 of 40');assert.equal(h.countNode.getAttribute('aria-label'),'1 to 15 of 40 parts');assert.equal(h.text.textContent,'1 to 15 of 40');
 assert.equal(h.pager.hidden,false);assert.equal(h.prev.disabled,true);assert.equal(h.next.disabled,false);
 assert.equal(h.more.hidden,true);assert.equal(h.loaded.textContent,'');
 const first=()=>h.container.querySelector('[data-bc-row]').dataset;
 await h.next.trigger();
 assert.equal(h.rows(),15);assert.equal(h.text.textContent,'16 to 30 of 40');assert.equal(h.prev.disabled,false);assert.equal(h.next.disabled,false);
 assert.equal(h.countNode.textContent,'16 to 30 of 40');
 await h.next.trigger();
 assert.equal(h.rows(),10);assert.equal(h.text.textContent,'31 to 40 of 40');assert.equal(h.next.disabled,true);
 await h.prev.trigger();assert.equal(h.text.textContent,'16 to 30 of 40');assert.equal(h.rows(),15);
 // The main list saves its page with the scroll offset (restored on Back, below).
 assert.equal(JSON.parse(h.stored.get('bw-collection-list:/collection/P:0')).page,2);
 // Search resets to page 1 and pages over matches only (Black = 20 matches, White = 20).
 h.search.value='Black';await h.search.trigger('input');
 assert.equal(h.countNode.textContent,'1 to 15 of 20');assert.equal(h.text.textContent,'1 to 15 of 20');assert.equal(h.rows(),15);
 await h.next.trigger();assert.equal(h.rows(),5);assert.equal(h.text.textContent,'16 to 20 of 20');
 // A search that fits on one page hides the pager.
 h.search.value='Part 3';await h.search.trigger('input');
 assert.ok(Number(h.countNode.textContent.split(' ')[0])<=15);assert.equal(h.pager.hidden,true);
 h.search.value='';await h.search.trigger('input');assert.equal(h.pager.hidden,false);assert.equal(h.text.textContent,'1 to 15 of 40');
 // Filter, sort and group changes reset the page.
 await h.next.trigger();assert.equal(h.text.textContent,'16 to 30 of 40');
 h.colourFilter.value='White';await h.colourFilter.trigger('change');assert.equal(h.text.textContent,'1 to 15 of 20');
 h.colourFilter.value='';await h.colourFilter.trigger('change');
 await h.next.trigger();assert.equal(h.text.textContent,'16 to 30 of 40');
 h.direction.value='desc';await h.direction.trigger('change');assert.equal(h.text.textContent,'1 to 15 of 40');
 await h.next.trigger();h.sort.value='name';await h.sort.trigger('change');assert.equal(h.text.textContent,'1 to 15 of 40');
 await h.next.trigger();h.group.value='colour';await h.group.trigger('change');assert.equal(h.text.textContent,'1 to 15 of 40');
 // Grouping: 20 Black then 20 White. Page 1 = 15 Black (heading), page 2 = 5 Black + 10 White (two headings), page 3 = 10 White (heading repeated).
 h.direction.value='asc';await h.direction.trigger('change');
 assert.deepEqual(h.headings(),['Black']);assert.equal(h.container.children[0].textContent,'Black');
 await h.next.trigger();
 assert.deepEqual(h.headings(),['Black','White']);assert.equal(h.container.children[0].textContent,'Black');assert.equal(h.rows(),15);
 await h.next.trigger();
 assert.deepEqual(h.headings(),['White']);assert.equal(h.container.children[0].textContent,'White');assert.equal(h.rows(),10);
 // DOM order is reading order: headings and rows interleave in the container itself.
 assert.ok(h.container.children.every((c,i)=>i===0?c.matches('[data-bc-group-heading]'):c.matches('[data-bc-row]')));
 // One page only: no pager visible, all rows shown.
 const few=makeList(9,15);assert.equal(few.rows(),9);assert.equal(few.pager.hidden,true);
 const exact=makeList(15,15);assert.equal(exact.rows(),15);assert.equal(exact.pager.hidden,true);
 // Lists without data-bc-page-size are unchanged: no pager, Load more window of 60.
 const plain=makeList(130,0);assert.equal(plain.pager,null);assert.equal(plain.rows(),60);assert.equal(plain.more.hidden,false);
 // Page numbers: first, last and current with neighbours; a long gap shows an ellipsis (kit 12h).
 const numbers=pg=>pg.pager.children.find(c=>c.className==='bc-page-numbers').children.map(c=>c.textContent);
 assert.deepEqual(numbers(h),['1','2','3']);
 const many=makeList(412,15);assert.deepEqual(numbers(many),['1','2','…','28']);
 for(let i=0;i<4;i++)await many.next.trigger();
 assert.deepEqual(numbers(many),['1','…','4','5','6','…','28']);assert.equal(many.text.textContent,'61 to 75 of 412');
 const current=many.pager.children.find(c=>c.className==='bc-page-numbers').children.find(c=>c.getAttribute('aria-current')==='page');assert.equal(current.textContent,'5');
 await many.pager.children.find(c=>c.className==='bc-page-numbers').children.find(c=>c.textContent==='28').trigger();
 assert.equal(many.rows(),7);assert.equal(many.text.textContent,'406 to 412 of 412');assert.equal(many.next.disabled,true);assert.deepEqual(numbers(many),['1','…','27','28']);
 // Activating a page number keeps focus on the new current-page button (the buttons are rebuilt on render).
 const pageButtons=pg=>pg.pager.children.find(c=>c.className==='bc-page-numbers').children;
 const fp=makeList(75,15);await pageButtons(fp).find(c=>c.textContent==='2').trigger();assert.equal(pageButtons(fp).find(c=>c.getAttribute('aria-current')==='page').focused,true);assert.equal(pageButtons(fp).find(c=>c.getAttribute('aria-current')==='page').textContent,'2');
 // A single skipped page shows as its number, not an ellipsis.
 const three=makeList(75,15);await three.next.trigger();await three.next.trigger();assert.deepEqual(numbers(three),['1','2','3','4','5']);
 // Back restores the saved page (clamped) and its scroll only when the page matches.
 const back=makeList(75,15,{saved:{page:3,scroll:500}});assert.equal(back.text.textContent,'31 to 45 of 75');assert.equal(back.context.window.scrolled[0],500);
 const clamped=makeList(75,15,{saved:{page:99,scroll:500}});assert.equal(clamped.text.textContent,'61 to 75 of 75');assert.deepEqual(clamped.context.window.scrolled,[]);
 const oldState=makeList(75,15,{saved:{scroll:500}});assert.equal(oldState.text.textContent,'1 to 15 of 75');assert.deepEqual(oldState.context.window.scrolled,[500]);
 // Focus survives the last page: Next becomes disabled and focus moves to the current page.
 const last=makeList(45,15);await last.next.trigger();await last.next.trigger();assert.equal(last.next.disabled,true);assert.equal(pageButtons(last).find(c=>c.getAttribute('aria-current')==='page').focused,true);
 // Page number text never carries a sign.
 assert.ok(!/[-−]\s*\d/.test(h.text.textContent));
 // Timing: render for 5,000 records (mock DOM; informative, not asserted).
 for(const [label,size] of [['without paging (60 rows)',0],['with paging (15 rows)',15]]){
  const t0=process.hrtime.bigint(),big=makeList(5000,size),cold=Number(process.hrtime.bigint()-t0)/1e6;const runs=[];
  for(let i=0;i<7;i++){big.search.value=i%2?'Part 4':'Part';const t=process.hrtime.bigint();await big.search.trigger('input');runs.push(Number(process.hrtime.bigint()-t)/1e6);}
  runs.sort((a,b)=>a-b);
  if(process.env.BW_PAGING_TIMING)console.log('render 5000 records, '+label+': median '+runs[3].toFixed(2)+' ms (page load incl. decode and first render '+cold.toFixed(1)+' ms), rows built '+big.rows());
 }
 // Paged split (missing and present) list: each page attaches only its own rows, in reading order.
 const sp=makeList(40,15,{missing:20});
 const attached=()=>[...sp.missingRows.querySelectorAll('[data-bc-row]'),...sp.presentRows.querySelectorAll('[data-bc-row]')];
 assert.equal(attached().length,15);assert.equal(sp.missingRows.querySelectorAll('[data-bc-row]').length,15);
 const page1=attached();
 await sp.next.trigger();
 assert.equal(sp.text.textContent,'16 to 30 of 40');assert.equal(attached().length,15);
 assert.equal(sp.missingRows.querySelectorAll('[data-bc-row]').length,5);assert.equal(sp.presentRows.querySelectorAll('[data-bc-row]').length,10);
 assert.ok(attached().every(n=>!page1.includes(n)),'page 1 nodes are detached on page 2');
 const second=attached();await second[0].trigger('keydown',{key:'ArrowDown'});assert.equal(second[1].focused,true);
 await sp.next.trigger();assert.equal(attached().length,10);assert.equal(sp.missingRows.querySelectorAll('[data-bc-row]').length,0);
 console.log('paging runtime ok');
})().catch(e=>{console.error(e);process.exit(1);});
