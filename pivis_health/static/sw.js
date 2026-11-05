const CACHE = 'pivis-v2';
const SHELL = ['/static/pivis-ui.css'];

self.addEventListener('install', (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL)).then(() => self.skipWaiting()));
});

self.addEventListener('activate', (e) => {
  e.waitUntil(
    caches.keys().then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

// 离线降级：页面导航失败时回缓存副本（数据层 JSON 也可短缓存 5 分钟）
self.addEventListener('fetch', (e) => {
  const url = new URL(e.request.url);
  if (e.request.method !== 'GET') return;
  if (url.pathname.startsWith('/v2/') || url.pathname === '/static/pivis-ui.css') {
    e.respondWith(
      fetch(e.request).then((res) => {
        const copy = res.clone();
        caches.open(CACHE).then((c) => c.put(e.request, copy));
        return res;
      }).catch(() => caches.match(e.request))
    );
  }
});

// Web Push：通知点击 → 打开对应页
self.addEventListener('push', (event) => {
  let data = {};
  try { data = event.data.json(); } catch (err) { data = { title: 'pivis health', body: event.data.text() }; }
  event.waitUntil(self.registration.showNotification(data.title || 'P-Health', {
    body: data.body || '',
    tag: data.tag || 'pivis',
    data: { url: data.url || '/v2/now' },
    requireInteraction: !!data.sticky,
  }));
});

self.addEventListener('notificationclick', (event) => {
  event.notification.close();
  const url = (event.notification.data && event.notification.data.url) || '/v2/now';
  event.waitUntil(clients.matchAll({ type: 'window' }).then((wins) => {
    for (const w of wins) { if ('focus' in w) { w.navigate(url); return w.focus(); } }
    return clients.openWindow(url);
  }));
});
