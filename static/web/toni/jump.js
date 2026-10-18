/* Native dialog focus containment/Escape comes from the shell. User data is
   assigned only through textContent; catalogue names never become markup. */
(() => {
 const dialog = document.getElementById('global-jump');
 if (!dialog) return;
 const input = document.getElementById('jump-query');
 const results = document.getElementById('jump-results');
 const message = document.getElementById('jump-message');
 let timer, controller, version = 0, links = [], selected = -1;
 const text = (tag, value, cls) => {
  const node = document.createElement(tag);
  node.textContent = value;
  if (cls) node.className = cls;
  return node;
 };
 function choose(index, focus = false) {
  selected = index;
  links.forEach((link, i) => link.classList.toggle('selected', i === index));
  if (selected >= 0) {
   links[selected].scrollIntoView({block: 'nearest'});
   if (focus) links[selected].focus();
  }
 }
 function row(parent, label, description, url) {
  const link = text('a', '', 'jump-copy');
  link.href = url;
  const body = text('span', '', 'stack');
  body.append(text('strong', label), text('span', description, 'secondary'));
  link.append(body);
  link.addEventListener('focus', () => choose(links.indexOf(link)));
  parent.append(link); links.push(link);
 }
 function paint(data) {
  results.replaceChildren(); links = []; selected = -1;
  for (const item of data.results) {
   if (dialog.dataset.check === 'true' && item.kind !== 'set') continue;
   const panel = text('section', '', 'jump-result');
   const head = text('div', '', 'jump-result-head');
   const tile = text('div', 'No image', 'jump-image tw-light');
   if (item.image) {
    const img = document.createElement('img');
    // Accept only web/local image URLs; reject executable or arbitrary schemes.
    const source = new URL(item.image, location.origin);
    if (['http:', 'https:'].includes(source.protocol)) {
     img.src = source.href; img.alt = ''; img.loading = 'lazy';
     img.addEventListener('error', () => tile.replaceChildren(text('span', 'No image')));
     tile.replaceChildren(img);
    }
   }
   const info = text('div', '', 'stack');
   const type = item.type_label || {set: 'Owned', wanted: 'Wanted', minifigure: 'Loose figure', part: 'Loose part'}[item.kind];
   info.append(text('p', `${item.number} · ${type}`, 'mono secondary'), text('h3', item.name || item.number));
   if (item.kind === 'set') info.append(text('p', `${item.copies.length} ${item.copies.length === 1 ? 'copy' : 'copies · choose the one in hand'}`, 'secondary'));
   head.append(tile, info); panel.append(head);
   if (item.kind === 'set') {
    item.copies.forEach((copy, i) => {
     if (dialog.dataset.check === 'true' && !copy.check_url) return;
     const condition = {N: 'New', U: 'Used'}[copy.condition] || 'Condition not recorded';
     const completeness = {S: 'Sealed', C: 'Complete', I: 'Incomplete'}[copy.completeness] || 'Not checked';
     row(panel, `Set ${i + 1} · ${condition} · ${completeness}`,
         copy.missing_label || '', dialog.dataset.check === 'true' ? copy.check_url : copy.url);
    });
   } else {
    row(panel, `Open ${item.kind === 'wanted' ? (item.item_type ? 'wish' : 'wanted set') : item.kind}`,
        item.item_type && item.kind==='wanted' ? `${item.quantity} wanted${item.color_name ? ' · ' + item.color_name : ''}` : item.quantity == null ? (item.item_type ? 'No loose stock' : 'Wanted set') : `${item.quantity} loose${item.color_name ? ' · ' + item.color_name : ''}`, item.url);
   }
   results.append(panel);
  }
  message.textContent = data.results.length ? `${data.results.length} results${data.truncated ? ' · refine your search for more' : ''}` : 'No matches.';
  if (links.length) choose(0);
 }
 async function search(ticket) {
  controller = new AbortController();
  const url = new URL(dialog.dataset.url, location.origin);
  url.searchParams.set('q', input.value.trim());
  try {
   const response = await fetch(url, {signal: controller.signal, credentials: 'same-origin', headers: {'Accept': 'application/json'}});
   if (ticket !== version || !dialog.open) return;
   if (response.redirected || response.status === 401) {
    message.replaceChildren(text('span', 'Log in to search your collection. '));
    // Return to the current page after login, never to the JSON endpoint.
    const login = text('a', 'Log in'); login.href = '/login?next=' + encodeURIComponent(location.pathname + location.search); message.append(login); return;
   }
   if (!response.ok) throw new Error('Search failed');
   const data = await response.json();
   if (ticket === version && dialog.open) paint(data);
  } catch (error) {
   if (error.name !== 'AbortError' && ticket === version) message.textContent = 'Search unavailable. Try again.';
  }
 }
 input.addEventListener('input', () => {
  clearTimeout(timer); controller?.abort(); const ticket = ++version;
  results.replaceChildren(); links = []; selected = -1;
  if (!input.value.trim()) {message.textContent = ''; return;}
  message.textContent = 'Searching…'; timer = setTimeout(() => search(ticket), 180);
 });
 dialog.addEventListener('keydown', event => {
  if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
   if (!links.length) return;
   event.preventDefault();
   choose((selected + (event.key === 'ArrowDown' ? 1 : -1) + links.length) % links.length, document.activeElement !== input);
  } else if (event.key === 'Enter' && document.activeElement === input && selected >= 0) {
   event.preventDefault(); links[selected].click();
  }
 });
 dialog.addEventListener('shell-open', () => {
  dialog.setAttribute('aria-label', dialog.dataset.check === 'true' ? 'Choose a set to check' : 'Jump to a set, copy, figure or part');
  input.focus();
  if (input.value.trim()) input.dispatchEvent(new Event('input'));
 });
 dialog.addEventListener('close', () => {clearTimeout(timer); controller?.abort(); ++version;});
 document.addEventListener('keydown', event => {
  if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'k') {
   event.preventDefault();
   if (!dialog.open) window.adminShell.open(dialog, document.activeElement);
   input.focus();
  }
 });
})();
