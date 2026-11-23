const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const context={window:{},document:{addEventListener(){}}};
vm.runInNewContext((fs.readFileSync('static/web/toni/formatting.js','utf8')+fs.readFileSync(require('node:path').join(__dirname,'../static/web/toni/bw-checker.js'),'utf8')),context);
const {progress,summary,cells,apply,merge,Queue,keyCommand}=context.window.BrickChecker;
const make=()=>({rows:[{token:'p:1',kind:'part',quantity:4,missing:0},{token:'p:2',kind:'part',quantity:2,missing:0},{token:'m:1',kind:'figure',quantity:1,missing:0},{token:'p:3',kind:'spare',quantity:1,missing:1,color_name:'Red',item_no:'b'},{token:'p:4',kind:'spare',quantity:3,missing:0,color_name:'Blue',item_no:'a'}],session:{id:'session',order:['p:1','p:2','m:1'],cursor:0,answers:{},misses:[],undo:[],spares:null,sort:'inventory'}});
const plain=x=>JSON.parse(JSON.stringify(x));
const state=make();
assert.deepEqual(plain(progress(state)),{found:0,missing:0,skipped:0,remaining:3});
{ // #489 (Argon review): a copy a pull labelled counts every line as checked before any session, as its bars do
  const labelled=make();labelled.session=null;labelled.copy={checked_by:'rebrickable'};   // the landing screen: no session yet
  assert.deepEqual(plain(progress(labelled)),{found:3,missing:0,skipped:0,remaining:0});
  assert.equal(summary(labelled).pieces,summary(labelled).total);
  const figure=make();figure.session=null;figure.copy={checked_by:'rebrickable'};figure.figure={id:'f1'};   // a figure's parts check: the label covers the set's list, never a figure's components
  assert.deepEqual(plain(progress(figure)),{found:0,missing:0,skipped:0,remaining:3});
  assert.equal(summary(figure).pieces,0);
}
apply(state,{action:'answer',token:'p:1',found:3});
assert.equal(state.rows[0].missing,1);assert.equal(state.session.cursor,1);
apply(state,{action:'skip',token:'p:2'});
apply(state,{action:'answer',token:'m:1',found:0});
assert.deepEqual(plain(progress(state)),{found:0,missing:2,skipped:1,remaining:0});
assert.deepEqual(plain(state.session.misses),['m:1','p:1']);
apply(state,{action:'found_one',token:'p:1'});assert.equal(state.rows[0].missing,0);
assert.deepEqual(plain(state.session.misses),['m:1']);   // #383: a part found in full leaves Missing so far
apply(state,{action:'answer',token:'p:1',found:3});assert.deepEqual(plain(state.session.misses),['p:1','m:1']);   // and a new miss goes back on top
{ // R3-02: "142 of 375 parts" counts the pieces of the answered part lines, and the strip is one cell per line, never one per piece.
 const s=make(), before=plain(summary(s));
 assert.deepEqual([before.pieces,before.total,before.lines,before.figures],[0,6,3,true]);
 apply(s,{action:'answer',token:'p:1',found:3});apply(s,{action:'skip',token:'p:2'});
 const after=plain(summary(s));
 assert.deepEqual([after.pieces,after.total,after.missing,after.skipped,after.remaining],[4,6,1,1,1]);   // a skipped line is still to check; its pieces are not counted
 const cursor=s.session.cursor;apply(s,{action:'set_count',token:'p:1',found:4});
 assert.equal(s.rows[0].missing,0);assert.equal(s.session.cursor,cursor,'editing a listed line leaves the cursor where it is');assert.deepEqual(plain(s.session.misses),['m:1'].filter(t=>s.session.misses.includes(t)));
 const frame=plain(cells({found:54,missing:4,skipped:0,remaining:73}));
 assert.equal(frame.marks.length,131);assert.equal(frame.per,1);assert.equal(frame.marks.slice(0,54).join(''),'f'.repeat(54));assert.equal(frame.marks.slice(54,58).join(''),'mmmm');assert.equal(frame.marks.slice(58).join(''),'u'.repeat(73));
 const big=plain(cells({found:600,missing:10,skipped:0,remaining:290}));
 assert(big.marks.length<=240);assert.equal(big.per,4);assert.equal(big.marks[0],'f');assert.equal(big.marks[big.marks.length-1],'u');   // 900 lines stay a strip of at most 240 cells
}
{ // #213: Found 1 in the sidebar, or answering a listed part again, keeps its place in Missing so far; only a new miss goes on top.
  const kept=make();
  apply(kept,{action:'answer',token:'p:1',found:1});apply(kept,{action:'answer',token:'m:1',found:0});
  assert.deepEqual(plain(kept.session.misses),['m:1','p:1']);
  apply(kept,{action:'found_one',token:'p:1'});assert.equal(kept.rows[0].missing,2);
  assert.deepEqual(plain(kept.session.misses),['m:1','p:1']);
  apply(kept,{action:'answer',token:'p:1',found:2});
  assert.deepEqual(plain(kept.session.misses),['m:1','p:1']);
  apply(kept,{action:'answer',token:'p:2',found:0});
  assert.deepEqual(plain(kept.session.misses),['p:2','m:1','p:1']);
}
apply(state,{action:'select',token:'p:2'});assert.equal(state.session.cursor,1);
apply(state,{action:'back'});assert.equal(state.session.cursor,0);
apply(state,{action:'next'});assert.equal(state.session.cursor,1);
for(const [key,result] of [['f',{action:'answer',count:4}],['m',{action:'missing'}],['s',{action:'skip'}],['z',{action:'undo'}],['ArrowLeft',{action:'back'}],['ArrowRight',{action:'next'}],['Enter',{action:'next'}],['9',{count:4}],['1',{count:1}]])assert.deepEqual(plain(keyCommand(key,false,true,4)),result);
assert.equal(keyCommand('f',true,true,4),null);assert.equal(keyCommand('f',false,true,null),null);
assert.deepEqual(plain(keyCommand('z',true,false,null)),{action:'undo'});
assert.equal(keyCommand('m',false,false,4),null);
// Offline spare order uses the server's group/size positions, including Other and ties.
{
 const grouped=make();grouped.session.sort='group';
 grouped.rows.push({token:'p:5',kind:'spare',group_order:1},{token:'p:6',kind:'spare',group_order:3});
 grouped.rows[3].group_order=4;grouped.rows[4].group_order=2;
 apply(grouped,{action:'spares',include:true});
 assert.deepEqual(plain(grouped.session.order).slice(3),['p:5','p:4','p:6','p:3']);
 const unknown=make();unknown.session.sort='old-mode';apply(unknown,{action:'spares',include:true});
 assert.deepEqual(plain(unknown.session.order).slice(3),['p:3','p:4']);
}
// Missing group ranks use quantity and token ties, including a mixed ranked/unranked pair.
{
 for (const ranked of [false,true]) {
  const fallback=make();fallback.session.sort='group';
  if(ranked) fallback.rows[3].group_order=0;
  apply(fallback,{action:'spares',include:true});
  assert.deepEqual(plain(fallback.session.order).slice(3),['p:4','p:3']);
 }
 const tied=make();tied.session.sort='group';tied.rows[3].quantity=3;
 tied.rows[3].token='p:z';tied.rows[4].token='p:a';
 apply(tied,{action:'spares',include:true});
 assert.deepEqual(plain(tied.session.order).slice(3),['p:a','p:z']);
}
// Answering one spare merges a subset delta without changing either spare's inventory ranks.
{
 const full=make();full.session.sort='group';
 full.rows[3].group_order=4;full.rows[3].largest_order=3;
 full.rows[4].group_order=2;full.rows[4].largest_order=1;
 apply(full,{action:'spares',include:true});
 const answered=plain(full);apply(answered,{action:'answer',token:'p:3',found:1});
 const result={partial:true,session:answered.session,rows:[{token:'p:3',missing:0,checked:1}]};
 const updated=merge(full,result);
 assert.deepEqual(plain(updated.rows.filter(r=>r.kind==='spare').map(r=>[r.group_order,r.largest_order])),[[4,3],[2,1]]);
 updated.session.order=updated.session.order.slice(0,3);
 apply(updated,{action:'spares',include:true});
 assert.deepEqual(plain(updated.session.order).slice(3),['p:4','p:3']);
}
// 4.8a: the last step asks about spares; "No" keeps them out of the sequence.
{
 const no=make();apply(no,{action:'spares',include:false});
 assert.equal(no.session.spares,'no');assert.deepEqual(plain(no.session.order),['p:1','p:2','m:1']);
 const yes=make();apply(yes,{action:'spares',include:true});
 assert.equal(yes.session.spares,'yes');assert.deepEqual(plain(yes.session.order),['p:1','p:2','m:1','p:3','p:4']);
 const largest=make();largest.session.sort='largest';apply(largest,{action:'spares',include:true});
 assert.deepEqual(plain(largest.session.order).slice(3),['p:4','p:3']);
 const colour=make();colour.session.sort='colour';apply(colour,{action:'spares',include:true});
 assert.deepEqual(plain(colour.session.order).slice(3),['p:4','p:3']);
 // Spares are never counted in the progress strip.
 assert.deepEqual(plain(progress(yes)),{found:0,missing:0,skipped:0,remaining:3});
}
// Save deltas preserve unchanged rows and GET images, including ordered replay.
const full=make();full.copy={id:'copy',image:77,set_checked:false};full.rows[0].image=42;
const delta={partial:true,copy:{set_checked:true},session:plain(full.session),rows:[{token:'p:1',missing:2}]};
const merged=merge(full,delta);
assert.equal(merged.rows.length,5);assert.equal(merged.rows[0].image,42);assert.equal(merged.rows[0].missing,2);
assert.equal(merged.copy.image,77);assert.equal(merged.copy.set_checked,true);assert.equal(merged.session.set_checked,undefined);
assert.equal(full.rows[0].missing,0);
(async()=>{
 const bytes=new Map();const storage={getItem:k=>bytes.get(k)||null,setItem:(k,v)=>bytes.set(k,v)};
 let online=false;const sent=[],updates=[];
 const send=async p=>{if(!online)throw Error('offline');sent.push(p.operation);return p.operation;};
 const queue=new Queue(storage,'copy',send,(...a)=>updates.push(a));
 queue.add({action:'answer',operation:'one'});queue.add({action:'answer',operation:'two'});
 await new Promise(resolve=>setImmediate(resolve));
 assert.equal(queue.items.length,2);assert.equal(updates[0][2].message,'offline');
 const restored=new Queue(storage,'copy',send,(...a)=>updates.push(a));
 assert.equal(restored.items.length,2);online=true;await restored.flush();
 assert.deepEqual(sent,['one','two']);assert.equal(storage.getItem('copy'),'[]');
 const blocked=new Queue(storage,'blocked',async()=>{throw Error('changed elsewhere');},()=>{});
 blocked.add({action:'answer',operation:'three'});blocked.add({action:'undo',operation:'four'});
 await new Promise(resolve=>setImmediate(resolve));assert.equal(blocked.items.length,2);
 const full=new Queue({getItem:()=>null,setItem:()=>{throw Error('full');}},'full',send,()=>{});
 assert.throws(()=>full.add({operation:'lost'}),/full/);assert.equal(full.items.length,0);
 let release;const sequential=new Queue(storage,'slow',p=>new Promise(resolve=>{release=()=>resolve(p);}),()=>{});
 sequential.add({operation:'slow'});sequential.flush();assert(sequential.running);assert.equal(sequential.items.length,1);release();await new Promise(resolve=>setImmediate(resolve));assert.equal(sequential.items.length,0);
 console.log('Brick Work checker model, keyboard and ordered offline queue passed');
})().catch(error=>{console.error(error);process.exitCode=1;});

