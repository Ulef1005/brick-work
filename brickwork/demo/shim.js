/* Brick Work static demo: loaded first on every exported page (brickwork/demo/export.py).
   Reads the pages make are answered from the saved JSON; every write is answered with "not saved";
   links to pages outside the demo say so instead of failing. No storage, no network beyond this site. */
(() => {
  'use strict';
  const demo = /*MANIFEST*/null;
  const base = demo.base;
  const keyOf = href => {
    let url;
    try { url = new URL(href, location.href); } catch (_) { return null; }
    if (url.origin !== location.origin || !url.pathname.startsWith(base)) return null;
    const path = '/' + url.pathname.slice(base.length).replace(/\/(index\.html)?$/, '');
    const query = [...url.searchParams].sort(([a], [b]) => a < b ? -1 : a > b ? 1 : 0).map(([k, v]) => encodeURIComponent(k) + '=' + encodeURIComponent(v)).join('&');
    return (path === '' ? '/' : path) + (query ? '?' + query : '');
  };
  const isPage = href => { try { const u = new URL(href, location.href); return Object.values(demo.pages).some(p => u.pathname === base + p); } catch (_) { return false; } };

  let toastTimer;
  function toast(text) {
    let box = document.getElementById('bw-demo-toast');
    if (!box) {
      box = document.createElement('p');
      box.id = 'bw-demo-toast'; box.setAttribute('role', 'status');
      box.style.cssText = 'position:fixed;left:50%;bottom:24px;transform:translateX(-50%);z-index:2147483647;margin:0;padding:12px 16px;border-radius:12px;background:#1A1816;color:#FAFAF8;font:500 14px/20px Inter,system-ui,sans-serif;max-width:calc(100% - 32px);text-align:center';
      document.body.append(box);
    }
    box.textContent = text; box.hidden = false;
    clearTimeout(toastTimer); toastTimer = setTimeout(() => { box.hidden = true; }, 3200);
  }

  // The banner: always visible, so nobody mistakes the demo for a live install.
  document.addEventListener('DOMContentLoaded', () => {
    const bar = document.createElement('p');
    bar.id = 'bw-demo-banner';
    bar.style.cssText = 'margin:0;padding:8px 16px;background:#E8E2D6;color:#1A1816;font:500 13px/18px Inter,system-ui,sans-serif;text-align:center';
    bar.append('Demo with sample data · changes are not saved · Pictures are placeholder drawings; a real install loads them from BrickLink and Rebrickable · ');
    const link = document.createElement('a');
    link.href = 'https://github.com/Ulef1005/brick-work'; link.textContent = 'Brick Work on GitHub'; link.style.color = 'inherit';
    bar.append(link);
    const website = document.createElement('a');
    website.href = 'https://ulef1005.github.io/brick-work/'; website.textContent = 'Website'; website.style.color = 'inherit';
    bar.append(' · ', website);
    document.body.prepend(bar);
  });

  const realFetch = window.fetch.bind(window);
  window.fetch = async (input, init = {}) => {
    const href = typeof input === 'string' ? input : input.url;
    const method = (init.method || (typeof input === 'object' && input.method) || 'GET').toUpperCase();
    const key = keyOf(href);
    const json = (status, body) => new Response(JSON.stringify(body), {status, headers: {'Content-Type': 'application/json'}});
    if (method !== 'GET' && method !== 'HEAD') { toast(demo.note); return json(403, {message: demo.note}); }
    if (key && demo.gets[key]) return realFetch(base + demo.gets[key]);
    if (key && !key.startsWith('/static/')) return json(404, {message: 'Not part of the demo'});
    return realFetch(input, init);
  };

  // Links: script-built rows carry app routes; send them to the exported page or say it is not included.
  document.addEventListener('click', event => {
    const link = event.target.closest && event.target.closest('a[href]');
    if (!link || link.target === '_blank' || event.defaultPrevented) return;
    const raw = link.getAttribute('href');
    if (raw === '#demo-not-included') { event.preventDefault(); toast('Not part of the demo'); return; }
    if (raw.startsWith('#') || isPage(link.href)) return;
    const key = keyOf(link.href);
    if (key === null || key.startsWith('/static/')) return;
    event.preventDefault();
    if (demo.pages[key]) location.href = base + demo.pages[key];
    else toast('Not part of the demo');
  }, true);

  // Forms: Start on a copy opens its running check, a GET form opens the exported result page,
  // anything else would post to the server and says it is not saved.
  document.addEventListener('submit', event => {
    if (event.defaultPrevented) return;
    const form = event.target, method = (form.getAttribute('method') || 'get').toLowerCase();
    const here = keyOf(location.href);
    let target = null;
    if (method === 'post' && form.querySelector('input[name=action][value=start]') && here) target = here.split('?')[0] + '?run=1';
    if (method === 'get') {
      const url = new URL(form.getAttribute('action') || location.pathname, location.href);
      url.search = new URLSearchParams(new FormData(form, event.submitter)).toString();
      target = keyOf(url.href);
    }
    event.preventDefault();
    if (target && demo.pages[target]) location.href = base + demo.pages[target];
    else toast(method === 'get' ? 'Not part of the demo' : demo.note);
  }, true);

  // Pictures: a page's script builds /manage/images/<id>?w=... from the page's image base; the demo keeps one <id>.png per picture.
  const pngOf = value => {
    const found = /^(.*\/manage\/images\/[1-9][0-9]*)(?:\?.*)?$/.exec(String(value));
    return found ? found[1] + '.png' : value;
  };
  const srcProperty = Object.getOwnPropertyDescriptor(HTMLImageElement.prototype, 'src');
  Object.defineProperty(HTMLImageElement.prototype, 'src', {configurable: true, enumerable: true, get: srcProperty.get, set(value) { srcProperty.set.call(this, pngOf(value)); }});
  const pngSet = value => String(value).replace(/(\/manage\/images\/[1-9][0-9]*)\?w=[0-9]+/g, '$1.png');
  const srcsetProperty = Object.getOwnPropertyDescriptor(HTMLImageElement.prototype, 'srcset');
  Object.defineProperty(HTMLImageElement.prototype, 'srcset', {configurable: true, enumerable: true, get: srcsetProperty.get, set(value) { srcsetProperty.set.call(this, pngSet(value)); }});
  const setAttribute = Element.prototype.setAttribute;
  Element.prototype.setAttribute = function (name, value) {
    if (this instanceof HTMLImageElement && name === 'src') value = pngOf(value);
    if (this instanceof HTMLImageElement && name === 'srcset') value = pngSet(value);
    return setAttribute.call(this, name, value);
  };
  // An <img> a script wrote as HTML starts loading before any setter runs: when it fails, it is tried as the .png.
  document.addEventListener('error', event => {
    const image = event.target;
    if (!(image instanceof HTMLImageElement)) return;
    if (image.hasAttribute('srcset') && pngSet(image.getAttribute('srcset')) !== image.getAttribute('srcset')) image.srcset = image.getAttribute('srcset');
    if (pngOf(image.getAttribute('src')) !== image.getAttribute('src')) image.src = image.getAttribute('src');
  }, true);
  // No service worker: a static demo must not cache itself as the app.
  if (navigator.serviceWorker) {
    navigator.serviceWorker.register = () => Promise.resolve({unregister: () => Promise.resolve(true)});
    navigator.serviceWorker.getRegistrations?.().then(list => list.forEach(r => r.unregister())).catch(() => {});
  }
  // Missing-picture tiles: the demo has no pictures (they belong to others), so each tile says where the
  // app gets them. Verified in the app: adding a set loads the set's picture (BrickLink, then Rebrickable);
  // part and minifigure pictures load with Tools & Admin > Refresh pictures (Rebrickable, then BrickLink).
  const PICTURE_NOTE = {
    set: 'Loads from BrickLink when you add the set',
    other: 'Loads from Rebrickable or BrickLink with Refresh pictures',
  };
  const setNumber = /^\d+[A-Za-z]?-\d+$/;
  const NOTE_MIN_WIDTH = 120;
  const NOTE_BOXES = '.bc-picture,.bw-picture,.check-picture,.scan-tile';
  function pictureNote(span) {
    const tile = span.closest('[data-item-no],[data-kind],.bc-picture,.bw-picture,.check-picture,.scan-tile') || span.parentElement;
    const kind = tile && tile.dataset ? tile.dataset.kind : null;
    const number = (tile && tile.dataset && tile.dataset.itemNo) || (tile && tile.querySelector('.mono')?.textContent) || '';
    const isSet = kind ? kind === 'S' : setNumber.test(number.trim());
    // #197: the sentence needs room, so it goes only into a picture box the pages draw large (a card's or a detail page's picture)
    // that is at least 120 px wide. Anything else, such as a list row's 56 px thumbnail, keeps the app's short "No image".
    const box = span.closest(NOTE_BOXES);
    if (!box || box.getBoundingClientRect().width < NOTE_MIN_WIDTH) return;
    span.textContent = isSet ? PICTURE_NOTE.set : PICTURE_NOTE.other;
    span.classList.add('bw-demo-picture-note');
  }
  function notePictures(root) {
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
    const found = [];
    for (let node = walker.nextNode(); node; node = walker.nextNode()) {
      if (node.nodeValue.trim() === 'No image' && node.parentElement) found.push(node.parentElement);
    }
    found.forEach(pictureNote);
  }
  document.addEventListener('DOMContentLoaded', () => {
    const style = document.createElement('style');
    style.textContent = '.bw-demo-picture-note{font-size:11px;line-height:14px;text-align:center;padding:0 6px;color:var(--tw-text-muted,#6b6660)}';
    document.head.append(style);
    notePictures(document.body);
    new MutationObserver(records => records.forEach(r => r.addedNodes.forEach(n => {
      if (n.nodeType === 1) notePictures(n);
      else if (n.nodeType === 3 && n.nodeValue.trim() === 'No image' && n.parentElement) pictureNote(n.parentElement);
    }))).observe(document.body, {childList: true, subtree: true});
  });

  window.BrickWorkDemo = {keyOf, toast, note: demo.note};
})();
