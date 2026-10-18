/* Shared group sheets, immutable page selection and native dialog lifecycle. */
const assert = require('node:assert/strict'), fs=require('node:fs'), vm=require('node:vm');
const pendingCloses=[];
class Element {
 constructor(dataset={}){this.dataset=dataset;this.attrs={};this.listeners={};this.open=false;this.hidden=false;this.buttons=[];this.opens=0;}
 addEventListener(type,fn){(this.listeners[type] ||= []).push(fn);}
 dispatchEvent(event){event.target ||= this;(this.listeners[event.type]||[]).forEach(fn=>fn(event));}
 click(extra={}){const event={type:'click',detail:1,preventDefault(){this.prevented=true;},...extra};this.dispatchEvent(event);return event;}
 getAttribute(name){return this.attrs[name];}setAttribute(name,value){this.attrs[name]=value;}
 show(){this.showModal();}
 showModal(){assert(!this.open);this.open=true;this.opens++;this.buttons[0]?.focus();}close(){this.open=false;const dispatch=()=>this.dispatchEvent({type:'close'});if(this.deferClose)pendingCloses.push(dispatch);else dispatch();}focus(){document.activeElement=this;}
 // The browser supplies Escape's default cancel/close behavior for native dialogs.
 escape(){const event={type:'cancel',preventDefault(){this.prevented=true;}};this.dispatchEvent(event);if(!event.prevented)this.close();}
 getBoundingClientRect(){return {left:0,right:390,top:200,bottom:844};}
 closest(){return this.parentSheet || null;}
 querySelectorAll(){return this.buttons;}
}
const groups=['Collection','Workbench','Planning','Manage'];
const tabs=groups.map(navGroup=>new Element({navGroup})),panels=groups.map(groupPanel=>new Element({groupPanel}));
const sheets=groups.map(navSheet=>new Element({navSheet}));
sheets.forEach((sheet,i)=>{sheet.id=i===1?'navbarSupportedContent':`navigation-${groups[i].toLowerCase()}`;sheet.buttons=[new Element()];tabs[i].attrs['aria-controls']=sheet.id;});
const segments=['system','light','dark'].map(themeMode=>new Element({themeMode}));
const mark=new Element({light:'mark.svg',dark:'mark-dark.svg'}),jump=new Element();jump.id='global-jump';jump.buttons=[new Element()];
const appearance=new Element();appearance.id='appearance';appearance.buttons=[new Element()];
const appearanceTile=new Element({open:'appearance'});appearanceTile.parentSheet=sheets[3];
const rails=groups.map(()=>new Element()),main=new Element();
const check=new Element({open:'global-jump',jumpCheck:'true'});
const document=new Element();document.getElementById=id=>[...sheets,jump,appearance].find(el=>el.id===id);
document.querySelectorAll=selector=>{
 const rail=selector.match(/^\.rail nav \[data-rail-group="([^"]+)"\] a$/);
 if(rail)return rails[groups.indexOf(rail[1])] ? [rails[groups.indexOf(rail[1])]] : [];
 return ({main:[main],'[data-theme-mode]':segments,'[data-nav-group]':tabs,'[data-group-panel]':panels,'[data-nav-sheet]':sheets,'.brand-mark':[mark],dialog:[...sheets,jump,appearance],'[data-open]':[check,appearanceTile]}[selector]||[]);};
