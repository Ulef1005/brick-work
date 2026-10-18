/* 4.9f shell geometry: phone bottom bar and Jump sheet against an offline page; no screenshots. */
const fs=require('node:fs'),path=require('node:path'),{spawn}=require('node:child_process'),assert=require('node:assert/strict');
const [chrome,dir]=process.argv.slice(2);
const profile=path.join(dir,'profile');
const child=spawn(chrome,['--headless','--disable-background-networking','--remote-debugging-port=0','--user-data-dir='+profile,'about:blank'],{stdio:['ignore','ignore','pipe']});
let launchErrors='';child.stderr.on('data',data=>launchErrors+=data.toString());
const delay=ms=>new Promise(resolve=>setTimeout(resolve,ms));
(async()=>{
 let port;
 for(let i=0;i<100;i++){try{port=fs.readFileSync(path.join(profile,'DevToolsActivePort'),'utf8').split('\n')[0];break;}catch{}await delay(50);}
 assert.ok(port,'Chromium did not start: '+launchErrors);
 const targets=await (await fetch('http://127.0.0.1:'+port+'/json/list')).json();
 const socket=new WebSocket(targets.find(t=>t.type==='page').webSocketDebuggerUrl);
 await new Promise(resolve=>socket.addEventListener('open',resolve));
 let id=0;const pending=new Map();
 socket.addEventListener('message',event=>{const data=JSON.parse(event.data);if(pending.has(data.id)){const {resolve,reject}=pending.get(data.id);pending.delete(data.id);data.error?reject(data.error):resolve(data.result);}});
 const call=(method,params={})=>new Promise((resolve,reject)=>{const n=++id;pending.set(n,{resolve,reject});socket.send(JSON.stringify({id:n,method,params}));});
 const evaluate=async expression=>{const result=await call('Runtime.evaluate',{expression,returnByValue:true});assert.ok(!result.exceptionDetails,JSON.stringify(result.exceptionDetails));return result.result.value;};
 await call('Emulation.setDeviceMetricsOverride',{width:390,height:844,deviceScaleFactor:1,mobile:false});
 await call('Page.navigate',{url:'file://'+path.join(dir,'shell.html')});
 for(let i=0;i<100;i++){if(await evaluate("document.readyState==='complete' && !!document.querySelector('.mobile-bottom')"))break;await delay(20);}
 const m=await evaluate(`(()=>{
  const bar=document.querySelector('.mobile-bottom'),a=bar.querySelector('a'),span=a.querySelector('span'),cs=getComputedStyle(span);
  const bs=document.body.appendChild(Object.assign(document.createElement('div'),{className:'savebar'})),ts=document.body.appendChild(Object.assign(document.createElement('div'),{className:'toast-live'}));const jump=document.getElementById('global-jump');jump.showModal();jump.getAnimations().forEach(a=>a.finish());const r=jump.getBoundingClientRect();
  return {save:bs&&getComputedStyle(bs).bottom,toast:ts&&getComputedStyle(ts).bottom,bar:bar.getBoundingClientRect().height,label:cs.lineHeight,size:cs.fontSize,link:a.getBoundingClientRect().height,
   jump:[r.left,r.top,r.width,r.height],message:getComputedStyle(document.getElementById('jump-message')).display,
   add:!!document.getElementById('jump-add'),text:jump.textContent};
 })()`);
 assert.equal(m.bar,83);assert.equal(m.save,'83px');assert.equal(m.toast,'99px');assert.equal(m.label,'12px');assert.equal(m.size,'11px');
 assert.ok(m.link>=48&&m.link<=49,'link '+m.link);
 assert.deepEqual(m.jump,[0,0,390,844]);
 assert.equal(m.message,'none');assert.equal(m.add,false);
 assert.ok(!/Enter opens copy|Search owned and wanted/.test(m.text));
 await evaluate("document.getElementById('global-jump').close()");
 // Real touch opens must focus the sheet; both keyboard activation keys focus a tile.
 await call('Emulation.setTouchEmulationEnabled',{enabled:true});
 for (const height of [844,480]) {
  await call('Emulation.setDeviceMetricsOverride',{width:390,height,deviceScaleFactor:1,mobile:true});
  for (let group=0;group<4;group++) {
   const point=await evaluate(`(()=>{const r=document.querySelectorAll('[data-nav-group]')[${group}].getBoundingClientRect();return {x:r.x+r.width/2,y:r.y+20};})()`);
   await call('Input.dispatchTouchEvent',{type:'touchStart',touchPoints:[point]});
   await call('Input.dispatchTouchEvent',{type:'touchEnd',touchPoints:[]});
   assert.equal(await evaluate(`document.activeElement===document.querySelectorAll('[data-nav-sheet]')[${group}]`),true);
   assert.equal(await evaluate("getComputedStyle(document.activeElement).outlineStyle"),'none');
   for (const key of ['Enter',' ']) {
    await call('Input.dispatchKeyEvent',{type:'keyDown',key:'Escape',code:'Escape'});
    await call('Input.dispatchKeyEvent',{type:'keyUp',key:'Escape',code:'Escape'});
    assert.equal(await evaluate(`document.activeElement===document.querySelectorAll('[data-nav-group]')[${group}]`),true);
    await call('Input.dispatchKeyEvent',{type:'keyDown',key,code:key===' '?'Space':'Enter'});
    await call('Input.dispatchKeyEvent',{type:'keyUp',key,code:key===' '?'Space':'Enter'});
    assert.equal(await evaluate(`document.activeElement===document.querySelectorAll('[data-nav-sheet]')[${group}].querySelector('.workbench-grid a, .workbench-grid button')`),true);
    const failures=await evaluate(`(()=>{
     const sheet=document.querySelectorAll('[data-nav-sheet]')[${group}];sheet.getAnimations().forEach(a=>a.finish());
     const grid=sheet.querySelector('.workbench-grid'),failures=[];
     for(const tile of grid.children){
      tile.focus();
      const r=tile.getBoundingClientRect(),s=getComputedStyle(tile),out=parseFloat(s.outlineWidth)+parseFloat(s.outlineOffset);
      if(!tile.matches(':focus-visible') || out<4)failures.push('missing keyboard ring');
      if(r.height<44 || r.width<44)failures.push('small target');
      for(let p=tile.parentElement;p;p=p.parentElement){
       const c=getComputedStyle(p),b=p.getBoundingClientRect();
       if(/auto|scroll|hidden|clip/.test(c.overflowX) && (r.left-out<b.left+p.clientLeft-.5 || r.right+out>b.left+p.clientLeft+p.clientWidth+.5))failures.push('horizontal clip: '+p.className);
       if(/auto|scroll|hidden|clip/.test(c.overflowY) && (r.top-out<b.top+p.clientTop-.5 || r.bottom+out>b.top+p.clientTop+p.clientHeight+.5))failures.push('vertical clip: '+p.className);
      }
     }
     return failures;
    })()`);
    assert.deepEqual(failures,[],`group ${group}, height ${height}, key ${key}`);
   }
   await evaluate(`document.querySelectorAll('[data-nav-sheet]')[${group}].close()`);
  }
 }
 socket.close();child.kill();process.exit(0);
})().catch(error=>{console.error(error);child.kill();process.exit(1);});
