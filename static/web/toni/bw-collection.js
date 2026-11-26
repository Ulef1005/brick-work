/* Collection lists materialize only their visible records. */
(() => {
  'use strict';
  const nowrapTail = window.BrickFormatting.nowrapTail;
  // The Rebrickable number first, the BrickLink number beside it where it differs, a local BrickLink-born item marked (core/items.py).
  function numberLabel(r){return !r.number?'':r.source==='bricklink'?r.number+' (BrickLink)':r.also?r.number+' · BrickLink '+r.also:r.number;}
  function filterRows(rows, query='', filters={}, sort='number', direction='asc', group='', rank=null) {   // `rank`: storage id -> place in the Sets page's storage order (#494)
    // #41: a size in the query ("2x1", "1 2", "1*2", "x2") matches by size key; other words as text.
    const size=(typeof window!=='undefined'&&window.BrickSize)?window.BrickSize.parse(query):{full:null,partial:null,rest:query};
    const sized=size.full||size.partial,term=(sized?size.rest:query).trim().toLocaleLowerCase();
    const text=r=>[r.name,r.number,r.also,r.colour,r.category,r.theme,r.year].join(' ').toLocaleLowerCase();
    const matches=rows.filter(r => (!sized || window.BrickSize.matches(r.name,size)) && (!term || (sized?term.split(/\s+/).every(w=>text(r).includes(w)):text(r).includes(term))) && Object.entries(filters).every(([key,value]) => {
      if (!value) return true;
      if (key==='inventory') return (value==='parts'?!['M','?','I','O'].includes(r.type):value==='figures'?['M','?'].includes(r.type):['I','O'].includes(r.type));
      if (key==='status' && value==='unknown') return (r.status||[]).includes('');
      if (key==='tag' || key==='has') return (r.flags||[]).includes(value);
      if (key==='lot' && value==='any') return (r.lot||[]).some(x=>String(x)!=='null');
      if (key==='problem') return defect(r,value,filters.stock)>0;
      if (key==='duplicates') return String(!!r.duplicates)===value;
      return (Array.isArray(r[key])?r[key].map(String):[String(r[key]??'')]).includes(value);
    }));
    const compare=(a,b,key)=>key==='storage'&&rank?(rank.get(groupValue(a,key))??1e9)-(rank.get(groupValue(b,key))??1e9):['lot','storage','place'].includes(key)?(groupValue(a,key)==='null')-(groupValue(b,key)==='null')||groupValue(a,key).localeCompare(groupValue(b,key),undefined,{numeric:true}):key==='index'?Number(a.index||0)-Number(b.index||0):key==='used_price'?comparePrice(a,b):key==='missing'?(defect(a,'missing')+defect(a,'damaged'))-(defect(b,'missing')+defect(b,'damaged')):key==='quantity'?Number((filters.stock==='sets'?a.in_sets:a.quantity)||0)-Number((filters.stock==='sets'?b.in_sets:b.quantity)||0):['missing','damaged'].includes(key)?defect(a,key)-defect(b,key):key==='year'?Number(a[key]||0)-Number(b[key]||0):String(a[key]||'').localeCompare(String(b[key]||''),undefined,{numeric:true});
    return matches.sort((a,b)=> (group?compare(a,b,group):0) || (sort==='used_price' && (!a.price || !b.price)?Number(!a.price)-Number(!b.price):0) || (compare(a,b,sort)*(direction==='desc' || sort==='missing'?-1:1)) || compare(a,b,'number') || compare(a,b,'id'));
  }
  // Array-valued fields (lot, storage, place) group by their first recorded value; 'null' means none.
  function groupValue(r,key) {
    const v=r[key];
    if(Array.isArray(v))return String(v.find(x=>String(x)!=='null')??(v.length?'null':''));
    return String(v??'');
  }
  function comparePrice(a,b) {
    // Keep unpriced rows last in either direction; currencies stay separate.
    if(!a.price || !b.price)return !a.price-!b.price;
    return String(a.price[0]).localeCompare(String(b.price[0])) || Number(a.price[1])-Number(b.price[1]);
  }
  function missingSummary(rows) {
    const gaps=rows.flatMap(r=>{
      const parts=Number(r.missing_parts||0),figures=Number(r.missing_figures||0);
      const labels=[parts?parts+' '+(parts===1?'part':'parts'):'',figures?figures+' '+(figures===1?'fig':'figs'):''].filter(Boolean);
      return labels.length?[labels.join(', ')+' in '+(numberLabel(r)||r.name)]:[];
    });
    // Kit 1c shows a short line: the first few sets, then a bare count of the rest.
    const shown=gaps.slice(0,3),more=gaps.length-shown.length;
    return gaps.length?'Missing in view: '+shown.join(' · ')+(more?' · and '+more+' more':''):'';
  }
  // The Instructions list counts booklets (its heading says so); resultNoun stays 'instructions' for other callers.
  function listNoun(kind) {
    return kind==='I'?'booklets':resultNoun(kind);
  }
  function singularNoun(kind) {
    return {S:'set',M:'minifigure',P:'part',I:'booklet',O:'box',G:'gear',B:'book',C:'catalog','?':'item',wish:'wish'}[kind]||'result';
  }
  function resultNoun(kind) {
    return {S:'sets',M:'minifigures',P:'parts',I:'instructions',O:'boxes',G:'gear',B:'books',C:'catalogs','?':'unresolved items',wish:'wishes'}[kind]||'results';
  }
  const resultCount = window.BrickFormatting.resultCount;
  function selectedInstances(checks) {
    const selected=checks.filter(c=>c.checked && !c.hidden).map(c=>({entity:c.entity,ids:c.ids}));
    if (new Set(selected.map(c=>c.entity)).size>1) throw new Error('Choose one instance type at a time');
    return {entity:selected[0]?.entity,ids:[...new Set(selected.flatMap(c=>c.ids))]};
  }
  // #463: a row's missing and damaged are the loose pieces; the ones inside set copies sit beside them. The scope (a filter's stock, else the row's own) picks the pair.
  const heldIn=(r,stock)=>(stock||r.scope)==='sets';
  const defect=(r,key,stock)=>Number(heldIn(r,stock)?r['in_sets_'+key]:r[key])||0;
  function decodeRecords(data) {
    return data.rows.map(packed=>{
      const r={quantity:0,missing:0,damaged:0,in_sets:0,condition:[''],status:[''],storage:['null'],place:['null'],flags:[],lot:['null'],ids:[],lot_links:[],selected:false};
      Object.entries(packed).forEach(([i,value])=>r[data.fields[i]]=value);
      r.name=r.name||'';r.colour=r.colour||'';r.stock=[...(r.quantity?['loose']:[]),...(r.in_sets?['sets']:[])];return r;
    });
  }
  // One row builder for every Collection kind, including wishes. Record values
  // are always text or DOM properties; no HTML parsing is involved.
  function buildRow(r, config, selecting, changed) {
    if(config.bpSets==='true'&&r.entity!=='wish')return buildSetTile(r,config,selecting,changed);
    const el=(tag,cls,text)=>{const n=document.createElement(tag);if(cls)n.className=cls;if(text!==undefined)n.textContent=String(text);return n;};
    const name=r.type==='P'?window.BrickFormatting.partName(r.name):r.name;
    const label=numberLabel(r),displayName=name||label||'Unidentified item';
    const row=el('article','bc-card');row.dataset.bcRow='';row.tabIndex=0;
    if(config.editable==='true' && r.ids.length && r.scope!=='sets'){   // under In sets a row shows the pieces inside set copies: its ids are the loose stock, so no selection (#20 review)
      const label=el('label','bc-selection'),check=el('input');label.hidden=!selecting;check.type='checkbox';check.dataset.bcSelected='';check.checked=r.selected;
      check.setAttribute('aria-label','Select '+displayName);check.addEventListener('change',()=>{r.selected=check.checked;changed();});label.append(check,el('span','','Select'));row.append(label);
    }
    const picture=el('div','bc-picture');picture.dataset.itemNo=r.number;
    if(r.image){const button=el('button'),img=el('img');button.type='button';button.dataset.bwLightbox=config.imageBase.replace(/0$/,r.image);button.dataset.caption=displayName+(r.colour?' · '+r.colour:'');button.setAttribute('aria-label','View '+displayName);const full=button.dataset.bwLightbox;img.src=full+'?w=320';img.srcset=full+'?w=320 320w, '+full+'?w=640 640w';img.sizes='160px';img.dataset.full=full;img.alt=button.dataset.caption;img.loading='lazy';button.append(img);picture.append(button);button.addEventListener('click',()=>openPicture(button));}
    else picture.append(...(label?[el('span','mono',label)]:[]),el('span','','No image'));
    // Gear, Books and Catalogs: a card without a picture shows the number once, in the tile (#153). The list view's 56 px tile clips a long
    // number, so the name line keeps a copy that only the list view shows (bc-tile-dupe, bw-collection.css).
    const numberInTile=!r.image&&'GBC'.includes(r.type);
    row.append(picture);
    const link=el('a'),identity=el('div','bc-identity');link.dataset.bcItemLink='';
    link.href=r.entity==='wish'?config.wishBase.replace(/0$/,r.ids[0]):config.itemBase.replace(/0$/,r.item_id)+(r.type==='P'&&r.color_id!=null?'?colour='+encodeURIComponent(r.color_id):'');
    if(r.type==='P'){const top=el('span','bc-identity-top'),colour=el('span','bc-colour',r.colour||'Unknown colour');if(/^[0-9a-f]{6}$/i.test(r.rgb||'')){colour.style.background='#'+r.rgb;colour.style.color=r.ink;}top.append(colour,...(label?[el('span','mono',label)]:[]));identity.append(top);}
    else if(label)identity.append(el('span',numberInTile?'mono bc-tile-dupe':'mono',label));
    if(r.name)identity.append(el('strong','',nowrapTail(name)));
    // Sets name the theme and sub-theme before the year ("Castle / Lion Knights · 1984").
    const secondary=[[r.theme||r.category,r.type==='S'&&r.entity!=='wish'?r.subtheme:''].filter(Boolean).join(' / '),r.year].filter(Boolean).join(' · ');
    if(secondary)identity.append(el('span','secondary',secondary));
    if(r.unresolved)identity.append(el('span','status',r.number?'To check':'Unidentified'));
    // #551 (frames 78, 79): where the row came from, one chip per origin; the pieces inside sets have none of their own.
    if(config.bList!==undefined&&r.scope!=='sets'){const words=JSON.parse(config.sourceWords||'{}');(r.via||[]).forEach(v=>identity.append(el('span','bc-source-chip',words[v]||v)));}
    link.append(identity);row.append(link);
    if(r.unresolved){const unresolved=el('a','','Unresolved items');unresolved.href=config.unresolvedUrl;row.append(unresolved);}
    if(r.entity==='wish'){const max=el('div','bc-wish-max');max.append(el('span','bc-wish-max-label','Your max price'),(r.max_price?el('strong','mono',r.max_price):el('span','bc-wish-max-none','No max set')));row.append(max);}
    const foot=el('div','bc-card-foot');
    if(r.entity==='wish'){
      foot.append(el('span','mono',r.defects||r.quantity+' wanted'));
    }else if(config.type==='S'){
      // Kit 1c: status pill left and price right on one line; the gap count and the price date below; tags last.
      const main=el('div','bc-foot-main'),pills=el('div','bc-foot-pills'),sub=el('div','bc-foot-sub');
      // #258: the payload sends completeness as words (core.list_records), not the old letters.
      [...new Set(r.status)].forEach(value=>{const states={complete:['complete','Complete'],incomplete:['incomplete','Incomplete'],sealed:['sealed','Sealed']},state=states[value]||['unknown','Not checked'];pills.append(el('span','bc-status '+state[0],state[1]));});
      main.append(pills);
      if(r.price){main.append(el('span','bc-card-money mono',r.price[4]));}else main.append(el('span','secondary','no sales'));
      const left=[r.quantity>1?r.quantity+' copies':'',r.defects].filter(Boolean).join(' · ');
      sub.append(el('span','mono bc-foot-gaps',left));
      if(r.price)sub.append(el('span','mono bc-age',r.price[5]+(r.price[3]?' · stale':'')));
      foot.append(main);if(left||r.price)foot.append(sub);
      if((r.tags||[]).length){const tags=el('div','bc-tags');r.tags.forEach(t=>tags.append(el('span','bc-tag',t)));foot.append(tags);}
    }else {
      const stock=el('span','bc-stock-count mono',r.scope==='sets'?r.in_sets+' in sets'+(r.quantity?' · '+r.quantity+' loose':''):r.quantity+' loose'+(r.in_sets?' · '+r.in_sets+' in sets':''));foot.append(stock);
      if(config.type==='I')foot.append(el('span','bc-pdf',r.pdf_available?'PDF available':'No PDF'));
    }
    {const shown=heldIn(r)?r.in_sets_defects:r.defects;if(r.entity!=='wish' && config.type!=='S' && shown)foot.append(el('span','mono',shown));}
    if(config.type!=='S'){
      if(r.price){const price=el('span','bc-card-money mono');price.append(el('span','',r.price[4]),el('span','bc-age',r.price[5]+(r.price[3]?' · stale':'')));foot.append(price);}else foot.append(el('span','secondary','no sales'));
    }
    r.lot_links.forEach(([id,name])=>{const lot=el('a','','Lot · '+name);lot.href=config.lotBase.replace('LOT',encodeURIComponent(id));foot.append(lot);});
    row.append(foot);
    if(config.type==='P' && r.entity!=='wish')row.append(...partCells(r,config,el));
    return row;
  }

  // The Sets page's tile (R3-01, #494): the picture, the set number in mono with the used price, the name, one bar per copy to scale (violet found, hatched
  // missing, dashed still to check), the Sealed tag for a sealed copy. The classes are the frames' (b-prime.css); the numbers are the row's `bars`
  // (core/collection.py `_copy_bars`): [found, missing, total, figures missing, damaged, checked by] per copy, in the order of the row's statuses.
  const fmt=n=>Number(n).toLocaleString('en-US');
  function copyLine(bar,index,several){
    const [found,missing,total,figures,damaged]=bar,prefix=several?'#'+(index+1)+' ':'',lost=Number(missing)||0,fig=Number(figures)||0,dmg=Number(damaged)||0;
    const parts=[lost?lost+' missing':'',fig?fig+(fig===1?' figure':' figures')+' missing':'',dmg?dmg+' damaged':''].filter(Boolean);   // damaged pieces are a gap by the completeness rule
    if(!parts.length)parts.push(found>=total?'complete':(total-found)+' to check');
    return prefix+fmt(found)+'/'+fmt(total)+' · '+parts.join(' · ');
  }
  function copyBar(bar,index,several){
    const el=(tag,cls,text)=>{const n=document.createElement(tag);if(cls)n.className=cls;if(text!==undefined)n.textContent=String(text);return n;};
    const [found,missing,total,figures]=bar,bartxt=el('div','bartxt'),track=el('div','bar');
    const never=!found&&!missing&&!figures&&!bar[4],pct=n=>(Math.round(n/total*10000)/100).toFixed(2)+'%';
    if(never){
      track.append(el('i','c'));
      const chip=el('span','xchip'),box=document.createElement('i'),svg=document.createElementNS('http://www.w3.org/2000/svg','svg'),path=document.createElementNS('http://www.w3.org/2000/svg','path');
      svg.setAttribute('width','10');svg.setAttribute('height','10');svg.setAttribute('viewBox','0 0 10 10');svg.setAttribute('aria-hidden','true');
      path.setAttribute('d','M2.6 2.6l4.8 4.8M7.4 2.6l-4.8 4.8');path.setAttribute('stroke','#fff');path.setAttribute('stroke-width','1.9');path.setAttribute('stroke-linecap','round');
      svg.append(path);box.append(svg);chip.append(box,'Not checked');
      bartxt.append(chip,el('span','',(several?'#'+(index+1)+' ':'')+'0/'+fmt(total)));
    }else{
      const found_=el('i','f'),lost=el('i','m'),rest=total-found-missing;
      found_.style.width=pct(found);track.append(found_);
      if(missing){lost.style.width=pct(missing);track.append(lost);}
      if(rest>0){const todo=el('i','c');if(found||missing)todo.classList.add('after');track.append(todo);}
      const line=copyLine(bar,index,several),cut=line.indexOf(' · ');
      if(line.length>21&&cut>0){bartxt.append(el('span','',line.slice(0,cut)),el('span','sep',' · '),el('span','',line.slice(cut+3)));bartxt.classList.add('two');}   // a phone tile holds 21 characters in mono 12 px: a longer line wraps at its dot, nothing is cut (design, 2026-11-20)
      else bartxt.textContent=line;
      bartxt.title=line;
    }
    // #489: a copy a Rebrickable pull checked says so under the bar (frame 48); a copy Brick Work checked itself carries no such line.
    return bar[5]==='rebrickable'?[track,bartxt,el('div','bar-src mono','Checked on Rebrickable')]:[track,bartxt];
  }
  function buildSetTile(r, config, selecting, changed) {
    const el=(tag,cls,text)=>{const n=document.createElement(tag);if(cls)n.className=cls;if(text!==undefined)n.textContent=String(text);return n;};
    const label=numberLabel(r),displayName=r.name||label||'Unidentified item';
    const tile=el('article','stile bp-tile');tile.dataset.bcRow='';tile.tabIndex=0;
    if(config.editable==='true' && r.ids.length){
      const pick=el('label','bc-selection bp-select'),check=el('input');pick.hidden=!selecting;check.type='checkbox';check.dataset.bcSelected='';check.checked=r.selected;
      check.setAttribute('aria-label','Select '+displayName);check.addEventListener('change',()=>{r.selected=check.checked;changed();});pick.append(check,el('span','bc-visually-hidden','Select'));tile.append(pick);
    }
    const picture=el('div','tile bp-pic');picture.dataset.itemNo=r.number;
    if(r.image){const button=el('button'),img=el('img');button.type='button';button.dataset.bwLightbox=config.imageBase.replace(/0$/,r.image);button.dataset.caption=displayName;button.setAttribute('aria-label','View '+displayName);const full=button.dataset.bwLightbox;img.src=full+'?w=320';img.srcset=full+'?w=320 320w, '+full+'?w=640 640w';img.sizes='206px';img.dataset.full=full;img.alt=displayName;img.loading='lazy';button.append(img);picture.append(button);button.addEventListener('click',()=>openPicture(button));}
    else picture.append(el('span','bp-alt','Set picture'));
    tile.append(picture);
    const link=el('a','bp-link');link.dataset.bcItemLink='';link.href=config.itemBase.replace(/0$/,r.item_id);
    const num=el('div','num');num.append(el('span','',label||'—'),el('span','bp-price',r.price?r.price[4]:'no sales'));
    const theme=[r.theme||r.category,r.subtheme].filter(Boolean).join(' / '),copies=r.quantity>1?r.quantity+' copies':'';
    link.append(num,el('div','nm',r.name||''),el('div','meta',[theme,r.year,copies].filter(Boolean).join(' · ')));
    tile.append(link);
    if(r.unresolved)tile.append(el('span','tag dash bp-self',r.number?'To check':'Unidentified'));
    const several=(r.status||[]).length>1;
    (r.status||['']).forEach((status,i)=>{
      if(status==='sealed'){tile.append(el('span','tag bp-self','Sealed'));return;}
      let bar=(r.bars||[])[i];
      if(bar&&status==='complete'&&bar[0]+bar[1]<bar[2])bar=[bar[2]-bar[1],bar[1],bar[2],bar[3],0,bar[5]];   // marked Complete by hand: the whole list counts as found
      if(!bar||!bar[2]){tile.append(el('span','tag dash bp-self',(several?'#'+(i+1)+' ':'')+'No part list'));return;}
      tile.append(...copyBar(bar,i,several));
    });
    if((r.tags||[]).length){const tags=el('div','bp-tags');r.tags.forEach(t=>tags.append(el('span','tag dash',t)));tile.append(tags);}
    return tile;
  }
  // Parts table (kit 7a): damaged, lot, used price and quantity as cells of the row grid.
  // The grid view hides them and shows the card foot instead; the table view does the reverse.
  function partCells(r,config,el) {
    // The header row is aria-hidden, so each cell names its own column for assistive technology.
    const hid=(cell,text)=>cell.append(el('span','bc-visually-hidden',text));
    const damaged=el('span','bc-cell bc-cell-damaged'),lot=el('span','bc-cell bc-cell-lot'),price=el('span','bc-cell bc-cell-price'),qty=el('span','bc-cell bc-cell-qty');
    const hurt=defect(r,'damaged'),lost=defect(r,'missing');
    hid(damaged,hurt>0||lost>0?'Damaged or missing ':'No damaged pieces');
    hid(lot,r.lot_links.length?'Lot ':'No lot');hid(price,'Used price ');hid(qty,'Quantity ');
    if(hurt>0)damaged.append(el('span','bc-status incomplete',hurt+' damaged'));
    if(lost>0)damaged.append(el('span','mono bc-cell-missing',lost+' missing'));
    if(r.lot_links.length)r.lot_links.forEach(([id,name])=>{const link=el('a','bc-lot-link',name);link.href=config.lotBase.replace('LOT',encodeURIComponent(id));lot.append(link);});
    else{const none=el('span','secondary','—');none.setAttribute('aria-hidden','true');lot.append(none);}
    if(r.price){price.append(el('span','bc-cell-money mono',r.price[4]),el('span','mono bc-age',r.price[5]+(r.price[3]?' · stale':'')));}else price.append(el('span','secondary','no sales'));
    const inSets=r.scope==='sets';
    qty.append(el('span','mono bc-cell-qty-main','×'+(inSets?r.in_sets:r.quantity)));
    if(inSets?r.quantity:r.in_sets)qty.append(el('span','mono bc-age',inSets?r.quantity+' loose':r.in_sets+' in sets'));
    return [damaged,lot,price,qty];
  }
  // Parts and Minifigures list what you own loose by default and the parts and figures inside set copies under In sets (#20). The headline follows the scope;
  // its loose total is the number the navigation rail shows. `records` are all rows, the scope picks the ones it counts.
  function scopeHeadline(kind, records, scope) {
    const inSets=scope==='sets',plural=(n,one,many)=>n+' '+(n===1?one:many);
    const rows=records.filter(r=>(r.stock||[]).includes(inSets?'sets':'loose'));
    const loose=records.reduce((n,r)=>n+Number(r.quantity||0),0),held=records.reduce((n,r)=>n+Number(r.in_sets||0),0),pieces=inSets?held:loose,other=inSets?loose:held;
    if(kind==='M')return {title:inSets?plural(pieces,'minifigure','minifigures')+' in sets':pieces+' loose '+(pieces===1?'minifigure':'minifigures'),
      sub:plural(rows.length,'different minifigure','different minifigures')+' · '+other+(inSets?' loose':' in sets')};
    const damaged=rows.filter(r=>defect(r,'damaged',scope)>0).length,lots=new Set(rows.flatMap(r=>(r.lot||[]).map(String).filter(x=>x!=='null').map(x=>x.toLowerCase()))).size;
    return {title:inSets?plural(pieces,'part','parts')+' in sets':damaged?damaged+' '+(damaged===1?'part has':'parts have')+' damaged pieces':'No parts have damaged pieces',
      sub:inSets?plural(rows.length,'entry','entries')+' · '+other+' loose':pieces+' loose '+(pieces===1?'part':'parts')+' · '+plural(rows.length,'entry','entries')+(lots?' in '+plural(lots,'lot','lots'):'')};
  }
  function priceBasis(rows) {
    const prices=rows.filter(r=>r.price).map(r=>r.price_basis||[]);
    if(!prices.length)return '';
    const bases=new Set(prices.map(p=>p.slice(0,2).join(':'))),sources=[...new Set(prices.map(p=>p[2]).filter(Boolean))];
    const names={bricklink:'BrickLink',brickset:'Brickset',rebrickable:'Rebrickable'};
    const labels={used:'used',new:'new'},guide={sold:'averages',stock:'listings'};
    const basis=bases.size===1&&labels[prices[0][0]]&&guide[prices[0][1]]?'prices are '+labels[prices[0][0]]+' '+guide[prices[0][1]]:'prices have mixed bases';
    return ' · '+basis+(sources.length===1?' from '+(names[sources[0]]||sources[0]):' from mixed sources');
  }
  function inventorySections(result) {
    const missing=result.filter(r=>Number(r.missing||0)+Number(r.damaged||0)+Number(r.parts_missing||0)>0);
    const missingSet=new Set(missing);
    return {missing,present:result.filter(r=>!missingSet.has(r))};
  }
  // Both Collection and Planning use the same per-viewer list state and switch.
  function listStateKey(index=0) {
    const params=new URLSearchParams(location.search);params.delete('inventory');
    const query=params.toString();
    return 'bw-collection-list:'+location.pathname+(query?'?'+query:'')+':'+index;
  }
  function viewSwitch(list,container,prefix,key,type) {
    const buttons=[...list.querySelectorAll('[data-'+prefix+'-view]')];
    // 49b: Instructions and Parts open as compact rows on a phone (kit 7a); the switch still offers the grid.
    if(['I','P'].includes(type)&&typeof matchMedia==='function'&&matchMedia('(max-width: 767px)').matches)container.dataset.view='list';
    try {const saved=JSON.parse(sessionStorage.getItem(key));if(['grid','list'].includes(saved?.view))container.dataset.view=saved.view;}catch(_){}
    const bp=!!container.closest?.('[data-bp-sets]');   // the Sets page's switch is drawn with a class (b-prime.css `.seg button.on`)
    const update=()=>buttons.forEach(b=>{const on=b.dataset[prefix+'View']===container.dataset.view;b.setAttribute('aria-pressed',String(on));if(bp)b.classList.toggle('on',on);});
    buttons.forEach(b=>b.addEventListener('click',()=>{
      container.dataset.view=b.dataset[prefix+'View'];update();
      let state={};try{state=JSON.parse(sessionStorage.getItem(key))||{};}catch(_){}
      sessionStorage.setItem(key,JSON.stringify({...state,view:container.dataset.view}));
    }));
    update();
  }
  /* Typing in the search box renders on a pause, not on every key. Without timers (the test harness) it runs at once. */
  function debounce(fn,ms){let timer;return (...args)=>{if(typeof setTimeout!=='function'){fn(...args);return;}clearTimeout(timer);timer=setTimeout(()=>fn(...args),ms);};}
  window.BrickCollection={debounce,groupValue,singularNoun,listStateKey,viewSwitch,nowrapTail,filterRows,selectedInstances,decodeRecords,buildRow,priceBasis,inventorySections,scopeHeadline,missingSummary,resultNoun,listNoun,resultCount};
  const root=document.querySelector('#bw-collection'); if (!root) return;
  const message=root.querySelector('[data-bc-message]'),undo=root.querySelector('[data-bc-undo]');
  const receiptKey='bw-collection-receipt';let receipt;
  const pathOf=u=>{const parts=String(u||'').replace(/^[a-z][a-z0-9+.-]*:\/\/[^/]*/i,'').split('#')[0].split('?');const q=new URLSearchParams(parts[1]||'');const id=['copy','stock','colour'].filter(k=>q.get(k)).map(k=>k+'='+q.get(k)).join('&');return id?parts[0]+'?'+id:parts[0];};   // the screen of a receipt: the path plus the query parts that choose which copy, stock row or colour the page shows
  try {receipt=JSON.parse(sessionStorage.getItem(receiptKey));}catch(_){}
  // #236: a receipt belongs to the screen it was made for (the page a save leads to); elsewhere it is dropped, not shown.
  if(receipt&&receipt.screen!==pathOf(location.pathname+(location.search||''))){receipt=null;try{sessionStorage.removeItem(receiptKey);}catch(_){}}
  function stamp(target) {if(!receipt)return;receipt.screen=pathOf(target);sessionStorage.setItem(receiptKey,JSON.stringify(receipt));}
  function showReceipt(data) {receipt={...data,screen:pathOf(data.url||location.pathname+(location.search||''))};sessionStorage.setItem(receiptKey,JSON.stringify(receipt));if(message)message.textContent=data.message;if(undo)undo.hidden=false;}
  if(receipt) {if(message)message.textContent=receipt.message;if(undo)undo.hidden=false;}
  async function send(action,data,multipart=false,quiet=false) {
    if(multipart)data.append('csrf_token',root.dataset.csrf);else data.csrf_token=root.dataset.csrf;
    const response=await fetch(root.dataset.saveUrl.replace('ACTION',action),{method:'POST',headers:multipart?{}:{'Content-Type':'application/json'},body:multipart?data:JSON.stringify(data)});
    const result=await response.json();if(!response.ok)throw new Error(result.message||'Not saved · try again');
    if(action!=='undo'&&!quiet)showReceipt(result);return result;
  }
  // Undo takes back the last thing the Save did first: the photo, then removals and captions, then the details.
  undo?.addEventListener('click',async()=>{undo.disabled=true;try {for(const id of [...(receipt.also||[])].reverse().concat(receipt.event_id))await send('undo',{event_id:id});sessionStorage.removeItem(receiptKey);message.textContent='Undone';location.reload();}catch(e){message.textContent=e.message;}finally{undo.disabled=false;}});
  root.querySelectorAll('[data-bw-open]').forEach(b=>b.addEventListener('click',()=>{const dialog=document.getElementById(b.dataset.bwOpen);dialog?.showModal();if(/^[a-z_]+$/.test(b.dataset.bcFocus||'')){const field=dialog?.querySelector(`[name=${b.dataset.bcFocus}]`);const folded=field?.closest?.('details');if(folded)folded.open=true;field?.focus();}}));
  root.querySelectorAll('[data-bw-close]').forEach(b=>b.addEventListener('click',()=>b.closest('dialog')?.close()));
  let carried=[];                           // events of Saves whose photo is still to be added, oldest first: a Save sent again must not make Undo forget them
  let photoRetry=null;                      // the details are saved and only the photo failed: Save again sends the photo alone, to the row the details ended in
  root.querySelectorAll('form[data-bc-action]').forEach(form=>form.addEventListener('submit',async e=>{
    e.preventDefault();const group=form.closest('[data-bc-save-group]')||form;
    if(group.dataset.bcSaving==='true')return;
    group.dataset.bcSaving='true';
    const outside=form.id?[...document.querySelectorAll(`button[form="${form.id}"]`)]:[],buttons=[...new Set([...group.querySelectorAll('button'),...outside])].map(button=>({button,disabled:button.disabled})),status=form.querySelector('[data-bc-form-message]')||(form.id?document.querySelector(`[data-bc-for="${form.id}"]`):null);buttons.forEach(({button})=>button.disabled=true);
    if(status)status.textContent='Saving';
    const banner=root.querySelector('[data-bc-photo-warning]');if(banner)banner.hidden=true;
    const photoRows=form.id?[...root.querySelectorAll('[data-bc-photo-row]')].filter(r=>r.dataset.bcForm===form.id):[];      // the saved photos of this sheet: their captions and removals go with its Save
    try {
      const action=form.dataset.bcAction,identity=JSON.parse(form.dataset.identity||'{}');
      let data,newPhoto=null,newPhotoCaption='';
      if(action==='photo') {data=new FormData(form);Object.entries(identity).forEach(([k,v])=>data.append(k,v));}
      else {
        const values=Object.fromEntries(new FormData(form));
        newPhoto=values.new_photo;newPhotoCaption=values.new_photo_caption||'';delete values.new_photo;delete values.new_photo_caption;        // the photo goes up after the save, from the same button
        if(form.dataset.bcFlags!==undefined)values.flags=[...form.querySelectorAll('[name=flags]:checked,input[type=hidden][name=flags]')].map(c=>c.value);      // switches and the multi-select fields all post the flag ids that stay on; a wish's Status and Owners ride along hidden (#670)
        data=action==='save'?{...identity,values}:{...identity,...values};
        if(action==='save'&&photoRows.length) {
          const captions={},removals=[];
          photoRows.forEach(r=>{
            const input=r.querySelector('[data-bc-photo-caption]'),remove=r.querySelector('[data-bc-photo-remove]');
            if(remove&&remove.getAttribute('aria-pressed')==='true')removals.push(r.dataset.photoId);
            else if(input&&input.value.trim()!==(input.dataset.initial||'').trim())captions[r.dataset.photoId]=input.value;
          });
          if(Object.keys(captions).length)data.photo_captions=captions;
          if(removals.length)data.remove_photos=removals;
        }
      }
      if(action==='lot'){
        const chosen=mainSelection();
        if(chosen.entity!=='stock'||!chosen.ids.length)throw new Error('Select loose stock for this lot');data.ids=chosen.ids;
      }
      const retry=action==='save'&&photoRetry&&photoRetry.result.merged_ids&&newPhoto&&newPhoto.size?photoRetry:null;      // only a row that merged away cannot be saved again
      const result=retry?retry.result:await send(action,data,action==='photo');
      if(action==='save'&&!retry) {        // the receipt undoes every attempt: event_id is the first save, `also` holds the rest oldest first, and Undo runs them last first
        const chain=[...carried,result.event_id,...(result.also||[])];carried=chain;
        receipt={...receipt,event_id:chain[0],also:chain.slice(1)};sessionStorage.setItem(receiptKey,JSON.stringify(receipt));
      }
      if(action==='save'&&newPhoto&&newPhoto.size){
        const upload=new FormData();upload.append('entity',identity.entity);upload.append('identifier',retry?retry.id:(result.merged_ids||identity.ids)[0]);upload.append('photo',newPhoto);upload.append('caption',newPhotoCaption);
        try {const added=await send('photo',upload,true,true);photoRetry=null;receipt={...receipt,also:[...((receipt&&receipt.also)||[]),added.event_id]};sessionStorage.setItem(receiptKey,JSON.stringify(receipt));}      // quiet: the page keeps the details' save as its receipt, and Undo takes the photo back with it
        catch(error){
          photoRetry={id:upload.get('identifier'),result};
          photoRows.forEach(r=>{const input=r.querySelector('[data-bc-photo-caption]'),remove=r.querySelector('[data-bc-photo-remove]');   // those edits are saved: a second Save must not send them again
            if(remove&&remove.getAttribute('aria-pressed')==='true')r.remove();else if(input)input.dataset.initial=input.value;});
          photoSummary();
          const text=banner?banner.querySelector('[data-bc-photo-warning-text]'):null;
          if(banner&&text){banner.hidden=false;text.textContent=error.message+'. Press Save to try again: it saves the details again and sends the photo.';if(status)status.textContent='';}
          else if(status)status.textContent='Details saved, but the photo was not added: '+error.message+' · Press Save to try the photo again';
          return;
        }
      }
      carried=[];
      if(action==='archive'){stamp(root.dataset.backUrl||location.pathname);location.href=root.dataset.backUrl||location.pathname;}
      else if(result.url)location.href=result.url;
      else location.reload();
    }catch(error){if(status)status.textContent=error.message+' · Try again';}
    finally{buttons.forEach(({button,disabled})=>button.disabled=disabled);delete group.dataset.bcSaving;}
  }));
  // The Photos section of the edit sheet: the chosen photo is a row with a preview until Save sends it, a saved photo's x marks it for removal.
  function photoSummary() {
    const count=root.querySelector('[data-bc-photo-count]'),pending=root.querySelector('[data-bc-photo-pending]'),empty=root.querySelector('[data-bc-photo-empty]');
    const saved=root.querySelectorAll('[data-bc-photo-row]').length,added=pending&&!pending.hidden?1:0;
    if(count)count.textContent=[saved?saved+' saved':'',added?added+' new':''].filter(Boolean).join(' · ')||'none yet';
    if(empty)empty.hidden=added>0;
  }
  root.querySelectorAll('[data-bc-photo-file]').forEach(input=>{
    const pending=root.querySelector('[data-bc-photo-pending]'),preview=pending?pending.querySelector('[data-bc-photo-preview]'):null,cancel=pending?pending.querySelector('[data-bc-photo-cancel]'):null,caption=pending?pending.querySelector('[name=new_photo_caption]'):null;
    let objectUrl=null;
    const release=()=>{if(objectUrl&&typeof URL!=='undefined'&&URL.revokeObjectURL)URL.revokeObjectURL(objectUrl);objectUrl=null;};
    const show=file=>{
      if(!pending)return;
      release();
      if(file) {if(typeof URL!=='undefined'&&URL.createObjectURL){objectUrl=URL.createObjectURL(file);if(preview)preview.src=objectUrl;}}
      else {if(preview)preview.removeAttribute('src');if(caption)caption.value='';}
      pending.hidden=!file;photoSummary();
    };
    input.addEventListener('change',()=>show(input.files&&input.files[0]?input.files[0]:null));
    if(cancel)cancel.addEventListener('click',()=>{input.value='';show(null);});
  });
  root.querySelectorAll('[data-bc-photo-remove]').forEach(button=>button.addEventListener('click',()=>{
    const marked=button.getAttribute('aria-pressed')!=='true',row=button.closest('[data-bc-photo-row]');
    button.setAttribute('aria-pressed',marked?'true':'false');
    if(!row)return;
    row.dataset.removed=marked?'true':'false';
    const input=row.querySelector('[data-bc-photo-caption]'),meta=row.querySelector('[data-bc-photo-meta]');
    if(input)input.disabled=marked;
    if(meta)meta.textContent=marked?'Removed when you press Save':(meta.dataset.text||'');
  }));
  // A multi-select field of flags shows the chosen names in its closed state.
  root.querySelectorAll('[data-bc-multi]').forEach(box=>{
    const out=box.querySelector('[data-bc-multi-value]');
    box.addEventListener('change',()=>{
      const names=[...box.querySelectorAll('input[type=checkbox]')].filter(c=>c.checked).map(c=>c.dataset.name);
      if(!out)return;
      out.textContent=names.length?names.join(', '):'None';
      if(names.length)delete out.dataset.empty;else out.dataset.empty='';
    });
  });
  const lists=[];let mainSelection=()=>({ids:[]});
  root.querySelectorAll('[data-bc-list]').forEach((list,index)=>{
    const container=list.querySelector('[data-bc-rows]'); if(!container)return;
    const source=list.querySelector('[data-bc-records]'),virtual=!!source;
    let nodes=[...container.querySelectorAll('[data-bc-row]')];
    const records=virtual?decodeRecords(JSON.parse(source.textContent)):nodes.map((node,i)=>({...JSON.parse(node.dataset.record||'{}'),node,index:i}));
    const search=list.querySelector('[data-bc-search]'),sort=list.querySelector('[data-bc-sort]'),direction=list.querySelector('[data-bc-direction]'),group=list.querySelector('[data-bc-group]');
    const filterControls=[...list.querySelectorAll('[data-bc-filter]')],chips=list.querySelector('[data-bc-chips]'),count=list.querySelector('[data-bc-count]'),panel=list.querySelector('[data-bc-panel]');
    let inventory='parts',shownScope;
    // A filter with a default (the Stock scope of Parts and Minifigures, #20) returns to it instead of to Any.
    const preset=c=>c.dataset.bcDefault||'';
    const scopeControl=filterControls.find(c=>c.dataset.bcFilter==='stock'&&c.dataset.bcDefault);
    const picks=[...list.querySelectorAll('[data-bc-pick]')],groupPicks=[...list.querySelectorAll('[data-bc-group-pick]')];
    // Quick chips (Parts, kit 7a) set one of a small family of filters; All clears the family.
    const quick=[...list.querySelectorAll('[data-bc-quick]')],quickKeys=[...new Set(quick.map(b=>b.dataset.bcQuick.split(':')[0]).filter(Boolean))];
    const srcButtons=[...list.querySelectorAll('[data-bc-src]')],srcPair=b=>{const t=b.dataset.bcSrc,i=t.indexOf(':');return [t.slice(0,i),t.slice(i+1)];};
    const tabs=[...list.querySelectorAll('[data-bc-tab]')],statusButtons=[...list.querySelectorAll('[data-bc-status]')];
    const more=list.querySelector('[data-bc-more]'),loaded=list.querySelector('[data-bc-loaded]');let limit=60,selecting=false,missingExpanded=false;
    /* Paging (4.8d): optional, switched on per list by data-bc-page-size. The main list saves its page with its scroll offset so Back returns to the same page. */
    const pageSize=Math.max(0,Math.floor(Number(list.dataset?.bcPageSize))||0);let page=1;const pager=pageSize?buildPager():null;
    function buildPager(target=container, section=null){
      const nav=document.createElement('nav'),prev=document.createElement('button'),next=document.createElement('button'),numbers=document.createElement('div'),text=document.createElement('p');
      nav.className='bc-pager';nav.hidden=true;nav.setAttribute('aria-label','Pages');nav.dataset.bcPager='';
      const goTo=n=>{if(section)section.page=n;else page=n;render();const first=container.querySelector('[data-bc-row]');if(first&&typeof first.scrollIntoView==='function'&&list.hasAttribute('data-bc-main'))first.scrollIntoView({block:'start'});};
      // Page buttons are rebuilt on every render: focus returns to the current page when the activated button is gone or disabled.
      const focusCurrent=()=>[...numbers.children].find(c=>c.getAttribute&&c.getAttribute('aria-current')==='page')?.focus({preventScroll:true});
      for(const [b,label,delta] of [[prev,'Previous',-1],[next,'Next',1]]){b.type='button';b.className='bc-page-step bc-page-'+(delta<0?'prev':'next');b.textContent=label;b.setAttribute('aria-label',label+' page');b.addEventListener('click',()=>{goTo((section?section.page:page)+delta);if(b.disabled)focusCurrent();});}
      numbers.className='bc-page-numbers';
      text.className='mono';text.dataset.bcPageText='';
      nav.append(prev,numbers,next,text);target.after(nav);return {nav,prev,next,numbers,text,goTo,focusCurrent};
    }
    // The visible range, for example "16 to 30 of 412".
    const rangeText=total=>total?((page-1)*pageSize+1)+' to '+Math.min(total,page*pageSize)+' of '+total:'';
    // First, last and current page with their neighbours; a single skipped page shows as its number, longer gaps as an ellipsis.
    function pageItems(pages,current=page){
      const page=current;
      const wanted=[...new Set([1,page-1,page,page+1,pages].filter(n=>n>=1&&n<=pages))].sort((a,b)=>a-b),items=[];
      wanted.forEach((n,i)=>{if(i){const gap=n-wanted[i-1];if(gap===2)items.push(n-1);else if(gap>2)items.push('…');}items.push(n);});
      return items;
    }
    const visibleSlice=rows=>pageSize?rows.slice((page-1)*pageSize,page*pageSize):(!search&&!sort?rows:rows.slice(0,limit));
    function updatePager(total,controls=pager,current=page,size=pageSize,section=false){
      const pager=controls,page=current,pageSize=size;
      if(!pager)return;const pages=Math.max(1,Math.ceil(total/pageSize));
      pager.nav.hidden=section?total===0:pages<2;pager.prev.hidden=pager.next.hidden=pager.numbers.hidden=section&&pages<2;pager.text.textContent=section?(total?((page-1)*pageSize+1)+'–'+Math.min(total,page*pageSize)+' of '+total:''):rangeText(total);pager.prev.disabled=page<=1;pager.next.disabled=page>=pages;
      pager.numbers.replaceChildren(...pageItems(pages,page).map(n=>{
        if(n==='…'){const gap=document.createElement('span');gap.className='bc-page-gap';gap.textContent='…';gap.setAttribute('aria-hidden','true');return gap;}
        const b=document.createElement('button');b.type='button';b.textContent=String(n);b.setAttribute('aria-label','Page '+n);
        b.className='bc-page-number'+(n!==1&&n!==pages&&n!==page?' bc-page-neighbour':'');
        if(n===page){b.setAttribute('aria-current','page');b.disabled=false;}
        b.addEventListener('click',()=>{pager.goTo(n);pager.focusCurrent();});return b;
      }));
      if(more)more.hidden=true;if(loaded)loaded.textContent='';
    }
    // Section state belongs to this item and selected copy, independent of list filters.
    const sectionKey='bw-part-sections:'+location.pathname+':'+(list.dataset.bcSectionCopy||new URLSearchParams(location.search).get('copy'));
    let sectionMemory={};
    try {const stored=JSON.parse(localStorage.getItem(sectionKey));if(stored&&typeof stored==='object')sectionMemory=stored;}catch(_){}
    const partSections=[...list.querySelectorAll('[data-bc-part-section]')].map(element=>{
      const name=element.dataset.bcPartSection,button=element.querySelector('[data-bc-section-toggle]'),body=element.querySelector('[data-bc-section-body]'),rows=element.querySelector('[data-bc-section-rows]');
      const section={element,name,button,body,rows,page:1};
      section.pager=buildPager(rows,section);
      section.setOpen=(open,remember=false)=>{
        body.hidden=!open;button.setAttribute('aria-expanded',String(open));
        if(remember){sectionMemory[name]=open;try{localStorage.setItem(sectionKey,JSON.stringify(sectionMemory));}catch(_){}}
      };
      section.setOpen(typeof sectionMemory[name]==='boolean'?sectionMemory[name]:element.dataset.bcDefaultOpen==='true');
      button.addEventListener('click',()=>section.setOpen(body.hidden,true));return section;
    });
    const figureRows=list.querySelector('[data-bc-figure-rows]');
    const figureBatch=figureRows?{page:1}:null;
    if(figureBatch)figureBatch.pager=buildPager(figureRows,figureBatch);
    const groupedInventory=partSections.length>0||!!figureBatch;
    if(partSections.length){
      const actions=list.querySelector('[data-bc-section-actions]');if(actions)actions.hidden=false;
      list.querySelectorAll('[data-bc-sections]').forEach(button=>button.addEventListener('click',event=>{
        event.preventDefault();partSections.forEach(section=>section.setOpen(button.dataset.bcSections==='expand',true));
      }));
    }
    const key=listStateKey(index);let saved;
    try {saved=JSON.parse(sessionStorage.getItem(key));}catch(_){}
    filterControls.filter(c=>c.hasAttribute('data-bc-options')).forEach(c=>{
      [...new Set(records.map(r=>String(r[c.dataset.bcFilter]||'')).filter(Boolean))].sort().forEach(value=>{const o=document.createElement('option');o.value=value;o.textContent=value;c.append(o);});
    });
    if(!saved && list.querySelector('[data-bc-inventory-rows]') && sort)sort.value='missing';
    if(saved) {if(search)search.value=saved.query||'';if(sort)sort.value=saved.sort||'number';if(direction)direction.value=saved.direction||'asc';if(group)group.value=saved.group||'';filterControls.forEach(c=>c.value=saved.filters?.[c.dataset.bcFilter]||preset(c));limit=saved.limit||60;if(saved.view)container.dataset.view=saved.view;}
    if(pageSize && saved?.page && list.hasAttribute('data-bc-main'))page=Math.max(1,Math.floor(Number(saved.page))||1);
    if(!saved && list.dataset?.bcDefaultGroup && group)group.value=list.dataset.bcDefaultGroup;
    // A grouping the list does not offer (Lot on Sets and the Wishlist) falls back to None.
    if(group && group.value && group.options?.length && ![...group.options].some(o=>o.value===group.value))group.value='';
    const params=new URLSearchParams(location.search);
    if(tabs.length){const requested=params.get('inventory')||saved?.filters?.inventory;if(tabs.some(t=>t.dataset.bcTab===requested))inventory=requested;}
    filterControls.forEach(c=>{if(params.has(c.dataset.bcFilter)){c.value=params.get(c.dataset.bcFilter);if(!c.value)c.value=preset(c);}});
    // #551: a Source filter that no chip offers any more (a set archived, a run undone, a stale link) is dropped, not kept invisible; a select drops it by itself.
    filterControls.forEach(c=>{if(c.type==='hidden'&&c.value&&!srcButtons.some(b=>{const [k,v]=srcPair(b);return k===c.dataset.bcFilter&&v===c.value;}))c.value='';});
    function filters(){return {...Object.fromEntries(filterControls.map(c=>[c.dataset.bcFilter,c.value])),...(tabs.length && inventory!=='extras'?{inventory}:{})};}
    function selection(){if(virtual)return selectedInstances(records.map(r=>({checked:r.selected,entity:r.entity,ids:r.ids})));return selectedInstances([...list.querySelectorAll('[data-bc-selected]')].map(c=>({checked:c.checked,hidden:c.closest('[data-bc-row]').hidden,entity:c.dataset.entity,ids:JSON.parse(c.value)})));}
    if(virtual)mainSelection=selection;
    function selectionCount(){const n=list.querySelector('[data-bc-selected-count]');if(n){try{n.textContent=selection().ids.length+' selected';}catch(e){n.textContent=e.message;}}}
    function saveState(){
      sessionStorage.setItem(key,JSON.stringify({query:search?.value,sort:sort?.value,direction:direction?.value,group:group?.value,filters:{...filters(),...(tabs.length?{inventory}:{})},limit,view:container.dataset.view,page:pageSize&&list.hasAttribute('data-bc-main')?page:undefined,scroll:window.scrollY}));
    }
    const canFilter=()=>inventory!=='extras';
    // The Sets page (R3-01, #494): the sets sit under their storage's label tape in the storage index's order, under a plain label for another grouping, or in
    // one grid with no storage set at all. The index, the phone's "Storage: all" row and the status tabs drive the same filters as the sheet.
    const bpSets=root.dataset.bpSets==='true';
    const bpStorages=bpSets?JSON.parse(list.querySelector('[data-bp-storages]')?.textContent||'[]'):[];
    const bpRank=bpStorages.length?new Map(bpStorages.map((s,i)=>[s.id,i])):null,bpById=new Map(bpStorages.map(s=>[s.id,s]));
    const bpStorageFilter=filterControls.find(c=>c.dataset.bcFilter==='storage');
    function bpGroups(result){
      const made=new Map(),counts=new Map(),byStorage=group?.value==='storage'&&bpStorages.length>0;
      const flat=group?.value==='storage'&&!bpStorages.length,keyOf=r=>group?.value&&!flat?(groupValue(r,group.value)||'Not recorded'):'';   // storage grouping with no storage set at all is one flat grid, no label
      if(group?.value&&!flat)result.forEach(r=>counts.set(keyOf(r),(counts.get(keyOf(r))||0)+1));
      container.dataset.bpFlow=byStorage?'drawers':group?.value&&!flat?'sections':'flat';
      return r=>{
        const key=keyOf(r);
        if(!made.has(key)){
          const section=document.createElement('section'),tiles=document.createElement('div'),n=counts.get(key)||0,count=n+' '+(n===1?'set':'sets');
          section.className='bp-group group';section.dataset.bpGroup=key;tiles.className='bp-tiles';
          if(byStorage&&bpById.has(key)){
            const storage=bpById.get(key),tape=document.createElement('div'),code=document.createElement('span'),name=document.createElement('span'),total=document.createElement('span');
            tape.className='tape';code.className='mono bp-code';code.textContent=storage.code;name.className='bp-tape-name';name.textContent=storage.name;total.className='mono';total.textContent=count;
            tape.append(code,name,total);section.append(tape);
          }else if(group?.value&&!byStorage&&!flat){
            const control=filterControls.find(c=>c.dataset.bcFilter===group.value),head=document.createElement('div'),total=document.createElement('span');
            head.className='lbl';head.textContent=control?[...control.options].find(o=>o.value===key)?.textContent||key:key;total.className='mono';total.textContent=' · '+count;head.append(total);section.append(head);
          }
          section.append(tiles);container.append(section);made.set(key,tiles);
        }
        return made.get(key);
      };
    }
    // What the page says about the sets in view, which storage is chosen, and what Sort is set to.
    function bpState(result){
      const copies=result.reduce((n,r)=>n+Number(r.quantity||0),0),lost=result.reduce((n,r)=>n+Number(r.missing_parts||0),0);
      const summary=list.querySelector('[data-bp-view-summary]');if(summary)summary.textContent=copies+' '+(copies===1?'copy':'copies')+' · '+lost+' '+(lost===1?'part':'parts')+' missing in view';
      const chosen=bpStorageFilter?bpStorageFilter.value:'';
      list.querySelectorAll('[data-bp-storage]').forEach(b=>{const on=b.dataset.bpStorage===chosen;b.setAttribute('aria-pressed',String(on));b.classList.toggle('on',on);});
      const pick=list.querySelector('[data-bp-storage-select]');if(pick)pick.value=chosen;
      const label=list.querySelector('[data-bp-storage-label]');if(label)label.textContent='Storage: '+(chosen===''?'all':chosen==='null'?'none':(bpById.get(chosen)?.name||'chosen'));
      const sorted=list.querySelector('[data-bp-sort-label]');if(sorted&&sort)sorted.textContent=(sort.options[sort.selectedIndex]?.textContent||'').toLowerCase();
    }
    list.querySelectorAll('[data-bp-storage]').forEach(b=>b.addEventListener('click',()=>{if(bpStorageFilter){bpStorageFilter.value=b.dataset.bpStorage;render(true);}}));
    list.querySelector('[data-bp-storage-select]')?.addEventListener('change',e=>{if(bpStorageFilter){bpStorageFilter.value=e.target.value;render(true);}});
    // Search and Sort sit beside the tabs on a desktop and at the top of the Filter sheet on a phone.
    const bpFind=list.querySelector('[data-bp-find]');
    if(bpFind&&panel&&typeof matchMedia==='function'){
      const home=bpFind.parentElement,wide=matchMedia('(min-width: 1024px)'),slot=document.createElement('div');
      slot.className='bp-sets b-prime bp-find-slot';   // the sheet is outside .b-prime: the moved block brings its own scope, so the frame's rules still match it
      const place=()=>{if(wide.matches){home.append(bpFind);slot.remove();}else{panel.querySelector('.actions')?.after(slot);slot.append(bpFind);}};
      place();wide.addEventListener?.('change',place);
    }
    function render(reset=false) {
      if(reset){limit=60;page=1;partSections.forEach(section=>section.page=1);if(figureBatch)figureBatch.page=1;}
      const extras=list.querySelector('[data-bc-tab-extras]'),inventoryPanel=list.querySelector('[data-bc-tab-inventory]');
      if(extras)extras.hidden=inventory!=='extras';
      if(inventoryPanel)inventoryPanel.hidden=inventory==='extras';
      const figureHeading=list.querySelector('[data-bc-figure-heading]'),partProgress=list.querySelector('[aria-label="Copy progress"]');
      if(figureHeading)figureHeading.hidden=inventory!=='figures';
      if(partProgress)partProgress.hidden=inventory!=='parts';
      list.dataset.inventory=inventory;
      list.bcPartEditVisibility?.();
      tabs.forEach(t=>t.setAttribute('aria-pressed',String(t.dataset.bcTab===inventory)));
      if(inventory==='extras'){
        if(panel){panel.hidden=true;panel.removeAttribute('aria-modal');}
        list.querySelectorAll('[data-bc-filters]').forEach(b=>b.setAttribute('aria-expanded','false'));
        saveState();
        return;
      }
      const scope=scopeControl?scopeControl.value:'';
      if(virtual&&scope!==shownScope){
        records.forEach(r=>{r.scope=scope;if(scope==='sets')r.selected=false;if(r.node){r.node.remove();r.node=null;}});shownScope=scope;
        if(scopeControl&&list.hasAttribute('data-bc-main')){
          const head=scopeHeadline(root.dataset.type,records,scope),title=root.querySelector('[data-bc-headline]'),sub=root.querySelector('[data-bc-subline]');
          if(title)title.textContent=head.title;if(sub)sub.textContent=head.sub;
          quick.forEach(b=>{const total=b.querySelector('.mono'),[k,v]=b.dataset.bcQuick.split(':');if(total)total.textContent=String(filterRows(records,'',{stock:scope,...(k?{[k]:v}:{})}).length);});
        }
      }
      // #551: the Added via row of a loose-stock list is about loose stock: under In sets it is gone and filters nothing.
      const sourceRow=list.querySelector('[data-bc-source]');
      if(sourceRow){sourceRow.hidden=scope==='sets';if(scope==='sets')sourceRow.querySelector('input').value='';}
      const result=filterRows(records,search?.value||'',filters(),sort?sort.value:'index',direction?.value,group?.value,bpRank);
      if(pageSize)page=Math.min(Math.max(1,page),Math.max(1,Math.ceil(result.length/pageSize)));
      const focused=document.activeElement,focusedRow=focused?.closest?.('[data-bc-row]');
      const copyCards=groupedInventory && root.hasAttribute('data-b-copy') && !list.hasAttribute('data-bc-pl-editing') && inventory!=='figures' && !!list.querySelector('[data-bc-missing]');
      const sections=inventorySections(result),split=(!groupedInventory || copyCards) && inventory!=='figures' && !!list.querySelector('[data-bc-missing]') && sections.missing.length>0;
      const missingSet=new Set(sections.missing);
      let displayed=visibleSlice(split?[...sections.missing,...sections.present]:result); // one array for retention and render
      if(groupedInventory){
        displayed=[];
        partSections.forEach(section=>{
          const matches=result.filter(r=>r.part_group===section.name && r.type!=='M' && !(copyCards && split && missingSet.has(r)));
          section.element.hidden=inventory==='figures'||!matches.length;
          section.page=Math.min(Math.max(1,section.page),Math.max(1,Math.ceil(matches.length/25)));
          updatePager(matches.length,section.pager,section.page,25,true);
          displayed.push(...matches.slice((section.page-1)*25,section.page*25));
        });
        const figures=result.filter(r=>r.type==='M');
        if(figureBatch){
          figureBatch.page=Math.min(Math.max(1,figureBatch.page),Math.max(1,Math.ceil(figures.length/25)));
          updatePager(figures.length,figureBatch.pager,figureBatch.page,25,true);
          figureBatch.pager.nav.hidden=inventory!=='figures'||figures.length<=25;
          displayed.push(...figures.slice((figureBatch.page-1)*25,figureBatch.page*25));
        }
        if(copyCards && split)displayed.push(...sections.missing);
      }
      if(virtual){
        const matching=new Set(result),shown=new Set(displayed);
        records.forEach(r=>{if(!matching.has(r))r.selected=false;if(r.node && !shown.has(r))r.node.remove();});
        nodes=[];
      }
      else nodes.forEach(n=>n.hidden=true);container.querySelectorAll('[data-bc-group-heading]').forEach(n=>n.remove());if(bpSets)container.querySelectorAll('[data-bp-group]').forEach(n=>n.remove());   // the tiles are kept by their records and placed again
      const missingSection=list.querySelector('[data-bc-missing]'),presentSection=list.querySelector('[data-bc-present]'),missingRows=list.querySelector('[data-bc-missing-rows]'),presentRows=list.querySelector('[data-bc-present-rows]');
      // #33 (frame 1d): the first three present lines show inline above "Show all N present parts".
      const presentInline=list.querySelector('[data-bc-present-inline]'),inlinePresent=new Set(split&&!copyCards&&presentInline?displayed.filter(r=>Number(r.missing||0)+Number(r.damaged||0)+Number(r.parts_missing||0)===0).slice(0,3):[]);
      if(presentInline)presentInline.hidden=copyCards || !inlinePresent.size;
      if(missingSection)missingSection.hidden=!split;
      if(missingSection){const label='Missing '+(inventory==='figures'?'minifigures':'parts');missingSection.setAttribute('aria-label',label);}
      if(presentSection){presentSection.hidden=copyCards || !split || sections.present.length<=inlinePresent.size;list.querySelector('[data-bc-present-summary]').textContent='Show all '+sections.present.length+(sections.present.some(r=>r.missing_recorded===false)?' other ':' present ')+(inventory==='figures'?'minifigures':'parts');}
      const basis=root.querySelector('[data-bc-price-basis]');if(basis && list.hasAttribute('data-bc-main'))basis.textContent=priceBasis(result);
      let previous;const groupCounts=new Map();const bpTiles=bpSets?bpGroups(result):null;
      if(group?.value)result.forEach(r=>{const k=groupValue(r,group.value)||'Not recorded';groupCounts.set(k,(groupCounts.get(k)||0)+1);});
      displayed.forEach(r=>{
        if(group?.value && !partSections.length && !bpSets) {const name=groupValue(r,group.value)||'Not recorded';if(name!==previous){const h=document.createElement('h3');h.dataset.bcGroupHeading='';const control=filterControls.find(c=>c.dataset.bcFilter===group.value);const headingLabel=control?[...control.options].find(o=>o.value===name)?.textContent||name:name;h.textContent=headingLabel;const n=groupCounts.get(name)||0,noun=singularNoun(root.dataset.type);h.append(Object.assign(document.createElement('span'),{className:'bc-group-count',textContent:' · '+n+' '+(n===1?noun:listNoun(root.dataset.type))}));if(group.value==='lot'&&name!=='null'&&root.dataset.lotBase){const open=document.createElement('a');open.className='bc-group-open';open.textContent='Open';open.setAttribute('aria-label','Open lot '+headingLabel);open.href=root.dataset.lotBase.replace('LOT',encodeURIComponent(name));h.append(open);}container.append(h);previous=name;}}
        const node=virtual?(r.node ||= buildRow(r,root.dataset,selecting,selectionCount)):r.node;
        if(virtual){const check=node.querySelector('[data-bc-selected]');if(check)check.checked=r.selected;const label=node.querySelector('.bc-selection');if(label)label.hidden=!selecting;}
        node.hidden=false;const partSection=partSections.find(section=>section.name===r.part_group && r.type!=='M');const destination=(copyCards && split && missingSet.has(r))?missingRows:partSection?partSection.rows:figureRows&&r.type==='M'?figureRows:split?(defect(r,'missing')+defect(r,'damaged')+Number(r.parts_missing||0)>0?missingRows:inlinePresent.has(r)?presentInline:presentRows):(bpSets?bpTiles(r):container);destination.append(node);if(virtual)nodes.push(node);
        bindRow(node);
      });
      const missingLabel=list.querySelector('[data-bc-missing-label]'),missingMore=list.querySelector('[data-bc-missing-more]');
      if(copyCards && split){
        const n=sections.missing.length,unfiltered=!search?.value && filterControls.every(c=>!c.value || c.value===preset(c));
        if(missingLabel){missingLabel.textContent='Missing parts · '+n+(n===1?' line':' lines');missingLabel.hidden=false;}
        if(unfiltered && !missingExpanded)sections.missing.slice(2).forEach(r=>{if(r.node)r.node.hidden=true;});
        if(missingMore){const canCollapse=unfiltered && n>2;missingMore.hidden=!canCollapse;if(canCollapse)missingMore.textContent=missingExpanded?'Show fewer':'+ '+(n-2)+' more missing lines';}
      }else{
        if(missingLabel)missingLabel.hidden=true;
        if(missingMore)missingMore.hidden=true;
      }
      list.querySelectorAll('[data-bc-view-only]').forEach(n=>n.hidden=!copyCards);
      list.querySelectorAll('[data-bc-edit-only]').forEach(n=>n.hidden=copyCards);
      if(focusedRow && nodes.includes(focusedRow) && !focusedRow.hidden && document.activeElement!==focused)focused.focus({preventScroll:true});
      list.querySelectorAll('[data-bc-selected]').forEach(c=>{if(c.closest('[data-bc-row]').hidden)c.checked=false;});
      if(count){const countKind=root.dataset.bcCollectionList!==undefined?root.dataset.type:'',countNoun=tabs.length?(inventory==='figures'?'minifigures':'parts'):listNoun(countKind),countOne=tabs.length?(inventory==='figures'?'minifigure':'part'):singularNoun(countKind),noun=resultCount(result.length,countNoun,countOne);count.hidden=root.dataset.type==='S' && tabs.length>0;count.textContent=count.hidden?'':(pageSize&&result.length?rangeText(result.length):noun);if(pageSize&&result.length)count.setAttribute('aria-label',rangeText(result.length)+' '+(result.length===1?countOne:countNoun));else count.removeAttribute('aria-label');}
      const summary=list.querySelector('[data-bc-missing-summary]');if(summary){summary.textContent=missingSummary(result);summary.hidden=!summary.textContent;}
      const apply=list.querySelector('[data-bc-apply]');if(apply)apply.textContent='Show '+resultCount(result.length,listNoun(root.dataset.type),singularNoun(root.dataset.type));if(loaded)loaded.textContent='Loaded '+Math.min(limit,result.length)+' of '+result.length;
      if(more)more.hidden=limit>=result.length;updatePager(result.length);
      const empty=list.querySelector('[data-bc-empty]');if(empty)empty.hidden=result.length>0;
      if(chips){chips.replaceChildren();const active=[...(search?.value?[{label:'Search: '+search.value,clear:()=>search.value=''}]:[]),...filterControls.filter(c=>c.options&&c.value&&c.value!==preset(c)).map(c=>({label:c.parentElement.firstChild.textContent.trim()+': '+c.options[c.selectedIndex].textContent,clear:()=>c.value=preset(c)}))];active.forEach(a=>{const b=document.createElement('button');b.type='button';b.textContent=a.label+' ×';b.setAttribute('aria-label','Remove '+a.label);b.addEventListener('click',()=>{a.clear();render(true);});chips.append(b);});}
      picks.forEach(b=>b.setAttribute('aria-pressed',String(filters()[b.dataset.bcPick]===b.dataset.value)));
      groupPicks.forEach(b=>b.setAttribute('aria-pressed',String((group?.value||'')===b.dataset.bcGroupPick)));
      quick.forEach(b=>{const [k,v]=b.dataset.bcQuick.split(':');b.setAttribute('aria-pressed',String(k?filters()[k]===v:quickKeys.every(x=>!filters()[x])));});
      srcButtons.forEach(b=>{const [k,v]=srcPair(b);b.setAttribute('aria-pressed',String((filters()[k]||'')===v));});
      statusButtons.forEach(b=>{const on=b.dataset.bcStatus===(filters().status||'');b.setAttribute('aria-pressed',String(on));if(bpSets)b.classList.toggle('on',on);});
      list.querySelectorAll('[data-bc-view]').forEach(b=>{const on=b.dataset.bcView===container.dataset.view;b.setAttribute('aria-pressed',String(on));if(bpSets)b.classList.toggle('on',on);});
      if(bpSets)bpState(result);
      list.querySelectorAll('[data-bc-sort-pick]').forEach(b=>b.setAttribute('aria-pressed',String(sort?.value===b.dataset.bcSortPick)));
      list.querySelectorAll('[data-bc-order-pick]').forEach(b=>b.setAttribute('aria-pressed',String(direction?.value===b.dataset.bcOrderPick)));
      selectionCount();saveState();
    }
    list.bcRender=()=>render();
    list.querySelector('[data-bc-missing-more]')?.addEventListener('click',()=>{missingExpanded=!missingExpanded;render();});
    const searchRender=debounce(()=>render(true),120);
    // #226: Date added starts newest first; the order buttons still turn it round.
    const sorted=()=>{if(sort?.value==='added'&&direction)direction.value='desc';render(true);};
    [...filterControls,search,sort,direction,group].filter(Boolean).forEach(c=>c.addEventListener(c===search?'input':'change',c===search?searchRender:c===sort?sorted:()=>render(true)));
    const scrim=list.querySelector('[data-bc-sheet-scrim]');
    const sortPanel=list.querySelector('[data-bc-sort-panel]');
    function syncSheets(){if(scrim)scrim.hidden=(panel.hidden||desktop())&&(!sortPanel||sortPanel.hidden||desktop());}
    const desktop=()=>list.hasAttribute('data-bc-main') && !bpSets && typeof matchMedia==='function' && matchMedia('(min-width: 1024px)').matches;
    function togglePanel(){
      if(!canFilter())return;
      if(desktop()) {panel.hidden=false;panel.setAttribute('role','region');panel.removeAttribute('aria-modal');panel.querySelector('[data-bc-pick],select')?.focus();return;}
      panel.hidden=!panel.hidden;
      if(scrim && !panel.hidden && sortPanel){sortPanel.hidden=true;list.querySelectorAll('[data-bc-sort-open]').forEach(b=>b.setAttribute('aria-expanded','false'));}
      syncSheets();
      list.querySelectorAll('[data-bc-filters]').forEach(t=>t.setAttribute('aria-expanded',String(!panel.hidden)));
      panel.setAttribute('role','dialog');panel.setAttribute('aria-modal',String(!panel.hidden));
      if(!panel.hidden)panel.querySelector('button,select')?.focus();else ([...list.querySelectorAll('[data-bc-filters]')].find(b=>b.offsetParent)||list.querySelector('[data-bc-filters]'))?.focus();
    }
    list.querySelectorAll('[data-bc-filters]').forEach(b=>b.addEventListener('click',togglePanel));
    if(panel&&desktop()){panel.hidden=false;panel.setAttribute('role','region');list.querySelectorAll('[data-bc-filters]').forEach(b=>b.setAttribute('aria-expanded','true'));}
    if(panel && typeof matchMedia==='function' && list.hasAttribute('data-bc-main'))matchMedia('(min-width: 1024px)').addEventListener?.('change',()=>{panel.hidden=!canFilter()||!desktop();panel.setAttribute('role',desktop()?'region':'dialog');panel.removeAttribute('aria-modal');list.querySelectorAll('[data-bc-filters]').forEach(b=>b.setAttribute('aria-expanded',String(!panel.hidden)));syncSheets();});
    list.querySelectorAll('[data-bc-sort-open]').forEach(b=>b.addEventListener('click',()=>{sortPanel.hidden=!sortPanel.hidden;if(scrim&&!sortPanel.hidden&&!desktop()){panel.hidden=true;list.querySelectorAll('[data-bc-filters]').forEach(b=>b.setAttribute('aria-expanded','false'));}syncSheets();if(scrim){sortPanel.setAttribute('role','dialog');sortPanel.setAttribute('aria-modal',String(!sortPanel.hidden&&!desktop()));}list.querySelectorAll('[data-bc-sort-open]').forEach(t=>t.setAttribute('aria-expanded',String(!sortPanel.hidden)));if(!sortPanel.hidden)(sortPanel.querySelector('[data-bc-sort-pick]')||sort)?.focus();else list.querySelector('[data-bc-sort-open]')?.focus();}));
    function closeSheets(){
      if(!desktop()){panel.hidden=true;panel.removeAttribute('aria-modal');list.querySelectorAll('[data-bc-filters]').forEach(b=>b.setAttribute('aria-expanded','false'));}
      if(sortPanel){sortPanel.hidden=true;sortPanel.removeAttribute('aria-modal');list.querySelectorAll('[data-bc-sort-open]').forEach(b=>b.setAttribute('aria-expanded','false'));}
      syncSheets();
    }
    scrim?.addEventListener('click',closeSheets);
    list.querySelector('[data-bc-apply]')?.addEventListener('click',()=>{closeSheets();([...list.querySelectorAll('[data-bc-filters]')].find(b=>b.offsetParent)||list.querySelector('[data-bc-filters]'))?.focus();});
    list.querySelectorAll('[data-bc-sort-pick]').forEach(b=>b.addEventListener('click',()=>{sort.value=b.dataset.bcSortPick;sorted();}));
    list.querySelectorAll('[data-bc-order-pick]').forEach(b=>b.addEventListener('click',()=>{direction.value=b.dataset.bcOrderPick;render(true);}));
    picks.forEach(b=>b.addEventListener('click',()=>{const control=filterControls.find(c=>c.dataset.bcFilter===b.dataset.bcPick);if(control)control.value=control.value===b.dataset.value?preset(control):b.dataset.value;render(true);}));
    groupPicks.forEach(b=>b.addEventListener('click',()=>{if(group){group.value=b.dataset.bcGroupPick;render(true);}}));
    quick.forEach(b=>b.addEventListener('click',()=>{
      const setFilter=(k,v)=>{const control=filterControls.find(c=>c.dataset.bcFilter===k);if(control)control.value=v;};
      quickKeys.forEach(k=>setFilter(k,''));const [k,v]=b.dataset.bcQuick.split(':');if(k)setFilter(k,v);render(true);
    }));
    // #551 (frame 45): the two Source chip rows, Added via and Last synced from, combine with each other and with the status tabs; a pressed chip clears its row.
    srcButtons.forEach(b=>b.addEventListener('click',()=>{const [k,v]=srcPair(b),control=filterControls.find(c=>c.dataset.bcFilter===k);if(control){const on=control.value===v;srcButtons.forEach(o=>{if(srcPair(o)[0]===k)o.setAttribute('aria-pressed','false');});control.value=on?'':v;}render(true);}));
    statusButtons.forEach(b=>b.addEventListener('click',()=>{const control=filterControls.find(c=>c.dataset.bcFilter==='status');if(control)control.value=b.dataset.bcStatus;render(true);}));
    tabs.forEach(b=>b.addEventListener('click',()=>{inventory=b.dataset.bcTab;render(true);const query=new URLSearchParams(location.search);query.set('inventory',inventory);try{window.history?.replaceState(null,'',location.pathname+'?'+query.toString()+ (location.hash||''));}catch(_){}}));
    list.querySelector('[data-bc-reset]')?.addEventListener('click',()=>{filterControls.forEach(c=>c.value=preset(c));if(search)search.value='';render(true);});
    viewSwitch(list,container,'bc',key,root.dataset.type);
    const reveal=()=>{limit+=60;render();};more?.addEventListener('click',reveal);
    if(more && 'IntersectionObserver' in window)new IntersectionObserver(entries=>{if(entries.some(e=>e.isIntersecting)&&!more.hidden)reveal();},{rootMargin:'300px'}).observe(more);
    list.querySelectorAll('[data-bc-select]').forEach(b=>b.addEventListener('click',()=>{selecting=!selecting;list.querySelectorAll('.bc-selection').forEach(n=>n.hidden=!selecting);list.querySelector('[data-bc-selection-bar]').hidden=!selecting;list.querySelectorAll('[data-bc-select]').forEach(x=>{if(x.getAttribute('role')==='switch')x.setAttribute('aria-checked',String(selecting));});if(!selecting){records.forEach(r=>r.selected=false);list.querySelectorAll('[data-bc-selected]').forEach(c=>c.checked=false);}selectionCount();}));
    list.querySelectorAll('[data-bc-selected]').forEach(c=>c.addEventListener('change',selectionCount));
    const bulkField=list.querySelector('[data-bc-bulk-field]'),bulkValue=list.querySelector('[data-bc-bulk-value]');
    bulkField?.addEventListener('change',()=>{
      const data=JSON.parse(list.querySelector('[data-bc-bulk-options]').textContent);let choices;
      if(bulkField.value==='condition')choices=[{value:'new',label:'New'},{value:'used',label:'Used'}];
      else choices=[{value:'',label:bulkField.value==='lot_id'?'No lot':'Not stored'},...(bulkField.value==='lot_id'?data.lots:data.storages).map(r=>({value:r.id,label:r.name||r.id}))];
      bulkValue.replaceChildren();choices.forEach(c=>{const o=document.createElement('option');o.value=c.value;o.textContent=c.label;bulkValue.append(o);});
    });
    async function bulk(action,button){button.disabled=true;try{const chosen=selection();if(!chosen.ids.length)throw new Error('Select an owned instance');if(chosen.entity==='wish'&&bulkField.value!=='condition'&&action!=='archive')throw new Error('Edit wish limits and quantities on the wish');if(chosen.entity==='copy'&&bulkField.value==='lot_id'&&action!=='archive')throw new Error('Only loose stock belongs to a lot');let value=bulkValue.value;const result=await send(action,{...chosen,values:action==='save'?{[bulkField.value]:value}:{}});if(result.url)location.href=result.url;else location.reload();}catch(e){message.textContent=e.message;}finally{button.disabled=false;}}
    list.querySelector('[data-bc-bulk-save]')?.addEventListener('click',e=>bulk('save',e.currentTarget));
    root.querySelector('[data-bc-bulk-archive]')?.addEventListener('click',e=>bulk('archive',e.currentTarget));
    const top=list.querySelector('[data-bc-top]');top?.addEventListener('click',()=>window.scrollTo({top:0,behavior:matchMedia('(prefers-reduced-motion: reduce)').matches?'instant':'smooth'}));
    window.addEventListener('scroll',()=>{if(top)top.hidden=window.scrollY<window.innerHeight*3;},{passive:true});
    window.addEventListener('pagehide',()=>{const data=JSON.parse(sessionStorage.getItem(key)||'{}');data.scroll=window.scrollY;sessionStorage.setItem(key,JSON.stringify(data));});
    function bindRow(n){if(n.dataset.bcKeyboard)return;n.dataset.bcKeyboard='true';n.addEventListener('keydown',e=>{if(e.target!==n)return;const visible=nodes.filter(x=>!x.hidden),i=visible.indexOf(n);if(e.key==='ArrowDown'||e.key==='ArrowUp'){e.preventDefault();visible[Math.max(0,Math.min(visible.length-1,i+(e.key==='ArrowDown'?1:-1)))]?.focus();}else if(e.key==='Enter')n.querySelector('[data-bc-item-link],a')?.click();});}
    try{render();}finally{list.removeAttribute('data-bc-pending');}if(saved?.scroll && list.hasAttribute('data-bc-main') && (!pageSize || (Number(saved.page)||1)===page))requestAnimationFrame(()=>window.scrollTo(0,saved.scroll));
    lists.push({list,search,panel,sortPanel,desktop,togglePanel,canFilter,syncSheets});

  });
  const lightbox=root.querySelector('#bc-lightbox'),full=root.querySelector('[data-bc-full-picture]'),caption=root.querySelector('[data-bc-caption]'),pictureButtons=[...root.querySelectorAll('[data-bw-lightbox]')];let pictures=pictureButtons,pictureIndex=0,zoom=1;
  function showPicture(index){if(!pictures.length)return;pictureIndex=(index+pictures.length)%pictures.length;zoom=1;full.src=pictures[pictureIndex].dataset.bwLightbox;full.alt=pictures[pictureIndex].dataset.caption||'';caption.textContent=full.alt;full.style.width='100%';}
  function openPicture(b){const group=b.closest('[data-bc-list],.bc-photos,.bc-detail-hero');pictures=group?[...group.querySelectorAll('[data-bw-lightbox]')]:[b];showPicture(pictures.indexOf(b));lightbox.showModal();}
  pictureButtons.forEach(b=>{if(!b.closest('[data-bc-main]'))b.addEventListener('click',()=>openPicture(b));});
  function changeZoom(delta){zoom=Math.max(1,Math.min(4,zoom+delta*.25));full.style.width=(zoom*100)+'%';}
  root.querySelectorAll('[data-bc-zoom]').forEach(b=>b.addEventListener('click',()=>changeZoom(Number(b.dataset.bcZoom))));
  root.querySelector('[data-bc-prev]')?.addEventListener('click',()=>showPicture(pictureIndex-1));root.querySelector('[data-bc-next]')?.addEventListener('click',()=>showPicture(pictureIndex+1));
  let pinch;lightbox?.addEventListener('touchstart',e=>{if(e.touches.length===2)pinch=Math.hypot(e.touches[0].clientX-e.touches[1].clientX,e.touches[0].clientY-e.touches[1].clientY);},{passive:true});
  lightbox?.addEventListener('touchmove',e=>{if(e.touches.length===2&&pinch){const distance=Math.hypot(e.touches[0].clientX-e.touches[1].clientX,e.touches[0].clientY-e.touches[1].clientY);changeZoom(distance>pinch?1:-1);pinch=distance;}},{passive:true});
  root.querySelectorAll('dialog').forEach(d=>d.addEventListener('click',e=>{const r=d.getBoundingClientRect();if(e.target===d&&(e.clientX<r.left||e.clientX>r.right||e.clientY<r.top||e.clientY>r.bottom))d.close();}));
  document.addEventListener('keydown',e=>{
    if(lightbox?.open){if(e.key==='ArrowLeft')showPicture(pictureIndex-1);if(e.key==='ArrowRight')showPicture(pictureIndex+1);if(e.key==='+')changeZoom(1);if(e.key==='-')changeZoom(-1);return;}
    if(e.key==='Escape'){lists.forEach(l=>{if(l.sortPanel&&!l.sortPanel.hidden){l.sortPanel.hidden=true;l.list.querySelectorAll('[data-bc-sort-open]').forEach(b=>b.setAttribute('aria-expanded','false'));l.list.querySelector('[data-bc-sort-open]')?.focus();}
      if(l.panel&&!l.panel.hidden&&!l.desktop()){l.panel.hidden=true;l.list.querySelectorAll('[data-bc-filters]').forEach(b=>b.setAttribute('aria-expanded','false'));([...l.list.querySelectorAll('[data-bc-filters]')].find(b=>b.offsetParent)||l.list.querySelector('[data-bc-filters]'))?.focus();}l.syncSheets();});return;}
    const activePanel=lists.map(l=>({...l,panel:l.sortPanel&&!l.sortPanel.hidden?l.sortPanel:l.panel})).find(l=>l.panel&&!l.panel.hidden);
    if(e.key==='Tab'&&activePanel&&typeof matchMedia==='function'&&matchMedia('(max-width: 1023px)').matches){
      const controls=[...activePanel.panel.querySelectorAll('button,input,select,textarea,a[href]')].filter(n=>!n.disabled&&!n.hidden&&(!n.getClientRects||n.getClientRects().length)),first=controls[0],last=controls.at(-1);
      if(e.shiftKey&&document.activeElement===first){e.preventDefault();last?.focus();}else if(!e.shiftKey&&document.activeElement===last){e.preventDefault();first?.focus();}
    }
    if(/INPUT|TEXTAREA|SELECT/.test(e.target.tagName)||document.querySelector('dialog[open]'))return;
    if(e.key==='/'){e.preventDefault();lists[0]?.search?.focus();}
    if(e.key.toLowerCase()==='f'&&lists[0]?.panel&&lists[0].canFilter()){e.preventDefault();if(lists[0].panel.hidden||lists[0].desktop())lists[0].togglePanel();}

  });
})();
// Fetch prices in place; polling uses the existing durable job status contract.
document.addEventListener?.('click',async event=>{
  const button=event.target.closest('[data-bc-fetch-prices]');
  if(!button || button.disabled)return;
  const root=document.getElementById('bw-collection'),scope=button.closest('[data-bc-fetch-scope]');
  const status=scope?.querySelector('[data-bc-fetch-status]'),pending=button.closest('[data-bc-partout]');
  const items=JSON.parse(button.dataset.bcFetchPrices),label=button.textContent;
  const before=Number(pending?.dataset.priced || 0);
  button.disabled=true;
  if(pending)button.textContent=`Fetching ${items.length} part prices`;
  if(status){status.textContent='Queued with the market price refresh · the card updates here';delete status.dataset.state;}
  scope?.setAttribute('aria-busy','true');
  try{
    const response=await fetch(button.dataset.refreshUrl,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({items,csrf_token:root.dataset.csrf})});
    const result=await response.json().catch(()=>({}));
    if(!response.ok)throw new Error(result.message||'Could not queue the price refresh');
    const urls=result.status_urls || [];
    if(!urls.length)throw new Error('Could not read the price refresh status');
    let finished=false,failed=0,budget=false;
    while(!finished){
      const events=await Promise.all(urls.map(async url=>{
        const response=await fetch(url,{cache:'no-store'});
        if(!response.ok)throw new Error('Could not read the price refresh status');
        return (await response.json()).events;
      }));
      const states=events.map(events=>events[events.length-1]?.job_state);
      failed=states.filter(state=>state==='failed' || state==='cancelled').length;
      budget=states.includes('waiting_for_budget');
      finished=budget || states.every(state=>['done','failed','cancelled'].includes(state));
      if(!finished)await new Promise(resolve=>setTimeout(resolve,2000));
    }
    const page=await fetch(location.href,{cache:'no-store'});
    if(!page.ok)throw new Error('Could not update the Prices card · try again');
    const doc=new DOMParser().parseFromString(await page.text(),'text/html');
    const fresh=doc.querySelector('[data-module="prices"]');
    if(!fresh)throw new Error('Could not update the Prices card · try again');
    const updated=fresh.querySelector('[data-bc-partout]');
    const notes=[];
    if(budget)notes.push('BrickLink budget reached · the worker continues later');
    if(failed)notes.push(`${failed} price refresh jobs failed or were cancelled`);
    if(pending && updated){
      const priced=Number(updated.dataset.priced),missing=Number(updated.dataset.lines)-priced;
      const remaining=Math.max(0,Number(pending.dataset.unpricedItemsCount || items.length)-items.length);
      const complete=!budget && !failed && !remaining;
      if(complete){
        updated.querySelector('[data-bc-fetch-prices]')?.remove();
        updated.querySelector('[data-bc-fetch-status]')?.remove();
      }
      notes.unshift(`Fetched ${Math.max(0,priced-before)} part prices`);
      if(remaining)notes.push(`${remaining} parts remain to fetch`);
      else if(complete && missing)notes.push(`${missing} ${missing===1?'part has':'parts have'} no sales yet`);
    }
    if(notes.length){
      const note=document.createElement('p');note.className='secondary';note.setAttribute('role','status');if(failed)note.dataset.state='error';   // a job the worker failed or cancelled is said in the danger colour (R2-04)
      note.textContent=notes.join(' · ');(updated || fresh).append(note);
    }
    const card=scope?.closest('[data-module="prices"]') || document.querySelector('[data-module="prices"]');
    card?.replaceWith(fresh);
    // A wish's page opens with the answer and a state tag that come from the same prices: they follow the card (#654).
    for(const selector of ['[data-wish-answer]','.bc-hero-status']){const next=doc.querySelector(selector),current=document.querySelector(selector);if(next&&current)current.replaceWith(next);}
    button.disabled=false;button.textContent=label;
  }catch(error){button.disabled=false;button.textContent=label;if(status){status.textContent=error.message;status.dataset.state='error';}}
  finally{scope?.setAttribute('aria-busy','false');}
});