// Mount the real screen against a small DOM, then exercise the actual handlers.
class Element {
 constructor(tag='div'){this.tagName=tag.toUpperCase();this.dataset={};this.style={};this.children=[];this.handlers={};this.textContent='';this.hidden=false;this.disabled=false;this._value='';}
 append(...nodes){this.children.push(...nodes);}
 appendChild(node){this.children=this.children.filter(n=>n!==node);this.children.push(node);return node;}
 replaceChildren(...nodes){this.children=nodes;}
 prepend(...nodes){this.children.unshift(...nodes);}
 addEventListener(type,fn){this.handlers[type]=fn;}
 setAttribute(name,value){this[name]=value;}
 get value(){return this._value||this.children.find(n=>n.tagName==='OPTION')?.value||'';}
 set value(value){this._value=value;}
 get selectedOptions(){return this.children.filter(n=>n.tagName==='OPTION'&&n.value===this.value);}
 querySelectorAll(selector){const m=/\[data-([\w-]+)/.exec(selector);const key=m?.[1].replace(/-([a-z])/g,(_,c)=>c.toUpperCase());const all=this.children.flatMap(n=>[n,...n.querySelectorAll(selector)]);const value=/="([^"]+)"/.exec(selector)?.[1];return all.filter(n=>key?Object.hasOwn(n.dataset,key)&&(value===undefined||n.dataset[key]===value):selector[0]==='#'?n.id===selector.slice(1):n.tagName===selector.toUpperCase());}
 querySelector(selector){return this.querySelectorAll(selector)[0]||null;}
 focus(){this.focused=true;}
 click(){this.handlers.click?.({preventDefault(){}});}
 closest(){return this;}
 get text(){return this.textContent+' '+this.children.map(n=>n.text).join(' ');}
}
// The default chooser excludes flagged copies even during an unfinished check.
{
 const root=new Element();root.dataset.copyChooser='';
 const field=(tag,key,value,options=[])=>{const n=new Element(tag);n.dataset[key]='';n.value=value;for(const v of options){const o=new Element('option');o.value=v;o.textContent=v;n.append(o);}root.append(n);return n;};
 const search=field('input','checkSearch','');const filter=field('select','filter','unchecked',['all','progress','unchecked']);const sort=field('select','checkSort','largest',['largest','number']);const direction=field('select','checkOrder','asc',['asc','desc']);
 const caption=field('p','sortCaption','');
 const headline=field('h1','choiceHeadline','');
 const entries=field('div','listRows','');field('div','chips','');field('p','checkCount','');const fallback=field('button','checkAllFallback','');const allCopies=new Element('button');allCopies.dataset.checkAllCopies='';
 for(const [number,count,state,checked] of [['small',1,'unchecked','false'],['flagged',999,'progress','true'],['large',20,'unchecked','false'],['active',2,'progress','false'],['finished',4,'checked','true'],['finished-unchecked',5,'unchecked','false']]){const r=new Element('a');r.dataset={listRow:'',number,name:number,count,state,checked};entries.append(r);}
 const sections={};for(const group of ['progress','unchecked','checked']){const section=new Element();section.dataset.copySection=group;const count=new Element();count.dataset.sectionCount='';const container=new Element();container.dataset.sectionRows='';section.append(count,container);sections[group]=section;}
 for(const row of [...entries.children])sections[row.dataset.state].querySelector('[data-section-rows]').append(row);entries.replaceChildren(...Object.values(sections));sections.unchecked.append(allCopies);
 const filterPanel=field('div','checkFilterPanel','');filterPanel.hidden=true;filterPanel.append(filter);const toggle=field('button','checkFilters','');
 let loaded;const browser={window:{},document:{addEventListener:(k,fn)=>loaded=fn,createElement:t=>new Element(t),querySelectorAll:()=>[root],querySelector:()=>null}};
 vm.runInNewContext((fs.readFileSync('static/web/toni/formatting.js','utf8')+fs.readFileSync(require('node:path').join(__dirname,'../static/web/toni/bw-checker.js'),'utf8')),browser);loaded();
 assert.deepEqual(entries.querySelectorAll('[data-list-row]').filter(r=>!r.hidden).map(r=>r.dataset.number),['active','large','finished-unchecked','small']);
 assert.equal(root.querySelector('[data-check-count]').textContent,'4 results');
 assert.equal(caption.textContent,'Largest first');
 const agreement=()=>{const visible=entries.querySelectorAll('[data-list-row]').filter(r=>!r.hidden);for(const group of ['progress','unchecked','checked'])assert.equal(Number(sections[group].querySelector('[data-section-count]').textContent),visible.filter(r=>r.dataset.state===group).length);const p=visible.filter(r=>r.dataset.state==='progress').length,u=visible.filter(r=>r.dataset.state==='unchecked').length;assert.equal(headline.textContent,`${p} ${p===1?'check':'checks'} in progress, ${u} ${u===1?'set':'sets'} not checked`);};
 agreement();
 for(const value of ['all','progress','unchecked'])for(const term of ['','active','flagged','finished','no match']){filter.value=value;search.value=term;search.handlers.input();agreement();}
 filter.value='unchecked';search.value='';search.handlers.input();
 direction.value='desc';direction.handlers.input();assert.equal(caption.textContent,'Smallest first');
 sort.value='number';sort.handlers.input();assert.equal(caption.textContent,'Number · descending');
 direction.value='asc';direction.handlers.input();assert.equal(caption.textContent,'Number');
 sort.value='largest';sort.handlers.input();
 search.value='large';search.handlers.input();assert.equal(entries.querySelectorAll('[data-list-row]').filter(r=>!r.hidden).length,1);search.value='';search.handlers.input();
 toggle.handlers.click();assert.equal(filterPanel.hidden,false);assert.equal(filter.focused,true);root.handlers.keydown({key:'Escape',target:toggle});assert.equal(filterPanel.hidden,true);assert.equal(toggle.focused,true);
 assert.equal(root.querySelector('[data-chips]').children.length,0);assert.equal(allCopies.hidden,false);assert.equal(fallback.hidden,true);allCopies.handlers.click();assert.equal(filter.value,'all');assert.equal(allCopies.hidden,true);assert.equal(root.querySelector('[data-chips]').children.length,0);agreement();
 {// Nothing visible in the unchecked section: the section button goes with it, the fallback stays reachable.
  filter.value='unchecked';search.value='no such copy';filter.handlers.input();
  assert.equal(sections.unchecked.hidden,true);assert.equal(allCopies.hidden,true);assert.equal(fallback.hidden,false);
  fallback.handlers.click();assert.equal(filter.value,'all');assert.equal(fallback.hidden,true);
  search.value='';filter.handlers.input();}
 assert.equal(entries.querySelectorAll('[data-list-row]').filter(r=>!r.hidden).length,6);
 filter.value='progress';filter.handlers.input();assert.equal(entries.querySelectorAll('[data-list-row]').filter(r=>!r.hidden).length,2);assert.equal(sections.unchecked.hidden,true);assert.equal(sections.progress.querySelector('[data-section-count]').textContent,2);
 filter.value='all';sort.value='name';filter.handlers.input();assert.equal(caption.textContent,'Name');assert.deepEqual(sections.unchecked.querySelectorAll('[data-list-row]').map(r=>r.dataset.number),['finished-unchecked','large','small']);
}
(async()=>{
 const root=new Element();root.id='bw-checker';root.dataset={checkStage:'running',endpoint:'/check/copy',imageUrl:'/images/0',unresolvedUrl:'/unresolved'};
 const initial=make();initial.copy={id:'copy',completeness_source:'manual'};
 const stateEl=new Element('script');stateEl.dataset.checkState='';stateEl.textContent=JSON.stringify(initial);root.append(stateEl);
 for(const key of ['copyStatus','checkBody','stage','history','progress','legend','chkBig','chkCellsLabel','chkTag']){const n=new Element();n.dataset[key]='';root.append(n);}
 const feedback=new Element();feedback.dataset.saveFeedback='';root.children.unshift(feedback);
 for(const key of ['saveStatus','saveUndo','retry']){const n=new Element(key==='saveStatus'?'span':'button');n.dataset[key]='';n.hidden=key!=='saveStatus';if(key==='saveUndo')n.dataset.action='undo';feedback.append(n);}
 const undoButton=feedback.querySelector('[data-save-undo]');
 initial.rows[0].name='Plate 2 x 4';initial.rows[0].item_no='3020';initial.rows[0].color_name='Tan';
 initial.rows[1].name='98313';initial.rows[1].item_no='98313';initial.rows[1].color_name='Pearl Dark Gray';
 initial.rows[2].name='';initial.rows[2].item_no='figure-1';
 stateEl.textContent=JSON.stringify(initial);
 const timers=new Map();let timerId=0;
 const handlers={};const data=new Map();let server=plain(initial),receipt=0;
 const browser={window:{addEventListener(){}},document:{addEventListener:(k,fn)=>handlers[k]=fn,createElement:t=>new Element(t),querySelector:s=>s==='#bw-checker'?root:null,querySelectorAll:()=>[]},
 localStorage:{getItem:k=>data.get(k)||null,setItem:(k,v)=>data.set(k,v)},crypto:{randomUUID:()=>String(++receipt)},setTimeout:(fn,ms)=>{const id=++timerId;timers.set(id,{fn,ms});return id;},clearTimeout:id=>timers.delete(id),
 fetch:async(url,options)=>{const payload=JSON.parse(options.body);if(payload.action==='undo')throw Error('offline');apply(server,payload);if(payload.action==='finish')server.copy.completeness='complete';server.session.undo.push(receipt);return {ok:true,json:async()=>({state:{partial:true,copy:plain(server.copy),session:plain(server.session),rows:server.rows.filter(r=>r.token===payload.token).map(r=>plain(r))}})};}};
 vm.runInNewContext((fs.readFileSync('static/web/toni/formatting.js','utf8')+fs.readFileSync(require('node:path').join(__dirname,'../static/web/toni/bw-checker.js'),'utf8')),browser);handlers.DOMContentLoaded();
  const stage=root.querySelector('[data-stage]');assert(stage.text.includes('Found ×4'));assert(stage.text.includes('Part line 1'));
 // R3-02: the answer card is its own .b-prime scope: head, picture, Need beside the name block, the old stepper, Missing, Back / Skip / Undo.
 const card=()=>stage.children[0].children[0], block=()=>card().children[2].children[1];
 assert.equal(stage.children[0].className,'bp-chk b-prime');
 assert.deepEqual([block().children[0].textContent,block().children[1].children.map(n=>n.textContent).join('|')],['Plate 2\u00a0×\u00a04','Tan|3020']);   // the card shows a name as every name does: × and the tail kept together (#630)
 assert.equal(block().style.backgroundColor,undefined,'no colour in the test data: the plain block');
 assert(block().className.includes('chk-plain'));
 assert.equal(root.querySelector('[data-toast]'),null);
 assert(root.children.indexOf(feedback)<root.children.indexOf(stage),'Top status precedes the part heading');
 const template=fs.readFileSync(require('node:path').join(__dirname,'../templates/web/toni/web/bw_checker.html'),'utf8');
 assert(!template.includes('data-toast'));
 assert(template.indexOf('data-save-feedback')<template.indexOf('data-stage'));
 const css=fs.readFileSync(require('node:path').join(__dirname,'../static/web/toni/bw-checker.css'),'utf8');
 assert(!css.includes('.check-toast'));
 // The frame has no row for the message (R3-02), so the bar is hidden while empty and floats at the top right of the page, beside the label, while it shows; nothing sticks to the stepper.
 assert(!/\.check-stepper\{[^}]*position:(?:sticky|fixed|absolute)/.test(css));assert(/data-bp-checker\] \.check-save-feedback \{ position:absolute/.test(css));
 assert(!root.querySelector('[data-legend]').text.includes('to go'));
 const click=action=>{const target=root.querySelectorAll('[data-action]').find(b=>b.dataset.action===action&&!b.disabled);assert(target,'Action '+action+' exists');root.handlers.click({target});};
 const primaryAnswer=stage.querySelectorAll('[data-action]').find(n=>n.dataset.action==='answer');
 assert.equal(primaryAnswer.className,'btn chk-found');
 assert.equal(card().children[2].children[0].children[1].textContent,'4');   // Need 4
 assert(!stage.text.includes('4 required'));
 const missingButton=stage.querySelectorAll('[data-action]').find(n=>n.dataset.action==='missing');
 assert.equal(missingButton.className,'btn sec chk-missing');
 const nav=card().children.find(n=>n.className==='chk-nav');
 assert.deepEqual(nav.children.map(n=>n.textContent),['Back','Skip for later','Undo']);
 const history=root.querySelector('[data-history]');
 assert(history.text.includes('Checked so far'));assert(history.text.includes('Nothing checked yet.'));
 assert.equal(history.querySelectorAll('SELECT').length,0);
 assert.equal(history.querySelectorAll('INPUT').length,0);
 assert(!history.text.includes('results'));
 assert(!/[−–-]\d/.test(stage.text+' '+root.querySelector('[data-history]').text));
 click('decrease');assert(stage.text.includes('Found ×3'));click('answer');
 await new Promise(resolve=>setImmediate(resolve));assert.equal(server.rows[0].missing,1);assert.equal(server.rows[0].checked,1);assert(history.text.includes('Missing · larger, so the count stays editable'));assert(history.text.includes('1 missing'));assert.equal(history.querySelectorAll('[data-action]').filter(b=>b.dataset.action==='set_count').length,2);assert(stage.text.includes('Found ×2'));
 // #649: the stepper of a missing line counts what was found (need 4, 1 missing: "3 found"); − is one fewer found, + one more found, 0 to the need
 {const steps=()=>history.querySelectorAll('[data-action]').filter(b=>b.dataset.action==='set_count');const [less,more]=steps();
  assert.deepEqual([less.textContent,less.dataset.delta,less['aria-label'].startsWith('One fewer found'),less.disabled],['−','1',true,false]);
  assert.deepEqual([more.textContent,more.dataset.delta,more['aria-label'].startsWith('One more found'),more.disabled],['+','-1',true,false]);
  const mid=history.querySelectorAll('SPAN').find(n=>n.className==='chk-found-n');assert.equal(mid.text.replace(/\s+/g,' ').trim(),'3 found');
  root.handlers.click({target:less});await new Promise(resolve=>setImmediate(resolve));assert.equal(server.rows[0].missing,2);   // one fewer found = one more missing
  assert.equal(history.querySelectorAll('SPAN').find(n=>n.className==='chk-found-n').text.replace(/\s+/g,' ').trim(),'2 found');
  root.handlers.click({target:steps()[1]});await new Promise(resolve=>setImmediate(resolve));assert.equal(server.rows[0].missing,1);   // and back
  assert.equal(history.querySelectorAll('SPAN').find(n=>n.className==='chk-found-n').text.replace(/\s+/g,' ').trim(),'3 found');
  for(let n=0;n<3;n++){root.handlers.click({target:steps()[0]});await new Promise(resolve=>setImmediate(resolve));}   // down to 0 found: − stops there
  assert.equal(server.rows[0].missing,4);assert.equal(steps()[0].disabled,true);assert.equal(steps()[1].disabled,false);
  assert.equal(history.querySelectorAll('SPAN').find(n=>n.className==='chk-found-n').text.replace(/\s+/g,' ').trim(),'0 found');
  for(let n=0;n<3;n++){root.handlers.click({target:steps()[1]});await new Promise(resolve=>setImmediate(resolve));}
  assert.equal(server.rows[0].missing,1);}
 assert.equal(undoButton.hidden,false);assert(root.querySelector('[data-save-status]').text.includes('Saved'));
 assert.equal(feedback.querySelector('[data-action]'),undoButton);
 assert.deepEqual([block().children[0].textContent,block().children[1].children.map(n=>n.textContent).join('|')],['98313','Pearl Dark Gray|98313']);
 const expiry=[...timers.values()].find(t=>t.ms===5000);assert(expiry);expiry.fn();
 assert.equal(undoButton.hidden,true);assert.equal(root.querySelector('[data-save-status]').textContent,'');
 const key=k=>handlers.keydown({key:k,target:new Element(),preventDefault(){}});
 key('m');await new Promise(resolve=>setImmediate(resolve));assert.equal(server.rows[1].missing,2);
 assert.equal(block().children[0].textContent,'figure-1');
 key('f');await new Promise(resolve=>setImmediate(resolve));assert.equal(server.rows[2].missing,0);
 // The final step: two buttons, "No" first, primary and focused; "Yes" outlined.
 assert(stage.text.includes('Include spare parts?'));assert(!stage.text.includes('Spare pass'));
 const spareNo=stage.querySelectorAll('[data-action]').find(b=>b.dataset.action==='spares_no'),spareYes=stage.querySelectorAll('[data-action]').find(b=>b.dataset.action==='spares_yes');
 assert.equal(spareNo.textContent,'No, skip them');assert.equal(spareNo.className,'primary bw-primary');assert.equal(spareNo.focused,true);
 assert.equal(spareYes.textContent,'Yes, check them');assert(!spareYes.className);
 assert(!/[−–-]\d/.test(stage.text));
 click('spares_yes');await new Promise(resolve=>setImmediate(resolve));assert.equal(server.session.spares,'yes');assert(stage.text.includes('Spare pass'));
 key('s');await new Promise(resolve=>setImmediate(resolve));assert(stage.text.includes('Spare pass'));
 key('s');await new Promise(resolve=>setImmediate(resolve));assert(stage.text.includes('Found one in the pile?'));assert(stage.text.includes('Done · 3 still missing'));assert(!/[−–-]\d/.test(stage.text));assert(stage.text.includes('missing of'));
 click('found_one');await new Promise(resolve=>setImmediate(resolve));assert(stage.text.includes('Done · 2 still missing'));
 click('finish_view');assert(stage.text.includes('Set is checked'));assert(stage.text.includes('Your manual completeness stays unchanged.'));
 assert(root.querySelector('[data-copy-status]').hidden);click('finish');await new Promise(resolve=>setImmediate(resolve));assert(stage.text.includes('Check saved'));assert(root.querySelector('[data-copy-status]').text.includes('Complete'));assert(!root.querySelector('[data-copy-status]').hidden);
 key('z');await new Promise(resolve=>setImmediate(resolve));assert(root.querySelector('[data-save-status]').text.includes('Not saved · waiting for network'));assert.equal(root.querySelector('[data-retry]').hidden,false);
 console.log('Brick Work checker mounted screens, count actions, passes, finish and offline feedback passed');
})().catch(error=>{console.error(error);process.exitCode=1;});

