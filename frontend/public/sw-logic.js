// The service worker's pure logic (W32). A classic script, so the worker can load it with
// importScripts; it is tested by loading this same file (test/pwa/sw-logic.test.ts).
// It exposes its functions on self.DiucsSw and never logs a payload.
(function (scope) {
  var FALLBACK = '/app';
  var OFFLINE = '/offline';
  var STATIC_PREFIX = '/_next/static/';

  // Same-origin relative paths only: a single leading slash, never a protocol-relative "//".
  function sameOriginPath(url) {
    return typeof url === 'string' && url.charAt(0) === '/' && url.charAt(1) !== '/' && url.indexOf('\\') < 0;
  }

  // Keeps title, body and url. Every other field of the push payload is dropped.
  function handlePush(data) {
    var source = data && typeof data === 'object' ? data : {};
    var title = typeof source.title === 'string' ? source.title : 'DIUCS capacity';
    var body = typeof source.body === 'string' ? source.body : '';
    var url = sameOriginPath(source.url) ? source.url : FALLBACK;
    return { title: title, body: body, data: { url: url } };
  }

  // Focus the first open window of this origin, otherwise open the url (same origin only).
  function pickClientOrOpen(clientUrls, url, origin) {
    for (var i = 0; i < clientUrls.length; i += 1) {
      if (typeof clientUrls[i] === 'string' && clientUrls[i].indexOf(origin) === 0) {
        return { kind: 'focus', index: i };
      }
    }
    return { kind: 'open', url: sameOriginPath(url) ? url : FALLBACK };
  }

  // Only the offline page and the build's static assets, and only for GET.
  function isCacheable(request) {
    var url = typeof request === 'string' ? request : request && request.url;
    var method = typeof request === 'string' ? 'GET' : (request && request.method) || 'GET';
    if (String(method).toUpperCase() !== 'GET' || typeof url !== 'string') return false;
    var path = url.split('?')[0];
    return path === OFFLINE || path.indexOf(STATIC_PREFIX) === 0;
  }

  scope.DiucsSw = {
    handlePush: handlePush,
    pickClientOrOpen: pickClientOrOpen,
    isCacheable: isCacheable,
    OFFLINE: OFFLINE,
    FALLBACK: FALLBACK,
  };
})(self);