const saved=[];const window={adminTheme:{mode:'system',apply(mode,persist){this.mode=mode;if(persist)saved.push(mode);document.dispatchEvent({type:'admin-theme'});}}};
let resize;
const desktop={matches:false,addEventListener(type,fn){resize=event=>{this.matches=event.matches;fn(event);};}};
vm.runInNewContext(fs.readFileSync('static/web/toni/shell.js','utf8'),{document,window,matchMedia:query=>query==='(min-width: 1024px)'?desktop:{matches:false,addEventListener(){}},Event:class{constructor(type){this.type=type;}},WeakMap,setTimeout,clearTimeout});
assert.equal(segments[0].attrs['aria-pressed'],'true');
segments[2].click();assert.equal(mark.src,'mark-dark.svg');assert.deepEqual(saved,['dark']);
// Every group from every server-selected group, including repeated open/close.
for(let active=0;active<groups.length;active++){
 tabs.forEach((tab,i)=>tab.attrs['aria-current']=String(i===active));
 panels.forEach((panel,i)=>panel.hidden=i!==active);
 for(let i=0;i<groups.length;i++){
  const tab=tabs[i],sheet=sheets[i],before=sheet.opens;
  for(const close of ['escape','backdrop','resize']){
   resize({matches:false});
   assert(tab.click().prevented);
   assert.equal(document.activeElement,sheet);
   assert.equal(sheet.opens, before+['escape','backdrop','resize'].indexOf(close)+1);
   assert.deepEqual(sheets.map(s=>s.open),groups.map((_,n)=>n===i));
   assert.equal(tab.attrs['aria-expanded'],'true');
   sheet.click({clientX:10,clientY:210});assert(sheet.open); // Dialog padding is inside.
   sheet.click({target:sheet.buttons[0],clientX:10,clientY:100});assert(sheet.open);
   if(close==='button')sheet.buttons[0].click();
   if(close==='escape')document.dispatchEvent({type:'keydown',key:'Escape',preventDefault(){}});
   if(close==='backdrop')sheet.click({clientX:10,clientY:100});
   if(close==='resize'){resize({matches:false});assert(sheet.open);resize({matches:true});}
   assert(!sheet.open);assert.equal(document.activeElement,close==='resize'?rails[i]:tab);assert.equal(tab.attrs['aria-expanded'],'false');
   assert.deepEqual(tabs.map(t=>t.attrs['aria-current']),groups.map((_,n)=>String(n===active)));
   assert.deepEqual(panels.map(p=>p.hidden),groups.map((_,n)=>n!==active));
  }
 }
}
resize({matches:false});
// Enter and Space open every group on its first tile; pointer opens focus the sheet.
for (const [i,tab] of tabs.entries()) {
 for (const key of ['Enter',' ']) {
  const event={type:'keydown',key,preventDefault(){this.prevented=true;}};
  tab.dispatchEvent(event);assert(event.prevented);
  assert.equal(document.activeElement,sheets[i].buttons[0]);
  document.dispatchEvent({type:'keydown',key:'Escape',preventDefault(){}});
  assert.equal(document.activeElement,tab);
 }
 tab.click({detail:0});assert.equal(document.activeElement,sheets[i].buttons[0]);
 sheets[i].close();assert.equal(document.activeElement,tab);
}
// Switching groups while open leaves one sheet; repeated active taps keep it open.
tabs[0].click();sheets[0].deferClose=true;
tabs[1].click();assert(!sheets[0].open);assert(sheets[1].open);
pendingCloses.splice(0).forEach(dispatch=>dispatch());
assert.equal(document.activeElement,sheets[1]);
assert.equal(tabs[0].attrs['aria-expanded'],'false');
sheets[0].deferClose=false;
const opens=sheets[1].opens;tabs[1].click();assert.equal(sheets[1].opens,opens);
sheets[1].close();
sheets[3].deferClose=true;
tabs[3].click();appearanceTile.click();
assert.equal(document.activeElement,appearance.buttons[0]);
pendingCloses.splice(0).forEach(dispatch=>dispatch());
assert.equal(document.activeElement,appearance.buttons[0]);
sheets[3].deferClose=false;
assert(!sheets[3].open);assert(appearance.open);
assert.equal(tabs[3].attrs['aria-expanded'],'false');
assert.equal(appearanceTile.attrs['aria-expanded'],'true');
appearance.buttons[0].click();assert.equal(document.activeElement,tabs[3]);
assert.equal(appearanceTile.attrs['aria-expanded'],'false');
// If the group's rail destination is absent, restore to the main landmark.
const manageRail=rails[3];rails[3]=null;
tabs[3].click();resize({matches:true});assert.equal(document.activeElement,main);
rails[3]=manageRail;resize({matches:false});
const destination=tabs[0].attrs['aria-controls'];tabs[0].attrs['aria-controls']='absent';
assert(!tabs[0].click().prevented);assert(sheets.every(s=>!s.open));tabs[0].attrs['aria-controls']=destination;
// Jump keeps focus after the navigation sheet's deferred close event.
tabs[0].click();sheets[0].deferClose=true;
check.click();assert(jump.open);assert.equal(jump.dataset.check,'true');
pendingCloses.splice(0).forEach(dispatch=>dispatch());
assert.equal(document.activeElement,jump.buttons[0]);
assert.equal(tabs[0].attrs['aria-expanded'],'false');
sheets[0].deferClose=false;
jump.close();assert.equal(document.activeElement,check);
console.log('All four group sheets on every tap, native Escape, backdrop, resize, focus and immutable selection passed');
