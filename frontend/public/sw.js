// The DIUCS service worker (W32). Logic is in sw-logic.js, which is tested as shipped.
importScripts('/sw-logic.js');

var CACHE = 'diucs-shell-v1';
var logic = self.DiucsSw;

self.addEventListener('install', function (event) {
  // Precache the offline page only. Nothing else is stored up front.
  event.waitUntil(caches.open(CACHE).then(function (cache) { return cache.add(logic.OFFLINE); }));
  self.skipWaiting();
});

self.addEventListener('activate', function (event) {
  event.waitUntil(self.clients.claim());
});

self.addEventListener('fetch', function (event) {
  var request = event.request;
  if (request.mode === 'navigate') {
    event.respondWith(
      fetch(request).catch(function () {
        return caches.match(logic.OFFLINE).then(function (hit) {
          return hit || new Response('No connection', { status: 503 });
        });
      }),
    );
    return;
  }
  if (logic.isCacheable(request)) {
    event.respondWith(
      caches.match(request).then(function (hit) {
        return hit || fetch(request).then(function (response) {
          if (response.ok) caches.open(CACHE).then(function (cache) { cache.put(request, response.clone()); });
          return response;
        });
      }),
    );
  }
});

self.addEventListener('push', function (event) {
  var data = {};
  try {
    data = event.data ? event.data.json() : {};
  } catch {
    data = {};
  }
  var shown = logic.handlePush(data);
  event.waitUntil(self.registration.showNotification(shown.title, { body: shown.body, data: shown.data }));
});

self.addEventListener('notificationclick', function (event) {
  event.notification.close();
  var url = event.notification.data && event.notification.data.url;
  event.waitUntil(
    self.clients.matchAll({ type: 'window', includeUncontrolled: true }).then(function (clients) {
      var urls = clients.map(function (client) { return client.url; });
      var choice = logic.pickClientOrOpen(urls, url, self.location.origin);
      if (choice.kind === 'focus') return clients[choice.index].focus();
      return self.clients.openWindow(choice.url);
    }),
  );
});
