const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const context={window:{},document:{addEventListener(){}}};
vm.runInNewContext((fs.readFileSync('static/web/toni/formatting.js','utf8')+fs.readFileSync(require('node:path').join(__dirname,'../static/web/toni/bw-checker.js'),'utf8')),context);
const {progress,apply,merge,Queue,keyCommand}=context.window.BrickChecker;
const make=()=>({rows:[{token:'p:1',kind:'part',quantity:4,missing:0},{token:'p:2',kind:'part',quantity:2,missing:0},{token:'m:1',kind:'figure',quantity:1,missing:0},{token:'p:3',kind:'spare',quantity:1,missing:1,color_name:'Red',item_no:'b'},{token:'p:4',kind:'spare',quantity:3,missing:0,color_name:'Blue',item_no:'a'}],session:{id:'session',order:['p:1','p:2','m:1'],cursor:0,answers:{},misses:[],undo:[],spares:null,sort:'inventory'}});
const plain=x=>JSON.parse(JSON.stringify(x));
const state=make();
assert.deepEqual(plain(progress(state)),{found:0,missing:0,skipped:0,remaining:3});
apply(state,{action:'answer',token:'p:1',found:3});
assert.equal(state.rows[0].missing,1);assert.equal(state.session.cursor,1);
apply(state,{action:'skip',token:'p:2'});
apply(state,{action:'answer',token:'m:1',found:0});
assert.deepEqual(plain(progress(state)),{found:0,missing:2,skipped:1,remaining:0});
assert.deepEqual(plain(state.session.misses),['m:1','p:1']);
apply(state,{action:'found_one',token:'p:1'});assert.equal(state.rows[0].missing,0);
assert.deepEqual(plain(state.session.misses),['m:1','p:1']);
apply(state,{action:'select',token:'p:2'});assert.equal(state.session.cursor,1);
apply(state,{action:'back'});assert.equal(state.session.cursor,0);
apply(state,{action:'next'});assert.equal(state.session.cursor,1);
for(const [key,result] of [['f',{action:'answer',count:4}],['m',{action:'missing'}],['s',{action:'skip'}],['z',{action:'undo'}],['ArrowLeft',{action:'back'}],['ArrowRight',{action:'next'}],['Enter',{action:'next'}],['9',{count:4}],['1',{count:1}]])assert.deepEqual(plain(keyCommand(key,false,true,4)),result);
assert.equal(keyCommand('f',true,true,4),null);assert.equal(keyCommand('f',false,true,null),null);
assert.deepEqual(plain(keyCommand('z',true,false,null)),{action:'undo'});
assert.equal(keyCommand('m',false,false,4),null);
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
 for(const key of ['copyStatus','checkBody','stage','history','progress','legend']){const n=new Element();n.dataset[key]='';root.append(n);}
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
 const strip=root.querySelector('[data-progress]'), originalSegment=strip.children[0];
 const stage=root.querySelector('[data-stage]');assert(stage.text.includes('Found 4'));assert(stage.text.includes('Part 1'));
 const identity=()=>stage.children[1].children[1];
 assert.deepEqual(identity().children.slice(0,3).map(n=>n.textContent),['Tan','Plate 2\u00a0x\u00a04','3020']);
 assert.equal(identity().children[1].tagName,'H2');
 assert.equal(root.querySelector('[data-toast]'),null);
 assert(root.children.indexOf(feedback)<root.children.indexOf(stage),'Top status precedes the part heading');
 const template=fs.readFileSync(require('node:path').join(__dirname,'../templates/web/toni/web/bw_checker.html'),'utf8');
 assert(!template.includes('data-toast'));
 assert(template.indexOf('data-save-feedback')<template.indexOf('data-stage'));
 const css=fs.readFileSync(require('node:path').join(__dirname,'../static/web/toni/bw-checker.css'),'utf8');
 assert(!css.includes('.check-toast'));
 for(const rule of css.matchAll(/\.check-(?:stepper|save-feedback)\{([^}]*)\}/g))assert(!/position:(?:sticky|fixed|absolute)/.test(rule[1]),'Feedback and answers stay in flow at every width');
 assert(!root.querySelector('[data-legend]').text.includes('to go'));
 const click=action=>{const target=root.querySelectorAll('[data-action]').find(b=>b.dataset.action===action&&!b.disabled);assert(target,'Action '+action+' exists');root.handlers.click({target});};
 const primaryAnswer=stage.querySelectorAll('[data-action]').find(n=>n.dataset.action==='answer');
 assert.equal(primaryAnswer.className,'primary bw-primary');
 assert.equal(identity().children.find(n=>n.className==='check-quantity mono').textContent,'4×');
 assert(!stage.text.includes('4 required'));
 const missingButton=stage.querySelectorAll('[data-action]').find(n=>n.dataset.action==='missing');
 assert.equal(missingButton.className,'check-missing');
 const nav=identity().children.find(n=>n.className==='check-answer-nav');
 assert.deepEqual(nav.children.map(n=>n.textContent),['Back','Skip for later','Undo']);
 const history=root.querySelector('[data-history]');
 assert(history.text.includes('Missing so far · 0 entries · 0 missing'));
 assert.equal(history.querySelectorAll('SELECT').length,0);
 assert.equal(history.querySelectorAll('INPUT').length,0);
 assert(!history.text.includes('results'));
 assert(!/[−–-]\d/.test(stage.text+' '+root.querySelector('[data-history]').text));
 click('decrease');assert(stage.text.includes('Found 3'));click('answer');
 await new Promise(resolve=>setImmediate(resolve));assert.equal(server.rows[0].missing,1);assert.equal(server.rows[0].checked,1);assert(history.text.includes('Missing so far · 1 entry · 1 missing'));assert(history.text.includes('Found 1'));assert.equal(strip.children[0],originalSegment);assert(stage.text.includes('Found 2'));
 assert.equal(undoButton.hidden,false);assert(root.querySelector('[data-save-status]').text.includes('Saved'));
 assert.equal(feedback.querySelector('[data-action]'),undoButton);
 assert.deepEqual(identity().children.slice(0,2).map(n=>n.textContent),['Pearl Dark Gray','98313']);
 assert.equal(identity().children.filter(n=>n.textContent==='98313').length,1);
 const expiry=[...timers.values()].find(t=>t.ms===5000);assert(expiry);expiry.fn();
 assert.equal(undoButton.hidden,true);assert.equal(root.querySelector('[data-save-status]').textContent,'');
 const key=k=>handlers.keydown({key:k,target:new Element(),preventDefault(){}});
 key('m');await new Promise(resolve=>setImmediate(resolve));assert.equal(server.rows[1].missing,2);
 assert.equal(identity().children[0].textContent,'figure-1');assert.equal(identity().children[0].tagName,'H2');
 assert.equal(identity().children.filter(n=>n.textContent==='figure-1').length,1);
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
 for(const key of ['copyStatus','checkBody','stage','history','progress','legend']){const n=new Element();n.dataset[key]='';root.append(n);}
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
 assert(screen.stage.text.includes('Part 1 of 2'));
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
 assert(screen.stage.text.includes('Part 2 of 3'));
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
 initial.session.misses=['p:1','p:2','m:1'];
 initial.rows.filter(r=>initial.session.misses.includes(r.token)).forEach(r=>r.missing=1);
 const screen=boot(initial,{endpoint:'/check/copy',imageUrl:'/images/0'});
 assert(screen.root.querySelector('[data-history]').text.includes('3 entries · 3 missing'));
 assert(!/[−–-]\d/.test(screen.root.querySelector('[data-history]').text));
}
