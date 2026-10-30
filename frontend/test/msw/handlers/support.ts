import { http, HttpResponse, type HttpResponseResolver } from 'msw';
import { EXEC_BACKEND } from './exec';

// The back end's support-code routes (R18, O06) for the share screen's tests: the code is created once and
// returned once; the stand-in keeps what it was asked to do.

export type SeenSupport = { method: string; path: string; idempotencyKey: string | null; body: unknown };
export const seenSupport: SeenSupport[] = [];
export const SHARE_CODE = 'K7R4-92QX';
export const SHARE_EXPIRES = '2026-10-23T17:02:00Z';

export function resetSupportBackend() {
  seenSupport.length = 0;
}

export const supportBackendHandlers = [
  http.post(`${EXEC_BACKEND}/support/codes`, (async ({ request }) => {
    const body = await request.json().catch(() => undefined);
    seenSupport.push({ method: 'POST', path: '/support/codes', idempotencyKey: request.headers.get('Idempotency-Key'), body });
    return HttpResponse.json({ code: SHARE_CODE, expiresAt: SHARE_EXPIRES }, { status: 201 });
  }) as HttpResponseResolver),
  http.delete(`${EXEC_BACKEND}/support/codes/current`, (({ request }) => {
    seenSupport.push({ method: 'DELETE', path: `/support/codes/current?${new URL(request.url).search.slice(1)}`, idempotencyKey: request.headers.get('Idempotency-Key'), body: undefined });
    return new HttpResponse(null, { status: 204 });
  }) as HttpResponseResolver),
  http.get(`${EXEC_BACKEND}/support/accesses`, (({ request }) => {
    seenSupport.push({ method: 'GET', path: `/support/accesses?${new URL(request.url).search.slice(1)}`, idempotencyKey: null, body: undefined });
    return HttpResponse.json([{ openedAt: '2026-10-23T13:02:00Z', role: 'support' }]);
  }) as HttpResponseResolver),
];