// 4.8a: the default "No" skips the spare pass, a copy without spares never sees the
// step, and the figure stepper reuses the same machinery without touching the set.
function boot(initial, dataset) {
 const root=new Element();root.id='bw-checker';root.dataset={checkStage:dataset.landing==='true'?'start':'running',...dataset};
 const stateEl=new Element('script');stateEl.dataset.checkState='';stateEl.textContent=JSON.stringify(initial);root.append(stateEl);
 for(const key of ['copyStatus','checkBody','stage','history','progress','legend','chkBig','chkCellsLabel','chkTag']){const n=new Element();n.dataset[key]='';root.append(n);}
 const feedback=new Element();feedback.dataset.saveFeedback='';root.children.unshift(feedback);
 for(const key of ['saveStatus','saveUndo','retry']){const n=new Element(key==='saveStatus'?'span':'button');n.dataset[key]='';n.hidden=key!=='saveStatus';if(key==='saveUndo')n.dataset.action='undo';feedback.append(n);}
 if(root.dataset.checkStage==='start'){
  const start=new Element();start.dataset.start='';root.append(start);
  const resume=new Element('a');resume.dataset.resume='';start.append(resume);
 }
 const handlers={},data=new Map(),sent=[];let server=plain(initial),receipt=0;
 const browser={window:{addEventListener(){}},document:{addEventListener:(k,fn)=>handlers[k]=fn,createElement:t=>new Element(t),querySelector:s=>s==='#bw-checker'?root:null,querySelectorAll:()=>[]},
  localStorage:{getItem:k=>data.get(k)||null,setItem:(k,v)=>data.set(k,v)},crypto:{randomUUID:()=>String(++receipt)},setTimeout:()=>0,clearTimeout(){},
  fetch:async(url,options)=>{const payload=JSON.parse(options.body);sent.push({url,payload});apply(server,payload);server.session.undo.push(receipt);return {ok:true,json:async()=>({state:{partial:true,copy:plain(server.copy),session:plain(server.session),rows:[]}})};}};
 vm.runInNewContext((fs.readFileSync('static/web/toni/formatting.js','utf8')+fs.readFileSync(require('node:path').join(__dirname,'../static/web/toni/bw-checker.js'),'utf8')),browser);handlers.DOMContentLoaded();
 const stage=root.querySelector('[data-stage]');
 const click=action=>{const target=root.querySelectorAll('[data-action]').find(b=>b.dataset.action===action&&!b.disabled);assert(target,'Action '+action+' exists');root.handlers.click({target});};
 const settle=()=>new Promise(resolve=>setImmediate(resolve));
 return {root,stage,click,settle,sent,server:()=>server,key:key=>handlers.keydown({key,target:new Element(),preventDefault(){}})};
}
(async()=>{
 // "No" is the default: it moves on to the missing review without spare tokens.
 const withSpares=make();withSpares.copy={id:'copy',completeness_source:'derived'};
 withSpares.session.cursor=3;withSpares.session.answers={'p:1':'answered','p:2':'answered','m:1':'answered'};
 let screen=boot(withSpares,{endpoint:'/check/copy',imageUrl:'/images/0',unresolvedUrl:'/unresolved'});
 assert(screen.stage.text.includes('Include spare parts?'));
 screen.click('spares_no');await screen.settle();
 assert.equal(screen.server().session.spares,'no');assert(!screen.stage.text.includes('Include spare parts?'));
 assert(screen.stage.text.includes('Found one in the pile?'));
 assert.deepEqual(screen.sent.map(x=>x.payload.action),['spares']);assert.equal(screen.sent[0].payload.include,false);
 // A copy without spare lines has no spare step.
 const none=make();none.rows=none.rows.filter(r=>r.kind!=='spare');none.copy={id:'copy',completeness_source:'derived'};
 none.session.cursor=3;none.session.answers={'p:1':'answered','p:2':'answered','m:1':'answered'};
 screen=boot(none,{endpoint:'/check/copy',imageUrl:'/images/0',unresolvedUrl:'/unresolved'});
 assert(!screen.stage.text.includes('Include spare parts?'));assert(screen.stage.text.includes('Found one in the pile?'));
 // Figure stepper: its own endpoint, no set checkbox, no spare question, Done returns to the set.
 const figure={copy:{id:'copy',completeness_source:'derived'},figure:{id:3,item_type:'M',item_no:'fig-1',name:'Figure',quantity:1,missing:0},
  rows:[{token:'p:1',kind:'part',quantity:2,missing:0,name:'Hair',item_no:'h',color_name:'Black',parent_minifig:'fig-1'},{token:'p:2',kind:'part',quantity:1,missing:0,name:'Legs',item_no:'l',color_name:'Blue',parent_minifig:'fig-1'},
         {token:'p:9',kind:'spare',quantity:1,missing:0,name:'Spare',item_no:'s',color_name:'Red'}],
  session:{id:'fig-session',order:['p:1','p:2'],cursor:0,answers:{},misses:[],undo:[],spares:null,sort:'inventory'}};
 screen=boot(figure,{endpoint:'/check/copy/figure/M/fig-1',doneUrl:'/set?inventory=figures',imageUrl:'/images/0',unresolvedUrl:'/unresolved'});
 assert(screen.stage.text.includes('Part line 1 of 2'));
 screen.click('decrease');screen.click('answer');await screen.settle();
 assert.equal(screen.server().rows[0].missing,1);assert.equal(screen.sent[0].url,'/check/copy/figure/M/fig-1');
 screen.click('answer');await screen.settle();
 // Even with a spare line in the rows, a figure never asks the spare question.
 assert(!screen.stage.text.includes('Include spare parts?'));assert(screen.stage.text.includes('Found one in the pile?'));
 screen.click('finish_view');
 assert(!screen.stage.text.includes('Set is checked'));assert(screen.stage.text.includes('count on the figure, not on the set'));
 screen.click('finish');await screen.settle();
 assert.equal(screen.sent.at(-1).payload.checked,undefined);
 assert(screen.stage.text.includes('Figure parts checked'));assert(screen.stage.text.includes('unchanged'));
 const done=screen.stage.querySelectorAll('A').find(n=>n.textContent==='Done')||screen.stage.children.find(n=>n.textContent==='Done');
 assert.equal(done.href,'/set?inventory=figures');
 // A whole figure line links to its own parts and shows how many are missing.
 const wholeFigure=make();wholeFigure.copy={id:'copy',completeness_source:'derived'};
 Object.assign(wholeFigure.rows[2],{id:7,item_type:'M',item_no:'fig-1',name:'Figure',parts_lines:5,parts_missing:2});
 wholeFigure.session.cursor=2;
 screen=boot(wholeFigure,{endpoint:'/check/copy',figureUrl:'/check/copy/figure/0',imageUrl:'/images/0',unresolvedUrl:'/unresolved'});
 assert(screen.stage.text.includes('2 parts missing'));
 const link=screen.stage.children.flatMap(n=>[n,...n.querySelectorAll('A')]).find(n=>n.textContent==='Check figure parts');
 assert.equal(link.href,'/check/copy/figure/7');
 console.log('Brick Work spare question and figure stepper passed');
})().catch(error=>{console.error(error);process.exitCode=1;});

