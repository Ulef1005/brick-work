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
    const query = [...url.searchParams].sort(([a, x], [b, y]) => a < b ? -1 : a > b ? 1 : x < y ? -1 : x > y ? 1 : 0).map(([k, v]) => encodeURIComponent(k) + '=' + encodeURIComponent(v)).join('&');
    return (path === '' ? '/' : path) + (query ? '?' + query : '');
  };
  const isPage = href => { try { const u = new URL(href, location.href); return Object.values(demo.pages).some(p => u.pathname === base + p); } catch (_) { return false; } };

  let toastTimer;
  function toast(text) {
    let box = document.getElementById('bw-demo-toast');
    if (!box) {
      box = document.createElement('p');
      box.id = 'bw-demo-toast'; box.setAttribute('role', 'status');
      box.style.cssText = 'position:fixed;left:50%;bottom:24px;transform:translateX(-50%);z-index:2147483647;margin:0;padding:12px 16px;border-radius:12px;background:var(--tw-toast-bg);color:var(--tw-toast-fg);font:500 14px/20px var(--tw-font),system-ui,sans-serif;max-width:calc(100% - 32px);text-align:center';
      document.body.append(box);
    }
    box.textContent = text; box.hidden = false;
    clearTimeout(toastTimer); toastTimer = setTimeout(() => { box.hidden = true; }, 3200);
  }

  // The banner: always visible, so nobody mistakes the demo for a live install; one line with the way to the install, the disclaimer under it.
  const BANNER_STYLE = '#bw-demo-banner{--bn-bg:#F1F1EE;--bn-fg:#1A1E1E;--bn-line:#C9CDC8;--bn-btn:#6D3FD1;--bn-on:#FFFFFF;margin:0;padding:8px 16px;background:var(--bn-bg);color:var(--bn-fg);border-bottom:1px solid var(--bn-line);font:500 13px/18px var(--tw-font),system-ui,sans-serif;text-align:center}'
    + '@media (prefers-color-scheme:dark){:root:not(.tw-light) #bw-demo-banner{--bn-bg:#262A29;--bn-fg:#E3E6E2;--bn-line:#3E4442;--bn-btn:#A98BF0;--bn-on:#14171A}}'
    + 'html.tw-dark #bw-demo-banner{--bn-bg:#262A29;--bn-fg:#E3E6E2;--bn-line:#3E4442;--bn-btn:#A98BF0;--bn-on:#14171A}'
    + '#bw-demo-banner a{color:inherit}#bw-demo-banner .bw-demo-install{display:inline-block;margin-left:8px;padding:2px 12px;border-radius:999px;background:var(--bn-btn);color:var(--bn-on);font-weight:600;text-decoration:none;white-space:nowrap}'
    + '#bw-demo-banner small{display:block;margin-top:2px;font:400 11px/15px var(--tw-font),system-ui,sans-serif;opacity:.8}'
    + '#bw-demo-start{--bn-bg:#FFFFFF;--bn-fg:#1A1E1E;--bn-line:#C9CDC8;margin:0;padding:10px 16px;background:var(--bn-bg);color:var(--bn-fg);border-bottom:1px solid var(--bn-line);font:400 14px/20px var(--tw-font),system-ui,sans-serif;text-align:center}'
    + '@media (prefers-color-scheme:dark){:root:not(.tw-light) #bw-demo-start{--bn-bg:#1F2322;--bn-fg:#E3E6E2;--bn-line:#3E4442}}html.tw-dark #bw-demo-start{--bn-bg:#1F2322;--bn-fg:#E3E6E2;--bn-line:#3E4442}'
    + '#bw-demo-start a{color:inherit;font-weight:600;white-space:nowrap}';
  document.addEventListener('DOMContentLoaded', () => {
    const style = document.createElement('style');
    style.textContent = BANNER_STYLE;
    document.head.append(style);
    const bar = document.createElement('p');
    bar.id = 'bw-demo-banner';
    bar.append('Demo with sample data, changes are not saved.');
    const install = document.createElement('a');
    install.className = 'bw-demo-install'; install.href = base.replace(/demo\/$/, 'install/'); install.textContent = 'Install it in 15 minutes';
    bar.append(install);
    const fine = document.createElement('small');
    fine.append('Set pictures: Rebrickable · LEGO® is a trademark of the LEGO Group of companies, which does not sponsor, authorize or endorse this site · ');
    const link = document.createElement('a');
    link.href = 'https://github.com/Ulef1005/brick-work'; link.textContent = 'Brick Work on GitHub';
    fine.append(link);
    bar.append(fine);
    // Under the site's top bar when the page has one (scripts/site_nav.py adds it to the built demo), else first.
    const top = document.querySelector('[data-bw-topbar]');
    if (top) top.after(bar); else document.body.prepend(bar);
    // The first screen says what the app is for and where to start (the Sets list is where every demo visit begins).
    if (keyOf(location.href) === '/collection/sets') {
      const start = document.createElement('p');
      start.id = 'bw-demo-start';
      start.append('Free, self-hosted app for your brick collection and its missing parts. Try: ');
      [['Set Inspector', 'workbench/check-parts/'], ['Build Scout', 'workbench/build-scout/'], ['Lot Sorter', 'workbench/lot-sorter/'], ['Order missing parts', 'planning/order-missing-parts/']].forEach(([name, path], index) => {
        const link = document.createElement('a');
        link.href = base + path; link.textContent = name;
        start.append(index ? ' · ' : '', link);
      });
      start.append('.');
      bar.after(start);
    }
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
  const kindOf = id => (demo.pictures && demo.pictures[id]) || 'png';   // a picture that is not a PNG is listed in the manifest
  const pngOf = value => {
    const found = /^(.*\/manage\/images\/([1-9][0-9]*))(?:\?.*)?$/.exec(String(value));
    return found ? found[1] + '.' + kindOf(found[2]) : value;
  };
  const srcProperty = Object.getOwnPropertyDescriptor(HTMLImageElement.prototype, 'src');
  Object.defineProperty(HTMLImageElement.prototype, 'src', {configurable: true, enumerable: true, get: srcProperty.get, set(value) { srcProperty.set.call(this, pngOf(value)); }});
  const pngSet = value => String(value).replace(/(\/manage\/images\/([1-9][0-9]*))\?w=[0-9]+/g, (all, stem, id) => stem + '.' + kindOf(id));
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
  // A write the demo refuses must not read like a broken install: the Set Inspector's "Not saved · waiting for network" and Jump's "Search unavailable"
  // say what the demo does instead, and the retry button that could never succeed is hidden.
  const REWRITE = [[/^Not saved · waiting for network.*$/, 'Demo: this answer is shown here and not saved'], [/^Search unavailable\. Try again\.$/, 'Search is not part of the demo'],
    [/^Authentication disabled$/, 'Demo: nothing is saved'], [/^(Set and part data from Rebrickable) · \d+ ?m?s$/, '$1']];
  function calmNode(node) {
    const text = node.nodeValue.trim();
    for (const [pattern, say] of REWRITE) if (pattern.test(text)) { node.nodeValue = text.replace(pattern, say); node.parentElement?.closest('[data-save-status]')?.parentElement?.querySelectorAll('[data-retry]').forEach(b => { b.hidden = true; }); }
  }
  function calmTree(root) {
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
    for (let node = walker.nextNode(); node; node = walker.nextNode()) calmNode(node);
  }
  document.addEventListener('DOMContentLoaded', () => {
    calmTree(document.body);   // the text the server rendered (the footer) is rewritten once, before the observer takes over
    new MutationObserver(records => records.forEach(r => {
      if (r.type === 'characterData') calmNode(r.target);
      else r.addedNodes.forEach(n => { if (n.nodeType === 3) calmNode(n); else if (n.nodeType === 1) calmTree(n); });
    })).observe(document.body, {childList: true, subtree: true, characterData: true});
  });

  window.BrickWorkDemo = {keyOf, toast, note: demo.note};
})();
