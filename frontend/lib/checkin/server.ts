import { createHash, timingSafeEqual } from 'node:crypto';
import { cookies } from 'next/headers';
import { baseCookieOptions, readRequestCookie } from '@/lib/auth/session';
import { callLinkApi, hostOf } from '@/lib/links/server';

// Server-only. The check-in page's own API (DEC-1346): the page a service's printed QR code opens. No session: the
// code in the address says which service, and a six-digit code texted to a rostered number says who. The tenant is the
// host the request was addressed to; nothing here reads a tenant from the request.

export const CHECKIN_CSRF_COOKIE = 'overwatch_checkin_csrf';
export const TOKEN_SHAPE = /^[A-Za-z0-9_-]{1,64}$/;
const MAX_BODY_BYTES = 512;
const MAX_AGE_SECONDS = 60 * 60;
const NO_STORE = { 'Cache-Control': 'no-store' };

export const checkinPath = (token: string) => `/api/bff/checkin/${token}`;

/** The answers the page can tell apart, and the fields of each; anything else the back end sent is dropped. */
const FIELDS: Record<number, readonly string[]> = {
  200: ['state', 'service', 'until', 'csrfToken'],
  202: ['state'],
  400: ['state'],
  403: ['state'],
  410: ['state'],
  429: ['state'],
};
const STATE_WORD = /^[a-z-]{1,24}$/;

export function reply(status: number, body: unknown, retryAfter?: string): Response {
  const known = FIELDS[status];
  const source = typeof body === 'object' && body !== null ? (body as Record<string, unknown>) : {};
  const out: Record<string, unknown> = {};
  if (known === undefined) {
    out.state = status >= 500 ? 'error' : 'invalid';
  } else {
    for (const field of known) {
      if (!(field in source)) continue;
      const value = source[field];
      if (field === 'state' && (typeof value !== 'string' || !STATE_WORD.test(value))) continue;
      if (field === 'until' && value !== null && typeof value !== 'string') continue;
      if ((field === 'service' || field === 'csrfToken') && typeof value !== 'string') continue;
      out[field] = value;
    }
  }
  const headers: Record<string, string> = { ...NO_STORE };
  if (status === 429 && retryAfter !== undefined && /^\d{1,6}$/.test(retryAfter)) headers['Retry-After'] = retryAfter;
  return Response.json(out, { status: known === undefined ? (status >= 500 ? 502 : 400) : status, headers });
}

export const unavailable = () => Response.json({ state: 'unavailable' }, { status: 503, headers: NO_STORE });

export async function issueCheckinCsrf(token: string, value: string): Promise<void> {
  const store = await cookies();
  store.set(CHECKIN_CSRF_COOKIE, value, { ...baseCookieOptions(), httpOnly: true, path: checkinPath(token), maxAge: MAX_AGE_SECONDS });
}

const digest = (value: string) => createHash('sha256').update(value).digest();

/** True only when the request is for this code's path and its header equals its cookie. Constant-time. */
export function checkCheckinCsrf(request: Request, token: string): boolean {
  if (!new URL(request.url).pathname.startsWith(`${checkinPath(token)}/`)) return false;
  const header = request.headers.get('X-CSRF-Token');
  const cookie = readRequestCookie(request, CHECKIN_CSRF_COOKIE);
  if (!header || !cookie) return false;
  return timingSafeEqual(digest(header), digest(cookie));
}

/** The JSON body of a write, with only the named fields, or null when it is not a small JSON object. */
export async function readFields(request: Request, allowed: readonly string[]): Promise<Record<string, unknown> | null> {
  const text = await request.text();
  if (new TextEncoder().encode(text).length > MAX_BODY_BYTES) return null;
  let parsed: unknown;
  try {
    parsed = JSON.parse(text) as unknown;
  } catch {
    return null;
  }
  if (typeof parsed !== 'object' || parsed === null || Array.isArray(parsed)) return null;
  const source = parsed as Record<string, unknown>;
  if (Object.keys(source).some((key) => !allowed.includes(key))) return null;
  return source;
}

/** One write to the back end for this code, with the page's CSRF header passed on. */
export async function postCheckin(request: Request, token: string, step: 'code' | 'confirm', body: Record<string, unknown>): Promise<Response> {
  try {
    const result = await callLinkApi({
      method: 'POST',
      path: `/checkin/${token}/${step}`,
      host: hostOf(request),
      body,
      csrf: request.headers.get('X-CSRF-Token') ?? undefined,
    });
    return reply(result.status, result.body, result.retryAfter);
  } catch {
    return unavailable();
  }
}