// C1: a saved check opens on the copy page; Resume only reveals the stage.
{
 const initial=make();initial.copy={id:'copy',completeness_source:'derived'};
 initial.session.cursor=1;initial.session.answers={'p:1':'answered'};
 const screen=boot(initial,{endpoint:'/check/copy',imageUrl:'/images/0',landing:'true'});
 assert.equal(screen.root.querySelector('[data-check-body]').hidden,true);
 assert.equal(screen.stage.children.length,0);
 screen.key('f');assert.equal(screen.sent.length,0);
 screen.root.querySelector('[data-resume]').click();
 assert.equal(screen.root.querySelector('[data-check-body]').hidden,false);
 assert.equal(screen.root.querySelector('[data-start]').hidden,true);
 assert(screen.stage.text.includes('Part line 2 of 3'));
 assert.equal(screen.sent.length,0);
 assert.equal(screen.server().session.cursor,1);
}

// Finished reloads use the server's start-card decision, even with run=1.
for(const figureMode of [false,true]) {
 const initial=make();initial.copy={id:'copy'};initial.session.finished=true;
 if(figureMode)initial.figure={id:3,item_type:'M',item_no:'fig-1'};
 const screen=boot(initial,{endpoint:'/check/copy',imageUrl:'/images/0',landing:'false',checkStage:'start'});
 assert.equal(screen.root.querySelector('[data-check-body]').hidden,true);
 assert.equal(screen.root.querySelector('[data-start]').hidden,false);
 assert.equal(screen.stage.children.length,0);
 screen.key('f');assert.equal(screen.sent.length,0);
}
// Mixed missing history counts entries, including figures, with unsigned totals.
{
 const initial=make();initial.copy={id:'copy'};
 initial.session.misses=['p:1','p:2','m:1'];initial.session.answers={'p:1':'answered','p:2':'answered','m:1':'answered'};initial.session.order=['p:1','p:2','m:1'];
 initial.rows.filter(r=>initial.session.misses.includes(r.token)).forEach(r=>r.missing=1);
 const screen=boot(initial,{endpoint:'/check/copy',imageUrl:'/images/0'});
 assert.equal(screen.root.querySelector('[data-history]').text.split('1 missing').length-1,3);   // three larger cards, each with its own stepper
 assert(!/[−–-]\d/.test(screen.root.querySelector('[data-history]').text));
}

