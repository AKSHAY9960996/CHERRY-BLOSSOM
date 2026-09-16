// Admin PWA Service Worker
// Caches admin shell pages for offline fallback and fast repeat loads

const CACHE_NAME = 'admin-shell-v1';

// Resources to pre-cache on install
const PRECACHE_URLS = [
  '/admin',
  '/admin/orders',
  '/admin/products',
  '/static/css/admin.css',
  '/static/admin-icons/icon-192.png',
  '/static/admin-icons/icon-512.png',
];

// ── Install ──────────────────────────────────────────────────────────────────
self.addEventListener('install', event => {
  event.waitUntil(
    caches.open(CACHE_NAME).then(cache => {
      return cache.addAll(PRECACHE_URLS).catch(err => {
        console.warn('[Admin SW] Pre-cache failed for some URLs:', err);
      });
    })
  );
  self.skipWaiting();
});

// ── Activate ─────────────────────────────────────────────────────────────────
self.addEventListener('activate', event => {
  event.waitUntil(
    caches.keys().then(keys =>
      Promise.all(
        keys.filter(k => k !== CACHE_NAME).map(k => caches.delete(k))
      )
    )
  );
  self.clients.claim();
});

// ── Fetch ─────────────────────────────────────────────────────────────────────
// Strategy: Network-first for admin pages (always fresh data),
//           Cache-first for static assets.
self.addEventListener('fetch', event => {
  const { request } = event;
  const url = new URL(request.url);

  // Only handle same-origin requests
  if (url.origin !== location.origin) return;

  // Static assets → Cache-first
  if (url.pathname.startsWith('/static/')) {
    event.respondWith(
      caches.match(request).then(cached => {
        if (cached) return cached;
        return fetch(request).then(response => {
          if (response.ok) {
            const clone = response.clone();
            caches.open(CACHE_NAME).then(c => c.put(request, clone));
          }
          return response;
        });
      })
    );
    return;
  }

  // Admin pages → Network-first with offline fallback
  if (url.pathname.startsWith('/admin')) {
    event.respondWith(
      fetch(request)
        .then(response => {
          // Cache successful GET responses for offline fallback
          if (request.method === 'GET' && response.ok) {
            const clone = response.clone();
            caches.open(CACHE_NAME).then(c => c.put(request, clone));
          }
          return response;
        })
        .catch(() => {
          // Offline: serve cached version if available
          return caches.match(request).then(cached => {
            if (cached) return cached;
            // Final fallback — serve cached dashboard
            return caches.match('/admin');
          });
        })
    );
  }
});

// ── Push Notifications ───────────────────────────────────────────────────────
self.addEventListener('push', event => {
  const data = event.data ? event.data.json() : {};
  const title = data.title || '🛍️ New Order!';
  const options = {
    body: data.body || 'You have a new order. Tap to view.',
    icon: '/static/admin-icons/icon-192.png',
    badge: '/static/admin-icons/icon-72.png',
    tag: data.tag || 'admin-notification',
    requireInteraction: true,
    data: { url: data.url || '/admin/orders' }
  };
  event.waitUntil(self.registration.showNotification(title, options));
});

// ── Notification Click ───────────────────────────────────────────────────────
self.addEventListener('notificationclick', event => {
  event.notification.close();
  const targetUrl = (event.notification.data && event.notification.data.url)
    ? event.notification.data.url
    : '/admin/orders';
  event.waitUntil(
    clients.matchAll({ type: 'window', includeUncontrolled: true }).then(list => {
      for (const client of list) {
        if (client.url.includes('/admin') && 'focus' in client) {
          client.navigate(targetUrl);
          return client.focus();
        }
      }
      if (clients.openWindow) return clients.openWindow(targetUrl);
    })
  );
});
