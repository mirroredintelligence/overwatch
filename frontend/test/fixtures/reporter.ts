import { http, HttpResponse, type RequestHandler } from 'msw';
import { fakeBackendToken, type TokenClaims } from '@/test/backendToken';
import { SAMPLE_DEVICE } from '@/test/requests';
import { TENANTS } from '@/test/tenants';

// Sample values for the reporter's sign-in and its token (W8E, DEC-792). The shapes are the back
// end's: `POST /identity/pin/verify` answers the PIN session, and `POST /identity/session-token`
// exchanges it for a 30-minute token whose claims are `sub role services tenant epoch aud exp device`
// (routes_registration_session.py, registration_session.py). Sample ids only: nothing here is a real
// person, phone, device or session.

export const BACKEND = 'http://backend.test';
/** The back end's PIN session id: 256 bits, urlsafe (43 characters). Never in a browser answer. */
export const PIN_SESSION = 'ps-sample-0123456789abcdefghijklmnopqrstuvw';
export const PERSON = 'prac-0123456789abcdef0123456789abcdef';
export const DEVICE = SAMPLE_DEVICE;
export const A = TENANTS.A;
/** The token's life, as the back end gives it (DEC-792, [ASSUMED] 30 minutes). */
export const TOKEN_MINUTES = 30;

export const iso = (moment: Date) => moment.toISOString().replace(/\.\d{3}Z$/, 'Z');

/** A reporter token as the back end signs it, with no valid signature (the front end checks none). */
export function reporterToken(over: Partial<TokenClaims> = {}, now: Date = new Date(), minutes = TOKEN_MINUTES): string {
  const iat = Math.floor(now.getTime() / 1000);
  return fakeBackendToken(
    { sub: PERSON, role: 'reporter', services: ['s1'], tenant: A.id, device: DEVICE, iat, exp: iat + minutes * 60, ...over },
    now,
  );
}

/** The 200 body of `POST /identity/session-token`. */
export function exchangeBody(over: Record<string, unknown> = {}, tokenOver: Partial<TokenClaims> = {}, now: Date = new Date()) {
  const token = reporterToken(tokenOver, now);
  const expires = new Date(now.getTime() + TOKEN_MINUTES * 60_000);
  return { token, expiresAt: iso(expires), role: 'reporter', ...over };
}

/** The 200 body of `POST /identity/pin/verify`. */
export const SIGNED_IN = { signedIn: true, sessionId: PIN_SESSION, tenant: A.id, role: 'reporter', services: ['s1'] };

export type SeenExchange = { host: string | null; authorization: string | null; body: unknown };

/**
 * A stand-in `POST /identity/session-token`. Calls are kept in `seen`; `reply` decides the answer
 * (a function, so a test can change it between calls).
 */
export function exchangeHandler(
  seen: SeenExchange[],
  reply: () => { status?: number; body?: unknown } | 'network-error',
): RequestHandler {
  return http.post(`${BACKEND}/identity/session-token`, async ({ request }) => {
    seen.push({
      host: request.headers.get('host'),
      authorization: request.headers.get('authorization'),
      body: await request.json().catch(() => undefined),
    });
    const answer = reply();
    if (answer === 'network-error') return HttpResponse.error();
    return HttpResponse.json((answer.body ?? {}) as Record<string, unknown>, { status: answer.status ?? 200 });
  });
}