// R3-02: "Checked so far" shows the last four answers; a line with missing parts older than that stays one button away, and a miss a narrowed walk left out of `order` is reachable too.
{
 const initial=make();initial.copy={id:'copy'};
 for(let i=10;i<16;i++)initial.rows.push({token:'p:'+i,kind:'part',quantity:2,missing:i===10||i===99?1:0,name:'Part '+i,item_no:String(i),color_name:'Red'});
 initial.rows.push({token:'p:99',kind:'part',quantity:2,missing:1,name:'Left out',item_no:'99',color_name:'Red'});
 initial.session.order=['p:10','p:11','p:12','p:13','p:14','p:15'];initial.session.cursor=6;initial.session.misses=['p:99','p:10'];
 initial.session.answers={'p:99':'answered'};for(const t of initial.session.order)initial.session.answers[t]='answered';
 const screen=boot(initial,{endpoint:'/check/copy',imageUrl:'/images/0'});
 const history=screen.root.querySelector('[data-history]');
 assert(history.text.includes('Show all 7 checked lines · 2 more with missing parts'));
 assert.equal(history.querySelectorAll('[data-action]').filter(b=>b.dataset.action==='set_count').length,0,'none of the last four has a missing count');
 screen.root.handlers.click({target:history.querySelectorAll('[data-action]').find(b=>b.dataset.action==='show_found')});
 const all=screen.root.querySelector('[data-history]');
 assert.equal(all.querySelectorAll('[data-action]').filter(b=>b.dataset.action==='set_count').length,4,'both missing lines, the one left out of the walk too, have a stepper');
}
// #222: a missing-only run counts the parts it walks. #214: Check on skipped parts walks them in the part view.
{
  const run=make();run.session.scope='missing';run.session.order=['p:1'];run.session.answers={'p:2':'answered'};
  assert.deepEqual(plain(progress(run)),{found:0,missing:0,skipped:0,remaining:1});
  const skipped=make();skipped.session.answers={'p:1':'skipped','p:2':'answered','m:1':'skipped'};skipped.session.cursor=3;
  apply(skipped,{action:'recheck'});
  assert.deepEqual(plain(skipped.session.order),['p:1','m:1']);assert.equal(skipped.session.cursor,0);assert.equal(skipped.session.scope,'skipped');
  assert.equal(skipped.session.answers['p:2'],'answered');
  apply(skipped,{action:'recheck',tokens:['m:1']});assert.deepEqual(plain(skipped.session.order),['m:1']);
}

