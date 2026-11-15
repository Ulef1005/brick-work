(() => {
  'use strict';
  const capacity = layout => ({'a4-21':21, 'a4-14':14, 'tape-62':1})[layout];
  const state = (ids, layout, page=0, phase='ready') => ({ids:[...new Set(ids)], layout,
    pages:Math.ceil(new Set(ids).size / capacity(layout)), page, phase,
    download:layout === 'tape-62' ? `Download ${new Set(ids).size} PNG` : 'Download PDF'});
  const selected = (rows, action, id) => rows.map(row => ({...row, checked:action === 'all' || (action === 'toggle' ? row.id === id ? !row.checked : row.checked : false)}));
  window.BrickLabels = {state, selected, capacity};
  const root = document.querySelector('#bw-ledger.bw-storage');
  if (!root) return;
  const dialog = root.querySelector('[data-label-dialog]');
  const q = selector => dialog.querySelector(selector);
  const qrIcon = root.querySelector('[data-label-icon]');
  const addIcon = button => {if (qrIcon) button.prepend(qrIcon.content.cloneNode(true));};
  const boxes = [...root.querySelectorAll('[data-label-id]')];
  const toggle = root.querySelector('[data-label-select]');
  const bar = root.querySelector('[data-label-bar]');
  const opener = root.querySelector('[data-label-open]');
  let selecting=false, ids=[], page=0, phase='ready', generation=0, previewURL=null, failedDownload=false;
  const layout = q('[data-label-layout]'), download = q('[data-label-download]'), picture=q('[data-label-preview]');
  const url = output => {
    const params=new URLSearchParams({ids:ids.join(','),layout:layout.value,page:String(page)});
    return dialog.dataset.base.replace('OUTPUT',output)+'?'+params;
  };
  const renderBar = () => {
    const count=boxes.filter(b=>b.checked).length;
    root.querySelector('[data-label-count]')?.replaceChildren(document.createTextNode(`${count} selected`));
    if (opener) {opener.disabled=!count; opener.textContent=count ? `Print labels · ${count}` : 'Choose storages';if(count)addIcon(opener);}
  };
  const selectMode = value => {
    selecting=value;
    toggle.textContent=value?'Done':'Print labels';
    if(!value)addIcon(toggle);
    toggle.setAttribute('aria-pressed',String(value));
    bar.hidden=!value;
    boxes.forEach(b=>b.closest('label').hidden=!value);
    renderBar();
  };
  toggle?.addEventListener('click',()=>selectMode(!selecting));
  boxes.forEach(b=>b.addEventListener('change',renderBar));
  root.querySelector('[data-label-all]')?.addEventListener('click',()=>{boxes.forEach(b=>b.checked=true);renderBar();});
  root.querySelector('[data-label-clear]')?.addEventListener('click',()=>{boxes.forEach(b=>b.checked=false);renderBar();});
  const update = () => {
    const model=state(ids,layout.value,page,phase);
    q('[data-label-total]').textContent=`${ids.length} labels`;
    q('[data-label-sheets]').textContent=layout.value==='tape-62'?`${ids.length} images`:`${ids.length} labels · ${model.pages} ${model.pages===1?'sheet':'sheets'}`;
    download.disabled=!ids.length || phase==='loading' || phase==='downloading';
    download.textContent=phase==='error'?'Retry':phase==='downloading'?'Downloading…':model.download;
    q('[data-label-status]').textContent=phase==='loading'?'Making preview…':phase==='error'?'The PDF was not made. Nothing was changed. Retry makes it again.':!ids.length?'Choose storages':'';
    const pager=q('[data-label-pager]');pager.hidden=model.pages<2;
    q('[data-label-prev]').disabled=page===0;q('[data-label-next]').disabled=page>=model.pages-1;
    q('[data-label-page]').textContent=`${page+1} of ${model.pages}`;
    q('[data-label-size]').textContent=({'a4-21':'63.5 × 38.1 mm · Avery L7160 compatible','a4-14':'99.1 × 38.1 mm · Avery L7163 compatible','tape-62':'62 mm wide · 45 mm long'})[layout.value];
    const chips=q('[data-label-chips]');chips.replaceChildren();
    ids.forEach(id=>{
      const name=boxes.find(b=>b.dataset.labelId===id)?.dataset.labelName || id;
      const chip=document.createElement('span');chip.className='lb-chip';chip.append(document.createTextNode(name));
      const remove=document.createElement('button');remove.type='button';remove.textContent='×';remove.setAttribute('aria-label',`Remove ${name}`);
      remove.addEventListener('click',()=>{ids=ids.filter(i=>i!==id);const box=boxes.find(b=>b.dataset.labelId===id);if(box)box.checked=false;renderBar();page=0;refresh();});
      chip.append(remove);chips.append(chip);
    });
  };
  const clearPicture = () => {picture.hidden=true;if(previewURL){URL.revokeObjectURL(previewURL);previewURL=null;}picture.removeAttribute('src');};
  const refresh = async () => {
    const current=++generation;
    clearPicture();phase=ids.length?'loading':'ready';update();
    if(!ids.length)return;
    try {
      const response=await fetch(url('preview.png'),{headers:{Accept:'image/png'}});
      if(!response.ok)throw new Error('preview');
      const blob=await response.blob();
      if(current!==generation)return;
      previewURL=URL.createObjectURL(blob);picture.src=previewURL;picture.hidden=false;phase='ready';failedDownload=false;update();
    } catch(error) {if(current===generation){phase='error';update();}}
  };
  const open = chosen => {ids=[...new Set(chosen)];page=0;dialog.showModal();refresh();};
  opener?.addEventListener('click',()=>open(boxes.filter(b=>b.checked).map(b=>b.dataset.labelId)));
  root.querySelector('[data-label-single]')?.addEventListener('click',e=>open([e.currentTarget.dataset.labelSingle]));
  dialog.querySelectorAll('[data-label-close]').forEach(b=>b.addEventListener('click',()=>dialog.close()));
  dialog.addEventListener('close',()=>{generation++;clearPicture();});
  layout.addEventListener('change',()=>{page=0;refresh();});
  q('[data-label-prev]').addEventListener('click',()=>{page--;refresh();});
  q('[data-label-next]').addEventListener('click',()=>{page++;refresh();});
  download.addEventListener('click',async()=>{
    if(phase==='error'&&!failedDownload){refresh();return;}
    phase='downloading';update();
    try {
      const response=await fetch(url('download'));
      if(!response.ok)throw new Error('download');
      const blob=await response.blob(), href=URL.createObjectURL(blob), anchor=document.createElement('a');
      anchor.href=href;anchor.download=layout.value==='tape-62'?(ids.length===1?'storage-label.png':'storage-labels.zip'):'storage-labels.pdf';
      document.body.append(anchor);anchor.click();anchor.remove();setTimeout(()=>URL.revokeObjectURL(href),1000);phase='ready';failedDownload=false;update();
    }catch(error){phase='error';failedDownload=true;update();}
  });
  // Screen-gate entry points use the same real selection and preview flow.
  const scene=new URLSearchParams(window.location.search).get('labels');
  if(scene&&toggle){
    selectMode(true);
    const count=scene==='select-none'?0:scene==='two-sheets'?22:3;
    boxes.slice(0,count).forEach(b=>b.checked=true);renderBar();
    if(!scene.startsWith('select-')){
      open(boxes.filter(b=>b.checked).map(b=>b.dataset.labelId));
      if(scene==='error'){generation++;clearPicture();phase='error';update();}
    }
  }
})();
