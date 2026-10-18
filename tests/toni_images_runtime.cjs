const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
class Element {
 constructor(tag='div'){this.tagName=tag.toUpperCase();this.children=[];this.attrs={};this.listeners={};this.hidden=false;this.text='';this.dataset={};}
 get textContent(){return this.text;}
 set textContent(value){this.text=String(value);this.children=[];}
 setAttribute(k,v){this.attrs[k]=String(v);}
 hasAttribute(k){return k in this.attrs;}
 append(...elements){this.children.push(...elements);}
 appendChild(el){this.children.push(el);}
 replaceChildren(...elements){this.text='';this.children=[...elements];}
 addEventListener(type,fn){(this.listeners[type]??=[]).push(fn);}
 dispatch(type,event={}){for(const fn of this.listeners[type]??[])fn(event);}
 click(){if(!this.disabled)this.onclick?.();}
 focus(){this.focused=true;}
 showModal(){this.open=true;}
 close(){this.open=false;this.dispatch('close');}
 closest(){return null;}
}
const listeners={},body=new Element(),created=[];
function link(caption){const a=new Element('a');a.href='/image/'+caption;a.dataset.caption=caption;a.setAttribute('data-lightbox','');a.querySelector=()=>({alt:caption});a.closest=selector=>selector==='a[data-lightbox]'?a:selector==='[hidden]' && a.parentHidden?a:null;return a;}
const first=link('Castle'),second=link('Boat'),links=[first,second];
const document={body,addEventListener:(type,fn)=>{(listeners[type]??=[]).push(fn);},createElement:tag=>{const el=new Element(tag);created.push(el);return el;},querySelectorAll:selector=>selector==='a[data-lightbox]'?links:[]};
vm.runInNewContext(fs.readFileSync((process.argv[2] || require('node:path').resolve(__dirname, '../static/web/toni/images.js')),'utf8'),{document});
listeners.DOMContentLoaded[0]();
const dialog=body.children[0],stack=dialog.children[0];
const [title,close,stage,caption,actions]=stack.children,[prev,next,retry]=actions.children;
let prevented=false;
listeners.click[0]({target:first,preventDefault(){prevented=true;}});
assert.equal(prevented,true);assert.equal(dialog.open,true);assert.equal(close.focused,true);assert.equal(caption.textContent,'Castle');
assert.equal(prev.disabled,true);assert.equal(next.disabled,false);
dialog.dispatch('keydown',{key:'ArrowRight',preventDefault(){}});assert.equal(caption.textContent,'Boat');assert.equal(next.disabled,true);
stage.children[0].onerror();assert.equal(stage.textContent,'Image unavailable');assert.equal(caption.textContent,'Boat');assert.equal(retry.hidden,false);
retry.click();assert.equal(stage.children[0].src,second.href);assert.equal(retry.hidden,true);
close.click();assert.equal(dialog.open,false);assert.equal(first.focused,true);
second.parentHidden=true;listeners.click[0]({target:first,preventDefault(){}});assert.equal(next.disabled,true);
close.click();prevented=false;listeners.click[0]({target:first,ctrlKey:true,preventDefault(){prevented=true;}});assert.equal(prevented,false);assert.equal(dialog.open,false);
// Failed non-solo thumbnails preserve their detail link and reveal its fallback.
const thumb=new Element('img'),region=new Element(),detail=new Element('a'),placeholder=new Element();placeholder.hidden=true;
region.querySelector=()=>placeholder;thumb.closest=selector=>selector==='.collection-image'?region:selector==='a'?detail:null;
listeners.error[0]({target:thumb});assert.equal(thumb.hidden,true);assert.equal(detail.hidden,false);assert.equal(placeholder.hidden,false);assert.equal(detail.children[0],placeholder);
console.log('Delegated lightbox, filtered gallery, captions, retry, close/focus and missing image passed');
// Standalone and dynamically inserted pictures also enlarge; picture click closes.
const dynamic=new Element('img');dynamic.src='/images/bl/P/11/3004.png';dynamic.alt='Black brick';dynamic.matches=selector=>selector.startsWith('#content img');dynamic.closest=selector=>selector==='img'?dynamic:null;
const originalQuery=document.querySelectorAll;document.querySelectorAll=selector=>selector.startsWith('#content img')?[dynamic]:originalQuery(selector);
let stopped=false;listeners.click[0]({target:dynamic,preventDefault(){},stopPropagation(){stopped=true;}});
assert.equal(dialog.open,true);assert.equal(stage.children[0].src,dynamic.src);assert.equal(caption.textContent,'Black brick');assert.equal(stopped,true);
stage.children[0].onclick();assert.equal(dialog.open,false);assert.equal(dynamic.focused,true);
console.log('Dynamic standalone image enlargement and click-on-picture closing passed');

// A click on the picture tile itself must work, including overlays/padding.
const tile=new Element('span');tile.querySelector=()=>dynamic;tile.closest=selector=>selector==='[data-inventory-image],.image-stage,.collection-image'?tile:null;
listeners.click[0]({target:tile,preventDefault(){},stopPropagation(){}});
assert.equal(dialog.open,true);assert.equal(stage.children[0].src,dynamic.src);
stage.children[0].onclick();assert.equal(dialog.open,false);
console.log('Picture-tile hit area also opens the viewer');

// Shared shell fallback covers server rows and rows inserted later in all three screens.
for(const screen of ['Collection','Workbench','Planning']) {
 const tile=new Element(),img=new Element('img'),original=new Element('a');
 tile.dataset.itemNo='3022';tile.append(original);original.append(img);
 img.attrs.src='/manage/images/404';img.getAttribute=k=>img.attrs[k];
 img.removeAttribute=k=>delete img.attrs[k];
 img.closest=selector=>selector==='.bc-picture,.bw-picture'?tile:null;
 listeners.error[0]({target:img});
 assert.equal(tile.children[0].textContent,'3022',screen);
 assert.equal(tile.children[1].textContent,'No image',screen);
 assert.ok(!tile.children.includes(original),screen);
 tile.children[2].dispatch('click');assert.equal(tile.children[0],original,screen);
 assert.equal(img.attrs.src,'/manage/images/404',screen);
}
console.log('Collection, Workbench and Planning share missing-picture tiles and retry');