// #214 / #222: the end of a check shows three steps, starts at step 2 with nothing skipped; a missing-only run is headed and counted on its own.
(async()=>{
 const ended=()=>{const s=make();s.copy={id:'copy',completeness_source:'derived'};s.session.cursor=3;s.session.spares='no';s.session.answers={'p:1':'skipped','p:2':'answered','m:1':'skipped'};
  s.rows.forEach(r=>{r.name='Part';r.item_no=r.token;r.color_name='Red';r.image=null;});s.rows[1].missing=1;s.session.misses=['p:2'];return s;};
 let screen=boot(ended(),{endpoint:'/check/copy',imageUrl:'/images/0'});
 assert(screen.stage.text.includes('Skipped · 2 entries not checked yet'));
 assert(screen.stage.text.includes('Check the 2 skipped parts'));assert(screen.stage.text.includes('Leave them unchecked'));
 assert(screen.stage.text.includes('Missing so far · 1 entry'));
 assert(screen.stage.querySelectorAll('[data-action]').filter(b=>b.dataset.action==='check_one').length===2);
 screen.click('leave_skipped');
 assert(screen.stage.text.includes('Done · 1 still missing'));assert(!screen.stage.text.includes('Check the 2 skipped parts'));
 assert(screen.stage.querySelectorAll('LI').length===3,'Step 2 shows the 1/2/3 header');assert.equal(screen.stage.children[0].tagName,'OL');
 screen.click('finish_view');assert(screen.stage.text.includes('Finish'));
 // Check on one skipped part walks only that part in the part view.
 screen=boot(ended(),{endpoint:'/check/copy',imageUrl:'/images/0'});
 const one=screen.stage.querySelectorAll('[data-action]').find(b=>b.dataset.action==='check_one'&&b.dataset.token==='m:1');
 screen.root.handlers.click({target:one});await screen.settle();
 assert.equal(screen.sent[0].payload.action,'recheck');assert.deepEqual(screen.sent[0].payload.tokens,['m:1']);
 assert.deepEqual(JSON.parse(JSON.stringify(screen.server().session.order)),['m:1']);assert(screen.stage.text.includes('Figure review'));
 // Nothing skipped: the screen starts at the missing step.
 const none=ended();none.session.answers={'p:1':'answered','p:2':'answered','m:1':'answered'};
 screen=boot(none,{endpoint:'/check/copy',imageUrl:'/images/0'});
 assert(!screen.stage.text.includes('not checked yet'));assert(screen.stage.text.includes('Done · 1 still missing'));
 // A missing-only run: heading with the tag, the part's missing count, its own legend.
 const run=ended();run.session.scope='missing';run.session.order=['p:2'];run.session.cursor=0;run.session.answers={'p:1':'answered'};run.rows[1].quantity=3;
 screen=boot(run,{endpoint:'/check/copy',imageUrl:'/images/0'});
 assert(screen.stage.text.includes('Missing part line 1 of 1'));assert(screen.stage.text.includes('Missing only'));
 assert(screen.stage.text.includes('Missing since the last check: 1 of 3'));assert(screen.stage.text.includes('Found ×3'));
 assert.equal(screen.root.querySelector('[data-legend]').children.map(n=>n.textContent).join(' · '),'0 lines found · 0 missing · 1 to check · missing parts only');
 console.log('Brick Work checker end steps and missing-only run passed');
})().catch(error=>{console.error(error);process.exitCode=1;});

// Review of a part outside a narrowed walk joins the walk; a missing-only run stays one after a skipped walk and counts its own members.
{
  const s=make();s.session.order=['p:1'];s.session.cursor=1;s.session.answers={'p:1':'answered'};
  apply(s,{action:'select',token:'m:1'});assert.deepEqual(plain(s.session.order),['p:1','m:1']);assert.equal(s.session.cursor,1);
  const run=make();run.session.scope='missing';run.session.members=['p:1','p:2'];run.session.order=['p:1','p:2'];run.session.answers={'p:1':'answered','p:2':'skipped'};
  apply(run,{action:'recheck'});assert.equal(run.session.scope,'missing');assert.deepEqual(plain(run.session.order),['p:2']);
  assert.deepEqual(plain(progress(run)),{found:1,missing:0,skipped:1,remaining:0});
}
