(() => {
  'use strict';
  const nowrapTail = window.BrickFormatting.nowrapTail;
  const clone = value => JSON.parse(JSON.stringify(value));
  function progress(state) {
    const counts = {found:0, missing:0, skipped:0, remaining:0};
    // #222: a missing-only run counts the parts it walks, as the server's progress does.
    const walked = state.session?.scope === 'missing' ? new Set(state.session.members || state.session.order) : null;
    for (const r of state.rows.filter(r => r.kind !== 'spare' && (!walked || walked.has(r.token)))) {
      const answer = state.session ? state.session.answers[r.token] : (r.checked || r.missing > 0 ? 'answered' : undefined);   // no session: the marks the copy already has (Edit parts, a Rebrickable pull)
      if (!answer) counts.remaining++;
      else if (answer === 'skipped') counts.skipped++;
      else if (r.missing > 0) counts.missing++;
      else counts.found++;
    }
    return counts;
  }
  // The top block's numbers (R3-02): the pieces of the answered lines of the pieces of all lines, and the lines found, missing and still to check. A
  // line is a part line, or a figure line; only part lines have pieces. The same lines as progress().
  function summary(state) {
    const counts = progress(state), answers = state.session?.answers || {};
    const marked = r => state.session ? answers[r.token] === 'answered' : (r.checked || r.missing > 0);
    const walked = state.session?.scope === 'missing' ? new Set(state.session.members || state.session.order) : null;
    let pieces = 0, total = 0;
    for (const r of state.rows) {
      if (r.kind !== 'part' || (walked && !walked.has(r.token))) continue;
      total += r.quantity || 0;
      if (marked(r)) pieces += r.quantity || 0;
    }
    return {...counts, pieces, total, lines: counts.found + counts.missing + counts.skipped + counts.remaining, figures: state.rows.some(r => r.kind === 'figure')};
  }
  // One cell per line, found first, then missing, then still to check; a long list is grouped so the strip stays a strip (375 parts never become 375 cells,
  // 900 lines never become 900). A cell that holds several lines is still to check when any of them is, else missing when any is.
  const CELL_CAP = 240;
  function cells(counts, cap = CELL_CAP) {
    const todo = counts.skipped + counts.remaining, lines = counts.found + counts.missing + todo, per = Math.max(1, Math.ceil(lines / cap));
    const marks = [...Array(counts.found).fill('f'), ...Array(counts.missing).fill('m'), ...Array(todo).fill('u')], result = [];
    for (let i = 0; i < marks.length; i += per) {
      const group = marks.slice(i, i + per);
      result.push(group.includes('u') ? 'u' : group.includes('m') ? 'm' : 'f');
    }
    return {marks: result, per, lines};
  }
  // The spare pass walks in the order chosen at start; the server is authoritative
  // and replaces this optimistic order with its own once the save returns.
  function spareOrder(state, s) {
    const position = new Map(state.rows.map((r, i) => [r.token, i]));
    const spare = state.rows.filter(r => r.kind === 'spare' && !s.order.includes(r.token));
    const text = (a, b) => a < b ? -1 : a > b ? 1 : 0;
    const mode = s.sort || 'inventory';
    spare.sort((a, b) => mode === 'group' && a.group_order != null && b.group_order != null ? a.group_order - b.group_order
      : mode === 'largest' && a.largest_order != null && b.largest_order != null ? a.largest_order - b.largest_order
      : mode === 'largest' || mode === 'group' ? ((b.quantity || 0) - (a.quantity || 0)) || text(a.token, b.token)
      : mode === 'colour' ? text(a.color_name || 'Unknown colour', b.color_name || 'Unknown colour') || text(a.item_no, b.item_no)
      : position.get(a.token) - position.get(b.token));
    return spare.map(r => r.token);
  }
  function apply(state, payload) {
    const s = state.session, r = state.rows.find(r => r.token === payload.token);
    if (['answer','found_one','set_count'].includes(payload.action)) {
      const found = payload.action === 'found_one' ? r.quantity - (r.missing || 0) + 1 : payload.found;
      r.missing = r.quantity - found; r.checked = 1; s.answers[r.token] = 'answered';
      if (r.missing && !s.misses.includes(r.token)) s.misses = [r.token, ...s.misses];
      else if (!r.missing) s.misses = s.misses.filter(t => t !== r.token);   // found in full: the part leaves Missing so far (#383)
      if (payload.action === 'answer') s.cursor = Math.min(s.order.indexOf(r.token)+1, s.order.length);
    } else if (payload.action === 'recheck') {
      // #214: walk the skipped parts (or the named ones) in the part view; the server's order replaces this one once the save returns.
      const place = new Map(state.rows.map((x, i) => [x.token, i]));
      const skipped = state.rows.filter(x => x.kind !== 'spare' && s.answers[x.token] === 'skipped').map(x => x.token);
      s.order = (payload.tokens || skipped).slice().sort((a, b) => place.get(a) - place.get(b)); s.cursor = 0; if (s.scope !== 'missing') s.scope = 'skipped';
    } else if (payload.action === 'skip') {
      s.answers[r.token] = 'skipped'; s.cursor = Math.min(s.order.indexOf(r.token)+1, s.order.length);
    } else if (payload.action === 'select') { if (!s.order.includes(r.token)) s.order.push(r.token); s.cursor = s.order.indexOf(r.token); }
    else if (payload.action === 'back') s.cursor = Math.max(0, s.cursor-1);
    else if (payload.action === 'next') s.cursor = Math.min(s.order.length, s.cursor+1);
    else if (payload.action === 'spares') {
      s.spares = payload.include ? 'yes' : 'no';
      if (payload.include) s.order.push(...spareOrder(state, s));
    }
    else if (payload.action === 'finish') { s.finished = true; if (!state.figure) state.copy.set_checked = payload.checked; }
    return state;
  }
  function merge(state, result) {
    if (!result.partial) return result;
    const changed = new Map(result.rows.map(r => [r.token, r]));
    return {...state, copy:{...state.copy, ...result.copy}, session:result.session,
      rows:state.rows.map(r => ({...r, ...(changed.get(r.token) || {})}))};
  }
  class Queue {
    constructor(storage, key, send, update) {
      this.storage=storage; this.key=key; this.send=send; this.update=update;
      this.items=JSON.parse(storage.getItem(key) || '[]'); this.running=false;
    }
    persist() { this.storage.setItem(this.key, JSON.stringify(this.items)); }
    add(payload) {
      this.items.push(payload);
      try { this.persist(); } catch (e) { this.items.pop(); throw e; }
      this.flush();
    }
    async flush() {
      if (this.running || !this.items.length) return;
      this.running=true;
      try {
        while (this.items.length) {
          const completed=this.items[0];
          const result = await this.send(completed);
          this.items.shift(); this.persist(); this.update(result, this.items.length, null, completed);
        }
      } catch (error) { this.update(null, this.items.length, error); }
      finally { this.running=false; }
    }
  }
  function keyCommand(key, modified, active, quantity) {
    const k=key.toLowerCase();
    if(modified && k!=='z')return null;
    if(k==='z')return {action:'undo'};
    if(k==='arrowleft')return {action:'back'};
    if(k==='arrowright'||k==='enter')return {action:'next'};
    if(!active)return null;
    if(k==='f')return quantity===null?null:{action:'answer',count:quantity};
    if(k==='m')return quantity===null?null:{action:'missing'};
    if(k==='s')return {action:'skip'};
    if(/^[1-9]$/.test(k)&&quantity!==null)return {count:Math.min(Number(k),quantity)};
    return null;
  }
  window.BrickChecker = {nowrapTail,progress, summary, cells, apply, merge, Queue, keyCommand, spareOrder};
  function lists(root) {
    const search=root.querySelector('[data-search]') || root.querySelector('[data-check-search]'), filter=root.querySelector('[data-filter]'), sort=root.querySelector('[data-sort]') || root.querySelector('[data-check-sort]');
    const direction=root.querySelector('[data-check-order]');
    function update() {
      const container=root.querySelector('[data-list-rows]'), rows=[...container.querySelectorAll('[data-list-row]')];
      let count=0;
      const chooser=root.dataset.copyChooser!==undefined;
      const caption=root.querySelector('[data-sort-caption]');
      if(caption){
        const descending=direction?.value==='desc';
        caption.textContent=sort.value==='largest' ? (descending?'Smallest first':'Largest first') : (sort.value==='name'?'Name':'Number')+(descending?' · descending':'');
      }
      const group=row=>row.dataset.state==='progress'?0:row.dataset.checked==='true'?2:1;
      rows.sort((a,b) => (chooser ? group(a)-group(b) : 0) || (direction?.value==='desc' ? -1 : 1) * (sort.value === 'largest' ? Number(b.dataset.count)-Number(a.dataset.count) : (sort.value==='name' ? a.dataset.name.localeCompare(b.dataset.name) : a.dataset.number.localeCompare(b.dataset.number,undefined,{numeric:true})))).forEach(row => {
        row.hidden=!(row.dataset.name+' '+row.dataset.number).toLowerCase().includes(search.value.toLowerCase()) || (filter.value!=='all' && (filter.value==='unchecked' && row.dataset.checked!==undefined ? row.dataset.checked==='true' : filter.value!==row.dataset.state));
        if (!row.hidden) count++;
        const section=chooser ? root.querySelector(`[data-copy-section="${row.dataset.state}"]`) : null;
        (section?.querySelector('[data-section-rows]') || container).appendChild(row);
      });
      (root.querySelector('[data-result-count]') || root.querySelector('[data-check-count]')).textContent=window.BrickFormatting.resultCount(count);
      root.querySelectorAll('[data-copy-section]').forEach(section=>{const shown=[...section.querySelectorAll('[data-list-row]')].filter(r=>!r.hidden).length;section.hidden=!shown;section.querySelector('[data-section-count]').textContent=shown;});
      const headline=root.querySelector('[data-choice-headline]');
      if(headline){
        const visible=rows.filter(row=>!row.hidden), progress=visible.filter(row=>row.dataset.state==='progress').length, unchecked=visible.filter(row=>row.dataset.state==='unchecked').length;
        headline.textContent=`${progress} ${progress===1?'check':'checks'} in progress, ${unchecked} ${unchecked===1?'set':'sets'} not checked`;
      }
      const chips=root.querySelector('[data-chips]'); chips.replaceChildren();
      // 4.9c w10 · the chooser has no filter chip row: its default filter is not a chip and "All copies" sits beside the Not checked heading (3b).
      // The section button is kit 3b; when that section is hidden (nothing unchecked), a fallback row keeps the control reachable.
      const allCopies=root.querySelector('[data-check-all-copies]'), fallback=root.querySelector('[data-check-all-fallback]');
      const sectionShown=!!allCopies&&!root.querySelector('[data-copy-section="unchecked"]')?.hidden;
      if(allCopies)allCopies.hidden=filter.value==='all'||!sectionShown;
      if(fallback)fallback.hidden=filter.value==='all'||sectionShown;
      for (const [field,active,label] of [[search,!!search.value,search.value],[filter,filter.value!=='all'&&!(chooser&&filter.value==='unchecked'),filter.selectedOptions[0].textContent]]) {
        if (!active) continue;
        const b=document.createElement('button'); b.textContent=label+' ×'; b.setAttribute('aria-label','Remove filter: '+label);
        b.onclick=()=>{field.value=field===search?'':'all';update();};chips.appendChild(b);
      }
    }
    [search,filter,sort,direction].filter(Boolean).forEach(field=>field.addEventListener('input',update));
    for(const selector of ['[data-check-all-copies]','[data-check-all-fallback]'])root.querySelector(selector)?.addEventListener('click',()=>{filter.value='all';update();});
    let opener;
    for(const [buttons,panel] of [['[data-check-filters]','[data-check-filter-panel]'],['[data-check-sort-open]','[data-check-sort-panel]']]) {
      root.querySelectorAll(buttons).forEach(button=>button.addEventListener('click',()=>{
        const target=root.querySelector(panel);target.hidden=!target.hidden;
        if(!target.hidden)root.querySelectorAll('[data-check-filter-panel], [data-check-sort-panel]').forEach(p=>{if(p!==target)p.hidden=true;});
        root.querySelectorAll(buttons).forEach(b=>b.setAttribute('aria-expanded',String(!target.hidden)));
        if(!target.hidden){opener=button;target.querySelector('select')?.focus();}else opener?.focus();
      }));
    }
    root.addEventListener('keydown',event=>{
      if(event.key==='Escape') {root.querySelectorAll('[data-check-filter-panel], [data-check-sort-panel]').forEach(p=>p.hidden=true);root.querySelectorAll('[data-check-filters], [data-check-sort-open]').forEach(b=>b.setAttribute('aria-expanded','false'));opener?.focus();}
      const filterPanel=root.querySelector('[data-check-filter-panel]');
      if(event.key==='Tab' && filterPanel && !filterPanel.hidden && window.matchMedia?.('(max-width:1023px)').matches) {
        const controls=[...filterPanel.querySelectorAll('button, select')].filter(n=>!n.disabled && n.getClientRects().length);
        const first=controls[0],last=controls[controls.length-1];
        if(event.shiftKey && document.activeElement===first){event.preventDefault();last?.focus();}
        else if(!event.shiftKey && document.activeElement===last){event.preventDefault();first?.focus();}
      }
      if(!/INPUT|SELECT|TEXTAREA/.test(event.target.tagName)) {
        if(event.key==='/'){event.preventDefault();search.focus();}
        if(event.key.toLowerCase()==='f')root.querySelector('[data-check-filters]')?.click();
      }
    });
    update();
  }
  const count = n => Number(n).toLocaleString('en');
  const make = (tag, text, cls) => {const n = document.createElement(tag); if (text !== undefined) n.textContent = text; if (cls) n.className = cls; return n;};
  // The top block of the Set Inspector (R3-02): "142 of 375 parts", the lines found, missing and to check, and one cell per line.
  function renderTop(root, state) {
    const big = root.querySelector('[data-chk-big]');
    if (!big) return;
    const sum = summary(state), strip = root.querySelector('[data-progress]'), shape = cells(sum);
    big.replaceChildren(make('span', count(sum.pieces), 'chk-n'), make('span', ' of ' + count(sum.total) + (sum.total === 1 ? ' part' : ' parts')));
    const todo = sum.skipped + sum.remaining, legend = root.querySelector('[data-legend]');
    legend.replaceChildren(make('span', sum.found + (sum.found === 1 ? ' line found' : ' lines found')), make('span', sum.missing + ' missing'), make('span', todo + ' to check'),
      ...(state.session?.scope === 'missing' ? [make('span', 'missing parts only')] : []));
    const per = shape.per, noun = sum.figures ? 'line' : 'part line';
    root.querySelector('[data-chk-cells-label]').textContent = 'One cell per ' + (per > 1 ? per + ' ' + noun + 's' : noun) + ' · ' + sum.lines + (sum.lines === 1 ? ' line' : ' lines');
    strip.replaceChildren(...shape.marks.map(kind => make('i', undefined, kind)));
    strip.setAttribute('aria-label', sum.found + ' found · ' + sum.missing + ' missing · ' + sum.skipped + ' skipped · ' + sum.remaining + ' remaining');
    const tag = root.querySelector('[data-chk-tag]'), finished = state.session?.finished;
    if (tag && state.session) {
      tag.textContent = finished ? (state.copy.set_checked ? 'Set is checked' : 'Check finished') : state.session ? 'Check in progress' : 'Not checked';
      tag.className = 'tag' + (finished && state.copy.set_checked ? '' : ' dash');
    }
  }
  function mount(root) {
    let state=JSON.parse(root.querySelector('[data-check-state]').textContent);
    renderTop(root,state);
    if (!state.session) return;
    let running=root.dataset.checkStage==='running';
    let confirmed=clone(state);
    let mode='part', count=null, current=null, undoStates=[], slowTimer, savedTimer;
    const stage=root.querySelector('[data-stage]'), history=root.querySelector('[data-history]'), body=root.querySelector('[data-check-body]'), status=root.querySelector('[data-save-status]'), retry=root.querySelector('[data-retry]'), saveUndo=root.querySelector('[data-save-undo]');
    const figureMode=!!state.figure;
    const storageKey='bw-checker:'+state.copy.id+(figureMode?':fig:'+state.figure.id:'')+':'+state.session.id;
    const stateKey=storageKey+':state';
    const el=(tag,text,cls)=>{const n=document.createElement(tag);if(text!==undefined)n.textContent=text;if(cls)n.className=cls;return n;};
    const button=(label,action,token,primary=false)=>{const b=el('button',label,primary?'primary bw-primary':'');b.dataset.action=action;if(token)b.dataset.token=token;return b;};
    function image(r) {
      const tile=el('div',undefined,'check-picture');
      if (r.image) {const img=el('img');const full=root.dataset.imageUrl.replace(/\/0$/, '/'+r.image);img.src=full+'?w=320';img.srcset=full+'?w=320 320w, '+full+'?w=640 640w';img.sizes='160px';img.dataset.full=full;img.alt=r.name+(r.kind!=='figure'?' · '+r.color_name:'');tile.append(img);img.onerror=()=>{tile.replaceChildren(el('span','Image did not load'),button('Retry','image_retry',r.token));};}
      else tile.append(el('span',r.item_no,'mono'),el('span','No image'));
      return tile;
    }
    function colour(r) {
      const c=el('span',r.color_name,'check-colour');
      if(r.rgb){c.style.backgroundColor=r.rgb;c.style.color=r.ink;}return c;
    }
    function row(r, recovery=true) {
      const n=el('div',undefined,'check-miss');n.append(image(r));const identity=el('div');
      if(r.kind!=='figure')identity.append(colour(r));identity.append(el('span',r.item_no,'mono'),el('p',nowrapTail(r.name)));
      if(r.unresolved){const a=el('a','Unresolved · review in Tools & Admin');a.href=root.dataset.unresolvedUrl;identity.append(a);}
      if(r.kind==='spare')identity.append(el('span','Spare · optional'));
      n.append(identity,el('span',(r.missing||0)+' missing of '+(r.quantity??'Unknown'),'mono'));
      const b=button(recovery?'Found 1':'Review',recovery?'found_one':'select',r.token);
      b.disabled=recovery && (!(r.missing>0) || r.quantity===null);n.append(b);return n;
    }
    const btn=(label,action,token,cls)=>{const b=el('button',label,cls);b.type='button';b.dataset.action=action;if(token)b.dataset.token=token;return b;};
    // a name block, a tile, a missing card and a found row of the frame (R3-02): the part's own colour fills the name block, white or ink, whichever reads
    const paint=(n,r)=>{if(r.rgb&&r.kind!=='figure'){n.style.backgroundColor=r.rgb;if(r.ink)n.style.color=r.ink;}else n.className+=' chk-plain';};
    function pic(r,size) {
      const wrap=el('div',undefined,'chk-pic '+size),tile=el('div',undefined,'tile');wrap.append(tile);
      if(r.image){const img=el('img'),full=root.dataset.imageUrl.replace(/\/0$/,'/'+r.image);img.src=full+'?w=320';img.srcset=full+'?w=320 320w, '+full+'?w=640 640w';img.sizes='(max-width:767px) 100vw, 400px';img.dataset.full=full;img.alt=r.name+(r.kind!=='figure'?' · '+r.color_name:'');tile.append(img);
        img.onerror=()=>{tile.replaceChildren(el('span','Image did not load','chk-alt'),btn('Retry','image_retry',r.token,'chk-link'));};}
      else tile.append(el('span',r.kind==='figure'?'Figure picture':'Part picture','chk-alt'));
      return wrap;
    }
    const nameBlock=(r,extra)=>{const n=el('div',undefined,'chk-mname');paint(n,r);n.append(el('div',(r.name||'').trim()||r.item_no,'chk-mn1'));
      const line=el('div',undefined,'chk-mn2');if(r.kind!=='figure')line.append(el('span',r.color_name+' · '));line.append(el('span',r.item_no,'mono'));if(extra)line.append(el('span',extra));n.append(line);return n;};
    function missCard(r) {
      const card=el('div',undefined,'card chk-miss'),n=nameBlock(r,' · need '+(r.quantity??'?')),step=el('div',undefined,'step'),gap=r.missing||0;
      n.append(el('div',gap+' missing','chk-mn3'));
      const less=el('button','−'),more=el('button','+'),mid=el('span',String(gap));
      for(const [b,delta,label] of [[less,-1,'One fewer missing'],[more,1,'One more missing']]){b.type='button';b.dataset.action='set_count';b.dataset.token=r.token;b.dataset.delta=String(delta);b.setAttribute('aria-label',label+', '+r.color_name+' '+r.item_no);}
      less.disabled=r.quantity===null;more.disabled=r.quantity===null||gap>=r.quantity;
      const bl=el('b'),br=el('b');bl.append(less);br.append(more);step.append(bl,mid,br);
      card.append(pic(r,'chk-sm96'),n,step);return card;
    }
    function foundRow(r) {
      const n=el('div',undefined,'chk-found-row'),text=el('div',undefined,'chk-ft'),sub=el('div',undefined,'chk-fs');
      if(r.kind!=='figure')sub.append(el('span',r.color_name+' · '));sub.append(el('span',r.item_no,'mono'));
      text.append(el('div',(r.name||'').trim()||r.item_no,'chk-fn'),sub);n.append(pic(r,'chk-sm44'),text,el('span',(r.quantity??'?')+' of '+(r.quantity??'?'),'mono chk-of'));return n;
    }
    // "Checked so far": the lines with a missing count first, as larger cards with a stepper so the count stays editable (O10b), then the found lines, newest first.
    const RECENT=4;let allChecked=false;   // the frame draws the last four answers; the rest is one button away
    function fillHistory() {
      history.replaceChildren();const s=state.session;if(!s)return;
      // The answered lines, the one answered last first. A line a narrowed walk (missing only, skipped) left out of `order` has no place in it: it follows the others.
      const byToken=new Map(state.rows.map(r=>[r.token,r])),place=t=>s.order.indexOf(t);
      const walked=s.scope==='missing'?new Set(s.members||s.order):null,keys=Object.keys(s.answers),seq=t=>keys.indexOf(t);
      const answered=keys.filter(t=>s.answers[t]==='answered'&&(!walked||walked.has(t))).sort((a,b)=>(place(a)<0)!==(place(b)<0)?(place(a)<0?1:-1):place(a)<0?seq(b)-seq(a):place(b)-place(a)).map(t=>byToken.get(t)).filter(r=>r&&r.kind!=='spare');
      const shown=allChecked?answered:answered.slice(0,RECENT);
      const misses=shown.filter(r=>(r.missing||0)>0),found=shown.filter(r=>!(r.missing>0)),older=answered.filter(r=>(r.missing||0)>0&&!shown.includes(r)).length;
      const wrap=el('div',undefined,'bp-chk b-prime chk-hist'),head=el('div',undefined,'chk-hhead');head.append(el('h2','Checked so far','lbl'),el('span','newest first','chk-note12'));wrap.append(head);
      if(!answered.length)wrap.append(el('p','Nothing checked yet.','chk-note12'));
      if(misses.length){wrap.append(el('h3','Missing · larger, so the count stays editable','lbl chk-gl'));misses.forEach(r=>wrap.append(missCard(r)));}
      if(found.length){wrap.append(el('h3','Found','lbl chk-gl chk-gl2'));found.forEach(r=>wrap.append(foundRow(r)));}
      // every line with parts missing stays one button away, so no missing count is out of reach
      if(answered.length>shown.length)wrap.append(btn('Show all '+answered.length+' checked lines'+(older?' · '+older+' more with missing parts':''),'show_found',null,'chk-link chk-more'));
      history.append(wrap);
    }
    const skippedRows=()=>state.rows.filter(r=>r.kind!=='spare'&&state.session.answers[r.token]==='skipped');
    // #214: the end of a check is three steps, 1 Skipped, 2 Missing, 3 Save; the current one is marked, an earlier one is done.
    function steps(active) {
      const nav=el('ol',undefined,'check-steps');nav.setAttribute('aria-label','Steps to finish');
      [['Skipped · '+skippedRows().length],['Missing · '+state.session.misses.length],['Save']].forEach(([label],i)=>{
        const n=i+1,li=el('li',undefined,'check-step');li.dataset.state=n<active?'done':n===active?'current':'next';
        if(n===active)li.setAttribute('aria-current','step');
        li.append(el('span',String(n),'check-step-n'),el('span',label));nav.append(li);
      });
      return nav;
    }
    function skippedRow(r) {
      const n=el('div',undefined,'check-miss');n.append(image(r));const identity=el('div');
      if(r.kind!=='figure')identity.append(colour(r));identity.append(el('span',r.item_no,'mono'),el('p',nowrapTail(r.name)));
      n.append(identity,el('span','skipped · '+(r.quantity??'Unknown')+' needed','mono'));
      n.append(button('Check','check_one',r.token));return n;
    }
    function skippedScreen() {
      const rows=skippedRows(),n=rows.length;
      stage.append(steps(1),el('h2','Skipped · '+n+(n===1?' entry':' entries')+' not checked yet'),el('p','Check them now, part by part, or leave them unchecked. Unchecked parts keep the copy at Not checked.'));
      const list=el('div');rows.forEach(r=>list.append(skippedRow(r)));stage.append(list);
      const choice=el('div',undefined,'check-skipped-choice');
      choice.append(button('Check the '+n+(n===1?' skipped part':' skipped parts'),'check_skipped',null,true),button('Leave them unchecked','leave_skipped'));stage.append(choice);
      const next=el('div',undefined,'check-next-step');next.setAttribute('inert','');next.setAttribute('aria-hidden','true');missingList(next);stage.append(next);
      const nav=el('div',undefined,'actions');nav.append(button('Back','back'),button('Undo last','undo'));stage.append(nav);
    }
    function missingList(target, finishing=false) {
      target.replaceChildren();
      const misses=state.session.misses.map(t=>state.rows.find(r=>r.token===t)).filter(Boolean);
      const total=misses.reduce((n,r)=>n+(r.missing||0),0);
      const heading=el('h2','Missing so far · '+misses.length+(misses.length===1?' entry · ':' entries · ')+total+' missing');
      target.append(heading);
      const entries=el('div');misses.forEach(r=>entries.append(row(r)));target.append(entries);
      target.append(el('p','Found one in the pile? Tap Found 1 and the count drops.'));
      if(finishing)target.append(button('Done · '+total+' still missing','finish_view',null,true));
    }
    function uncheckedList(rows) {
      const list=el('div'),toolbar=el('div',undefined,'check-toolbar');
      for(const [label,attr,options] of [['Search','search',null],['Filters','filter',[['all','All unchecked'],['part','Parts'],['figure','Figures']]],['Sort','sort',[['number','Inventory order'],['name','Name'],['largest','Required count']]]]) {
        const l=el('label',label),f=el(options?'select':'input');if(!options)f.type='search';f.dataset[attr]='';
        if(options)options.forEach(([v,text])=>{const o=el('option',text);o.value=v;f.append(o);});l.append(f);toolbar.append(l);
      }
      list.append(toolbar);const chips=el('div',undefined,'actions');chips.dataset.chips='';list.append(chips);const result=el('p',undefined,'mono');result.dataset.resultCount='';list.append(result);
      const entries=el('div');entries.dataset.listRows='';rows.forEach((r,i)=>{const n=row(r,false);n.dataset.listRow='';n.dataset.name=r.color_name+' '+r.item_no+' '+r.name;n.dataset.number=String(i).padStart(8,'0');n.dataset.count=r.quantity||0;n.dataset.state=r.kind;entries.append(n);});list.append(entries);lists(list);return list;
    }
    function render() {
      if(!running)return;
      const s=state.session, copyStatus=root.querySelector('[data-copy-status]');
      if(copyStatus){
        const pill=el('span',undefined,'check-pill'),dot=el('span','●');dot.setAttribute('aria-hidden','true');pill.dataset.status=state.copy.completeness||'unknown';
        pill.append(dot,el('span',({complete:'Complete',incomplete:'Incomplete',sealed:'Sealed'})[state.copy.completeness]||'Not checked'));copyStatus.replaceChildren(pill);
        // 3e: a running check shows the set line, the name and the progress; the status pill returns at the finish.
        copyStatus.hidden=!(s&&s.finished);
      }
      if(!s){renderTop(root,state);const tg=root.querySelector('[data-chk-tag]'),w=root.querySelector('[data-chk-saved]');if(tg){tg.textContent=state.copy.set_checked?'Set is checked':'Not checked';tg.className='tag dash';}if(w)w.textContent='';stage.replaceChildren(el('h2','Check undone'));const a=el('a','Start again','button primary');a.href=root.dataset.endpoint;stage.append(a);history.hidden=true;return;}
      renderTop(root,state);
      stage.replaceChildren();fillHistory();root.dataset.chkMode='other';
      if(s.finished) {
        history.hidden=true;stage.append(el('h2',queue.items.length?'Finish waiting to save':'Check saved'),el('p',figureMode?'Figure parts checked':state.copy.set_checked?'Set is checked':'Set is not checked'));
        if(figureMode)stage.append(el('p','The set’s numbers and status are unchanged.'));
        else if(state.copy.completeness_source==='manual')stage.append(el('p','Your manual completeness stays unchanged.'));
        const a=el('a','Done','button primary');a.href=root.dataset.doneUrl||root.dataset.endpoint;stage.append(a,button('Undo','undo'));return;
      }
      if(!figureMode && s.cursor>=s.order.length && mode!=='finish' && s.spares==null && state.rows.some(r=>r.kind==='spare')) {
        // Last step of the set check: spare parts are opt in, and "No" is the default.
        history.hidden=false;stage.append(el('h2','Include spare parts?'),el('p','Spares are the extra pieces that came with the set. They are not counted.'));
        const choice=el('div',undefined,'check-spare-choice'),no=button('No, skip them','spares_no',null,true);
        choice.append(no,button('Yes, check them','spares_yes'));stage.append(choice);
        const nav=el('div',undefined,'actions');nav.append(button('Back','back'),button('Undo last','undo'));stage.append(nav);
        no.autofocus=true;if(no.focus)no.focus({preventScroll:true});return;
      }
      if(s.cursor>=s.order.length && mode!=='finish' && mode!=='missing')mode=skippedRows().length?'skipped':'missing';
      if(mode==='skipped' && !skippedRows().length)mode='missing';
      if(mode==='skipped') {history.hidden=true;skippedScreen();return;}
      if(mode==='missing') {history.hidden=true;missingList(stage,true);stage.prepend(steps(2));stage.append(button('Back','back'),button('Undo last','undo'));return;}
      if(mode==='finish') {
        history.hidden=false;stage.append(steps(3),el('h2','Finish'));
        const unchecked=state.rows.filter(r=>r.kind!=='spare' && s.answers[r.token]!=='answered');
        const missing=state.rows.filter(r=>r.kind!=='spare').reduce((n,r)=>n+(r.missing||0),0);
        stage.append(el('p',missing?missing+' still missing':'Nothing missing'),el('p',unchecked.length+' entries still unchecked'));
        if(unchecked.length)stage.append(uncheckedList(unchecked));
        if(figureMode)stage.append(el('p','Missing figure parts count on the figure, not on the set.'));
        else {
          const l=el('label',undefined,'check-confirm'),check=el('input');check.type='checkbox';check.id='set-checked';check.checked=!!state.copy.set_checked&&!unchecked.length;check.disabled=!!unchecked.length;l.append(check,el('span','Set is checked'));stage.append(l);
          stage.append(el('p',unchecked.length?'Available after the skipped parts and figures are answered.':'Inspect the build and figures first. With gaps, the copy stays Incomplete.'));
          if(state.copy.completeness_source==='manual')stage.append(el('p','Your manual completeness stays unchanged.'));
        }
        stage.append(button('Done','finish',null,true),button('Review missing parts','missing_view'),button('Back','back'),button('Undo','undo'));return;
      }
      history.hidden=false;
      const r=state.rows.find(r=>r.token===s.order[s.cursor]);if(!r){stage.append(el('p','This inventory changed. Reload to continue.'));return;}
      if(current!==r.token){count=r.quantity;current=r.token;}
      const missingRun=s.scope==='missing'&&r.kind!=='spare';
      root.dataset.chkMode='part';
      // The card of R3-02: the line, its picture, Need beside the part's name block in the part's own colour, the old stepper, Missing, Back, Skip, Undo.
      const heading=r.kind==='figure'?'Figure review':r.kind==='spare'?'Spare pass · optional · not counted':(missingRun?'Missing part line ':'Part line ')+(s.cursor+1)+' of '+s.order.length;
      const scope=el('div',undefined,'bp-chk b-prime'),card=el('div',undefined,'card chk-card'),head=el('div',undefined,'chk-cardhead'),title=el('h2',heading,'lbl');
      if(missingRun)title.append(el('span','Missing only','tag chk-scope'));
      head.append(title,el('span','keys 1 to 9 count','chk-keys-note'));card.append(head,pic(r,'chk-bigpic'));
      const need=el('div',undefined,'cnt'),k=el('div',undefined,'k'),v=el('div',undefined,'v');
      k.append(el('div','Need','lbl'),el('div',r.quantity===null?'?':String(r.quantity),'chk-need'));
      const name=(r.name||'').trim()||r.item_no;paint(v,r);v.append(el('div',name,'chk-nm'));
      const sub=el('div',undefined,'chk-sub');if(r.kind!=='figure')sub.append(el('span',r.color_name,'chk-colour'));sub.append(el('span',r.item_no,'mono chk-no'));v.append(sub);need.append(k,v);card.append(need);
      const stepper=el('div',undefined,'chk-stepper'),minus=btn('−','decrease',null,'btn sec chk-sq'),found=btn('Found ×'+(count??'?'),'answer',r.token,'btn chk-found'),plus=btn('+','increase',null,'btn sec chk-sq');
      minus.setAttribute('aria-label','Found count, '+count+', decrease');plus.setAttribute('aria-label','Found count, '+count+', increase');
      minus.disabled=count===null;plus.disabled=count===null;found.disabled=count===null;/* the buttons stay as drawn at the ends; action() keeps the count inside 0 and the quantity */stepper.append(minus,found,plus);card.append(stepper);
      const miss=btn('Missing','missing',r.token,'btn sec chk-missing');miss.disabled=count===null;card.append(miss);
      const nav=el('div',undefined,'chk-nav');nav.append(btn('Back','back',null,'chk-link'),btn('Skip for later','skip',r.token,'chk-link'),btn('Undo','undo',null,'chk-link'));card.append(nav);
      const state_line=s.answers[r.token]==='answered'?'Recorded · '+r.missing+' missing':s.answers[r.token]==='skipped'?'Skipped · still unchecked':missingRun?'Missing since the last check: '+r.missing+' of '+r.quantity:'';
      if(state_line)card.append(el('p',state_line,'chk-note'));
      if(r.parent_minifig)card.append(el('p','Figure parts · '+r.parent_minifig,'chk-note'));
      if(r.unresolved){const a=el('a','Unresolved · review in Tools & Admin','chk-note');a.href=root.dataset.unresolvedUrl;card.append(a);}
      if(r.kind==='spare')card.append(el('p','Spare · optional','chk-note'));
      if(r.kind==='figure') {
        if(r.parts_missing>0)card.append(el('p',r.parts_missing+(r.parts_missing===1?' part missing':' parts missing'),'chk-note chk-figure-parts'));
        if(r.parts_lines&&root.dataset.figureUrl){const link=el('a','Check figure parts','btn sec sm chk-figlink');link.href=root.dataset.figureUrl.replace(/\/0$/,'/'+encodeURIComponent(r.id));card.append(link);}
      }
      if(r.quantity===null)card.append(el('p','Required count unavailable · resolve the inventory first.','chk-note'));
      stage.append(scope);scope.append(card);
    }
    const send=async payload=>{
      clearTimeout(slowTimer);slowTimer=setTimeout(()=>{status.className='check-saving';status.textContent='Saving';},400);
      try {
        const response=await fetch(root.dataset.endpoint,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({...payload,csrf_token:root.dataset.csrf}),credentials:'same-origin'});
        if(!response.ok){const data=await response.json().catch(()=>({}));throw Error(data.error||'The answer could not be saved. Retry.');}
        return (await response.json()).state;
      } finally {clearTimeout(slowTimer);}
    };
    let queue;
    function saved(result,pending,error,completed) {
      clearTimeout(savedTimer);
      if(error){status.className='check-waiting';status.textContent='Not saved · waiting for network · '+error.message;retry.hidden=false;return;}
      confirmed=merge(confirmed,result);
      if(!pending){state=clone(confirmed);localStorage.setItem(stateKey,JSON.stringify(state));root.dataset.direction='none';render();status.className='';status.textContent=completed?.action==='undo'?'✓ Undone':'✓ Saved';const when=root.querySelector('[data-chk-saved]');if(when)when.textContent=state.session&&!state.session.finished?'Saved just now · resume any time':'';retry.hidden=true;saveUndo.hidden=false;savedTimer=setTimeout(()=>{status.textContent='';saveUndo.hidden=true;},5000);}
    }
    try {
      queue=new Queue(localStorage,storageKey,send,saved);
      if(queue.items.length){const cached=JSON.parse(localStorage.getItem(stateKey)||'null');if(cached)state=cached;else queue.items.forEach(p=>{if(p.action!=='undo')apply(state,p);});}
    } catch(error){status.textContent='Local storage is unavailable. Enable storage and reload before checking.';return;}
    function action(name,token,delta) {
      if(!state.session)return;
      root.dataset.direction=['back','undo'].includes(name)?'back':['answer','missing','skip','next','select','check_skipped','check_one'].includes(name)?'forward':'none';
      if(name==='show_found'){allChecked=true;render();return;}
      if(name==='finish_view'){mode='finish';render();return;}
      if(name==='missing_view'){mode='missing';render();return;}
      if(name==='image_retry'){render();return;}
      if(name==='decrease'||name==='increase'){count=Math.max(0,Math.min(state.rows.find(r=>r.token===current).quantity,count+(name==='increase'?1:-1)));render();return;}
      if(name==='leave_skipped'){mode='missing';render();return;}
      if(name==='back'&&mode==='finish'){mode='missing';render();return;}
      if(name==='back')mode='part';
      if(name==='select')mode='part';
      const payload={action:name,token:token||current,operation:crypto.randomUUID(),session:state.session.id};
      if(name==='missing'){payload.action='answer';payload.found=0;}
      if(name==='set_count'){const line=state.rows.find(r=>r.token===token);if(!line||line.quantity===null)return;payload.found=line.quantity-Math.max(0,Math.min(line.quantity,(line.missing||0)+Number(delta)));}
      if(name==='answer')payload.found=count;
      if(name==='check_skipped'||name==='check_one'){payload.action='recheck';payload.token=null;if(name==='check_one')payload.tokens=[token];mode='part';}
      if(name==='spares_yes'||name==='spares_no'){payload.action='spares';payload.include=name==='spares_yes';mode='part';}
      if(name==='finish'&&!figureMode)payload.checked=!!root.querySelector('#set-checked')?.checked;
      const prior=clone(state);
      if(name==='undo') {
        mode='part';
        if(!undoStates.length&&!state.session.undo.length)return;
        if(undoStates.length)state=undoStates.pop();
      } else {undoStates.push(prior);apply(state,payload);}
      try {localStorage.setItem(stateKey,JSON.stringify(state));queue.add(payload);}
      catch(error){state=prior;status.textContent='Local storage is full. Free space and try again.';render();return;}
      clearTimeout(savedTimer);saveUndo.hidden=true;status.className='';status.textContent='Saving';render();
    }
    root.querySelector('[data-resume]')?.addEventListener('click',event=>{event.preventDefault();running=true;root.querySelector('[data-start]').hidden=true;body.hidden=false;render();});
    root.addEventListener('click',event=>{const b=event.target.closest('[data-action]');if(b&&!b.disabled)action(b.dataset.action,b.dataset.token,b.dataset.delta);});
    retry.onclick=()=>queue.flush();window.addEventListener('online',()=>queue.flush());
    document.addEventListener('keydown',event=>{
      if(!running||/INPUT|TEXTAREA|SELECT/.test(event.target.tagName)||event.target.isContentEditable||document.querySelector('dialog[open]'))return;
      const active=mode==='part'&&state.session&&state.session.cursor<state.session.order.length;
      const command=keyCommand(event.key,event.metaKey||event.ctrlKey,active,state.rows.find(r=>r.token===current)?.quantity??null);
      if(command){event.preventDefault();if(command.count!==undefined)count=command.count;if(command.action)action(command.action);else {root.dataset.direction='none';render();}}
    });
    body.hidden=!running;render();queue.flush();
  }
  document.addEventListener('DOMContentLoaded',()=>{document.querySelectorAll('[data-check-list]').forEach(lists);const root=document.querySelector('#bw-checker');if(root)mount(root);});
})();
