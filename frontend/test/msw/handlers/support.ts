import { http, HttpResponse, type HttpResponseResolver } from 'msw';
import { EXEC_BACKEND } from './exec';

// The support routes are at the back end's root, not under /fhir (routes_support.py, prefix /support).
const ROOT = EXEC_BACKEND.replace(/\/fhir$/, '');

// The back end's support-code routes (R18, O06) for the share screen's tests: the code is created once and
// returned once; the stand-in keeps what it was asked to do.

export type SeenSupport = { method: string; path: string; idempotencyKey: string | null; body: unknown };
export const seenSupport: SeenSupport[] = [];
export const SHARE_CODE = 'K7R4-92QX';
export const SHARE_EXPIRES = '2026-10-23T17:02:00Z';

/** Whether a code is live for the session (W7A, DEC-772): it says that and until when, never the code. */
export let sharing: { active: boolean; expiresAt?: string } = { active: false };
export function setSharing(next: { active: boolean; expiresAt?: string }) {
  sharing = next;
}

export function resetSupportBackend() {
  seenSupport.length = 0;
  sharing = { active: false };
}

export const supportBackendHandlers = [
  http.post(`${ROOT}/support/codes`, (async ({ request }) => {
    const body = await request.json().catch(() => undefined);
    seenSupport.push({ method: 'POST', path: '/support/codes', idempotencyKey: request.headers.get('Idempotency-Key'), body });
    return HttpResponse.json({ code: SHARE_CODE, expiresAt: SHARE_EXPIRES }, { status: 201 });
  }) as HttpResponseResolver),
  http.get(`${ROOT}/support/codes/current`, (({ request }) => {
    seenSupport.push({ method: 'GET', path: `/support/codes/current?${new URL(request.url).search.slice(1)}`, idempotencyKey: null, body: undefined });
    return HttpResponse.json(sharing);
  }) as HttpResponseResolver),
  http.delete(`${ROOT}/support/codes/current`, (({ request }) => {
    seenSupport.push({ method: 'DELETE', path: `/support/codes/current?${new URL(request.url).search.slice(1)}`, idempotencyKey: request.headers.get('Idempotency-Key'), body: undefined });
    return new HttpResponse(null, { status: 204 });
  }) as HttpResponseResolver),
  http.get(`${ROOT}/support/accesses`, (({ request }) => {
    seenSupport.push({ method: 'GET', path: `/support/accesses?${new URL(request.url).search.slice(1)}`, idempotencyKey: null, body: undefined });
    return HttpResponse.json([{ openedAt: '2026-10-23T13:02:00Z', role: 'support' }]);
  }) as HttpResponseResolver),
];
