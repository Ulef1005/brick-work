/* #258: the status pills a set card shows in real Chromium, from the Sets page the server rendered (records inline). Prints one JSON line:
   [{number, pills: [{text, state}]}] for every card on the page. */
const fs=require('node:fs'),path=require('node:path'),{spawn}=require('node:child_process'),{pathToFileURL}=require('node:url'),assert=require('node:assert/strict');
const [chrome,page]=process.argv.slice(2);
const profile=path.join(path.dirname(page),'profile');
const child=spawn(chrome,[...(process.env.BW_CHROME_NO_SANDBOX?['--no-sandbox']:[]),'--headless','--disable-background-networking','--hide-scrollbars','--remote-debugging-port=0','--user-data-dir='+profile,'about:blank'],{stdio:['ignore','ignore','pipe']});
let launchErrors='';child.stderr.on('data',data=>launchErrors+=data.toString());
let socket;
const delay=ms=>new Promise(resolve=>setTimeout(resolve,ms));
(async()=>{
 let port;
 for(let i=0;i<100;i++){try{port=fs.readFileSync(path.join(profile,'DevToolsActivePort'),'utf8').split('\n')[0];break;}catch{}await delay(50);}
 assert.ok(port,'Chromium did not start: '+launchErrors);
 // The page target can register after DevToolsActivePort is written: ask again until it is listed.
 let target;
 for(let i=0;i<100&&!target;i++){target=(await (await fetch('http://127.0.0.1:'+port+'/json/list')).json()).find(t=>t.type==='page');if(!target)await delay(50);}
 assert.ok(target,'no page target');
 socket=new WebSocket(target.webSocketDebuggerUrl);
 await new Promise(resolve=>socket.addEventListener('open',resolve));
 let id=0;const pending=new Map();
 socket.addEventListener('message',event=>{const data=JSON.parse(event.data);if(pending.has(data.id)){const {resolve,reject}=pending.get(data.id);pending.delete(data.id);data.error?reject(data.error):resolve(data.result);}});
 const call=(method,params={})=>new Promise((resolve,reject)=>{const n=++id;pending.set(n,{resolve,reject});socket.send(JSON.stringify({id:n,method,params}));});
 const evaluate=async expression=>{const result=await call('Runtime.evaluate',{expression,returnByValue:true});assert.ok(!result.exceptionDetails,JSON.stringify(result.exceptionDetails));return result.result.value;};
 await call('Emulation.setDeviceMetricsOverride',{width:1440,height:900,deviceScaleFactor:1,mobile:false});
 await call('Page.navigate',{url:pathToFileURL(page).href});
 let cards=[];
 for(let i=0;i<150;i++){
  // The navigation replaces the blank page's context; a poll that lands in between is retried.
  try{cards=await evaluate(`document.readyState==='complete'&&location.pathname.endsWith('/sets.html')?[...document.querySelectorAll('.bc-card-foot')].map(foot=>{const card=foot.parentElement;
   return {number:(card.querySelector('.bc-identity .mono')||{}).textContent||'',pills:[...foot.querySelectorAll('.bc-foot-pills .bc-status')].map(p=>({text:p.textContent,state:p.className.replace('bc-status','').trim()}))};}):[]`);}catch{cards=[];}
  if(cards.length)break;await delay(20);
 }
 process.stdout.write(JSON.stringify(cards)+'\n');
 socket.close();child.kill();process.exit(0);
})().catch(error=>{console.error(error);child.kill();process.exit(1);});
