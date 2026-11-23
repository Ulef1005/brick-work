/* The shell script since #492: theme segments and the native dialog lifecycle (open, close, focus back to the opener, one stale close ignored).
   The navigation is plain links, so there is no group sheet, tab handler or resize behaviour left to drive. */
const assert = require('node:assert/strict'), fs=require('node:fs'), vm=require('node:vm');
const pendingCloses=[];
class Element {
 constructor(dataset={}){this.dataset=dataset;this.attrs={};this.listeners={};this.open=false;this.buttons=[];this.opens=0;}
 addEventListener(type,fn){(this.listeners[type] ||= []).push(fn);}
 dispatchEvent(event){event.target ||= this;(this.listeners[event.type]||[]).forEach(fn=>fn(event));}
 click(){const event={type:'click',detail:1,preventDefault(){this.prevented=true;}};this.dispatchEvent(event);return event;}
 getAttribute(name){return this.attrs[name];}setAttribute(name,value){this.attrs[name]=value;}
 showModal(){assert(!this.open);this.open=true;this.opens++;this.buttons[0]?.focus();}
 close(){this.open=false;const dispatch=()=>this.dispatchEvent({type:'close'});if(this.deferClose)pendingCloses.push(dispatch);else dispatch();}
 focus(){document.activeElement=this;}
 querySelectorAll(){return this.buttons;}
}
const segments=['system','light','dark'].map(themeMode=>new Element({themeMode}));
const jump=new Element();jump.id='global-jump';jump.buttons=[new Element()];
const other=new Element();other.id='other';other.buttons=[new Element()];
const search=new Element({open:'global-jump',jumpCheck:'true'}),second=new Element({open:'other'});
const document=new Element();document.getElementById=id=>[jump,other].find(el=>el.id===id);
document.querySelectorAll=selector=>({'[data-theme-mode]':segments,dialog:[jump,other],'[data-open]':[search,second]}[selector]||[]);
const saved=[];const window={adminTheme:{mode:'system',apply(mode,persist){this.mode=mode;if(persist)saved.push(mode);document.dispatchEvent({type:'admin-theme'});}}};
vm.runInNewContext(fs.readFileSync('static/web/toni/shell.js','utf8'),{document,window,Event:class{constructor(type){this.type=type;}},WeakMap,setTimeout,clearTimeout});
assert.equal(segments[0].attrs['aria-pressed'],'true');
segments[2].click();assert.deepEqual(saved,['dark']);
assert.deepEqual(segments.map(s=>s.attrs['aria-pressed']),['false','false','true']);
// Jump opens from its trigger, marks it expanded, carries the check flag and gives focus back on close.
assert(search.click().prevented);assert(jump.open);assert.equal(jump.dataset.check,'true');assert.equal(search.attrs['aria-expanded'],'true');
assert.equal(document.activeElement,jump.buttons[0]);
jump.close();assert.equal(search.attrs['aria-expanded'],'false');assert.equal(document.activeElement,search);
// Opening an open dialog again does nothing.
search.click();const opens=jump.opens;search.click();assert.equal(jump.opens,opens);jump.close();
// A stale close event (another dialog is open again by then) must not pull focus back to the opener.
jump.deferClose=true;search.click();second.click();assert(other.open);
pendingCloses.splice(0).forEach(dispatch=>dispatch());jump.open=false;
assert.equal(document.activeElement,other.buttons[0]);
jump.deferClose=false;other.close();assert.equal(document.activeElement,second);
console.log('Theme segments and the dialog lifecycle passed');
