/* Design audit captures: PNGs of app pages at the kit sizes, light and dark, for approval (design/approval/README.md).

    node scripts/capture_screens.cjs CHROME JOBS.json

JOBS.json is {"headers": {...optional, e.g. Cookie}, "jobs": [{"url", "out", "width", "height"?, "theme": "light"|"dark",
"wait"?: CSS selector, "script"?: JS run before the capture (open a sheet, tick a box), "max"?: px, default 3000}]}.
The theme is the system preference (the app's default mode); long pages are clipped to their first `max` px. */
const fs=require('node:fs'),path=require('node:path'),os=require('node:os'),{spawn}=require('node:child_process');
const [chrome,jobsFile]=process.argv.slice(2);
if(!chrome||!jobsFile){console.error('usage: node scripts/capture_screens.cjs CHROME JOBS.json');process.exit(2);}
const {headers={},jobs}=JSON.parse(fs.readFileSync(jobsFile,'utf8'));
const profile=fs.mkdtempSync(path.join(os.tmpdir(),'bw-capture-'));
const child=spawn(chrome,['--headless','--disable-background-networking','--hide-scrollbars','--remote-debugging-port=0','--user-data-dir='+profile,'about:blank'],{stdio:['ignore','ignore','pipe']});
let launchErrors='';child.stderr.on('data',data=>launchErrors+=data.toString());
const delay=ms=>new Promise(resolve=>setTimeout(resolve,ms));
(async()=>{
 let port;
 for(let i=0;i<200;i++){try{port=fs.readFileSync(path.join(profile,'DevToolsActivePort'),'utf8').split('\n')[0];break;}catch{}await delay(50);}
 if(!port)throw new Error('Chrome did not start: '+launchErrors);
 const targets=await (await fetch('http://127.0.0.1:'+port+'/json/list')).json();
 const socket=new WebSocket(targets.find(t=>t.type==='page').webSocketDebuggerUrl);
 await new Promise(resolve=>socket.addEventListener('open',resolve));
 let id=0;const pending=new Map();
 socket.addEventListener('message',event=>{const data=JSON.parse(event.data);if(pending.has(data.id)){const {resolve,reject}=pending.get(data.id);pending.delete(data.id);data.error?reject(new Error(JSON.stringify(data.error))):resolve(data.result);}});
 const call=(method,params={})=>new Promise((resolve,reject)=>{const n=++id;pending.set(n,{resolve,reject});socket.send(JSON.stringify({id:n,method,params}));});
 const evaluate=async expression=>{const r=await call('Runtime.evaluate',{expression,returnByValue:true,awaitPromise:true});if(r.exceptionDetails)throw new Error(JSON.stringify(r.exceptionDetails));return r.result.value;};
 await call('Page.enable');await call('Network.enable');
 if(Object.keys(headers).length)await call('Network.setExtraHTTPHeaders',{headers});
 for(const job of jobs){
  const width=job.width,height=job.height||(width<600?844:width<1100?1024:900),max=job.max||3000;
  await call('Emulation.setDeviceMetricsOverride',{width,height,deviceScaleFactor:width<600?2:1,mobile:width<600});
  await call('Emulation.setEmulatedMedia',{features:[{name:'prefers-color-scheme',value:job.theme==='dark'?'dark':'light'}]});
  await call('Page.navigate',{url:job.url});
  for(let i=0;i<200;i++){if(await evaluate(`document.readyState==='complete'${job.wait?` && !!document.querySelector(${JSON.stringify(job.wait)})`:''}`))break;await delay(50);}
  await evaluate("document.fonts?document.fonts.ready.then(()=>true):true");
  if(job.script)await evaluate(`(async()=>{${job.script}})()`);
  await delay(250);
  const full=await evaluate('Math.max(document.documentElement.scrollHeight,document.body.scrollHeight)');
  const shot=await call('Page.captureScreenshot',{format:'png',captureBeyondViewport:true,clip:{x:0,y:0,width,height:Math.min(Math.max(full,height),max),scale:1}});
  fs.mkdirSync(path.dirname(job.out),{recursive:true});
  fs.writeFileSync(job.out,Buffer.from(shot.data,'base64'));
  console.log(job.out);
 }
 socket.close();const exited=new Promise(resolve=>child.once('exit',resolve));child.kill();await exited;
 try{fs.rmSync(profile,{recursive:true,force:true,maxRetries:5,retryDelay:100});}catch{}
})().catch(error=>{console.error(error.message||error);child.kill();process.exit(1);});
