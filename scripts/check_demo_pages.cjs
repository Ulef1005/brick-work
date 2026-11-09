/* Open every page of the exported demo in a browser, light and dark, and fail on a broken picture or a missing stylesheet.

    node scripts/check_demo_pages.cjs CHROME BASE_URL PAGES.json

PAGES.json is a list of paths under BASE_URL. Each page is loaded once per colour scheme; pictures are made eager, then the page must settle (fonts ready,
every stylesheet loaded, every img complete) within 15 s, and then: no `img` of a picture (/manage/images/) may have naturalWidth 0, every
<link rel=stylesheet> must have a sheet with rules, and a demo picture note must sit in a picture box of at least 120 px and stay inside it (#197). Prints one line per failure and a summary;
exit 1 on any failure. */
const fs=require('node:fs'),path=require('node:path'),os=require('node:os'),{spawn}=require('node:child_process');
const [chrome,base,pagesFile]=process.argv.slice(2);
const pages=JSON.parse(fs.readFileSync(pagesFile,'utf8'));
const profile=fs.mkdtempSync(path.join(os.tmpdir(),'bw-sweep-'));
const child=spawn(chrome,[...(process.env.BW_CHROME_NO_SANDBOX?['--no-sandbox']:[]),'--headless','--disable-background-networking','--hide-scrollbars','--remote-debugging-port=0','--user-data-dir='+profile,'about:blank'],{stdio:['ignore','ignore','ignore']});
const delay=ms=>new Promise(resolve=>setTimeout(resolve,ms));
const probe=`(async()=>{
 await (document.fonts?document.fonts.ready:null);
 const pending=()=>{for(const i of document.images)i.loading='eager';return [...document.images].filter(i=>!i.complete).length+[...document.querySelectorAll('link[rel=stylesheet]')].filter(l=>!l.sheet).length;};
 const end=Date.now()+15000;
 await new Promise(r=>setTimeout(r,500));
 while(pending()&&Date.now()<end)await new Promise(r=>setTimeout(r,50));
 const problems=[];
 if(pending())problems.push('page did not settle');
 for(const l of document.querySelectorAll('link[rel=stylesheet]')){let n=0;try{n=l.sheet?l.sheet.cssRules.length:0}catch(e){n=-1}if(!l.sheet||n===0)problems.push('stylesheet '+l.getAttribute('href'));}
 for(const i of document.images)if((i.getAttribute('src')||'').includes('/manage/images/')&&(!i.complete||i.naturalWidth===0))problems.push('picture '+i.getAttribute('src'));
 for(const n of document.querySelectorAll('.bw-demo-picture-note')){const t=n.closest('.bc-picture,.bw-picture,.check-picture,.scan-tile'),r=document.createRange();r.selectNodeContents(n);const a=r.getBoundingClientRect();if(!t){if(a.width)problems.push('picture note outside a picture box (#197)');continue;}const b=t.getBoundingClientRect();if(a.width&&b.width<120)problems.push('picture note in a box under 120 px (#197): '+(t.getAttribute('class')||t.tagName));if(a.width&&(a.top<b.top-1||a.bottom>b.bottom+1||a.left<b.left-1||a.right>b.right+1))problems.push('picture note overflows its picture box (#197): '+(n.closest('[data-item-no]')?.dataset.itemNo||t.getAttribute('class')||t.tagName));}
 return JSON.stringify({problems,images:document.images.length,sheets:document.styleSheets.length});
})()`;
(async()=>{
 let port;
 for(let i=0;i<200;i++){try{port=fs.readFileSync(path.join(profile,'DevToolsActivePort'),'utf8').split('\n')[0];break;}catch{}await delay(50);}
 if(!port)throw new Error('Chrome did not start');
 const targets=await (await fetch('http://127.0.0.1:'+port+'/json/list')).json();
 const socket=new WebSocket(targets.find(t=>t.type==='page').webSocketDebuggerUrl);
 await new Promise(resolve=>socket.addEventListener('open',resolve));
 let id=0;const pending=new Map();
 socket.addEventListener('message',event=>{const data=JSON.parse(event.data);if(pending.has(data.id)){const {resolve,reject}=pending.get(data.id);pending.delete(data.id);data.error?reject(new Error(JSON.stringify(data.error))):resolve(data.result);}});
 const call=(method,params={})=>new Promise((resolve,reject)=>{const n=++id;pending.set(n,{resolve,reject});socket.send(JSON.stringify({id:n,method,params}));});
 const evaluate=async expression=>{const r=await call('Runtime.evaluate',{expression,returnByValue:true,awaitPromise:true});if(r.exceptionDetails)throw new Error(JSON.stringify(r.exceptionDetails));return r.result.value;};
 await call('Page.enable');await call('Network.enable');
 let failures=0,checked=0,images=0;
 for(const theme of ['light','dark']){
  await call('Emulation.setDeviceMetricsOverride',{width:1280,height:900,deviceScaleFactor:1,mobile:false});
  await call('Emulation.setEmulatedMedia',{features:[{name:'prefers-color-scheme',value:theme}]});
  for(const page of pages){
   await call('Page.navigate',{url:base+page});
   for(let i=0;i<300;i++){if(await evaluate("document.readyState==='complete'"))break;await delay(50);}
   const result=JSON.parse(await evaluate(probe));
   checked++;images+=result.images;
   if(result.problems.length){failures++;console.log(`FAIL ${theme} ${page}: ${result.problems.slice(0,4).join('; ')}`);}
  }
 }
 console.log(`${checked} page loads (${pages.length} pages x 2 schemes), ${images} images seen, ${failures} with problems`);
 socket.close();const exited=new Promise(resolve=>child.once('exit',resolve));child.kill();await exited;
 try{fs.rmSync(profile,{recursive:true,force:true,maxRetries:5,retryDelay:100});}catch{}
 process.exit(failures?1:0);
})().catch(error=>{console.error(error.message||error);child.kill();process.exit(2);});
