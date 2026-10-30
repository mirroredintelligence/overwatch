import { hostOf } from '@/lib/links/server';

// A request that starts a pairing, or makes a screen's session, has no session of its own to hold a
// double-submit token, so it must come from this site's own pages. A browser says where a request
// came from in `Sec-Fetch-Site` and `Origin`, and a page of another site cannot forge either. A
// request that carries neither is not from a browser that can be tricked, so it is let through: the
// cookie on it is SameSite Strict and is not sent cross-site anyway. This is the second control.

export function isSameOriginRequest(request: Request): boolean {
  const site = request.headers.get('sec-fetch-site');
  if (site !== null && site !== 'same-origin') return false;
  const origin = request.headers.get('origin');
  if (origin === null) return true;
  let parsed: URL;
  try {
    parsed = new URL(origin);
  } catch {
    return false; // "null", or text that is not an origin
  }
  // The host, port included: each tenant's host is its own origin. The scheme is left out, since
  // behind a proxy that ends TLS the request here may not say https.
  return parsed.host === hostOf(request);
}
