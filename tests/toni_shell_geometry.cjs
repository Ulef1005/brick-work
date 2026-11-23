/* Shell geometry (#492): the B′ bars at 390 and 1440, the Jump sheet and the fixed bars' clearance against an offline page; no screenshots. */
const fs=require('node:fs'),path=require('node:path'),{spawn}=require('node:child_process'),assert=require('node:assert/strict');
const [chrome,dir]=process.argv.slice(2);
const {launch}=require('../scripts/chrome_launch.cjs');   // starts Chrome and retries a failed start (#293)
let child=null;
const delay=ms=>new Promise(resolve=>setTimeout(resolve,ms));
(async()=>{
 let port;
 const browser=await launch(chrome);child=browser.child;port=browser.port;
 const targets=await (await fetch('http://127.0.0.1:'+port+'/json/list')).json();
 const socket=new WebSocket(targets.find(t=>t.type==='page').webSocketDebuggerUrl);
 await new Promise(resolve=>socket.addEventListener('open',resolve));
 let id=0;const pending=new Map();
 socket.addEventListener('message',event=>{const data=JSON.parse(event.data);if(pending.has(data.id)){const {resolve,reject}=pending.get(data.id);pending.delete(data.id);data.error?reject(data.error):resolve(data.result);}});
 const call=(method,params={})=>new Promise((resolve,reject)=>{const n=++id;pending.set(n,{resolve,reject});socket.send(JSON.stringify({id:n,method,params}));});
 const evaluate=async expression=>{const result=await call('Runtime.evaluate',{expression,returnByValue:true});assert.ok(!result.exceptionDetails,JSON.stringify(result.exceptionDetails));return result.result.value;};
 const settled=async expression=>{for(let i=0;i<40;i++){if(await evaluate(expression)===true)return true;await delay(50);}return evaluate(expression);};   // focus moves after the event is handled: wait up to 2 s, never longer
 await call('Emulation.setDeviceMetricsOverride',{width:390,height:844,deviceScaleFactor:1,mobile:false});
 await call('Page.navigate',{url:'file://'+path.join(dir,'shell.html')});
 for(let i=0;i<100;i++){if(await evaluate("document.readyState==='complete' && !!document.querySelector('.tabbar')"))break;await delay(20);}
 // Phone (390): lockup bar 56, sub row 40, tab bar 78 fixed to the bottom, no desktop bars, nothing scrolls the page sideways.
 const m=await evaluate(`(()=>{
  const h=s=>document.querySelector(s).getBoundingClientRect(),bar=document.querySelector('.tabbar'),a=bar.querySelector('a'),span=a.querySelector('span');
  const bs=document.body.appendChild(Object.assign(document.createElement('div'),{className:'savebar'})),ts=document.body.appendChild(Object.assign(document.createElement('div'),{className:'toast-live'}));
  const jump=document.getElementById('global-jump');jump.showModal();jump.getAnimations().forEach(x=>x.finish());const r=jump.getBoundingClientRect();
  const out={save:getComputedStyle(bs).bottom,toast:getComputedStyle(ts).bottom,bar:[h('.tabbar').height,h('.tabbar').bottom,innerHeight],link:a.getBoundingClientRect().height,
   ptop:h('.ptop').height,psub:h('.psub').height,top:getComputedStyle(document.querySelector('.top')).display,sub:getComputedStyle(document.querySelector('.sub')).display,
   pos:getComputedStyle(bar).position,jump:[r.left,r.top,r.width,r.height],message:getComputedStyle(document.getElementById('jump-message')).display,
   add:!!document.getElementById('jump-add'),text:jump.textContent,scrollX:document.documentElement.scrollWidth-innerWidth};
  jump.close();return out;
 })()`);
 assert.deepEqual(m.bar,[78,844,844]);assert.equal(m.pos,'fixed');assert.equal(m.save,'78px');assert.equal(m.toast,'94px');
 assert.ok(m.link>=44,'link '+m.link);
 assert.equal(m.ptop,56);assert.ok(m.psub>=37&&m.psub<=41,'psub '+m.psub);   // content height (padding, a 13 px label, a 3 px rule): 40 with the shipped fonts, 39 with this offline page's fallback font on a Mac, 38 with the Ubuntu runner's (the push run on main is the only CI run that has Chrome: a pull request sets BW_NO_CHROME)
 assert.equal(m.top,'none');assert.equal(m.sub,'none');assert.ok(m.scrollX<=0,'page scrolls sideways');
 assert.deepEqual(m.jump,[0,0,390,844]);
 assert.equal(m.message,'none');assert.equal(m.add,false);
 assert.ok(!/Enter opens copy|Search owned and wanted/.test(m.text));
 // The sub row strip scrolls inside itself, never the page.
 assert.equal(await evaluate("getComputedStyle(document.querySelector('.psub')).overflowX"),'auto');
 // #245: content clears the bar with no inset (browser toolbar) and with a 34px home-indicator inset (installed app).
 for(const [inset,bar] of [[0,78],[34,112]]){
  const c=await evaluate(`(()=>{document.documentElement.style.setProperty('--tw-safe-bottom','${inset}px');const b=document.querySelector('.tabbar');window.scrollTo(0,document.documentElement.scrollHeight);
   const f=document.querySelector('.footer'),last=[...f.children].pop().getBoundingClientRect();return {bar:b.getBoundingClientRect().height,top:b.getBoundingClientRect().top,end:last.bottom,inner:parseFloat(getComputedStyle(b).paddingBottom)};})()`);
  assert.equal(c.bar,bar,'bar at inset '+inset);assert.equal(c.inner,inset);assert.ok(c.end<=c.top+.5,'last row hidden at inset '+inset+': '+JSON.stringify(c));
 }
 await evaluate("document.documentElement.style.removeProperty('--tw-safe-bottom')");
 // Desktop (1440): top bar 60, sub row 44, no phone bars and no tab bar; the page does not scroll sideways.
 await call('Emulation.setDeviceMetricsOverride',{width:1440,height:900,deviceScaleFactor:1,mobile:false});
 const d=await evaluate(`(()=>{const h=s=>document.querySelector(s).getBoundingClientRect(),cs=s=>getComputedStyle(document.querySelector(s));
  return {top:h('.top').height,sub:h('.sub').height,ptop:cs('.ptop').display,psub:cs('.psub').display,tabbar:cs('.tabbar').display,scrollX:document.documentElement.scrollWidth-innerWidth,overflow:cs('.sub').overflowX};})()`);
 assert.equal(d.top,60);assert.equal(d.sub,44);assert.equal(d.ptop,'none');assert.equal(d.psub,'none');assert.equal(d.tabbar,'none');assert.ok(d.scrollX<=0);assert.equal(d.overflow,'auto');
 socket.close();child?.kill();process.exit(0);
})().catch(error=>{console.error(error);child?.kill();process.exit(1);});
