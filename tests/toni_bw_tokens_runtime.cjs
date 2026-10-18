const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const source=fs.readFileSync(path.join(__dirname,'../static/web/toni/bw-tokens.js'),'utf8');
const load=(extra={})=>{const ctx={window:{listeners:{},addEventListener(e,fn){this.listeners[e]=fn;},location:{replaced:null,replace(u){this.replaced=u;},assign(u){this.assigned=u;}}},document:{addEventListener(event,fn){ctx.ready=fn;}},navigator:{},...extra};vm.runInNewContext(source,ctx);return ctx;};
(async()=>{
 const plain=load();
 assert.equal(plain.window.BrickTokenRevokeTitle('Spreadsheet export'),'Revoke Spreadsheet export?');
 // Copy uses the clipboard first, then the selection fallback, and reports failure.
 const written=[];
 assert.equal(await plain.window.BrickTokenCopy('secret',{writeText:async t=>{written.push(t);}},()=>false),true);
 assert.deepEqual(written,['secret']);
 assert.equal(await plain.window.BrickTokenCopy('secret',{writeText:async()=>{throw new Error('denied');}},()=>true),true);
 assert.equal(await plain.window.BrickTokenCopy('secret',undefined,()=>false),false);
 assert.equal(await plain.window.BrickTokenCopy('secret',undefined,undefined),false);
 // Page wiring: links open the dialogs, Done and Close never open a second one, server-opened dialogs become modal.
 const listeners=[];const el=(props={})=>({dataset:{},attrs:{},listeners:{},hasAttribute(n){return n in this.attrs;},removeAttribute(n){delete this.attrs[n];},
  addEventListener(e,fn){this.listeners[e]=fn;},querySelectorAll(){return [];},querySelector(){return null;},...props});
 const input=el({value:''});const title=el({textContent:''});
 const create=el({attrs:{},open:false,showModal(){this.open=true;this.modal=true;},close(){this.open=false;},matches(){return this.modal===true;},querySelector(s){return s==='input[name=name]'?{focus(){create.focused=true;}}:null;}});
 const confirm=el({open:false,showModal(){this.open=true;this.modal=true;},close(){this.open=false;},matches(){return this.modal===true;},querySelector(s){return s==='[data-token-confirm-title]'?title:s==='input[name=id]'?input:null;}});
 const done=el({tagName:'BUTTON'});const secret=el({textContent:'bw_secret_value'});
 const shown=el({attrs:{open:''},open:true,showModal(){this.modal=true;},close(){this.open=false;},matches(){return this.modal===true;},querySelectorAll(s){return s==='[data-token-close]'?[done]:[];}});
 const createLink=el();const revokeLink=el({dataset:{tokenRevoke:'abc',name:'Spreadsheet export'}});
 const root=el({dataset:{base:'/manage/tokens'},querySelector(s){return {'[data-token-create]':create,'[data-token-confirm]':confirm,'[data-token-shown]':shown,'[data-token-copy]':null}[s]||null;},
  querySelectorAll(s){return s==='[data-token-create-open]'?[createLink]:s==='[data-token-revoke]'?[revokeLink]:s==='[data-token-value]'?[secret]:[];}});
 const ctx=load({});ctx.document.querySelector=()=>root;ctx.ready();
 assert.equal(shown.modal,true,'server-rendered shown-once dialog becomes modal');
 let prevented=false;createLink.listeners.click({preventDefault(){prevented=true;}});
 assert(prevented&&create.open&&create.focused);
 prevented=false;revokeLink.listeners.click({preventDefault(){prevented=true;}});
 assert(prevented&&confirm.open);assert.equal(title.textContent,'Revoke Spreadsheet export?');assert.equal(input.value,'abc');
 // Done on the shown-once dialog clears the secret and replaces the history entry (Back cannot bring it back).
 done.listeners.click({preventDefault(){}});
 assert.equal(secret.textContent,'');assert.equal(ctx.window.location.replaced,'/manage/tokens');assert.equal(ctx.window.location.assigned,undefined);
 // A page restored from the back/forward cache with the secret dialog leaves it the same way.
 ctx.window.location.replaced=null;secret.textContent='bw_secret_value';
 ctx.window.listeners.pageshow({persisted:true});
 assert.equal(secret.textContent,'');assert.equal(ctx.window.location.replaced,'/manage/tokens');
 console.log('Brick Work tokens runtime passed');
})().catch(e=>{console.error(e);process.exitCode=1;});
