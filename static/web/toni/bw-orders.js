(() => {
  'use strict';
  // A shared gap can appear on several order lines. Reserve it once in the suggestion.
  const suggest = rows => {
    const reserved = new Map();
    return rows.map(row => {
      let left = row.available;
      const gaps = row.gaps.map(gap => {
        const used = reserved.get(gap.key) || 0;
        const quantity = Math.min(left, Math.max(0, gap.need - used));
        left -= quantity; reserved.set(gap.key, used + quantity);
        return quantity;
      });
      return {gaps, stock:left};
    });
  };
  window.BrickOrders = {suggest};
  const root = document.querySelector('.bw-orders'); if (!root) return;
  root.querySelectorAll('.status').forEach(node => {node.dataset.phase = node.textContent.trim();});
  // Keep the select as the form value, expose its options through keyboard accessible buttons.
  root.querySelectorAll('select').forEach(select => {
    select.hidden = true;
    const box = document.createElement('span'); box.className = 'order-select';
    const opener = document.createElement('button'); opener.type = 'button';
    opener.setAttribute('aria-expanded','false');
    const menu = document.createElement('span'); menu.className = 'order-select-menu'; menu.hidden = true;
    const refresh = () => {
      opener.textContent = select.options[select.selectedIndex]?.textContent || 'Choose';
      opener.setAttribute('aria-label', `${select.parentElement.firstChild.textContent.trim()}: ${opener.textContent}`);
      menu.replaceChildren();
      Array.from(select.options).forEach(option => {
        const pick = document.createElement('button'); pick.type = 'button'; pick.textContent = option.textContent;
        pick.setAttribute('aria-selected',String(option.selected));
        pick.addEventListener('click', () => {select.value=option.value; select.dispatchEvent(new Event('change',{bubbles:true})); menu.hidden=true; opener.setAttribute('aria-expanded','false'); opener.focus();});
        menu.append(pick);
      });
    };
    opener.addEventListener('click', () => {refresh(); menu.hidden=!menu.hidden; opener.setAttribute('aria-expanded',String(!menu.hidden)); if(!menu.hidden)menu.querySelector('button')?.focus();});
    box.addEventListener('keydown',event => {if(event.key==='Escape'){event.stopPropagation();menu.hidden=true;opener.setAttribute('aria-expanded','false');opener.focus();}});
    document.addEventListener('click',event => {if(!box.contains(event.target)){menu.hidden=true;opener.setAttribute('aria-expanded','false');}});
    select.addEventListener('change',refresh); box.append(opener,menu); select.after(box); refresh();
  });
  // Count what arrived: the state chip and progress bar follow the typed counts.
  const refreshCount = () => {
    let counted = 0;
    root.querySelectorAll('[data-received]').forEach(input => {
      counted += Number(input.value) || 0;
      const chip = input.closest?.('.order-count-row')?.querySelector('.order-count-state'); if (!chip) return;
      const ordered = Number(chip.dataset.ordered), got = Number(input.value) || 0;
      chip.textContent = got >= ordered ? 'Complete' : got === 0 ? 'Not counted' : `${ordered - got} short`;
    });
    const progress = root.querySelector('[data-progress]'), bar = root.querySelector('[data-bar]');
    if (progress) {const total = Number(progress.dataset.ordered); progress.textContent = `${counted} of ${total} pieces counted`; if (bar) bar.style.width = `${total ? Math.round(100 * counted / total) : 0}%`;}
  };
  const stepper = (input, delta) => {input.value = String(Math.max(Number(input.min || 0), Math.min(Number(input.max), (Number(input.value) || 0) + delta))); refreshCount();};
  root.querySelectorAll('.order-stepper').forEach(label => {
    const input = label.querySelector('input');
    const minus = document.createElement('button'), plus = document.createElement('button');
    minus.type = plus.type = 'button'; minus.textContent = '\u2212'; plus.textContent = '+';
    minus.setAttribute('aria-label', 'One fewer'); plus.setAttribute('aria-label', 'One more');
    minus.addEventListener('click', () => stepper(input, -1)); plus.addEventListener('click', () => stepper(input, 1));
    input.before(minus); input.after(plus); input.addEventListener('input', refreshCount);
  });
  root.querySelector('[data-mark-received]')?.addEventListener('click', () => {root.querySelectorAll('[data-received]').forEach(input => {input.value=input.max;}); refreshCount();});
  const allocation = root.querySelector('form[data-action="allocate"]');
  const reset = () => {
    if (!allocation) return;
    const articles = Array.from(allocation.querySelectorAll('[data-rows]>article'));
    const rows = articles.map(article => {
      const inputs=Array.from(article.querySelectorAll('[data-allocation]'));
      return {available:Number(inputs.find(input=>JSON.parse(input.dataset.allocation).target_type==='stock')?.max || 0),gaps:inputs.filter(input=>JSON.parse(input.dataset.allocation).target_type==='copy').map(input=>{const target=JSON.parse(input.dataset.allocation); return {key:`${target.copy_id}:${target.target}:${target.target_id}`,need:Number(input.dataset.gapNeed)};})};
    });
    suggest(rows).forEach((row,index) => {let gap=0; articles[index].querySelectorAll('[data-allocation]').forEach(input=>{input.value=JSON.parse(input.dataset.allocation).target_type==='stock'?row.stock:row.gaps[gap++];});});
  };
  reset(); root.querySelector('[data-reset-suggestion]')?.addEventListener('click',reset);
  root.querySelectorAll('[data-drop]').forEach(drop => {
    const input=drop.querySelector('input');
    const show=()=>{drop.querySelector('[data-file-name]').textContent=input.files[0]?.name || '';};
    input.addEventListener('change',show);
    drop.addEventListener('dragover',event=>{event.preventDefault();});
    drop.addEventListener('drop',event=>{event.preventDefault();if(event.dataTransfer.files.length){input.files=event.dataTransfer.files;show();}});
  });
  const load=root.querySelector('[data-load-orders]');
  load?.addEventListener('click',async()=>{
    const status=root.querySelector('[data-placed-message]'), container=root.querySelector('[data-placed-orders]');
    load.disabled=true;status.textContent='Loading placed orders';
    try {
      const response=await fetch(root.dataset.url.replace('ACTION','placed'),{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({csrf_token:root.dataset.csrf})});
      const result=await response.json();if(!response.ok)throw Error(result.message);
      container.replaceChildren();
      const choices=[];
      result.orders.forEach(order=>{
        const label=document.createElement('label'), checkbox=document.createElement('input');checkbox.type='checkbox';checkbox.value=order.number;checkbox.disabled=order.imported;choices.push(checkbox);
        label.append(checkbox,document.createTextNode(`${order.number} · ${order.store} · ${order.date.slice(0,10)}${order.imported?' · Already imported':''}`));container.append(label);
      });
      const submit=document.createElement('button');submit.type='button';container.append(submit);
      const relabel=()=>{const count=choices.filter(box=>box.checked&&!box.disabled).length;submit.textContent=count?`Import ${count} ${count===1?'order':'orders'}`:'Import selected orders';submit.className=count?'primary':'';};
      choices.forEach(box=>box.addEventListener('change',relabel));relabel();
      submit.addEventListener('click',async()=>{
        const selected=choices.filter(box=>box.checked&&!box.disabled);if(!selected.length){status.textContent='Choose an order';return;}
        submit.disabled=true;let last;
        try {
          for(const box of selected){
            const response=await fetch(root.dataset.url.replace('ACTION','import'),{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({csrf_token:root.dataset.csrf,source:'api',number:box.value})});
            const result=await response.json();if(!response.ok)throw Error(result.message);box.checked=false;box.disabled=true;relabel();last=result.url;
          }
          location.assign(last);
        }catch(error){status.textContent=`${error.message || 'Could not import'} · Retry the remaining selected orders`;}
        finally{submit.disabled=false;}
      });
      status.textContent=result.orders.length?'Choose the orders to import':'No placed orders found';
    }catch(error){status.textContent=error.message || 'Could not load orders · try again';}
    finally{load.disabled=false;}
  });
})();
