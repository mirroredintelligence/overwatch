import { http, HttpResponse, type HttpResponseResolver } from 'msw';
import {
  BACKEND_ROOT,
  csrfFor,
  EMPTY_VIEW,
  EXPIRED_BODY,
  LINK,
  RECORDED_ANSWER,
  RECORDED_VIEW,
} from '@/test/fixtures/links';

// The capacity link API as the back end answers it (L01, DEC-167), for the link
// pages' tests, and the same answers as the BFF route handlers send them to the
// browser (which drop nothing a page needs). Every POST the page makes is kept, so
// a test can assert that opening a page sent none.

/** Every POST the browser sent to the BFF, newest last. */
export const seenBffPosts: { token: string; body: unknown; csrf: string | null }[] = [];
/** Every renewal the browser asked the BFF for, newest last. */
export const seenBffRenews: string[] = [];
/** Every request the back end stand-in saw, with the Host it was sent to. */
export const seenBackendRequests: { method: string; token: string; host: string | null; body: unknown }[] = [];

export function resetLinkRequests() {
  seenBffPosts.length = 0;
  seenBffRenews.length = 0;
  seenBackendRequests.length = 0;
}

type Answer = { status: number; body: unknown; headers?: Record<string, string> };

function viewFor(token: string): Answer {
  const csrfToken = csrfFor(token);
  switch (token) {
    case LINK.recorded:
      return { status: 200, body: { ...RECORDED_VIEW, csrfToken } };
    case LINK.empty:
      return { status: 200, body: { ...EMPTY_VIEW, csrfToken } };
    case LINK.booking:
      return { status: 200, body: { ...RECORDED_VIEW, purpose: 'booking-request', csrfToken } };
    case LINK.used:
      return { status: 410, body: { state: 'used' } };
    case LINK.down:
      return { status: 503, body: { state: 'error' } };
    case LINK.limited:
    case LINK.stale:
      return { status: 200, body: { ...RECORDED_VIEW, csrfToken } };
    default:
      return { status: 410, body: EXPIRED_BODY };
  }
}

function answerFor(token: string, body: Record<string, unknown>): Answer {
  if (token === LINK.expired || token === LINK.used) {
    return { status: 410, body: { state: token === LINK.used ? 'used' : 'expired' } };
  }
  if (token === LINK.limited) return { status: 429, body: { state: 'rate-limited' }, headers: { 'Retry-After': '600' } };
  if (token === LINK.stale) return { status: 409, body: { state: 'send-number', reason: 'stale', message: 'Please send the number' } };
  if (body.action === 'confirm') return { status: 200, body: RECORDED_ANSWER };
  if (body.action === 'closed') return { status: 200, body: { ...RECORDED_ANSWER, value: 0 } };
  if (body.action === 'number') {
    const value = body.value as number;
    if (value > RECORDED_VIEW.usualMax && body.confirmOutOfRange !== true) {
      return { status: 422, body: { state: 'out-of-range', usualMin: RECORDED_VIEW.usualMin, usualMax: RECORDED_VIEW.usualMax } };
    }
    return { status: 200, body: { ...RECORDED_ANSWER, value } };
  }
  return { status: 400, body: { state: 'invalid' } };
}

function reply({ status, body, headers }: Answer) {
  return HttpResponse.json(body, { status, headers: { 'Cache-Control': 'no-store', ...headers } });
}

/** The back end stand-in: `GET /links/{token}`, `POST /links/{token}` and `POST /links/{token}/renew`. */
export const backendLinkHandlers = [
  http.get(`${BACKEND_ROOT}/links/:token`, (({ request, params }) => {
    const token = String(params.token);
    seenBackendRequests.push({ method: 'GET', token, host: request.headers.get('host'), body: undefined });
    return reply(viewFor(token));
  }) as HttpResponseResolver),
  http.post(`${BACKEND_ROOT}/links/:token`, (async ({ request, params }) => {
    const token = String(params.token);
    const body = (await request.json().catch(() => null)) as Record<string, unknown> | null;
    seenBackendRequests.push({ method: 'POST', token, host: request.headers.get('host'), body });
    if (request.headers.get('x-csrf-token') !== csrfFor(token)) {
      return reply({ status: 403, body: { state: 'forbidden' } });
    }
    return reply(answerFor(token, body ?? {}));
  }) as HttpResponseResolver),
  http.post(`${BACKEND_ROOT}/links/:token/renew`, (({ request, params }) => {
    const token = String(params.token);
    seenBackendRequests.push({ method: 'POST', token, host: request.headers.get('host'), body: undefined });
    if (token === LINK.limited) return reply({ status: 429, body: { state: 'rate-limited' }, headers: { 'Retry-After': '600' } });
    return reply({ status: 202, body: { state: 'accepted' } });
  }) as HttpResponseResolver),
];

/** The browser's view: the BFF answers the same shapes at its own relative paths. */
export const bffLinkHandlers = [
  http.get('/api/bff/links/:token', (async ({ params }) => reply(viewFor(String(params.token)))) as HttpResponseResolver),
  http.post('/api/bff/links/:token', (async ({ request, params }) => {
    const token = String(params.token);
    const body = (await request.json().catch(() => null)) as unknown;
    seenBffPosts.push({ token, body, csrf: request.headers.get('x-csrf-token') });
    if (request.headers.get('x-csrf-token') !== csrfFor(token)) {
      return reply({ status: 403, body: { code: 'csrf' } });
    }
    return reply(answerFor(token, (body ?? {}) as Record<string, unknown>));
  }) as HttpResponseResolver),
  http.post('/api/bff/links/:token/renew', (({ params }) => {
    const token = String(params.token);
    seenBffRenews.push(token);
    if (token === LINK.limited) return reply({ status: 429, body: { state: 'rate-limited' }, headers: { 'Retry-After': '600' } });
    return reply({ status: 202, body: { state: 'accepted' } });
  }) as HttpResponseResolver),
];

export const linkHandlers = [...backendLinkHandlers, ...bffLinkHandlers];
