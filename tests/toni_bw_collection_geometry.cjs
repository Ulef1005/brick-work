/* Real Chromium geometry against offline migration-fixture pages. */
const fs=require('node:fs'),path=require('node:path'),{spawn}=require('node:child_process'),assert=require('node:assert/strict');
const [chrome,dir]=process.argv.slice(2);
const profile=path.join(dir,'profile');
const child=spawn(chrome,['--headless','--disable-background-networking','--remote-debugging-port=0','--user-data-dir='+profile,'about:blank'],{stdio:['ignore','ignore','pipe']});
let launchErrors='';child.stderr.on('data',data=>launchErrors+=data.toString());
let socket;
const identityMeasurements=[];
const review49a=[];
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
 for(const width of [1024,1440]){
  await call('Emulation.setDeviceMetricsOverride',{width,height:900,deviceScaleFactor:1,mobile:false});
  await call('Page.navigate',{url:'file://'+path.join(dir,'detail.html')});
  for(let i=0;i<100;i++){if(await evaluate("document.readyState==='complete' && location.pathname.endsWith('/detail.html') && !!document.querySelector('#bw-collection')"))break;await delay(20);}
  const chipHeights=await evaluate('[...document.querySelectorAll(".bc-copy-chip")].map(n=>n.getBoundingClientRect().height)');
  assert.ok(chipHeights.length>0,'copy chips missing at '+width);assert.ok(chipHeights.every(h=>h===36),'copy chip height at '+width+': '+chipHeights);
 }
 for(const kind of ['S','M','P','I','detail']){
  for(const width of kind==='detail'?[360,390,768,820,1024,1440]:[360,390]){
   await call('Emulation.setDeviceMetricsOverride',{width,height:900,deviceScaleFactor:1,mobile:false});
   await call('Page.navigate',{url:'file://'+path.join(dir,kind+'.html')});
   for(let i=0;i<100;i++){if(await evaluate("document.readyState==='complete' && location.pathname.endsWith('/"+kind+".html') && !!document.querySelector('#bw-collection')"))break;await delay(20);}
   const size=await evaluate('({width:innerWidth,scroll:document.documentElement.scrollWidth})');
   assert.equal(size.width,width);assert.ok(size.scroll<=width,kind+' '+width+': '+JSON.stringify(size));
   // Offline lists have no rendered records: measure only their shell width/scroll.
   if(kind==='S'&&width===390){
    // 49b c26: the Show action is its own 350x56 row and overlaps nothing in the sheet.
    const sheet=await evaluate(`(()=>{
     const panel=document.querySelector('[data-bc-panel]');panel.hidden=false;
     const r=n=>{const b=n.getBoundingClientRect();return {x:b.x,y:b.y,width:b.width,height:b.height,bottom:b.bottom};};
     const apply=panel.querySelector('[data-bc-apply]'),a=r(apply);
     const overlaps=[...panel.querySelectorAll('h3,h4,label,button,select,summary,a')].filter(n=>n!==apply&&n.offsetParent&&n.getClientRects().length&&(n.matches('summary')||!n.closest('details:not([open])'))).filter(n=>{const b=r(n);return b.width&&b.height&&b.x<a.x+a.width&&b.x+b.width>a.x&&b.y<a.y+a.height&&b.y+b.height>a.y;}).map(n=>n.textContent.trim().slice(0,30));
     const rows=['.bc-theme-row','.bc-storage-row','.bc-year-row'].map(q=>({q,...r(panel.querySelector(q))}));
     return {apply:a,position:getComputedStyle(apply).position,overlaps,rows};
    })()`);
    assert.equal(sheet.apply.width,350,JSON.stringify(sheet));assert.equal(sheet.apply.height,56,JSON.stringify(sheet));
    assert.equal(sheet.position,'static');assert.deepEqual(sheet.overlaps,[],JSON.stringify(sheet));
    assert.ok(sheet.rows.every(row=>row.height===52&&row.width===350),JSON.stringify(sheet.rows));
   }
   if(kind!=='detail')continue;
   // A scrollbar that appears only in one of two compared states would change every width by its own width.
   await evaluate("document.documentElement.style.overflowY='scroll'");
   if([360,390,768,1024,1440].includes(width)){
    // 4.9a (c1, c11, c12, c14, c15): measured against the shipped CSS.
    review49a.push({width,...await evaluate(`(()=>{
     const rect=n=>n.getBoundingClientRect(),picture=document.querySelector('.bc-hero-picture');
     // The offline page has no local picture file: give the hero a wide image so contain versus cover is observable.
     let img=picture.querySelector('img');
     if(!img){picture.replaceChildren();img=document.createElement('img');img.alt='';picture.append(img);}
     img.src='data:image/svg+xml,'+encodeURIComponent('<svg xmlns="http://www.w3.org/2000/svg" width="400" height="100"><rect width="400" height="100" fill="#888"/></svg>');
     const hero={objectFit:getComputedStyle(img).objectFit,inside:rect(img).left>=rect(picture).left-.5&&rect(img).right<=rect(picture).right+.5&&rect(img).top>=rect(picture).top-.5&&rect(img).bottom<=rect(picture).bottom+.5};
     const pills=[...document.querySelectorAll('.bc-figure-status')];
     for(const row of document.querySelectorAll('.bc-figure-row'))row.hidden=false;
     const lines=n=>{const r=document.createRange();r.selectNodeContents(n);return new Set([...r.getClientRects()].map(b=>Math.round(b.top))).size;};
     const pill={height:Math.max(...pills.map(n=>rect(n).height)),lines:Math.max(...pills.map(lines))};
     if(!pills.length)throw new Error('no figure status pill in the fixture');
     const row=[...document.querySelectorAll('.bc-figure-row')].find(n=>n.textContent.includes('Breastplate'));
     const previous=row.style.width;row.style.width='344px';
     const link=row.querySelector('.bc-figure-identity>a'),walker=document.createTreeWalker(link,NodeFilter.SHOW_TEXT);let word=null;
     for(let node=walker.nextNode();node;node=walker.nextNode()){const at=node.textContent.indexOf('Breastplate');if(at>=0){const r=document.createRange();r.setStart(node,at);r.setEnd(node,at+'Breastplate'.length);word=r;break;}}
     const figure={linkWidth:rect(link).width,wordSplit:!word||new Set([...word.getClientRects()].map(b=>Math.round(b.top))).size>1};
     row.style.width=previous;
     const block=document.querySelector('.bc-progress-block'),present=block.querySelector('.bc-progress-present'),spans=[...block.querySelectorAll('.bc-progress-stats span')],coverage=block.querySelector('.bc-coverage');
     const missing=spans[0],taken=spans[1];
     const progress={presentBeforeMissing:rect(present).left<rect(missing).left&&Math.abs(rect(present).top-rect(missing).top)<1&&Math.abs(rect(missing).right-rect(block).right)<1,
      captionsBelowCoverage:!!coverage&&rect(taken).top>=rect(coverage).bottom&&Math.abs(rect(taken).top-rect(coverage).bottom-6)<1.5&&rect(coverage).top>=rect(present).bottom};
     const card=[...document.querySelectorAll('.bc-figure-row')].find(n=>n.querySelector('[data-figure-state=parts-missing]'));
     if(!card)throw new Error('no missing figure card in the fixture');
     const cardLink=card.querySelector('.bc-figure-identity>a'),inside=r=>r.left>=rect(card).left-.5&&r.right<=rect(card).right+.5;
     const missingCard={scrollFits:document.documentElement.scrollWidth<=innerWidth,identityInside:inside(rect(cardLink)),cardInsideViewport:rect(card).right<=innerWidth+.5};
     return {hero,pill,figure,progress,missingCard};
    })()`)});
   }
   // Exercise the actual shared inventory markup, independently of category visibility.
   const inventory=await evaluate(`(()=>{
    document.querySelector('[data-bc-present]').open=true;
    const rows=[...document.querySelectorAll('.bc-inventory-row')];
    for(const row of rows)row.hidden=false;
    return rows.map(row=>row.textContent.replaceAll('\u00a0',' '));
   })()`);
   for(const name of ['Tire Smooth Small Dually','Brick 2 x 4 without Cross Support'])assert.ok(inventory.some(text=>text.includes(name)),name+' missing');
   const measure=`(()=>[...document.querySelectorAll('.bc-inventory-row')].map(row=>{
    const r=n=>{const b=n.getBoundingClientRect();return {x:b.x,y:b.y,width:b.width,height:b.height,bottom:b.bottom};};
    const link=row.querySelector(':scope > a'),identity=link.querySelector('.bc-identity,.bc-missing-identity');
    return {figure:row.classList.contains('bc-figure-row'),missing:row.matches('.bc-missing-card'),padding:parseFloat(getComputedStyle(row).paddingLeft),name:identity.textContent,identity:r(identity),link:r(link),picture:r(row.querySelector('.bc-picture')),row:r(row),
     colours:[...row.querySelectorAll('.bc-colour')].map(chip=>{const range=document.createRange();range.selectNodeContents(chip);return {label:chip.textContent,lines:range.getClientRects().length};})};
   }))()`;
   const geometry=await evaluate(measure);
   assert.ok(geometry.length>0, width+': inventory rows missing');
   if([360,390,768,820].includes(width)){
    identityMeasurements.push({width,rows:geometry.map(row=>({name:row.name,missing:row.missing,cardWidth:row.row.width,width:row.link.width}))});
    for(const row of geometry){
     // Kit frame 1d: 16 px card padding, 96 px picture, 16 px gap.
     // At the kit's 390 px phone width (20 px page insets):
     // (390 - 2*20) - 2*16 - 96 - 16 = 206 px identity.
     // The identity box is content-sized inside its link, so the link is the identity column
     // (a short name would otherwise measure narrow without being squeezed).
     // Use the available card width here, including narrower tablet columns.
     const minimum=row.missing?row.row.width-2*16-96-16-1:150;
     const column=row.link.width;
     assert.ok(column>=minimum,width+' '+row.name+': identity column '+column+' < '+minimum);
     for(const chip of row.colours)assert.equal(chip.lines,1,chip.label+' wraps');
    }
   }
   if(width>=1024){
    // Removing only this fix must leave closed desktop/tablet geometry identical.
    // Figure rows (4.9a) wrap by design from 4.7f and change the column's content width, so the invariant covers the part rows alone.
    await evaluate("document.querySelectorAll('.bc-figure-row').forEach(n=>n.hidden=true)");
    const partRows=(await evaluate(measure)).filter(r=>!r.figure);
    await evaluate(`window.fixStyle=[...document.querySelectorAll('style')].find(s=>s.textContent.includes('/* 4.7f'));window.fixedCSS=fixStyle.textContent;fixStyle.textContent=fixedCSS.replace(/\\/\\* 4\\.7f[\\s\\S]*?(?=\\/\\* 4\\.7d)/,'')`);
    assert.deepEqual((await evaluate(measure)).filter(r=>!r.figure),partRows,width+' closed rows changed');
    await evaluate('fixStyle.textContent=fixedCSS');
    await evaluate("document.querySelectorAll('.bc-figure-row').forEach(n=>n.hidden=false)");
   }
   assert.equal(await evaluate("document.querySelectorAll('.bc-inventory-row-details').length"),0,'Part details disclosures removed');
   await evaluate("document.querySelector('#bc-edit').showModal()");
   for(const open of [false,true]){
    await evaluate(`document.querySelector('#bc-edit .bc-source-details').open=${open}`);
    const errors=await evaluate(`(()=>{
     const errors=[],rect=n=>n.getBoundingClientRect();
     const aside=document.querySelector('.bc-detail-aside'),modules=[...aside.children];
     for(let i=1;i<modules.length;i++)if(rect(modules[i-1]).bottom>rect(modules[i]).top+.5)errors.push('module overlap');
     for(const module of modules){
      const children=[...module.children].filter(n=>rect(n).height>0);
      for(let i=1;i<children.length;i++)if(rect(children[i-1]).bottom>rect(children[i]).top+.5)errors.push('module child overlap '+children[i].tagName);
     }
     const dialog=document.querySelector('#bc-edit'),source=dialog.querySelector('.bc-source-details');
     if(!dialog.open||rect(dialog).height<=0)errors.push('dialog not visible');
     const sourceFacts=[...source.querySelectorAll('.bc-fact')];
     if(!sourceFacts.length)errors.push('source facts missing');
     for(const fact of sourceFacts){
      // A closed details keeps stale rects under content-visibility:hidden; checkVisibility() reports the skipped contents.
      if(source.open&&(!fact.checkVisibility()||rect(fact).height<=0))errors.push('open source fact not visible');
      if(!source.open&&fact.checkVisibility())errors.push('closed source fact visible');
     }
     const visibleFacts=sourceFacts.filter(n=>n.checkVisibility()&&rect(n).height>0);
     for(let i=1;i<visibleFacts.length;i++)if(rect(visibleFacts[i-1]).bottom>rect(visibleFacts[i]).top+.5)errors.push('source fact row overlap');
     for(const fact of [...aside.querySelectorAll('.bc-fact'),...sourceFacts]){const dt=fact.querySelector('dt'),dd=fact.querySelector('dd');if(rect(dt).height&&rect(dt).bottom>rect(dd).top+.5)errors.push('fact overlap');}
     for(const price of aside.querySelectorAll('.bc-price')){const children=[...price.children];for(let i=1;i<children.length;i++)if(rect(children[i-1]).bottom>rect(children[i]).top+.5)errors.push('price overlap');}
     return errors;
    })()`);
    assert.deepEqual(errors,[],width+' source details '+open);
   }
   await evaluate("document.querySelector('#bc-edit').close()");
  }
 }
 console.log(JSON.stringify({identityMeasurements,review49a}));
 console.log('Collection geometry: list shells at 360/390; detail and inventory at 360/390/768/820/1024/1440, copy chips 36px at 1024/1440, source details closed/open passed');
})().catch(e=>{console.error(e);process.exitCode=1;}).finally(()=>{socket?.close();child.kill();});
