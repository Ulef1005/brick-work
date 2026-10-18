/* #45 What is this?: one photo → candidates with what you already own of each. */
(function () {
  const root = typeof document.querySelector === 'function' ? document.querySelector('[data-wi-root]') : null;
  if (!root) return;
  const file = root.querySelector('[data-wi-file]'), status = root.querySelector('[data-wi-status]'), results = root.querySelector('[data-wi-results]');
  const el = (tag, text, cls) => { const n = document.createElement(tag); if (text != null) n.textContent = text; if (cls) n.className = cls; return n; };
  const link = (text, href, cls) => { const a = el('a', text, cls); a.href = href; return a; };
  // Ink on a colour chip: dark ink on light colours, light ink on dark ones (relative luminance).
  const ink = rgb => { const v = [0, 2, 4].map(i => parseInt(rgb.slice(i, i + 2), 16) / 255).map(c => c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4);
    return 0.2126 * v[0] + 0.7152 * v[1] + 0.0722 * v[2] > 0.4 ? '#1A1816' : '#FAFAF8'; };
  function card(c) {
    const article = el('article', null, 'wi-card');
    const pic = el('div', null, 'wi-pic');
    if (c.image) { const img = el('img'); img.src = '/manage/images/' + c.image + '?w=320'; img.alt = c.name || c.item_no; img.loading = 'lazy'; pic.append(img); }
    else pic.append(el('span', 'No image', 'secondary'));
    const body = el('div', null, 'wi-body');
    body.append(el('span', c.item_no + ' · ' + (c.score != null ? c.score.toFixed(2) + ' match' : ''), 'mono wi-number'), el('h2', c.name || c.item_no, 'wi-name'));
    const owned = c.owned_summary || {text: 'Not in your collection', colours: [], needed_count: 0};
    const have = el('p', owned.text, owned.total ? 'wi-owned' : 'wi-owned wi-none'); body.append(have);
    if ((owned.colours || []).length) {
      const list = el('ul', null, 'wi-colours');
      owned.colours.slice(0, 8).forEach(o => {
        const li = el('li'); const chip = el('span', o.name || 'No colour', 'wi-chip');
        if (o.rgb) { chip.style.background = '#' + o.rgb; chip.style.color = ink(o.rgb); }
        li.append(chip, el('span', String(o.quantity), 'mono'), el('span', (o.storages || []).join(', ') || 'Not stored', 'secondary'));
        list.append(li);
      });
      body.append(list);
    }
    const actions = el('div', null, 'wi-card-actions');
    if (root.dataset.csrf) actions.append(link('Add to stock', '/manage/add?type=' + encodeURIComponent(c.item_type) + '&where=loose&number=' + encodeURIComponent(c.item_no), 'button'));
    actions.append(link('Open ' + (c.item_type === 'M' ? 'minifigure' : 'part'), '/collection/item/' + encodeURIComponent(c.item_type) + '/' + encodeURIComponent(c.item_no), 'button'));
    if (owned.needed_count) actions.append(link('Fill a missing part · ' + owned.needed_count + (owned.needed_count === 1 ? ' copy' : ' copies'), '/workbench/matcher', 'button'));
    body.append(actions);
    article.append(pic, body);
    return article;
  }
  async function identify(photo) {
    const form = new FormData();
    form.append('file', photo); form.append('csrf_token', root.dataset.csrf);
    const checked = root.querySelector('input[name=wi-endpoint]:checked');
    form.append('endpoint', checked ? checked.value : 'parts');
    status.textContent = 'Identifying'; results.replaceChildren();
    try {
      const response = await fetch(root.dataset.url, {method: 'POST', body: form, credentials: 'same-origin'});
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || 'Could not recognise this photo');
      status.textContent = data.candidates.length + (data.candidates.length === 1 ? ' match' : ' matches') + ' · best first';
      data.candidates.forEach(c => results.append(card(c)));
    } catch (error) { status.textContent = error.message || 'Could not recognise this photo · try again'; }
  }
  file.addEventListener('change', () => { if (file.files && file.files[0]) identify(file.files[0]); });
  window.BrickWhatIs = {card};
})();
