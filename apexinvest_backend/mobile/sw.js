/* ApexInvest mobile service worker.
 * Caches ONLY the static app shell so the app opens instantly / installs as a PWA.
 * It never caches or intercepts /v1/* (analysis results always come live from the engine),
 * and it is network-first so an updated app is picked up immediately when online. */
const CACHE = 'apex-m-shell-v1';
const SHELL = ['./', 'index.html', 'app.css', 'app.js', 'i18n.js', 'manifest.webmanifest', 'icons/icon-192.png', 'icons/icon-512.png'];

self.addEventListener('install', (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL)).then(() => self.skipWaiting()));
});
self.addEventListener('activate', (e) => {
  e.waitUntil(caches.keys().then((ks) => Promise.all(ks.filter((k) => k !== CACHE).map((k) => caches.delete(k)))).then(() => self.clients.claim()));
});
self.addEventListener('fetch', (e) => {
  const req = e.request, url = new URL(req.url);
  if (req.method !== 'GET' || url.origin !== location.origin || !url.pathname.startsWith('/m/')) return; // API & desktop untouched
  e.respondWith(
    fetch(req).then((res) => {
      if (res.ok) { const copy = res.clone(); caches.open(CACHE).then((c) => c.put(req, copy)); }
      return res;
    }).catch(() => caches.match(req).then((hit) => hit || caches.match('index.html')))
  );
});
