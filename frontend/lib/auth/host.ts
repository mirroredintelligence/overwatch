// The host a request was addressed to. One sub-domain per tenant (DEC-134 item 3, DEC-136 item 11), so
// the host is the tenant for every request that has no signed claim, and a session is tied to the host
// it was made on. Only the Host header is read (or, when a request was built without one, the host of
// its own address): never `X-Forwarded-Host`, `Forwarded`, a tenant header, a query or a body, because
// the caller controls those. A proxy in front of the app must pass the original Host on.

const HOST_NAME = /^[a-z0-9](?:[a-z0-9.-]{0,251}[a-z0-9])?(?::\d{1,5})?$/;
const EMPTY_LABEL = /(^|\.)\.|\.\./;

/**
 * The host in lower case, without a final dot, with its port when it has one; null for anything that
 * is not a plain host name (a path, a user, a space, an empty label, an IPv6 literal, too long).
 */
export function normaliseHost(value: unknown): string | null {
  if (typeof value !== 'string') return null;
  const host = value.toLowerCase().replace(/\.(?=(:\d{1,5})?$)/, '');
  if (!HOST_NAME.test(host) || EMPTY_LABEL.test(host)) return null;
  return host;
}

export function requestHost(request: Request): string | null {
  const header = request.headers.get('host');
  if (header !== null) return normaliseHost(header);
  try {
    return normaliseHost(new URL(request.url).host);
  } catch {
    return null;
  }
}
