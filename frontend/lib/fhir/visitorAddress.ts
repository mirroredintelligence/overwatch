import { isIP } from 'node:net';

// Server-only. Who the visitor is, as the web app's own ingress says, for the API's rate limits.
// Behind `web` the API sees only this app's address, so every visitor would share one bucket (KI-1303,
// DEC-1311). The address is sent on to the API as CF-Connecting-IP by `callBackend` and `fhirFetch`.
//
// Which header carries it is a deployment setting, OVERWATCH_VISITOR_ADDRESS_SOURCE:
// - `x-forwarded-for` (default, Azure Container Apps without a Cloudflare proxy): the RIGHT-MOST entry,
//   the one the ingress appended. Entries to its left came from the client or earlier proxies and are
//   never trusted.
// - `cf-connecting-ip`: set by Cloudflare, trusted only when the deployment says Cloudflare proxies it.
// Anything that is not exactly one IP address (v4 or v6) gives none: the API then keeps the shared bucket,
// which is slower and never a bypass. The address is never logged.

export type VisitorSource = 'x-forwarded-for' | 'cf-connecting-ip';

export const VISITOR_SOURCE_VARIABLE = 'OVERWATCH_VISITOR_ADDRESS_SOURCE';

export function visitorSource(value: string | undefined = process.env[VISITOR_SOURCE_VARIABLE]): VisitorSource {
  return value?.trim().toLowerCase() === 'cf-connecting-ip' ? 'cf-connecting-ip' : 'x-forwarded-for';
}

/** One address, or null: a port or square brackets are dropped, nothing else is repaired. */
function oneAddress(raw: string): string | null {
  let text = raw.trim();
  const bracketed = /^\[([^\]]+)\](?::\d{1,5})?$/.exec(text);
  if (bracketed !== null) text = bracketed[1] ?? '';
  else if (/^[0-9.]+:\d{1,5}$/.test(text)) text = text.slice(0, text.lastIndexOf(':'));
  return isIP(text) === 0 ? null : text;
}

export function visitorAddress(headers: Headers, source: VisitorSource = visitorSource()): string | null {
  if (source === 'cf-connecting-ip') {
    const value = headers.get('cf-connecting-ip');
    return value === null ? null : oneAddress(value);
  }
  const forwarded = headers.get('x-forwarded-for');
  if (forwarded === null) return null;
  const entries = forwarded.split(',');
  return oneAddress(entries[entries.length - 1] ?? '');
}

/**
 * The visitor of the request in progress (a route handler or a Server Component), or undefined outside one
 * or when there is no usable address. Callers that have the request may use `visitorAddress` directly.
 */
export async function ambientVisitorAddress(): Promise<string | undefined> {
  try {
    const { headers } = await import('next/headers');
    return visitorAddress(await headers()) ?? undefined;
  } catch {
    return undefined;
  }
}
