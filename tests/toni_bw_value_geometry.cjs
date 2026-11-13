/* #57 geometry of the three new screens (the Value module on a set's detail, Paid vs value on Statistics, the insurance report), against offline pages; no screenshots. */
const path=require('node:path'),assert=require('node:assert/strict');
const [chrome,dir]=process.argv.slice(2);
const {launch}=require('../scripts/chrome_launch.cjs');   // starts Chrome and retries a failed start (#293)
const delay=ms=>new Promise(resolve=>setTimeout(resolve,ms));
let browser=null,socket=null;
(async()=>{
 browser=await launch(chrome);
 const targets=await (await fetch('http://127.0.0.1:'+browser.port+'/json/list')).json();
 socket=new WebSocket(targets.find(t=>t.type==='page').webSocketDebuggerUrl);
 await new Promise(resolve=>socket.addEventListener('open',resolve));
 let id=0;const pending=new Map();
 socket.addEventListener('message',event=>{const data=JSON.parse(event.data);if(pending.has(data.id)){const {resolve,reject}=pending.get(data.id);pending.delete(data.id);data.error?reject(new Error(JSON.stringify(data.error))):resolve(data.result);}});
 const call=(method,params={})=>new Promise((resolve,reject)=>{const n=++id;pending.set(n,{resolve,reject});socket.send(JSON.stringify({id:n,method,params}));});
 const evaluate=async expression=>{const result=await call('Runtime.evaluate',{expression,returnByValue:true});assert.ok(!result.exceptionDetails,JSON.stringify(result.exceptionDetails));return result.result.value;};
 const checks={
  detail:"[data-module=value]",statistics:'.bw-value-stats',report:'.br-sheet'};
 for(const screen of Object.keys(checks)){
  for(const width of (screen==='report'?[1440,1280,1024,768,390]:[1440,390])){
   await call('Emulation.setDeviceMetricsOverride',{width,height:900,deviceScaleFactor:1,mobile:false});
   await call('Page.navigate',{url:'file://'+path.join(dir,screen+'.html')});
   for(let i=0;i<100;i++){if(await evaluate("document.readyState==='complete' && !!document.querySelector("+JSON.stringify(checks[screen])+")"))break;await delay(50);}
   await evaluate("document.fonts?document.fonts.ready.then(()=>true):true");
   const errors=await evaluate(`(()=>{
    const errors=[],rect=n=>n.getBoundingClientRect(),root=document.querySelector(${JSON.stringify(checks[screen])});
    if(document.documentElement.scrollWidth>innerWidth)errors.push('page overflow');
    const box=rect(root);
    for(const n of root.querySelectorAll('*')){const r=rect(n);if(r.width&&r.right>box.right+1)errors.push('outside the card: '+n.className);}
    const overlap=(items,label)=>{for(let i=1;i<items.length;i++)if(rect(items[i-1]).bottom>rect(items[i]).top+.5)errors.push(label+' overlap');};
    if(${JSON.stringify(screen)}==='detail'){
     const rows=[...root.querySelectorAll('.bc-value-row')];overlap(rows,'value rows');
     for(const row of rows){const label=row.querySelector('.bc-value-label'),figure=row.querySelector('.bc-value-figure');if(rect(label).right>rect(figure).left+.5&&rect(label).top<rect(figure).bottom&&rect(label).bottom>rect(figure).top)errors.push('label meets figure');}
    }
    if(${JSON.stringify(screen)}==='statistics'){
     for(const bars of root.querySelectorAll('.bv-bars')){
      const left=rect(bars).left,max=rect(bars).right;
      for(const i of bars.querySelectorAll('i')){if(Math.abs(rect(i).left-left)>1.5)errors.push('bar does not start at zero');}
      for(const s of bars.querySelectorAll('span')){if(rect(s).right>max+1)errors.push('bar figure outside its track');}
     }
     for(const row of root.querySelectorAll('.bv-row')){const g=row.querySelector('.bv-gain'),n=row.querySelector('.bv-name');if(g&&rect(g).right>rect(row).right+.5)errors.push('gain outside row');if(rect(n).width<40)errors.push('theme name squeezed');}
     for(const cell of root.querySelectorAll('.bv-cell')){if(rect(cell).height<44)errors.push('cell too short');}
     for(const b of root.querySelectorAll('.bw-outline'))if(rect(b).height<43.5)errors.push('button under 44px');
    }
    if(${JSON.stringify(screen)}==='report'){
     const rows=[...root.querySelectorAll('[data-copy-row]')];overlap(rows,'report rows');
     if(rows.length!==15)errors.push('not 15 rows: '+rows.length);
     for(const row of rows){
      const strip=row.querySelector('.br-strip'),line=row.querySelector('.br-line');
      if(rect(strip).top<rect(line).bottom-.5)errors.push('strip over its row');
      for(const t of row.querySelectorAll('.br-tile'))if(rect(t).right>rect(row).right+.5)errors.push('tile outside row');
      for(const n of line.children){if(rect(n).right>rect(row).right+.5)errors.push('cell outside row: '+n.className);}
     }
     for(const b of document.querySelectorAll('.br-actions a,.br-actions button'))if(rect(b).height<43.5)errors.push('button under 44px');
     const pager=document.querySelector('.br-pager');if(!pager||rect(pager).bottom>rect(root).bottom+.5)errors.push('pager missing or outside the sheet');
     const name=rows[0].querySelector('.br-name');
     if(${width}>=1280){const heads=[...root.querySelectorAll('.br-colheads span')],cells=[...rows[0].querySelectorAll('.br-line > .br-num,.br-line > .br-name,.br-line .br-year,.br-line .br-purchased,.br-line .br-paid,.br-line .br-worth')];
      if(heads.length!==8)errors.push('column heads');
      for(let i=1;i<heads.length;i++)if(rect(heads[i-1]).right>rect(heads[i]).left+.5)errors.push('heading overlaps the next');
      if(rect(name).width<150)errors.push('Name column under 150 px: '+rect(name).width);
      if(Math.abs(rect(heads[0]).left-rect(cells[0]).left)>1||Math.abs(rect(heads[7]).right-rect(cells[cells.length-1]).right)>1)errors.push('columns do not line up with their heads');}
     else{if(getComputedStyle(root.querySelector('.br-colheads')).display!=='none')errors.push('column heads shown in the card layout');
      if(rect(name).width<150)errors.push('Name under 150 px: '+rect(name).width);}
    }
    return errors;})()`);
   assert.deepEqual(errors,[],screen+' at '+width+': '+errors.join(', '));
  }
 }
})().catch(e=>{console.error(e);process.exitCode=1;}).finally(()=>{socket?.close();browser?.child?.kill();});
