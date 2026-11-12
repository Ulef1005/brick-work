/* Design audit captures: PNGs of app pages at the kit sizes, light and dark, for approval (design/screens/approval/README.md).

    node scripts/capture_screens.cjs CHROME JOBS.json

JOBS.json is {"headers": {...optional, e.g. Cookie}, "deterministic"?: true, "now"?: ISO time, "jobs": [{"url", "out", "width", "height"?, "theme": "light"|"dark",
"wait"?: CSS selector, "script"?: JS run before the capture (open a sheet, tick a box), "max"?: px, default 3000, "sheet_below"?: px}]}.
"deterministic" (the screenshot gate, scripts/screen_gate.py) starts every capture from an empty browser (no cache, no stored data, empty web storage), loads every declared font face, turns animations and transitions off, hides the caret, asks for reduced motion and, with "now",
fixes the page's clock (Date) at that instant. The theme is the system preference (the app's default mode). A page is captured whole with the viewport grown to its height (fixed
bars at its foot), clipped to its first `max` px; with a sheet open (`dialog[open]`) one viewport is captured, as the device shows it; so is a job below its `sheet_below` width. */
const fs=require('node:fs'),path=require('node:path'),{launch}=require('./chrome_launch.cjs');
const [chrome,jobsFile]=process.argv.slice(2);
if(!chrome||!jobsFile){console.error('usage: node scripts/capture_screens.cjs CHROME JOBS.json');process.exit(2);}
const {headers={},jobs,deterministic=false,now=null}=JSON.parse(fs.readFileSync(jobsFile,'utf8'));
const delay=ms=>new Promise(resolve=>setTimeout(resolve,ms));
let browser=null;
(async()=>{
 browser=await launch(chrome);   // starts Chrome, retries a failed start (scripts/chrome_launch.cjs)
 const {port}=browser;
 const targets=await (await fetch('http://127.0.0.1:'+port+'/json/list')).json();
 const socket=new WebSocket(targets.find(t=>t.type==='page').webSocketDebuggerUrl);
 await new Promise(resolve=>socket.addEventListener('open',resolve));
 let id=0;const pending=new Map();
 socket.addEventListener('message',event=>{const data=JSON.parse(event.data);if(pending.has(data.id)){const {resolve,reject}=pending.get(data.id);pending.delete(data.id);data.error?reject(new Error(JSON.stringify(data.error))):resolve(data.result);}});
 const call=(method,params={})=>new Promise((resolve,reject)=>{const n=++id;pending.set(n,{resolve,reject});socket.send(JSON.stringify({id:n,method,params}));});
 const evaluate=async expression=>{const r=await call('Runtime.evaluate',{expression,returnByValue:true,awaitPromise:true});if(r.exceptionDetails)throw new Error(JSON.stringify(r.exceptionDetails));return r.result.value;};
 await call('Page.enable');await call('Network.enable');
 if(Object.keys(headers).length)await call('Network.setExtraHTTPHeaders',{headers});
 if(deterministic){
  const fixed=now?Date.parse(now):null;
  const clock=fixed===null?'':'const T='+fixed+',R=Date;class D extends R{constructor(...a){a.length?super(...a):super(T);}static now(){return T;}}globalThis.Date=D;';
  await call('Page.addScriptToEvaluateOnNewDocument',{source:'(()=>{'+clock+
   "const style=()=>{const s=document.createElement('style');s.textContent='*,*::before,*::after{animation:none!important;transition:none!important;caret-color:transparent!important;scroll-behavior:auto!important}';(document.head||document.documentElement).appendChild(s);};"+
   "if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',style);else style();})()"});
 }
 if(deterministic)await call('Page.addScriptToEvaluateOnNewDocument',{source:"try{sessionStorage.clear();localStorage.clear();}catch(e){}"});   // every capture starts from empty web storage (#267)
 for(const job of jobs){
  if(deterministic){   // and from an empty browser: no cache, no stored data of the origin, nothing a capture earlier in the session left (#267)
   await call('Page.navigate',{url:'about:blank'});
   await call('Network.clearBrowserCache');
   await call('Storage.clearDataForOrigin',{origin:new URL(job.url).origin,storageTypes:'all'});
  }
  const width=job.width,height=job.height||(width<600?844:width<1100?1024:900),max=job.max||3000;
  await call('Emulation.setDeviceMetricsOverride',{width,height,deviceScaleFactor:width<600?2:1,mobile:width<600});
  await call('Emulation.setEmulatedMedia',{features:[{name:'prefers-color-scheme',value:job.theme==='dark'?'dark':'light'},...(deterministic?[{name:'prefers-reduced-motion',value:'reduce'}]:[])]});
  await call('Page.navigate',{url:job.url});
  for(let i=0;i<200;i++){if(await evaluate(`document.readyState==='complete'${job.wait?` && !!document.querySelector(${JSON.stringify(job.wait)})`:''}`))break;await delay(50);}
  await evaluate("document.fonts?Promise.all([...document.fonts].map(f=>f.load().catch(()=>null))).then(()=>document.fonts.ready).then(()=>true):true");   // every declared face loaded, not only those the first paint asked for
  if(deterministic)await evaluate("(()=>{const b=document.body;if(!b)return true;b.style.display='none';void b.offsetHeight;b.style.display='';void b.offsetHeight;return true;})()");   // lay the page out again with every font loaded: a form control laid out before its webfont arrived keeps the fallback's metrics, 1 px off from a warm session's (#267)
  if(job.script)await evaluate(`(async()=>{${job.script}})()`);
  await delay(250);
  // An open sheet is shown as the device sees it (one viewport); a page is shown whole, with the viewport grown to its height so the
  // fixed bars (phone tab bar, save bar) sit at its foot rather than across the middle of the capture.
  const sheet=(job.sheet_below&&width<job.sheet_below)||await evaluate("!!document.querySelector('dialog[open]')");   // sheet_below: a sheet that is not a dialog (a fixed panel) is still one viewport on a phone
  let shotHeight=height;
  if(!sheet){
   const full=await evaluate('Math.max(document.documentElement.scrollHeight,document.body.scrollHeight)');
   shotHeight=Math.min(Math.max(full,height),max);
   await call('Emulation.setDeviceMetricsOverride',{width,height:shotHeight,deviceScaleFactor:width<600?2:1,mobile:width<600});
   await delay(250);
  }
  const shot=await call('Page.captureScreenshot',{format:'png',clip:{x:0,y:0,width,height:shotHeight,scale:1}});
  fs.mkdirSync(path.dirname(job.out),{recursive:true});
  fs.writeFileSync(job.out,Buffer.from(shot.data,'base64'));
  console.log(job.out);
 }
 socket.close();await browser.stop();
})().catch(async error=>{console.error(error.message||error);if(browser)await browser.stop();process.exit(1);});
