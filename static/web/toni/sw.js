/* Shell assets only. Collection pages and API responses are never stored. */
const CACHE = 'brickwork-shell-4.1a-__ASSET_VERSION__';
const ASSETS = [
  "/static/brickwork/app-icon.svg",
  "/static/brickwork/brick-work.css",
  "/static/brickwork/favicon-16.png",
  "/static/brickwork/favicon-32.png",
  "/static/brickwork/favicon-48.png",
  "/static/brickwork/favicon-small-cut.svg",
  "/static/brickwork/favicon.svg",
  "/static/brickwork/icons-ui/add.svg",
  "/static/brickwork/icons-ui/auto.svg",
  "/static/brickwork/icons-ui/back.svg",
  "/static/brickwork/icons-ui/box.svg",
  "/static/brickwork/icons-ui/check.svg",
  "/static/brickwork/icons-ui/chev.svg",
  "/static/brickwork/icons-ui/chevd.svg",
  "/static/brickwork/icons-ui/close.svg",
  "/static/brickwork/icons-ui/cog.svg",
  "/static/brickwork/icons-ui/done.svg",
  "/static/brickwork/icons-ui/edit.svg",
  "/static/brickwork/icons-ui/ext.svg",
  "/static/brickwork/icons-ui/filter.svg",
  "/static/brickwork/icons-ui/grid.svg",
  "/static/brickwork/icons-ui/instr.svg",
  "/static/brickwork/icons-ui/list.svg",
  "/static/brickwork/icons-ui/manage.svg",
  "/static/brickwork/icons-ui/match.svg",
  "/static/brickwork/icons-ui/minifig.svg",
  "/static/brickwork/icons-ui/minus.svg",
  "/static/brickwork/icons-ui/moon.svg",
  "/static/brickwork/icons-ui/orders.svg",
  "/static/brickwork/icons-ui/parts.svg",
  "/static/brickwork/icons-ui/pick.svg",
  "/static/brickwork/icons-ui/price.svg",
  "/static/brickwork/icons-ui/scan.svg",
  "/static/brickwork/icons-ui/search.svg",
  "/static/brickwork/icons-ui/sets.svg",
  "/static/brickwork/icons-ui/sort.svg",
  "/static/brickwork/icons-ui/sprite.svg",
  "/static/brickwork/icons-ui/storage.svg",
  "/static/brickwork/icons-ui/sun.svg",
  "/static/brickwork/icons-ui/tick.svg",
  "/static/brickwork/icons-ui/tools.svg",
  "/static/brickwork/icons-ui/wish.svg",
  "/static/brickwork/icons/icon-1024.png",
  "/static/brickwork/icons/icon-152.png",
  "/static/brickwork/icons/icon-180.png",
  "/static/brickwork/icons/icon-192.png",
  "/static/brickwork/icons/icon-512.png",
  "/static/brickwork/icons/icon-maskable-192.png",
  "/static/brickwork/icons/icon-maskable-512.png",
  "/static/brickwork/lockup-horizontal-dark.svg",
  "/static/brickwork/lockup-horizontal.svg",
  "/static/brickwork/lockup-stacked-dark.svg",
  "/static/brickwork/lockup-stacked.svg",
  "/static/brickwork/mark-dark.svg",
  "/static/brickwork/mark-line.svg",
  "/static/brickwork/mark.svg",
  "/static/web/toni/bw-add.css",
  "/static/web/toni/bw-add.js",
  "/static/web/toni/bw-admin.css",
  "/static/web/toni/bw-admin.js",
  "/static/web/toni/bw-tokens.css",
  "/static/web/toni/bw-tokens.js",
  "/static/web/toni/bw-checker.css",
  "/static/web/toni/bw-checker.js",
  "/static/web/toni/bw-collection.css",
  "/static/web/toni/bw-collection.js",
  "/static/web/toni/size-search.js",
  "/static/web/toni/bw-whatis.js",
  "/static/web/toni/bw-whatis.css",
  "/static/web/toni/bw-print.css",
  "/static/web/toni/bw-print.js",
  "/static/web/toni/bw-places.js",
  "/static/web/toni/bw-sync.js",
  "/static/web/toni/bw-sync.css",
  "/static/web/toni/bw-options-menu.js",
  "/static/web/toni/bw-inventory.css",
  "/static/web/toni/bw-inventory.js",
  "/static/web/toni/bw-ledger.css",
  "/static/web/toni/bw-ledger.js",
  "/static/web/toni/bw-pictures.js",
  "/static/web/toni/bw-planning.css",
  "/static/web/toni/bw-planning.js",
  "/static/web/toni/bw-prices.js",
  "/static/web/toni/bw-take.js",
  "/static/web/toni/bw-workbench.css",
  "/static/web/toni/bw-workbench.js",
  "/static/web/toni/fonts/geist-mono-latin-400-normal.woff2",
  "/static/web/toni/fonts/geist-mono-latin-500-normal.woff2",
  "/static/web/toni/fonts/inter-latin-400-normal.woff2",
  "/static/web/toni/fonts/inter-latin-500-normal.woff2",
  "/static/web/toni/fonts/inter-latin-600-normal.woff2",
  "/static/web/toni/formatting.js",
  "/static/web/toni/images.js",
  "/static/web/toni/import-progress.js",
  "/static/web/toni/jump.js",
  "/static/web/toni/offline.html",
  "/static/web/toni/pwa.js",
  "/static/web/toni/remaining.css",
  "/static/web/toni/remaining.js",
  "/static/web/toni/shell.css",
  "/static/web/toni/shell.js",
  "/static/web/toni/theme.js",
  "/static/web/toni/tokens-v2.css",
  "/static/web/toni/toni.css"
];
const OFFLINE = '/static/web/toni/offline.html';
self.addEventListener('install', event => {
 event.waitUntil(caches.open(CACHE).then(cache => cache.addAll(ASSETS)).then(() => self.skipWaiting()));
});
self.addEventListener('activate', event => {
 event.waitUntil(caches.keys().then(names => Promise.all(names.filter(name => name.startsWith('brickwork-shell-') && name !== CACHE).map(name => caches.delete(name)))).then(() => self.clients.claim()));
});
self.addEventListener('fetch', event => {
 const request = event.request, url = new URL(request.url);
 // Do not intercept writes, API, uploads, user images or live transport.
 if (request.method !== 'GET' || url.origin !== self.location.origin ||
     url.pathname.startsWith('/api/') || url.pathname.startsWith('/socket.io') || /(?:^|\/)(?:data|uploads?|socket\.io)(?:\/|$)/.test(url.pathname)) return;
 if (request.mode === 'navigate') {
  event.respondWith(fetch(request).catch(() => caches.open(CACHE).then(cache => cache.match(OFFLINE))));
 } else if (ASSETS.includes(url.pathname)) {
  // Versioned assets (?v=) must match exactly, or a new page runs with the old JS once after each deploy.
  // The precached, unversioned copy is the offline fallback only.
  event.respondWith(caches.open(CACHE).then(cache => cache.match(request).then(hit => hit || fetch(request).then(response => {
   if (response.ok) cache.put(request, response.clone());
   return response;
  }).catch(() => cache.match(request, {ignoreSearch: true}).then(cached => cached || Response.error())))));
 }
});
