import { http, HttpResponse, type HttpResponseResolver } from 'msw';
import { deviceExchange, GRANTS, operatorExchange, staffExchange, tenantOfHost } from '@/test/fixtures/exchange';
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
  // DEC-1327: the one-domain sign-in. The tenants are every host whose directory the person's token
  // gives an answer for; the token route answers for the tenant named, as the host route does for its host.
  http.post(`${BACKEND_ROOT}/auth/staff/tenants`, (async ({ request }) => {
    const body = await bodyOf(request);
    seenExchanges.push({ path: '/auth/staff/tenants', host: request.headers.get('host'), authorization: null, body });
    // One directory is one tenant (the registry's unique directory, DEC-1327). The shared host, which
    // gives one directory to two tenants, serves the host-bound tests only, so it is not listed here.
    const tenants = Object.keys(GRANTS).filter((host) => host !== 'shared.example.test').flatMap((host) => {
      const reply = staffExchange(host, body);
      if (reply.status !== 200) return [];
      const { roles } = reply.body as { roles: string[] };
      return [{ id: tenantOfHost(host), name: `Organisation of ${host}`, roles }];
    });
    if (tenants.length === 0) return HttpResponse.json({}, { status: 403, headers: { 'Cache-Control': 'no-store' } });
    return HttpResponse.json({ tenants }, { status: 200, headers: { 'Cache-Control': 'no-store' } });
  }) as HttpResponseResolver),
  http.post(`${BACKEND_ROOT}/auth/staff/token`, (async ({ request }) => {
    const { tenant, ...rest } = (await bodyOf(request)) as { tenant?: string } & Record<string, unknown>;
    const host = Object.keys(GRANTS).find((h) => tenantOfHost(h) === tenant);
    seenExchanges.push({ path: '/auth/staff/token', host: host ?? null, authorization: null, body: { tenant, ...rest } });
    if (host === undefined) return HttpResponse.json({}, { status: 403, headers: { 'Cache-Control': 'no-store' } });
    const reply = staffExchange(host, rest);
    return HttpResponse.json(reply.body as Record<string, unknown>, { status: reply.status, headers: { 'Cache-Control': 'no-store' } });
  }) as HttpResponseResolver),
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
