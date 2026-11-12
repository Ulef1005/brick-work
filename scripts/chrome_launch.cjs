/* Start a headless Chrome for a CDP harness and wait until it is up (#293).

    const {launch}=require('./chrome_launch.cjs');
    const b=await launch(chrome,{extraArgs:[...]});   // {child, profile, port, stop()}

Chrome counts as started when it prints `DevTools listening on ws://HOST:PORT/...` on stderr (or writes DevToolsActivePort into its profile) and its
/json/list shows a page. On macOS under load the printed line can arrive without the file, or neither within a few seconds, so a failed attempt is
not the end: the process is killed, its profile removed, and the whole launch is tried again with a fresh user-data-dir, up to `attempts` times
(BW_CHROME_ATTEMPTS, default 3). The wait for one start is `startMs` (BW_CHROME_START_MS, default 30000). Only when every attempt failed does the
error carry the last lines of Chrome's stderr; the `CVDisplayLinkCreateWithCGDisplay failed` line macOS prints on every start is dropped from it. */
const fs=require('node:fs'),path=require('node:path'),os=require('node:os'),{spawn}=require('node:child_process');
const delay=ms=>new Promise(resolve=>setTimeout(resolve,ms));
const LISTENING=/DevTools listening on ws:\/\/[^:\s]+:(\d+)\//;
const NOISE=/CVDisplayLinkCreateWithCGDisplay/;

function killGroup(child){try{process.kill(-child.pid,'SIGKILL');}catch{try{child.kill('SIGKILL');}catch{}}}
function tail(text,lines=15){return text.split('\n').filter(l=>l.trim()&&!NOISE.test(l)).slice(-lines).join('\n');}

async function attempt(chrome,{extraArgs,startMs,profileDir}){
 const profile=profileDir||fs.mkdtempSync(path.join(os.tmpdir(),'bw-chrome-'));
 const child=spawn(chrome,[...(process.env.BW_CHROME_NO_SANDBOX?['--no-sandbox']:[]),'--headless','--disable-background-networking','--hide-scrollbars','--remote-debugging-port=0','--user-data-dir='+profile,...extraArgs,'about:blank'],{stdio:['ignore','ignore','pipe'],detached:true});   // its own process group, so a failed start can be killed with its helpers
 let stderr='',exited=false;
 child.stderr.on('data',data=>{stderr+=data.toString();});
 child.once('exit',()=>{exited=true;});
 const stop=async()=>{
  if(!exited){const gone=new Promise(resolve=>child.once('exit',resolve));killGroup(child);await Promise.race([gone,delay(5000)]);}
  try{fs.rmSync(profile,{recursive:true,force:true,maxRetries:5,retryDelay:100});}catch{}
 };
 const deadline=Date.now()+startMs;
 let port=null;
 while(Date.now()<deadline&&!exited){
  const printed=LISTENING.exec(stderr);
  if(printed)port=printed[1];
  else{try{port=fs.readFileSync(path.join(profile,'DevToolsActivePort'),'utf8').split('\n')[0]||null;}catch{}}
  if(port){
   try{
    const targets=await (await fetch('http://127.0.0.1:'+port+'/json/list',{signal:AbortSignal.timeout(5000)})).json();
    if(targets.some(t=>t.type==='page')){process.once('exit',()=>{killGroup(child);try{fs.rmSync(profile,{recursive:true,force:true});}catch{}});return {child,profile,port,stop};}   // a harness that ends by process.exit leaves nothing behind
   }catch{}
  }
  await delay(50);
 }
 const why=exited?'Chrome exited before it was ready':port?'Chrome printed its DevTools port '+port+' but no page appeared within '+startMs+' ms':'Chrome did not print its DevTools line within '+startMs+' ms';
 const logged=tail(stderr);
 await stop();
 const error=new Error(why);error.stderr=logged;throw error;
}

async function launch(chrome,{extraArgs=[],attempts=Number(process.env.BW_CHROME_ATTEMPTS)||3,startMs=Number(process.env.BW_CHROME_START_MS)||30000,profileDir=null}={}){
 const failures=[];
 for(let n=1;n<=attempts;n++){
  try{
   // a caller-owned profile folder is cleared between attempts so that each starts from nothing, like a fresh one
   if(profileDir&&n>1)fs.rmSync(profileDir,{recursive:true,force:true});
   return await attempt(chrome,{extraArgs,startMs,profileDir});
  }catch(error){failures.push(error);if(n<attempts)await delay(500*n);}
 }
 const last=failures[failures.length-1];
 throw new Error('Chrome did not start after '+attempts+' attempts: '+failures.map(f=>f.message).join('; ')+(last.stderr?'\nlast stderr lines:\n'+last.stderr:''));
}

module.exports={launch,tail,LISTENING};
