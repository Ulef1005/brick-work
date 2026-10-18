/* Planning geometry against offline migration-fixture pages; no screenshots. */
const fs=require('node:fs'),path=require('node:path'),{spawn}=require('node:child_process'),assert=require('node:assert/strict');
const [chrome,dir]=process.argv.slice(2);
const profile=path.join(dir,'profile');
const child=spawn(chrome,['--headless','--disable-background-networking','--remote-debugging-port=0','--user-data-dir='+profile,'about:blank'],{stdio:['ignore','ignore','pipe']});
let launchErrors='';child.stderr.on('data',data=>launchErrors+=data.toString());
let socket;
const delay=ms=>new Promise(resolve=>setTimeout(resolve,ms));
(async()=>{
 let port;
 for(let i=0;i<100;i++){try{port=fs.readFileSync(path.join(profile,'DevToolsActivePort'),'utf8').split('\n')[0];break;}catch{}await delay(50);}
 assert.ok(port,'Chromium did not start: '+launchErrors);
 const targets=await (await fetch('http://127.0.0.1:'+port+'/json/list')).json();
 socket=new WebSocket(targets.find(t=>t.type==='page').webSocketDebuggerUrl);
 await new Promise(resolve=>socket.addEventListener('open',resolve));
 let id=0;const pending=new Map();
 socket.addEventListener('message',event=>{const data=JSON.parse(event.data);if(pending.has(data.id)){const {resolve,reject}=pending.get(data.id);pending.delete(data.id);data.error?reject(data.error):resolve(data.result);}});
 const call=(method,params={})=>new Promise((resolve,reject)=>{const n=++id;pending.set(n,{resolve,reject});socket.send(JSON.stringify({id:n,method,params}));});
 const evaluate=async expression=>{const result=await call('Runtime.evaluate',{expression,returnByValue:true});assert.ok(!result.exceptionDetails,JSON.stringify(result.exceptionDetails));return result.result.value;};
 for(const screen of ['complete-sets','prices']){
  for(const width of [360,390,1024]){
   await call('Emulation.setDeviceMetricsOverride',{width,height:900,deviceScaleFactor:1,mobile:false});
   await call('Page.navigate',{url:'file://'+path.join(dir,screen+'.html')});
   for(let i=0;i<100;i++){if(await evaluate("document.readyState==='complete' && location.pathname.endsWith('/"+screen+".html') && !!document.querySelector('#bw-planning')"))break;await delay(20);}
   for(const open of [false,true]){
    await evaluate(`document.querySelectorAll('.bp-repair-details,.bp-records').forEach(n=>n.open=${open})`);
    const measured=await evaluate(`(()=>{
     const errors=[],rect=n=>n.getBoundingClientRect(),rows=[...document.querySelectorAll('[data-bp-row]')];
     if(document.documentElement.scrollWidth>innerWidth)errors.push('page overflow');
     for(const row of rows){
      const numbers=row.querySelector('.bp-repair-numbers'),label=row.querySelector('.bp-details-label');
      if(numbers){
       if(rect(numbers).bottom>rect(label).top+.5)errors.push('repair numbers overlap Details');
       if(rect(label).bottom>rect(row).bottom+.5)errors.push('summary outside row');
       const summary=numbers.parentElement;
       if(rect(summary).height+1<rect(numbers).height+rect(label).height)errors.push('summary fails to grow');
      }
     }
     for(let i=1;i<rows.length;i++)if(rect(rows[i-1]).bottom>rect(rows[i]).top+.5)errors.push('row overlap');
     const names=[...document.querySelectorAll('.bp-prices .bp-identity strong')].slice(0,2);
     for(const name of names){
      const text=name.firstChild,lines=new Map();
      for(let i=0;i<text.length;i++){
       if(!text.textContent[i].trim())continue;
       const range=document.createRange();range.setStart(text,i);range.setEnd(text,i+1);
       const top=range.getBoundingClientRect().top;
       lines.set(top,(lines.get(top)||'')+text.textContent[i]);
      }
      const last=[...lines.values()].at(-1);
      if(lines.size>1&&last.length<=2)errors.push('name orphan: '+name.textContent);
     }
     return {errors,rows:rows.length,numbers:document.querySelectorAll('.bp-repair-numbers').length,names:names.length};
    })()`);
    assert.ok(measured.rows>0,screen+' missing rows');
    if(screen==='complete-sets')assert.ok(measured.numbers>0,'missing repair numbers');
    else assert.equal(measured.names,2);
    assert.deepEqual(measured.errors,[],screen+' '+width+' details '+open);
   }
  }
 }
 // 4.9d w4/w5: wishlist range labels stack (label above value, 28 px at 390) over a coloured interval.
 await call('Emulation.setDeviceMetricsOverride',{width:390,height:900,deviceScaleFactor:1,mobile:false});
 await call('Page.navigate',{url:'file://'+path.join(dir,'wishlist.html')});
 for(let i=0;i<100;i++){if(await evaluate("document.readyState==='complete' && location.pathname.endsWith('/wishlist.html') && !!document.querySelector('.bp-wish-range-labels')"))break;await delay(20);}
 const range=await evaluate(`(()=>{const l=document.querySelector('.bp-wish-range-labels'),b=document.querySelector('.bp-wish-track b');return {height:l.getBoundingClientRect().height,fill:getComputedStyle(b).backgroundColor,fillHeight:b.getBoundingClientRect().height};})()`);
 assert.equal(range.height,28);assert.equal(range.fillHeight,6);assert.ok(range.fill.includes('0.83'),range.fill);
 console.log('Planning geometry: repair numbers/Details and price name orphans at 360/390/1024, closed/open passed');
})().catch(e=>{console.error(e);process.exitCode=1;}).finally(()=>{socket?.close();child.kill();});
