/* #153 Q5: at 390 px the phone top strip scrolls the active entry (Catalogs) into view on load, instant, page not scrolled. */
const fs=require('node:fs'),path=require('node:path'),{spawn}=require('node:child_process'),assert=require('node:assert/strict');
const [chrome,dir]=process.argv.slice(2);
const profile=path.join(dir,'profile');
const child=spawn(chrome,[...(process.env.BW_CHROME_NO_SANDBOX?['--no-sandbox']:[]),'--headless','--disable-background-networking','--hide-scrollbars','--remote-debugging-port=0','--user-data-dir='+profile,'about:blank'],{stdio:['ignore','ignore','pipe']});
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
 const settled=async expression=>{for(let i=0;i<40;i++){if(await evaluate(expression)===true)return true;await delay(50);}return evaluate(expression);};   // focus moves after the event is handled: wait up to 2 s, never longer
 await call('Emulation.setDeviceMetricsOverride',{width:390,height:844,deviceScaleFactor:1,mobile:false});
 const probe=`(()=>{
  const strip=[...document.querySelectorAll('.group-items > div')].find(d=>!d.hidden),link=strip.querySelector('a[aria-current=page]');
  const box=strip.getBoundingClientRect(),at=link.getBoundingClientRect();
  return {title:link.title,overflow:strip.scrollWidth>strip.clientWidth,left:strip.scrollLeft,inside:at.left>=box.left-.5&&at.right<=box.right+.5,pageY:scrollY,pageX:scrollX};
 })()`;
 for (const reduced of [false,true]) {
  await call('Emulation.setEmulatedMedia',{features:[{name:'prefers-reduced-motion',value:reduced?'reduce':'no-preference'}]});
  await call('Emulation.setDeviceMetricsOverride',{width:390,height:844,deviceScaleFactor:1,mobile:false});
  await call('Page.navigate',{url:'file://'+path.join(dir,'shell.html')});
  for(let i=0;i<100;i++){if(await evaluate("document.readyState==='complete' && !!document.querySelector('.group-items')"))break;await delay(20);}
  await delay(100);
  const m=await evaluate(probe);
  assert.equal(m.title,'Catalogs');
  assert.ok(m.overflow,'the strip overflows at 390 px, so the test means something');
  assert.ok(m.left>0,'strip scrolled, reduced='+reduced);
  assert.ok(m.inside,'Catalogs fully inside the strip, reduced='+reduced+' '+JSON.stringify(m));
  assert.equal(m.pageY,0);assert.equal(m.pageX,0);
 }
 // Opened wide, then narrowed into the phone layout: the reveal runs again on resize (Codex review).
 await call('Emulation.setDeviceMetricsOverride',{width:1440,height:900,deviceScaleFactor:1,mobile:false});
 await call('Page.navigate',{url:'file://'+path.join(dir,'shell.html')});
 for(let i=0;i<100;i++){if(await evaluate("document.readyState==='complete' && !!document.querySelector('.group-items')"))break;await delay(20);}
 await delay(100);
 await call('Emulation.setDeviceMetricsOverride',{width:390,height:844,deviceScaleFactor:1,mobile:false});
 assert.ok(await settled(`(()=>{const m=${probe};return m.left>0&&m.inside;})()`),'Catalogs revealed after narrowing to 390 px: '+JSON.stringify(await evaluate(probe)));
 console.log('strip ok');
 socket.close();child.kill();process.exit(0);
})().catch(error=>{console.error(error);child.kill();process.exit(1);});