// Refresh only derived tiles, preserving open forms and the selected tab.
(() => {
  const root=document.querySelector('#bw-collection');
  if(!root||!root.querySelector)return;
  let attempts=0;
  async function refresh(){
    const pending=[...root.querySelectorAll('.bc-booklet-card[data-thumbnail-state="pending"]')];
    if(!pending.length||attempts++>=30)return;
    try{
      const response=await fetch(location.href,{headers:{'Accept':'text/html'},cache:'no-store'});
      if(response.ok){  // a failed answer is retried by the next poll, like a network error
        const page=new DOMParser().parseFromString(await response.text(),'text/html');
        const fresh=new Map([...page.querySelectorAll('.bc-booklet-card')].map(c=>[c.dataset.fileId,c]));  // matched by file id, never by position
        root.querySelectorAll('.bc-booklet-card').forEach(card=>{
          const next=fresh.get(card.dataset.fileId);
          if(card.dataset.thumbnailState==='pending'&&next&&next.dataset.thumbnailState!=='pending'){
            card.querySelector('.bc-booklet-tile').replaceWith(next.querySelector('.bc-booklet-tile'));
            card.dataset.thumbnailState=next.dataset.thumbnailState;
          }
        });
      }
    }catch(error){ /* A later poll or reload can recover. */ }
    setTimeout(refresh,2000);
  }
  if(root.querySelector('.bc-booklet-card[data-thumbnail-state="pending"]'))setTimeout(refresh,2000);
})();
