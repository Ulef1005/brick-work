(() => {
  'use strict';
  document.querySelectorAll('[data-wl-root]').forEach((root, index) => {
    // Forms outside the root (the selection bar under the list) belong to the first root.
    const scope=index===0?document:root;
    const message=root.querySelector('[data-wl-message]'),undo=root.querySelector('[data-wl-undo]');
    const key='bw-wishlists-receipt';
    let receipt;
    try { receipt=JSON.parse(sessionStorage.getItem(key)); } catch (_) {}
    if(receipt){undo.hidden=false;message.textContent='Saved · Undo';}
    async function send(action,data){
      const response=await fetch(root.dataset.wlUrl.replace('ACTION',action),{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({...data,csrf_token:root.dataset.csrf})});
      const result=await response.json();
      if(!response.ok)throw Error(result.message || 'Could not save');
      if(action==='undo')sessionStorage.removeItem(key);
      else if(result.event_id)sessionStorage.setItem(key,JSON.stringify(result.event_id));
      location.reload();
    }
    async function run(button,fn){button.disabled=true;try{await fn();}catch(e){message.textContent=e.message;}finally{button.disabled=false;}}
    undo.addEventListener('click',()=>run(undo,async()=>{await send('undo',{event_id:receipt});sessionStorage.removeItem(key);}));
    root.querySelectorAll('[data-wl-open]').forEach(b=>b.addEventListener('click',()=>document.getElementById(b.dataset.wlOpen).showModal()));
    root.querySelectorAll('[data-wl-close]').forEach(b=>b.addEventListener('click',()=>b.closest('dialog').close()));
    const selected=()=>[...document.querySelectorAll('[data-wl-selected]:checked')].map(c=>c.value);
    const bar=scope.querySelector('[data-wl-selection]');
    function selectionChanged(){
      const n=selected().length,count=scope.querySelector('[data-wl-count]');
      if(count)count.textContent=n+' selected';
      if(bar)bar.hidden=n===0;  // the bar shows only while wishes are selected
    }
    document.addEventListener('change',event=>{if(event.target.matches('[data-wl-selected]'))selectionChanged();});
    scope.querySelector('[data-wl-clear]')?.addEventListener('click',()=>{document.querySelectorAll('[data-wl-selected]:checked').forEach(c=>{c.checked=false;});selectionChanged();});
    selectionChanged();
    const kind=root.querySelector('[data-wl-kind]');
    root.querySelectorAll('[data-wl-export] input[name=format]').forEach(r=>r.addEventListener('change',()=>{if(kind)kind.hidden=r.value!=='csv'||!r.checked;}));
    scope.querySelectorAll('form[data-wl-action]').forEach(form=>form.addEventListener('submit',e=>{
      e.preventDefault();const values=Object.fromEntries(new FormData(form));
      if('bricklink_id' in values && !values.bricklink_id)values.bricklink_id=null;
      const data=form.dataset.wlAction==='transfer'?{ids:form.dataset.wlIds?JSON.parse(form.dataset.wlIds):selected(),list_id:values.list_id,copy:e.submitter?.value==='true'}:{id:form.dataset.wlId,values};
      run(e.submitter || form.querySelector('button'),()=>send(form.dataset.wlAction,data));
    }));
    root.querySelector('[data-wl-export]')?.addEventListener('submit',e=>{
      e.preventDefault();const form=e.target,values=Object.fromEntries(new FormData(form));
      run(form.querySelector('button'),async()=>{
        const response=await fetch(form.dataset.wlExportUrl.replace('FORMAT',values.format)+'?summary=true&kind='+values.kind);
        const result=await response.json();if(!response.ok)throw Error(result.message || 'Could not export');
        const summary=root.querySelector('[data-wl-summary]'),content=root.querySelector('[data-wl-summary-content]');
        summary.hidden=false;summary.open=true;content.replaceChildren();
        const p=document.createElement('p');p.textContent=result.summary.exported+' rows exported · '+result.summary.omitted.length+' omitted';content.append(p);
        [...result.summary.omitted,...result.summary.notes].forEach(n=>{const line=document.createElement('p');line.textContent=n.item_no+' · '+n.reason;content.append(line);});
        const url=URL.createObjectURL(new Blob([result.content],{type:result.mimetype})),a=document.createElement('a');a.href=url;a.download=result.filename;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
        message.textContent='Exported';
      });
    });
  });
})();
