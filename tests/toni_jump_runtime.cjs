/* Execute shipped shell + jump with a minimal DOM and controllable I/O. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
class Element {
 constructor(tag) { this.tag = tag; this.children = []; this.listeners = {}; this.dataset = {}; this.attrs = {}; this.value = ''; this.open = false; this.textContent = ''; this.classList = {toggle: (name, on) => {this[name] = on;}}; }
 addEventListener(name, fn) { (this.listeners[name] ||= []).push(fn); }
 dispatchEvent(event) { event.target = this; (this.listeners[event.type] || []).forEach(fn => fn(event)); }
 append(...nodes) { this.children.push(...nodes); }
 replaceChildren(...nodes) { this.children = nodes; }
 querySelectorAll(selector) { return selector === '[data-close]' ? [this.closeButton ||= new Element('button')] : []; }
 setAttribute(name, value) {this.attrs[name] = value;}
 focus() {document.activeElement = this; this.dispatchEvent({type:'focus'});}
 scrollIntoView() {}
 click() {this.dispatchEvent({type:'click', preventDefault(){}}); clicked = this.href;}
 showModal() {this.open = true;}
 close() {this.open = false; this.dispatchEvent({type:'close'});}
}
const ids = Object.fromEntries(['theme','theme-mobile','global-jump','navbarSupportedContent','jump-query','jump-results','jump-message'].map(id => [id, new Element('div')]));
ids['global-jump'].dataset = {url:'/jump'};
const triggers = ['global-jump','navbarSupportedContent'].map(id => {const b = new Element('button'); b.dataset.open = id;return b;});
const document = new Element('document');
document.activeElement = new Element('a');
document.getElementById = id => ids[id];
document.createElement = tag => new Element(tag);
document.querySelectorAll = selector => selector === '[data-theme-selector]' ? [ids.theme,ids['theme-mobile']] : selector === '[data-open]' ? triggers : selector === 'dialog' ? [ids['global-jump'],ids.navbarSupportedContent] : [];
let timers = [], requests = [], clicked;
const context = {document, window:{adminTheme:{mode:'system',apply(){}}}, location:{origin:'http://local'}, URL, AbortController, Event:class{constructor(type){this.type=type;}}, matchMedia:()=>({addEventListener(){}}), setTimeout(fn){timers.push(fn); return fn;}, clearTimeout(fn){timers = timers.filter(t => t !== fn);}, fetch(url, options){return new Promise(resolve => requests.push({url, options, resolve}));}};
vm.createContext(context);
for (const name of ['shell','jump']) vm.runInContext(fs.readFileSync(`static/web/toni/${name}.js`, 'utf8'), context);
const tick = () => new Promise(resolve => setImmediate(resolve));
const input = ids['jump-query'];
function type(value) {input.value = value;input.dispatchEvent({type:'input'});}
function key(target, name, extra={}) {const e={type:'keydown',key:name,preventDefault(){this.prevented=true;},...extra};target.dispatchEvent(e);return e;}
function flush() {const pending = timers;timers=[];pending.forEach(fn=>fn());}
function anchors(node) {return [...(node.tag==='a'?[node]:[]),...node.children.flatMap(anchors)];}
const copy = (id, completeness) => ({id,condition:'U',completeness,missing_parts:0,missing_minifigs:0,missing_label:'',url:`/sets/${id}/details`});
const result = copies => ({kind:'set',number:'6081-1',name:'<img onerror=alert(1)>',image:'/static/image.jpg',copies});
(async () => {
 assert.equal(ids.theme.value,'system');assert.equal(ids['theme-mobile'].value,'system');
 ids['theme-mobile'].value='dark';ids['theme-mobile'].dispatchEvent({type:'change'});assert.equal(ids.theme.value,'dark');
 ids.theme.value='light';ids.theme.dispatchEvent({type:'change'});assert.equal(ids['theme-mobile'].value,'light');
 const previous = document.activeElement;
 assert(key(document, 'k', {ctrlKey:true}).prevented);
 assert(ids['global-jump'].open); assert.equal(document.activeElement, input);
 type('608'); type('6081'); assert.equal(timers.length, 1); flush();
 assert.equal(requests.length, 1); assert.equal(requests[0].url.searchParams.get('q'), '6081');
 requests[0].resolve({ok:true,json:async()=>({results:[result([{...copy('a','I'),missing_parts:1,missing_minifigs:1,missing_label:'1 part missing / 1 figure missing'},copy('b',null)])]})});await tick();
 const links = anchors(ids['jump-results']); assert.equal(links.length, 2);
 assert.equal(links[0].children[0].children[0].textContent, 'Set 1 · Used · Incomplete');
 assert.equal(links[1].children[0].children[0].textContent, 'Set 2 · Used · Not checked');
 assert.equal(links[0].children[0].children[1].textContent, '1 part missing / 1 figure missing');
 assert.equal(links[1].children[0].children[1].textContent, '');
 assert.equal(ids['jump-results'].children[0].children[0].children[1].children[1].textContent,'<img onerror=alert(1)>');
 key(ids['global-jump'], 'ArrowDown'); key(ids['global-jump'], 'Enter'); assert.equal(clicked, '/sets/b/details');
 key(ids['global-jump'], 'ArrowUp'); key(ids['global-jump'], 'Enter'); assert.equal(clicked, '/sets/a/details');
 type('single'); flush(); requests.at(-1).resolve({ok:true,json:async()=>({results:[result([copy('one','S')])]})});await tick();
 key(ids['global-jump'],'Enter');assert.equal(clicked,'/sets/one/details');
 type('old'); flush();const old=requests.at(-1);type('new');flush();const latest=requests.at(-1);
 assert(old.options.signal.aborted);
 latest.resolve({ok:true,json:async()=>({results:[]})}); await tick();
 old.resolve({ok:true,json:async()=>({results:[result([copy('old','I')])]})});await tick();
 assert.equal(anchors(ids['jump-results']).length,0);
 assert.equal(ids['jump-message'].textContent,'No matches.');
 type('');assert.equal(ids['jump-message'].textContent,'');
 ids['global-jump'].close(); assert.equal(document.activeElement,previous);
 triggers[0].click();assert(ids['global-jump'].open);assert.equal(triggers[0].attrs['aria-expanded'],'true');
 ids['global-jump'].closeButton.click();assert(!ids['global-jump'].open);assert.equal(triggers[0].attrs['aria-expanded'],'false');
 triggers[1].click();assert(ids.navbarSupportedContent.open);ids.navbarSupportedContent.close();assert.equal(document.activeElement,triggers[1]);
})().catch(error => {console.error(error);process.exitCode=1;});
