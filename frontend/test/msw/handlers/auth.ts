import { http, HttpResponse, type HttpResponseResolver } from 'msw';
import { deviceExchange, operatorExchange, staffExchange } from '@/test/fixtures/exchange';
import { BACKEND_ROOT } from '@/test/oidc/constants';

// The back end's token exchange (TEN-043) for the BFF's tests. Not in the default handlers: the
// tests that sign someone in add them. Every call is kept, with the Host it was sent to, so a test
// can show which host named the tenant and what the body held.

export type SeenExchange = { path: string; host: string | null; authorization: string | null; body: unknown };

export const seenExchanges: SeenExchange[] = [];

export function resetExchanges() {
  seenExchanges.length = 0;
}

async function bodyOf(request: Request): Promise<unknown> {
  return (await request.json().catch(() => undefined)) as unknown;
}

export const authHandlers = [
  http.post(`${BACKEND_ROOT}/auth/token`, (async ({ request }) => {
    const body = await bodyOf(request);
    const host = request.headers.get('host');
    seenExchanges.push({ path: '/auth/token', host, authorization: request.headers.get('authorization'), body });
    const reply = staffExchange(host, body);
    return HttpResponse.json(reply.body as Record<string, unknown>, { status: reply.status, headers: { 'Cache-Control': 'no-store' } });
  }) as HttpResponseResolver),
  http.post(`${BACKEND_ROOT}/auth/device-token`, (async ({ request }) => {
    const body = await bodyOf(request);
    const host = request.headers.get('host');
    const authorization = request.headers.get('authorization');
    seenExchanges.push({ path: '/auth/device-token', host, authorization, body });
    const reply = deviceExchange(host, authorization, body);
    return HttpResponse.json(reply.body as Record<string, unknown>, { status: reply.status, headers: { 'Cache-Control': 'no-store' } });
  }) as HttpResponseResolver),
  http.post(`${BACKEND_ROOT}/auth/operator-token`, (async ({ request }) => {
    const body = await bodyOf(request);
    const host = request.headers.get('host');
    seenExchanges.push({ path: '/auth/operator-token', host, authorization: request.headers.get('authorization'), body });
    const reply = operatorExchange(body);
    return HttpResponse.json(reply.body as Record<string, unknown>, { status: reply.status, headers: { 'Cache-Control': 'no-store' } });
  }) as HttpResponseResolver),
];
